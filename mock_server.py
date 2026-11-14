#!/usr/bin/env python3
"""Loopback-only mock HTTP server that replays SYNTHETIC delivery files as provider-like HTTP responses.

    python mock_server.py --input demo_data --files huawei/delivery/getDevRealKpi.ndjson --port 8765
    python scraper.py --config config/provider_profiles.yaml --input demo_data --out build_http \
        --as-of 2026-07-22T00:00:00+03:00 --http http://127.0.0.1:8765

* GET /replay/index           -> list of delivery URLs
* GET /replay/d/<n>           -> native payload body (status from the recorded envelope); the mock transport
                                 envelope travels in the X-Mock-Transport header, never inside the payload
* every --rate-limit-every-th delivery answers 429 + Retry-After on its first attempt
* every --slow-every-th delivery stalls longer than the client timeout on its first attempt

It binds to 127.0.0.1 only, exposes no write/command endpoint and never contacts a vendor system.
"""
from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class ReplayState:
    def __init__(self, lines, rate_limit_every=5, slow_every=0, slow_s=1.5, retry_after_s=0.2):
        self.items = []
        for src, line in lines:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                obj = {"mock_transport": {"http_status": 200}, "payload_text": line}  # serve broken body verbatim
            self.items.append((src, obj))
        self.attempts = {}
        self.rate_limit_every, self.slow_every = rate_limit_every, slow_every
        self.slow_s, self.retry_after_s = slow_s, retry_after_s
        self.lock = threading.Lock()


def make_handler(state: ReplayState):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body: str, headers=None):
            data = body.encode("utf-8")
            try:
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass  # client already gave up (simulated timeout)

        def do_GET(self):
            if self.path == "/replay/index":
                idx = [{"url": f"/replay/d/{i}", "source": src} for i, (src, _) in enumerate(state.items)]
                return self._send(200, json.dumps({"synthetic": True, "deliveries": idx}))
            if self.path.startswith("/replay/d/"):
                i = int(self.path.rsplit("/", 1)[1])
                src, obj = state.items[i]
                with state.lock:
                    n = state.attempts[i] = state.attempts.get(i, 0) + 1
                if state.slow_every and i % state.slow_every == 1 and n == 1:
                    time.sleep(state.slow_s)
                if state.rate_limit_every and i % state.rate_limit_every == 0 and n == 1:
                    return self._send(429, '{"error":"synthetic rate limit"}',
                                      {"Retry-After": str(state.retry_after_s)})
                env = dict(obj.get("mock_transport", {}))
                status = env.pop("http_status", 200) or 200
                hdr = {"X-Mock-Transport": json.dumps(env, separators=(",", ":"))}
                if status != 200:
                    return self._send(status, env.get("error_body_text") or "", hdr)
                body = obj["payload_text"] if "payload_text" in obj else json.dumps(obj.get("payload"),
                                                                                    separators=(",", ":"))
                return self._send(200, body, hdr)
            self._send(404, '{"error":"not found"}')

        def do_POST(self):  # no write / command interface exists
            self._send(405, '{"error":"read-only mock"}')

    return H


def serve(lines, port=0, **kw):
    state = ReplayState(lines, **kw)
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state))
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    return srv, state


def load_lines(input_root: Path, files):
    out = []
    for f in files:
        for line in (input_root / f).read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append((f, line))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", default="demo_data")
    ap.add_argument("--files", nargs="+", required=True, help="delivery files relative to --input")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--rate-limit-every", type=int, default=5)
    ap.add_argument("--slow-every", type=int, default=0)
    args = ap.parse_args(argv)
    srv, _ = serve(load_lines(Path(args.input), args.files), args.port, rate_limit_every=args.rate_limit_every,
                   slow_every=args.slow_every)
    print(f"[mock_server] SYNTHETIC replay on http://127.0.0.1:{srv.server_address[1]} (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
