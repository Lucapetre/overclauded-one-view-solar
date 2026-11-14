"""Transport abstraction: replay files listed in manifests, or fetch from a loopback mock HTTP server.

Both transports hand raw delivery lines to the same Ingestor.process_line(). Evaluation-only material (hidden
ground truth / injection labels) is refused outright.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

FORBIDDEN_NAMES = {"ground_truth", "injection_manifest.json"}


class EvaluationMaterialError(PermissionError):
    pass


def guard(path: Path):
    p = Path(path).resolve()
    parts = {x.lower() for x in p.parts}
    if parts & FORBIDDEN_NAMES or "tests" in parts:
        raise EvaluationMaterialError(f"refusing to read evaluation-only material: {p}")
    return p


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def discover(input_root: Path, datasets):
    """Yield (abs_path, rel_path, dataset, manifest_sha) for every manifest-listed file of the wanted datasets."""
    root = guard(input_root)
    manifests = []
    top = root / "manifest.json"
    if top.exists():
        for f in json.loads(top.read_text(encoding="utf-8")).get("files", []):
            if f["path"].endswith("manifest.json"):
                manifests.append(root / f["path"])
    else:
        manifests = sorted(root.glob("*/manifest.json"))
    for m in manifests:
        guard(m)
        doc = json.loads(m.read_text(encoding="utf-8"))
        for f in doc.get("files", []):
            if f.get("dataset") not in datasets:
                continue
            p = guard(m.parent / f["path"])
            yield p, p.relative_to(root).as_posix(), f["dataset"], f.get("sha256")


class HttpReplayTransport:
    """Loopback-only client with bounded retry, Retry-After support and exponential backoff.

    It yields delivery lines exactly like the file transport, so commits stay idempotent (delivery hash)."""

    def __init__(self, base_url: str, max_attempts: int = 4, base_backoff_s: float = 0.2, sleep=time.sleep,
                 timeout_s: float = 5.0):
        if not (base_url.startswith("http://127.0.0.1") or base_url.startswith("http://localhost")):
            raise ValueError("mock HTTP replay is loopback-only")
        self.base = base_url.rstrip("/")
        self.max_attempts, self.base_backoff_s, self.sleep = max_attempts, base_backoff_s, sleep
        self.timeout_s = timeout_s
        self.log = []

    def _get(self, path):
        last = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                with urllib.request.urlopen(self.base + path, timeout=self.timeout_s) as r:
                    return r.status, dict(r.headers), r.read().decode("utf-8")
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")
                if e.code in (429, 500, 502, 503) and attempt < self.max_attempts:
                    ra = e.headers.get("Retry-After")
                    wait = float(ra) if ra and ra.replace(".", "", 1).isdigit() else self.base_backoff_s * 2 ** (attempt - 1)
                    self.log.append({"path": path, "attempt": attempt, "status": e.code, "wait_s": wait})
                    self.sleep(min(wait, 5.0))
                    continue
                return e.code, dict(e.headers), body
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last = e
                self.log.append({"path": path, "attempt": attempt, "status": "timeout", "wait_s": self.base_backoff_s})
                if attempt < self.max_attempts:
                    self.sleep(self.base_backoff_s * 2 ** (attempt - 1))
        return None, {}, str(last)

    def lines(self):
        """Iterate the server's delivery index; each final response becomes one delivery line."""
        status, _, body = self._get("/replay/index")
        if status != 200:
            raise RuntimeError(f"mock index unavailable: {status} {body[:200]}")
        for item in json.loads(body)["deliveries"]:
            status, headers, body = self._get(item["url"])
            env = json.loads(headers.get("X-Mock-Transport", "{}"))
            env["http_status"] = status
            if status == 200:
                try:
                    payload = json.loads(body)
                    yield item["source"], json.dumps({"mock_transport": env, "payload": payload},
                                                     separators=(",", ":"), ensure_ascii=False)
                except json.JSONDecodeError:
                    yield item["source"], json.dumps({"mock_transport": env, "payload_text": body},
                                                     separators=(",", ":"), ensure_ascii=False)
            else:
                env["error_body_text"] = body[:300] if body else None
                if status is None:
                    env["transport_error"] = "timeout after bounded retries"
                yield item["source"], json.dumps({"mock_transport": env}, separators=(",", ":"), ensure_ascii=False)
