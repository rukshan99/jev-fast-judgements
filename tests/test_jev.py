"""Black-box tests for skills/jev-fast-judgements/scripts/jev.py against an offline mock API.

Run:  python -m unittest discover -s tests -v
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from mock_typesafe import API_KEY, MockTypeSafe  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "jev-fast-judgements" / "scripts" / "jev.py"

RELEVANCE_Q = {
    "relevant": {"type": "noul", "instructions": "Does `item` help answer `context`?",
                 "criteria": {"true": "States causes or timelines", "false": "Off-topic"}},
    "usefulness": {"type": "score", "instructions": "How directly does `item` answer `context`?",
                   "criteria": ["Not at all", "Mentions the topic", "Directly answers"]},
}
LOG_Q = {
    "category": {"type": "choice", "instructions": "What kind of event is {item}?",
                 "criteria": {"outage": "Service failures", "noise": "Routine output"}},
    "user_facing": {"type": "noul", "instructions": "Does {item} describe a failure a user would notice?"},
}


class JevScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        pages = self.dir / "pages"
        pages.mkdir()
        for i in range(1, 13):
            if i % 4 == 0:
                text = "Postmortem: the March outage was caused by a bad config push."
            elif i == 5:
                text = "Maybe related: some users reported slowness."
            else:
                text = "Cookie banner. Navigation. About us. Careers."
            (pages / f"p{i:02d}.md").write_text(text)
        lines = ["2026-09-21 INFO heartbeat ok" if n % 25 else "2026-09-21 ERROR outage in payments api"
                 for n in range(1, 301)]
        (self.dir / "app.log").write_text("\n".join(lines))
        (self.dir / "q_rel.json").write_text(json.dumps(RELEVANCE_Q))
        (self.dir / "q_log.json").write_text(json.dumps(LOG_Q))

    def tearDown(self):
        self.tmp.cleanup()

    def run_jev(self, *args, base_url=None, key=API_KEY):
        env = dict(os.environ, TYPESAFE_API_KEY=key)
        env.pop("TYPESAFE_MODEL", None)
        if base_url:
            env["TYPESAFE_BASE_URL"] = base_url
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=self.dir, env=env,
                              capture_output=True, text=True, timeout=120)

    def read_results(self, name="jev_results.jsonl"):
        return [json.loads(line) for line in (self.dir / name).read_text().splitlines()]

    # ------------------------------------------------------------ happy paths

    def test_each_keep_sort_and_unsure(self):
        with MockTypeSafe() as api:
            r = self.run_jev("each", "--dir", "pages", "--glob", "*.md", "-q", "q_rel.json",
                             "--context", "What caused the outage?", "--sort", "relevant",
                             "--keep", "relevant>=0.5", "--preview", "30", base_url=api.base_url)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("## KEPT 4", r.stdout)
        self.assertIn("## DROPPED 8", r.stdout)
        self.assertIn("p05.md", r.stdout)
        self.assertIn("?unsure", r.stdout)
        self.assertEqual(len(api.requests), 12)
        self.assertEqual(api.requests[0]["state"]["context"], "What caused the outage?")
        self.assertEqual(len(self.read_results()), 12)

    def test_pack_splits_requests_and_maps_answers_back(self):
        with MockTypeSafe() as api:
            r = self.run_jev("pack", "--lines", "app.log", "-q", "q_log.json", "--max-items", "40",
                             "--keep", "category==outage", "--sort", "user_facing",
                             base_url=api.base_url)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(api.requests), 8)  # 300 lines / 40 per request
        first = api.requests[0]
        self.assertIn("items", first["state"])
        self.assertEqual(first["questions"]["category@@0"]["instructions"],
                         "What kind of event is `items[0]`?")
        self.assertIn("## KEPT 12", r.stdout)
        rows = {row["id"]: row["answers"] for row in self.read_results()}
        self.assertEqual(len(rows), 300)
        self.assertEqual(rows["L25"]["category"]["choice"], "outage")
        self.assertEqual(rows["L24"]["category"]["choice"], "noise")

    def test_ask_mode(self):
        with MockTypeSafe() as api:
            r = self.run_jev("ask", "--state", "Big outage today", "-q", "q_rel.json",
                             base_url=api.base_url)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("relevant=0.95", r.stdout)
        self.assertIn("usefulness=1.80(0.88)", r.stdout)

    def test_object_items_from_jsonl(self):
        rows = [{"id": "c1", "claim": "The outage began at 09:14", "source": "outage began 09:14"},
                {"id": "c2", "claim": "Revenue grew 40%", "source": "Cookie banner"}]
        (self.dir / "claims.jsonl").write_text("\n".join(json.dumps(x) for x in rows))
        (self.dir / "q_claim.json").write_text(json.dumps(
            {"unsupported": {"type": "noul", "instructions": "Is `item.claim` unsupported by `item.source`?"}}))
        with MockTypeSafe() as api:
            r = self.run_jev("each", "--items", "claims.jsonl", "-q", "q_claim.json",
                             "--sort", "unsupported", base_url=api.base_url)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(api.requests[0]["state"]["item"], {"claim": rows[0]["claim"], "source": rows[0]["source"]})
        self.assertLess(r.stdout.index("c1"), r.stdout.index("c2"))

    def test_large_files_are_chunked(self):
        (self.dir / "pages" / "big.md").write_text("Paragraph about the outage timeline.\n\n" * 900)
        with MockTypeSafe() as api:
            r = self.run_jev("each", "--dir", "pages", "--glob", "big.md", "-q", "q_rel.json",
                             "--context", "outage", "--chunk-chars", "12000", base_url=api.base_url)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(api.requests), 3)
        self.assertIn("big.md#0", r.stdout)

    def test_dry_run_makes_no_calls(self):
        r = self.run_jev("pack", "--lines", "app.log", "-q", "q_log.json", "--dry-run", key="")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("# dry run: 3 calls", r.stdout)  # 300 lines / 100 default per request

    # ------------------------------------------------------------ resilience and errors

    def test_retries_after_overload(self):
        with MockTypeSafe(fail_first_with=529) as api:
            r = self.run_jev("ask", "--state", "outage", "-q", "q_rel.json", base_url=api.base_url)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(api.requests), 2)

    def test_bad_key_is_fatal_with_clear_message(self):
        with MockTypeSafe() as api:
            r = self.run_jev("ask", "--state", "x", "-q", "q_rel.json", base_url=api.base_url, key="wrong")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("401", r.stderr)

    def test_missing_key_explains_fallback(self):
        r = self.run_jev("ask", "--state", "x", "-q", "q_rel.json", key="")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("TYPESAFE_API_KEY is not set", r.stderr)

    def test_unreachable_api_explains_fallback(self):
        r = self.run_jev("ask", "--state", "x", "-q", "q_rel.json", "--timeout", "2",
                         base_url="http://127.0.0.1:9")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("read the items yourself", r.stderr)

    def test_invalid_questions_rejected_locally(self):
        (self.dir / "bad.json").write_text(json.dumps({"x": {"type": "choice", "instructions": "Which?"}}))
        r = self.run_jev("ask", "--state", "x", "-q", "bad.json", key="")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("needs criteria", r.stderr)

    def test_pack_requires_item_placeholder(self):
        r = self.run_jev("pack", "--lines", "app.log", "-q", "q_rel.json", "--dry-run", key="")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("{item}", r.stderr)


if __name__ == "__main__":
    unittest.main()
