from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest

from backend.errors import ApiError
from backend.ingestion import ingest
from backend.models import TelemetryRecord


def test_roundtrip_and_duplicate(database, record):
    accepted = ingest(database, record)
    duplicate = ingest(database, record)
    assert accepted.status == "accepted"
    assert duplicate.status == "duplicate"
    with database.connect() as connection:
        row = connection.execute(
            "SELECT payload,ingested_at FROM telemetry WHERE record_id='new-record'"
        ).fetchone()
        stored = TelemetryRecord.model_validate_json(row["payload"])
        assert stored.measurements["pv_power"].requirement == "mandatory"
        assert stored.measurements["grid_import"].value == 0
        assert stored.raw_record_ref == record["raw_record_ref"]
        assert row["ingested_at"] > "2026-07-15"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(schema_version="2.0"),
        lambda r: r.update(interval_start="yesterday"),
        lambda r: r.update(interval_start="2026-07-15T12:15:00"),
        lambda r: r.update(interval_start=1784117700),
        lambda r: r.update(interval_start="1784117700"),
        lambda r: r.update(interval_start=r["interval_end"]),
        lambda r: r.update(received_at="2026-07-15T12:00:00Z"),
        lambda r: r.update(site_id="unknown"),
        lambda r: r.update(device_id="meter-s4-01"),
        lambda r: r.update(source_id="unregistered"),
        lambda r: r["measurements"]["pv_power"].update(unit="W"),
        lambda r: r["measurements"]["pv_power"].update(value=-1),
        lambda r: r["measurements"]["pv_power"].update(value=True),
        lambda r: r["measurements"]["pv_power"].update(value="6"),
        lambda r: r["measurements"]["pv_power"].update(value=float("inf")),
        lambda r: r["measurements"]["pv_power"].update(value=None),
        lambda r: r["measurements"]["pv_power"].update(boundary="not_applicable"),
        lambda r: r["measurements"]["pv_power"].update(requirement="optional"),
        lambda r: r["measurements"].update(unknown_sensor={"value": 1}),
        lambda r: r.update(unexpected="not silently discarded"),
    ],
)
def test_invalid_records_are_quarantined(database, record, mutate):
    mutate(record)
    with pytest.raises(ApiError) as error:
        ingest(database, record)
    assert error.value.status == 422
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM quarantine").fetchone()[0] == 1
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM telemetry WHERE record_id='new-record'"
            ).fetchone()[0]
            == 0
        )


def test_missing_mandatory_reading_is_explicitly_degraded(database, record):
    del record["measurements"]["pv_power"]
    result = ingest(database, record)
    assert result.status == "accepted"
    assert result.quality_flags == ["mandatory_unavailable:pv_power"]
    assert ingest(database, record).quality_flags == result.quality_flags


def test_missing_optional_readings_are_accepted(database, record):
    record["measurements"] = {"pv_power": record["measurements"]["pv_power"]}
    assert ingest(database, record).quality_flags == []


def test_changed_record_is_not_silently_overwritten(database, record):
    ingest(database, record)
    record["measurements"]["pv_power"]["value"] = 7
    with pytest.raises(ApiError) as error:
        ingest(database, record)
    assert error.value.code == "record_conflict"


def test_overlapping_intervals_are_not_double_counted(database, record):
    record.update(interval_start="2026-07-15T12:10:00Z")
    with pytest.raises(ApiError) as error:
        ingest(database, record)
    assert error.value.code == "interval_conflict"


def test_concurrent_duplicate_delivery_is_idempotent(database, record):
    with ThreadPoolExecutor(max_workers=4) as executor:
        outcomes = list(
            executor.map(lambda _: ingest(database, deepcopy(record)).status, range(4))
        )
    assert outcomes.count("accepted") == 1
    assert outcomes.count("duplicate") == 3


def test_unknown_vendor_codes_and_quality_flags_survive(database, record):
    record.update(vendor_codes=["UNMAPPED-991"], quality_flags=["interpolated"])
    ingest(database, record)
    with database.connect() as connection:
        stored = TelemetryRecord.model_validate_json(
            connection.execute(
                "SELECT payload FROM telemetry WHERE record_id='new-record'"
            ).fetchone()[0]
        )
    assert stored.vendor_codes == ["UNMAPPED-991"]
    assert stored.quality_flags == ["interpolated"]


def test_migrations_and_demo_seed_are_repeatable(database):
    from backend.seed import seed_demo

    database.migrate()
    assert seed_demo(database, "must-not-reset-passwords") == {}
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM sites").fetchone()[0] == 60
        assert connection.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0] == 59
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
