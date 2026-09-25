#!/usr/bin/env python3
"""
jev.py - let an agent use TypeSafe's Jev (a System One decision model) while keeping
bulk content OUT of the agent's context window.

Modes
  ask    one request: a state + a questions file                  (raw access)
  each   one request per item; state = {"context", "item"}        (documents, big chunks)
  pack   many small items in one state; one question per item,
         generated from a template containing {item}              (lines, snippets, records)

Item sources for each/pack:  --items FILE.jsonl | --lines FILE | --dir DIR [--glob "*.md"]

Environment
  TYPESAFE_API_KEY   required unless --dry-run
  TYPESAFE_BASE_URL  default https://api.typesafe.ai (any /v1/systemone-compatible gateway works)
  TYPESAFE_MODEL     default jev-latest (pin e.g. jev-1.13.0 for repeatable thresholds)

Only a compact verdict table is printed. Full answers go to --out (JSONL) for later grep.
Python 3.8+, standard library only.
"""
import argparse
import glob
import http.client
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

DEFAULT_BASE = "https://api.typesafe.ai"
DEFAULT_MODEL = "jev-latest"
PRICE_PER_M_INPUT = 0.042      # USD per million input tokens (TypeSafe list price; output free)
MAX_STATE_CHARS = 90_000       # ~24k tokens: headroom under the 32k state+longest-question limit
UNSURE_NOUL = (0.3, 0.7)       # noul probabilities inside this band are flagged unsure
UNSURE_CONF = 0.6              # choice/score confidence below this is flagged unsure
VALID_TYPES = {"noul", "choice", "score"}


class JevError(Exception):
    pass


class FatalJevError(JevError):
    """Errors that will fail every call (bad key, bad schema): stop the whole run."""


def est_tokens(text):
    return len(text) // 4 + 1


def warn(msg):
    print(f"[jev] {msg}", file=sys.stderr)


# ---------------------------------------------------------------- HTTP

def call_jev(payload, base, key, timeout=60, retries=4):
    url = base.rstrip("/") + "/v1/systemone"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:1500]
            if e.code in (429, 500, 502, 503, 504, 529) and attempt < retries:
                try:
                    wait = float(e.headers.get("Retry-After"))
                except (TypeError, ValueError, AttributeError):
                    wait = 2 ** attempt + random.random()
                time.sleep(min(wait, 30))
                continue
            if e.code == 401:
                raise FatalJevError("HTTP 401: missing or invalid TYPESAFE_API_KEY")
            if e.code in (400, 422):
                raise FatalJevError(f"HTTP {e.code}: request failed validation. Fix the field "
                                    f"named here, then rerun: {detail}")
            raise JevError(f"HTTP {e.code}: {detail}")
        except urllib.error.URLError as e:
            if attempt < retries:
                time.sleep(2 ** attempt + random.random())
                continue
            raise FatalJevError(f"network error ({e.reason}). If outbound network is blocked "
                                "in this environment, skip Jev and read the items yourself.")
        except (http.client.HTTPException, OSError, ValueError) as e:
            # dropped connections, read timeouts, truncated/non-JSON bodies: transient, retry
            if attempt < retries:
                time.sleep(2 ** attempt + random.random())
                continue
            raise JevError(f"connection/response error: {type(e).__name__}: {e}")
    raise JevError("exhausted retries")


# ---------------------------------------------------------------- loading

def read_json_or_text(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        raw = f.read()
    if path.lower().endswith(".json"):
        return json.loads(raw)
    return raw


def chunk_text(text, size):
    if len(text) <= size:
        return [text]
    chunks, cur = [], ""
    for para in re.split(r"(\n\s*\n)", text):
        if len(cur) + len(para) <= size:
            cur += para
            continue
        if cur.strip():
            chunks.append(cur)
        while len(para) > size:
            chunks.append(para[:size])
            para = para[size:]
        cur = para
    if cur.strip():
        chunks.append(cur)
    return chunks


def load_items(args):
    items = []  # (id, value)
    if args.items:
        with open(args.items, encoding="utf-8") as f:
            for n, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    items.append((str(n), obj))
                    continue
                iid = str(obj.pop("id", n))
                value = obj["text"] if list(obj) == ["text"] else obj
                items.append((iid, value))
    if args.lines:
        with open(args.lines, encoding="utf-8", errors="replace") as f:
            for n, line in enumerate(f, 1):
                if line.strip():
                    items.append((f"L{n}", line.rstrip("\n")))
    if args.dir:
        pattern = os.path.join(args.dir, "**", args.glob)
        for path in sorted(glob.glob(pattern, recursive=True)):
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
            rel = os.path.relpath(path, args.dir)
            parts = chunk_text(text, args.chunk_chars)
            for i, part in enumerate(parts):
                items.append((rel if len(parts) == 1 else f"{rel}#{i}", part))
    if not items:
        raise SystemExit("[jev] no items loaded: pass --items, --lines or --dir")
    return items


def load_context(args):
    if getattr(args, "context_file", None):
        return read_json_or_text(args.context_file)
    return getattr(args, "context", None)


def load_questions(path):
    with open(path, encoding="utf-8") as f:
        qs = json.load(f)
    if not isinstance(qs, dict) or not qs:
        raise SystemExit("[jev] questions file must be a non-empty JSON object {id: question}")
    for qid, q in qs.items():
        if "@@" in qid:
            raise SystemExit(f"[jev] question id '{qid}' must not contain '@@'")
        if q.get("type") not in VALID_TYPES:
            raise SystemExit(f"[jev] question '{qid}': type must be one of {sorted(VALID_TYPES)}")
        if not q.get("instructions"):
            raise SystemExit(f"[jev] question '{qid}': instructions are required")
        if q["type"] in ("choice", "score") and not q.get("criteria"):
            raise SystemExit(f"[jev] question '{qid}': {q['type']} needs criteria")
    return qs


# ---------------------------------------------------------------- answers

def brief(ans):
    """-> (display string, sortable number, unsure flag)"""
    t = ans.get("type")
    if t == "noul":
        p = float(ans.get("noul", 0.0))
        return f"{p:.2f}", p, UNSURE_NOUL[0] < p < UNSURE_NOUL[1]
    conf = ans.get("confidence")
    conf_s = f"{conf:.2f}" if isinstance(conf, (int, float)) else "?"
    unsure = isinstance(conf, (int, float)) and conf < UNSURE_CONF
    if t == "choice":
        return f"{ans.get('choice')}({conf_s})", conf or 0.0, unsure
    if t == "score":
        s = float(ans.get("score", 0.0))
        return f"{s:.2f}({conf_s})", s, unsure
    return json.dumps(ans)[:60], 0.0, True


def sort_value(answers, spec):
    qid, _, option = spec.partition("=")
    ans = answers.get(qid)
    if not ans:
        return -1.0
    if option:
        return float(ans.get("probabilities", {}).get(option, 0.0))
    return brief(ans)[1]


KEEP_RE = re.compile(r"^\s*([\w.\-]+)\s*(>=|<=|==|!=|>|<)\s*(.+?)\s*$")


def passes(answers, expr):
    m = KEEP_RE.match(expr)
    if not m:
        raise SystemExit(f"[jev] bad --keep expression: {expr!r} (use e.g. relevant>=0.5 or topic==billing)")
    qid, op, rhs = m.groups()
    ans = answers.get(qid)
    if not ans:
        return False
    if ans.get("type") == "choice" and op in ("==", "!="):
        return (ans.get("choice") == rhs) == (op == "==")
    try:
        val, target = brief(ans)[1], float(rhs)
    except ValueError:
        return False
    return {">=": val >= target, "<=": val <= target, ">": val > target,
            "<": val < target, "==": val == target, "!=": val != target}[op]


def one_line(value, n):
    s = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    s = " ".join(s.split())
    return s[:n] + ("…" if len(s) > n else "")


# ---------------------------------------------------------------- reporting

def report(mode, rows, items_by_id, args, calls, usage_tokens, models, errors, item_chars):
    focus = set()
    for spec in (args.sort or []):
        focus.add(spec.partition("=")[0])
    for expr in (args.keep or []):
        m = KEEP_RE.match(expr)
        if m:
            focus.add(m.group(1))

    def row_unsure(ans):
        qs = [q for q in ans if not focus or q in focus]
        return any(brief(ans[q])[2] for q in qs)

    def fmt(rid, ans):
        cells = [f"{q}={brief(a)[0]}" for q, a in ans.items()]
        line = f"{rid}  " + "  ".join(cells)
        if args.preview:
            line += f"  | {one_line(items_by_id.get(rid, ''), args.preview)}"
        return line

    if args.sort:
        for spec in reversed(args.sort):
            rows.sort(key=lambda r: sort_value(r[1], spec), reverse=True)

    cost = usage_tokens * PRICE_PER_M_INPUT / 1e6
    model = ",".join(sorted(m for m in models if m)) or "?"
    print(f"# jev {mode}: {len(rows)} items answered, {calls} calls, model {model}")
    print(f"# jev input tokens {usage_tokens:,} (~${cost:.4f}); ~{item_chars // 4:,} tokens of item "
          f"text stayed out of your context. Full answers: {args.out}")

    if args.keep:
        kept = [r for r in rows if all(passes(r[1], e) for e in args.keep)]
        kept_ids = {r[0] for r in kept}
        unsure = [r for r in rows if r[0] not in kept_ids and row_unsure(r[1])]
        shown = kept[: args.top] if args.top else kept
        print(f"## KEPT {len(kept)} (showing {len(shown)}) - keep: {' AND '.join(args.keep)}")
        for rid, ans in shown:
            print(fmt(rid, ans) + ("  ?unsure" if row_unsure(ans) else ""))
        if unsure and not args.no_unsure:
            print(f"## UNSURE {len(unsure)} - not kept, but Jev was uncertain: read these yourself")
            for rid, ans in unsure[: max(args.top or 25, 25)]:
                print(fmt(rid, ans))
        dropped = len(rows) - len(kept) - (0 if args.no_unsure else len(unsure))
        print(f"## DROPPED {dropped} (confident no; details in {args.out})")
    else:
        shown = rows[: args.top] if args.top else rows
        print(f"## RESULTS (showing {len(shown)} of {len(rows)}; '?unsure' = read yourself)")
        for rid, ans in shown:
            print(fmt(rid, ans) + ("  ?unsure" if row_unsure(ans) else ""))
    if errors:
        print(f"## ERRORS {len(errors)} (unanswered; read these yourself or rerun)")
        for rid, err in errors[:10]:
            print(f"{rid}: {err[:200]}")


def write_out(path, rows, models):
    with open(path, "w", encoding="utf-8") as f:
        for rid, ans in rows:
            f.write(json.dumps({"id": rid, "answers": ans}, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- modes

def substitute(obj, ref):
    if isinstance(obj, str):
        return obj.replace("`{item}`", ref).replace("{item}", ref)
    if isinstance(obj, list):
        return [substitute(x, ref) for x in obj]
    if isinstance(obj, dict):
        return {k: substitute(v, ref) for k, v in obj.items()}
    return obj


def fit_value(iid, value):
    s = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if len(s) <= MAX_STATE_CHARS - 2000:
        return value
    warn(f"item {iid} is {len(s):,} chars; truncating to fit Jev's context. Use --dir with "
         "--chunk-chars, or pre-split, to evaluate all of it.")
    return s[: MAX_STATE_CHARS - 2000]


def build_each(items, context, questions, model):
    payloads = []
    for iid, value in items:
        state = {"item": fit_value(iid, value)}
        if context is not None:
            state["context"] = context
        payloads.append(([iid], {"model": model, "state": state, "questions": questions}))
    return payloads


def build_pack(items, context, template, model, max_items):
    if "{item}" not in json.dumps(template):
        raise SystemExit("[jev] pack mode: every question template must reference {item}")
    base = len(json.dumps(context, ensure_ascii=False)) + 200 if context is not None else 200
    groups, cur, size = [], [], base
    for iid, value in items:
        value = fit_value(iid, value)
        s = len(json.dumps(value, ensure_ascii=False)) + 8
        if cur and (size + s > MAX_STATE_CHARS or len(cur) >= max_items):
            groups.append(cur)
            cur, size = [], base
        cur.append((iid, value))
        size += s
    if cur:
        groups.append(cur)
    payloads = []
    for group in groups:
        state = {"items": [v for _, v in group]}
        if context is not None:
            state["context"] = context
        qs = {}
        for i in range(len(group)):
            for qid, q in template.items():
                qs[f"{qid}@@{i}"] = substitute(q, f"`items[{i}]`")
        payloads.append(([iid for iid, _ in group], {"model": model, "state": state, "questions": qs}))
    return payloads


def run_payloads(payloads, mode, args, key, base):
    rows, errors, models, usage = [], [], set(), 0

    def work(entry):
        ids, payload = entry
        return ids, call_jev(payload, base, key, timeout=args.timeout)

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(work, p) for p in payloads]
        for fut, (ids, _) in zip(futures, payloads):
            try:
                ids, resp = fut.result()
            except FatalJevError:
                for f in futures:
                    f.cancel()
                raise
            except JevError as e:
                errors.extend((i, str(e)) for i in ids)
                continue
            models.add(resp.get("model"))
            usage += int(resp.get("usage", {}).get("input_tokens", 0) or 0)
            answers = resp.get("answers", {})
            if mode == "pack":
                per = {i: {} for i in range(len(ids))}
                for qkey, ans in answers.items():
                    qid, _, idx = qkey.rpartition("@@")
                    if idx.isdigit() and int(idx) in per:
                        per[int(idx)][qid] = ans
                rows.extend((ids[i], per[i]) for i in range(len(ids)))
            else:
                rows.append((ids[0], answers))
    return rows, errors, models, usage


def dry_run(payloads, item_chars):
    total = sum(est_tokens(json.dumps(p, ensure_ascii=False)) for _, p in payloads)
    print(f"# dry run: {len(payloads)} calls, ~{total:,} input tokens "
          f"(~${total * PRICE_PER_M_INPUT / 1e6:.4f}); ~{item_chars // 4:,} tokens of item text "
          "would stay out of your context")
    sample = json.dumps(payloads[0][1], ensure_ascii=False, indent=1)
    print("# first request:")
    print(sample[:2500] + ("\n… (truncated)" if len(sample) > 2500 else ""))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)

    def common(p):
        p.add_argument("-q", "--questions", required=True, help="JSON file {id: question}")
        p.add_argument("--model", default=os.environ.get("TYPESAFE_MODEL", DEFAULT_MODEL))
        p.add_argument("--out", default="jev_results.jsonl", help="full answers (JSONL)")
        p.add_argument("--dry-run", action="store_true", help="build requests, estimate cost, no call")
        p.add_argument("--timeout", type=float, default=60)
        p.add_argument("--raw", action="store_true", help="ask mode: print the full JSON response")

    def batch(p):
        common(p)
        p.add_argument("--items", help="JSONL: one object per line; optional 'id'; 'text' or any fields")
        p.add_argument("--lines", help="text file: each non-empty line is an item (ids L<n>)")
        p.add_argument("--dir", help="directory: each file (or chunk) is an item")
        p.add_argument("--glob", default="*", help="file pattern under --dir (recursive)")
        p.add_argument("--chunk-chars", type=int, default=12000, help="split --dir files into chunks")
        p.add_argument("--context", help="shared context string (the research question, a claim...)")
        p.add_argument("--context-file", help="shared context from a .json or text file")
        p.add_argument("--sort", action="append", help="qid or qid=option; sort desc (repeatable)")
        p.add_argument("--keep", action="append", help="filter: qid>=0.5, topic==billing (AND, repeatable)")
        p.add_argument("--top", type=int, default=0, help="show at most N rows")
        p.add_argument("--preview", type=int, default=0, help="append first N chars of each item")
        p.add_argument("--no-unsure", action="store_true", help="hide the UNSURE section")
        p.add_argument("--workers", type=int, default=8)

    p_ask = sub.add_parser("ask", help="one state + questions")
    common(p_ask)
    g = p_ask.add_mutually_exclusive_group(required=True)
    g.add_argument("--state", help="state as a string (or JSON if it parses)")
    g.add_argument("--state-file", help="state from a .json or text file")

    p_each = sub.add_parser("each", help="one request per item")
    batch(p_each)
    p_pack = sub.add_parser("pack", help="many small items per request, one question per item")
    batch(p_pack)
    p_pack.add_argument("--max-items", type=int, default=100, help="items per request")

    args = ap.parse_args()
    key = os.environ.get("TYPESAFE_API_KEY", "")
    base = os.environ.get("TYPESAFE_BASE_URL", DEFAULT_BASE)
    questions = load_questions(args.questions)

    if not key and not args.dry_run:
        raise SystemExit("[jev] TYPESAFE_API_KEY is not set. Ask the user to export it (key from "
                         "console.typesafe.ai, or a compatible gateway via TYPESAFE_BASE_URL), or "
                         "continue without Jev by reading the items yourself.")

    try:
        if args.mode == "ask":
            if args.state_file:
                state = read_json_or_text(args.state_file)
            else:
                try:
                    state = json.loads(args.state)
                except ValueError:
                    state = args.state
            payload = {"model": args.model, "state": state, "questions": questions}
            if args.dry_run:
                dry_run([(["state"], payload)], 0)
                return
            resp = call_jev(payload, base, key, timeout=args.timeout)
            if args.raw:
                print(json.dumps(resp, indent=1, ensure_ascii=False))
                return
            print(f"# model {resp.get('model')}, input tokens {resp.get('usage', {}).get('input_tokens')}")
            for qid, ans in resp.get("answers", {}).items():
                disp, _, unsure = brief(ans)
                extra = ""
                if ans.get("type") in ("choice", "score") and ans.get("probabilities"):
                    extra = "  probs=" + json.dumps(ans["probabilities"])
                print(f"{qid}={disp}{'  ?unsure' if unsure else ''}{extra}")
            return

        items = load_items(args)
        items_by_id = {iid: v for iid, v in items}
        item_chars = sum(len(v) if isinstance(v, str) else len(json.dumps(v)) for _, v in items)
        context = load_context(args)
        if args.mode == "each":
            payloads = build_each(items, context, questions, args.model)
        else:
            payloads = build_pack(items, context, questions, args.model, args.max_items)
        if args.dry_run:
            dry_run(payloads, item_chars)
            return
        rows, errors, models, usage = run_payloads(payloads, args.mode, args, key, base)
        write_out(args.out, rows, models)
        report(args.mode, rows, items_by_id, args, len(payloads), usage, models, errors, item_chars)
    except FatalJevError as e:
        raise SystemExit(f"[jev] {e}")


if __name__ == "__main__":
    main()
