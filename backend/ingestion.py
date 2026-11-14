import hashlib
import json
import sqlite3
from typing import Any

from pydantic import ValidationError

from backend.db import Database, site_from_row, stamp
from backend.errors import ApiError
from backend.models import IngestResult, Metric, TelemetryRecord


def ingest(
    database: Database, payload: Any, request_id: str = "local-import"
) -> IngestResult:
    """Single handoff for a local worker, CLI import, or authenticated HTTP pipeline."""
    try:
        record = TelemetryRecord.model_validate(payload)
        canonical = json.dumps(
            record.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )
        fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
        with database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM sites WHERE site_id=?", (record.site_id,)
            ).fetchone()
            if not row:
                raise ValueError("Site is not registered")
            site = site_from_row(row)
            stream = connection.execute(
                "SELECT 1 FROM energy_streams WHERE site_id=? AND device_id=? AND source_id=?",
                (record.site_id, record.device_id, record.source_id),
            ).fetchone()
            if not stream:
                raise ValueError(
                    "Device and source are not the registered site energy stream"
                )
            existing = connection.execute(
                "SELECT fingerprint,payload FROM telemetry WHERE source_id=? AND record_id=?",
                (record.source_id, record.record_id),
            ).fetchone()
            if existing:
                if existing["fingerprint"] != fingerprint:
                    raise ApiError(
                        409,
                        "record_conflict",
                        "This record identifier already has different content",
                    )
                previous = TelemetryRecord.model_validate_json(existing["payload"])
                return IngestResult(
                    record_id=record.record_id,
                    status="duplicate",
                    quality_flags=previous.quality_flags,
                )
            for metric, reading in record.measurements.items():
                if metric not in site.capabilities:
                    if reading.availability != "unsupported":
                        raise ValueError(f"{metric.value} is unsupported by this site")
                elif reading.availability == "unsupported":
                    raise ValueError(
                        f"{metric.value} is declared as a supported site capability"
                    )
                requirement = site.measurement_requirements.get(metric, "optional")
                if reading.requirement != requirement:
                    raise ValueError(
                        f"{metric.value} requirement differs from the registered contract"
                    )
            for metric, requirement in site.measurement_requirements.items():
                reading = record.measurements.get(metric)
                if requirement == "mandatory" and (
                    reading is None or reading.availability != "available"
                ):
                    record.quality_flags.append(f"mandatory_unavailable:{metric.value}")
            # Do not compare or aggregate overlapping sample intervals as independent energy.
            if connection.execute(
                "SELECT 1 FROM telemetry WHERE site_id=? AND interval_start<? AND interval_end>?",
                (
                    record.site_id,
                    stamp(record.interval_end),
                    stamp(record.interval_start),
                ),
            ).fetchone():
                raise ApiError(
                    409,
                    "interval_conflict",
                    "An overlapping interval already exists for this site",
                )
            # Direction changes within an averaged interval are possible and must stay visible.
            for first, second in (
                (Metric.grid_import, Metric.grid_export),
                (Metric.battery_charge, Metric.battery_discharge),
            ):
                a, b = record.measurements.get(first), record.measurements.get(second)
                if a and b and a.value and b.value and a.boundary == b.boundary:
                    # Interval averages can include both directions; preserve that fact rather than reject.
                    record.quality_flags.append(
                        f"bidirectional_interval:{first.value}:{second.value}"
                    )
            record.quality_flags = sorted(set(record.quality_flags))
            connection.execute(
                "INSERT INTO telemetry(record_id,site_id,device_id,source_id,interval_start,interval_end,"
                "received_at,ingested_at,payload,fingerprint) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    record.record_id,
                    record.site_id,
                    record.device_id,
                    record.source_id,
                    stamp(record.interval_start),
                    stamp(record.interval_end),
                    stamp(record.received_at),
                    stamp(),
                    record.model_dump_json(),
                    fingerprint,
                ),
            )
            database.audit(
                connection,
                "pipeline",
                "telemetry.accepted",
                record.record_id,
                request_id,
            )
        return IngestResult(
            record_id=record.record_id,
            status="accepted",
            quality_flags=record.quality_flags,
        )
    except (ValidationError, ValueError, ApiError, sqlite3.IntegrityError) as exc:
        with database.connect() as connection:
            connection.execute(
                "INSERT INTO quarantine(received_at,request_id,payload,reason) VALUES (?,?,?,?)",
                (stamp(), request_id, json.dumps(payload, default=str), str(exc)),
            )
            database.audit(
                connection, "pipeline", "telemetry.rejected", "quarantine", request_id
            )
        if isinstance(exc, ApiError):
            raise
        raise ApiError(
            422,
            "invalid_telemetry",
            "Telemetry failed contract validation; inspect backend quarantine",
        ) from exc
