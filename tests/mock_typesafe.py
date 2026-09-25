"""Minimal offline stand-in for TypeSafe's POST /v1/systemone, used by the test suite.

Answers are deterministic: an item whose text contains "outage" is a confident yes / first
option / top level; "maybe" gives an uncertain answer; anything else is a confident no.
It does not model Jev's real behaviour; it only exercises jev.py's request/response plumbing.
"""
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

API_KEY = "test-key"


def _target_text(state, instructions):
    m = re.search(r"`items\[(\d+)\]`", instructions)
    if m and isinstance(state, dict) and "items" in state:
        return json.dumps(state["items"][int(m.group(1))])
    if isinstance(state, dict) and "item" in state:
        return json.dumps(state["item"])
    return json.dumps(state)


def _answer(question, text):
    text = text.lower()
    hit, maybe = "outage" in text, "maybe" in text
    kind = question["type"]
    if kind == "noul":
        return {"type": "noul", "noul": 0.5 if maybe else (0.95 if hit else 0.04)}
    confidence = 0.4 if maybe else 0.88
    if kind == "choice":
        options = list(question["criteria"])
        pick = options[0] if hit else options[-1]
        rest = 0.1 / max(len(options) - 1, 1)
        probs = {o: (0.9 if o == pick else rest) for o in options}
        return {"type": "choice", "choice": pick, "probabilities": probs, "confidence": confidence}
    levels = len(question["criteria"])
    return {"type": "score", "score": (levels - 1) * 0.9 if hit else 0.2,
            "legend": {}, "probabilities": {}, "confidence": confidence}


class MockTypeSafe:
    """Context manager: starts the mock on a free port and exposes .base_url and .requests."""

    def __init__(self, fail_first_with=None):
        self.fail_first_with = fail_first_with
        self.requests = []
        self._lock = threading.Lock()

    def __enter__(self):
        mock = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, obj, headers=None):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                with mock._lock:
                    mock.requests.append(body)
                    fail, mock.fail_first_with = mock.fail_first_with, None
                if fail:
                    return self._send(fail, {"detail": "overloaded"}, {"Retry-After": "0.05"})
                if self.headers.get("Authorization") != f"Bearer {API_KEY}":
                    return self._send(401, {"detail": "invalid api key"})
                if self.path != "/v1/systemone":
                    return self._send(404, {"detail": "not found"})
                answers = {}
                for qid, q in body["questions"].items():
                    text = _target_text(body["state"], json.dumps(q["instructions"]))
                    answers[qid] = _answer(q, text)
                self._send(200, {"model": "jev-1.13.0", "answers": answers,
                                 "usage": {"input_tokens": len(json.dumps(body)) // 4,
                                           "output_tokens": len(answers)}})

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self._server.server_address[1]}"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()
