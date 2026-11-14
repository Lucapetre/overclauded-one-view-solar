"""Optional loopback HTTP replay: bounded retry with Retry-After/backoff, timeouts, and no duplicate commits."""
import sqlite3

import pytest

from conftest import AS_OF, CONFIG


def test_http_replay_retries_and_commits_once(gen, tmp_path):
    import mock_server
    import scraper
    from engine.transport import HttpReplayTransport

    files = ["huawei/delivery/getDevRealKpi.ndjson"]
    lines = mock_server.load_lines(gen / "demo_data", files)
    srv, state = mock_server.serve(lines, 0, rate_limit_every=5, slow_every=7, slow_s=0.8, retry_after_s=0.05)
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        db = tmp_path / "http.sqlite"
        _, _, store, _ = scraper.ingest([CONFIG], gen / "demo_data", db, AS_OF, [], http_url=url,
                                        log=lambda m: None, http_timeout_s=0.3)
        n_http = store.con.execute("SELECT COUNT(*) FROM raw_records WHERE status='accepted'").fetchone()[0]
        notes = store.con.execute("SELECT notes FROM runs").fetchone()[0]
        store.close()
        assert n_http == len(lines)
        assert '"http_retry_attempts"' in notes
        assert max(state.attempts.values()) >= 2  # 429 and timeouts were retried
        # rerun: every delivery already committed -> nothing new
        _, _, store, _ = scraper.ingest([CONFIG], gen / "demo_data", db, AS_OF, [], http_url=url,
                                        log=lambda m: None, http_timeout_s=0.3)
        assert store.con.execute("SELECT COUNT(*) FROM raw_records").fetchone()[0] == n_http
        store.close()
    finally:
        srv.shutdown()


def test_http_transport_is_loopback_only():
    from engine.transport import HttpReplayTransport
    with pytest.raises(ValueError):
        HttpReplayTransport("https://example.com")


def test_bounded_retry_gives_up(tmp_path):
    from engine.transport import HttpReplayTransport
    t = HttpReplayTransport("http://127.0.0.1:9", max_attempts=3, base_backoff_s=0.01, sleep=lambda s: None,
                            timeout_s=0.2)
    status, _, _ = t._get("/replay/index")
    assert status is None and len(t.log) == 3
