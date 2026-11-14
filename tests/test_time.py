"""Timestamp roles, Europe/Bucharest DST ambiguity / nonexistence, epoch/offset parsing and DST frame counts."""
import sqlite3
from datetime import date

import pytest

from engine.timeparse import local_day_frames, parse_time

TZ = "Europe/Bucharest"


def test_ambiguous_and_nonexistent_local_times_are_not_guessed():
    amb = parse_time("2026-10-25 03:15:00", "local_naive", TZ)
    gap = parse_time("2026-03-29 03:30:00", "local_naive", TZ)
    ok = parse_time("2026-10-25 04:15:00", "local_naive", TZ)
    assert amb.status == "ambiguous_local_time" and amb.utc is None
    assert gap.status == "nonexistent_local_time" and gap.utc is None
    assert ok.status == "ok" and ok.utc.isoformat() == "2026-10-25T02:15:00+00:00"


def test_explicit_offsets_resolve_the_repeated_hour():
    a = parse_time("2026-10-25T03:15:00+03:00", "iso_offset")
    b = parse_time("2026-10-25T03:15:00+02:00", "iso_offset")
    assert a.status == b.status == "ok" and (b.utc - a.utc).total_seconds() == 3600


@pytest.mark.parametrize("raw,fmt,status", [
    ("2026-07-16T12:00:00", "iso_offset", "missing_offset"),
    (1784192400, "epoch_ms", "invalid"),            # seconds passed where ms expected: unit not guessed
    (1784192400000, "epoch_ms", "ok"),
    ("16/07/2026 12:00", "local_naive", "invalid"),
    (None, "epoch_ms", "missing"),
    (True, "epoch_ms", "invalid"),
])
def test_time_formats(raw, fmt, status):
    assert parse_time(raw, fmt, TZ).status == status


def test_quarter_hours_per_local_day_follow_dst():
    assert len(local_day_frames(date(2026, 3, 29), TZ)) == 92
    assert len(local_day_frames(date(2026, 7, 15), TZ)) == 96
    assert len(local_day_frames(date(2026, 10, 25), TZ)) == 100


def test_dst_side_dataset(build):
    con = sqlite3.connect(str(build / "side" / "dst_edge_cases.sqlite"))
    rows = con.execute("SELECT provider, source_time_raw, status, status_reason, effective_time_ms FROM raw_records").fetchall()
    se = [r for r in rows if r[0] == "solaredge"]
    amb = [r for r in se if r[1] is None or "03:15" in (r[3] or "") or r[2] == "quarantined"]
    reasons = " ".join(r[3] or "" for r in se)
    assert sum(1 for r in se if r[2] == "quarantined") == 3  # two repeated 03:15 + one nonexistent 03:30
    assert "ambiguous_local_time" in reasons and "nonexistent_local_time" in reasons
    assert all(r[2] == "accepted" for r in se if r[2] != "quarantined") and len(se) == 9
    fr = [r for r in rows if r[0] == "fronius"]
    assert len(fr) == 6 and all(r[2] == "accepted" for r in fr)
    assert len({r[4] for r in fr}) == 6  # +03:00 and +02:00 copies of 03:15/03:45 are distinct instants
    assert amb
