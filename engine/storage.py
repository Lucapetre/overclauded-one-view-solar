"""SQLite persistence: raw evidence, measurement-level observations, derived intervals, audit and health."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(
  run_id TEXT PRIMARY KEY, started_at_utc TEXT, finished_at_utc TEXT, as_of_utc TEXT, mode TEXT,
  datasets TEXT, input_root TEXT, config_hash TEXT, engine_hash TEXT, registry_version TEXT,
  deliveries_seen INTEGER, deliveries_new INTEGER, deliveries_skipped_known INTEGER,
  observations_added INTEGER, status TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS input_files(
  run_id TEXT, path TEXT, dataset TEXT, sha256_manifest TEXT, sha256_actual TEXT, checksum_ok INTEGER, lines INTEGER);
CREATE TABLE IF NOT EXISTS raw_deliveries(
  delivery_hash TEXT PRIMARY KEY, first_run_id TEXT, source_path TEXT, source_line INTEGER, dataset TEXT,
  delivery_id TEXT, provider TEXT, provider_profile_id TEXT, endpoint_key TEXT, variant TEXT, mapping_version TEXT,
  account_id TEXT, site_id TEXT, site_key TEXT, request_scope TEXT, recorded_at_ms INTEGER, received_at_ms INTEGER,
  http_status INTEGER, status TEXT, status_class TEXT, status_detail TEXT, effective_time_ms INTEGER,
  payload_hash TEXT, n_records INTEGER, synthetic INTEGER, raw_text TEXT);
CREATE TABLE IF NOT EXISTS raw_records(
  raw_record_id TEXT PRIMARY KEY, delivery_hash TEXT, record_index INTEGER, run_id TEXT, provider TEXT,
  provider_profile_id TEXT, profile_version TEXT, endpoint_key TEXT, variant TEXT, mapping_version TEXT,
  account_id TEXT, site_id TEXT, site_key TEXT, device_id TEXT, device_key TEXT, entity_scope TEXT,
  source_path TEXT, source_line INTEGER, payload_hash TEXT, content_hash TEXT, identity_key TEXT,
  source_time_raw TEXT, source_time_role TEXT, times_json TEXT, measurement_time_ms INTEGER,
  response_time_ms INTEGER, capture_time_ms INTEGER, received_at_ms INTEGER, effective_time_ms INTEGER,
  effective_time_basis TEXT, arrival_lag_s REAL, status TEXT, status_reason TEXT, duplicate_of TEXT,
  record_flags TEXT, record_json TEXT);
CREATE INDEX IF NOT EXISTS rr_identity ON raw_records(identity_key);
CREATE INDEX IF NOT EXISTS rr_series ON raw_records(site_key, endpoint_key, device_key, effective_time_ms);
CREATE TABLE IF NOT EXISTS observations(
  obs_id INTEGER PRIMARY KEY AUTOINCREMENT, raw_record_id TEXT, site_key TEXT, endpoint_key TEXT,
  device_id TEXT, device_key TEXT, entity_scope TEXT, channel TEXT, effective_time_ms INTEGER, metric_name TEXT,
  original_value TEXT, original_unit TEXT, canonical_value REAL, canonical_text TEXT, canonical_unit TEXT,
  metric_kind TEXT, boundary TEXT, value_origin TEXT, availability_status TEXT, quality_flags TEXT,
  assumption_basis TEXT, requirement_class TEXT, transform_log TEXT, field_rule_id TEXT,
  is_conflicted INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS obs_series ON observations(site_key, endpoint_key, metric_name, device_key, channel, effective_time_ms);
CREATE INDEX IF NOT EXISTS obs_raw ON observations(raw_record_id);
CREATE TABLE IF NOT EXISTS capability_states(
  site_key TEXT, endpoint_key TEXT, device_key TEXT, metric_name TEXT, channel TEXT, state TEXT, reason TEXT,
  field_rule_id TEXT, n_records INTEGER,
  PRIMARY KEY(site_key, endpoint_key, device_key, metric_name, channel, state, reason));
CREATE TABLE IF NOT EXISTS delivery_events(
  delivery_hash TEXT PRIMARY KEY, site_key TEXT, endpoint_key TEXT, status_class TEXT, http_status INTEGER,
  code TEXT, informational INTEGER, start_ms INTEGER, end_ms INTEGER, event_time_ms INTEGER, detail TEXT);
CREATE TABLE IF NOT EXISTS quality_issues(
  issue_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, stage TEXT, category TEXT, issue_code TEXT,
  severity TEXT, provider TEXT, site_key TEXT, endpoint_key TEXT, device_key TEXT, metric_name TEXT,
  raw_record_id TEXT, delivery_hash TEXT, source_path TEXT, source_line INTEGER, effective_time_ms INTEGER,
  rule_id TEXT, rule_version TEXT, mapping_version TEXT, original_value TEXT, output_state TEXT, reason TEXT,
  series_key TEXT);
CREATE INDEX IF NOT EXISTS qi_code ON quality_issues(issue_code);
CREATE TABLE IF NOT EXISTS audit_actions(
  action_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, stage TEXT, action TEXT, category TEXT,
  issue_id INTEGER, raw_record_id TEXT, delivery_hash TEXT, provider TEXT, site_key TEXT, endpoint_key TEXT,
  metric_name TEXT, rule_id TEXT, rule_version TEXT, mapping_version TEXT, original_value TEXT, output TEXT,
  reason TEXT, series_key TEXT);
CREATE TABLE IF NOT EXISTS routine_transform_counts(
  run_id TEXT, provider TEXT, endpoint_key TEXT, transform TEXT, detail TEXT, n INTEGER,
  PRIMARY KEY(run_id, provider, endpoint_key, transform, detail));
CREATE TABLE IF NOT EXISTS interval_energy(
  rule_id TEXT, series_key TEXT, site_key TEXT, endpoint_key TEXT, device_key TEXT, entity_scope TEXT,
  channel TEXT, metric_name TEXT, source_metric TEXT, priority INTEGER, start_ms INTEGER, end_ms INTEGER,
  duration_s REAL, energy_kwh REAL, status TEXT, allocatable INTEGER, value_origin TEXT, formula TEXT,
  dependencies TEXT, rule_version TEXT, PRIMARY KEY(rule_id, series_key, start_ms, end_ms));
CREATE TABLE IF NOT EXISTS source_health(
  site_key TEXT, endpoint_key TEXT, device_key TEXT, provider TEXT, variant TEXT, n_records INTEGER,
  first_source_ms INTEGER, latest_source_ms INTEGER, latest_received_ms INTEGER, cadence_s INTEGER,
  as_of_ms INTEGER, latest_source_age_s REAL, stale_threshold_s REAL, freshness_status TEXT,
  late_arrivals INTEGER, historical_gaps INTEGER, events_json TEXT, access_status TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS data_gaps(
  site_key TEXT, endpoint_key TEXT, device_key TEXT, start_ms INTEGER, end_ms INTEGER, duration_s REAL,
  gap_class TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS review_candidates(
  candidate_id TEXT PRIMARY KEY, policy_id TEXT, policy_version TEXT, site_key TEXT, endpoint_key TEXT,
  device_key TEXT, channel TEXT, metric_name TEXT, start_ms INTEGER, end_ms INTEGER, duration_s REAL,
  peak_value REAL, n_samples INTEGER, evidence TEXT, status TEXT, label TEXT, disclaimer TEXT);
"""

OBS_COLS = ["raw_record_id", "site_key", "endpoint_key", "device_id", "device_key", "entity_scope", "channel",
            "effective_time_ms", "metric_name", "original_value", "original_unit", "canonical_value",
            "canonical_text", "canonical_unit", "metric_kind", "boundary", "value_origin", "availability_status",
            "quality_flags", "assumption_basis", "requirement_class", "transform_log", "field_rule_id",
            "is_conflicted"]
RECORD_COLS = ["raw_record_id", "delivery_hash", "record_index", "run_id", "provider", "provider_profile_id",
               "profile_version", "endpoint_key", "variant", "mapping_version", "account_id", "site_id", "site_key",
               "device_id", "device_key", "entity_scope", "source_path", "source_line", "payload_hash",
               "content_hash", "identity_key", "source_time_raw", "source_time_role", "times_json",
               "measurement_time_ms", "response_time_ms", "capture_time_ms", "received_at_ms", "effective_time_ms",
               "effective_time_basis", "arrival_lag_s", "status", "status_reason", "duplicate_of", "record_flags",
               "record_json"]
DELIVERY_COLS = ["delivery_hash", "first_run_id", "source_path", "source_line", "dataset", "delivery_id",
                 "provider", "provider_profile_id", "endpoint_key", "variant", "mapping_version", "account_id",
                 "site_id", "site_key", "request_scope", "recorded_at_ms", "received_at_ms", "http_status", "status",
                 "status_class", "status_detail", "effective_time_ms", "payload_hash", "n_records", "synthetic",
                 "raw_text"]
ISSUE_COLS = ["run_id", "stage", "category", "issue_code", "severity", "provider", "site_key", "endpoint_key",
              "device_key", "metric_name", "raw_record_id", "delivery_hash", "source_path", "source_line",
              "effective_time_ms", "rule_id", "rule_version", "mapping_version", "original_value", "output_state",
              "reason", "series_key"]
ACTION_COLS = ["run_id", "stage", "action", "category", "issue_id", "raw_record_id", "delivery_hash", "provider",
               "site_key", "endpoint_key", "metric_name", "rule_id", "rule_version", "mapping_version",
               "original_value", "output", "reason", "series_key"]
INTERVAL_COLS = ["rule_id", "series_key", "site_key", "endpoint_key", "device_key", "entity_scope", "channel",
                 "metric_name", "source_metric", "priority", "start_ms", "end_ms", "duration_s", "energy_kwh",
                 "status", "allocatable", "value_origin", "formula", "dependencies", "rule_version"]

CANONICAL_VIEW = """
CREATE VIEW IF NOT EXISTS canonical_observations AS
SELECT o.obs_id, r.provider, r.profile_version AS provider_profile_version, r.provider_profile_id,
       r.mapping_version, r.endpoint_key, r.variant AS profile_variant, r.account_id, r.site_id, o.site_key,
       o.device_id, o.device_key, o.entity_scope, o.channel, o.raw_record_id, r.payload_hash, r.content_hash,
       r.source_path, r.source_line, r.source_time_raw, r.source_time_role,
       strftime('%Y-%m-%dT%H:%M:%fZ', r.measurement_time_ms/1000.0, 'unixepoch') AS measurement_time_utc,
       strftime('%Y-%m-%dT%H:%M:%fZ', r.response_time_ms/1000.0, 'unixepoch') AS response_time_utc,
       strftime('%Y-%m-%dT%H:%M:%fZ', r.capture_time_ms/1000.0, 'unixepoch') AS capture_time_utc,
       strftime('%Y-%m-%dT%H:%M:%fZ', r.received_at_ms/1000.0, 'unixepoch') AS received_at_utc,
       strftime('%Y-%m-%dT%H:%M:%fZ', o.effective_time_ms/1000.0, 'unixepoch') AS effective_time_utc,
       r.effective_time_basis, o.metric_name, o.original_value, o.original_unit, o.canonical_value,
       o.canonical_text, o.canonical_unit, o.metric_kind, o.boundary, o.value_origin, o.availability_status,
       o.quality_flags, o.is_conflicted, o.assumption_basis, o.requirement_class, o.transform_log,
       o.field_rule_id, r.status AS record_status
FROM observations o JOIN raw_records r ON r.raw_record_id = o.raw_record_id;
"""


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(self.path))
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA synchronous=NORMAL")
        self.con.execute("PRAGMA cache_size=-262144")
        self.con.execute("PRAGMA temp_store=MEMORY")
        self.con.executescript(SCHEMA)
        self.con.executescript(CANONICAL_VIEW)

    def q(self, sql, args=()):
        return self.con.execute(sql, args).fetchall()

    def insert_many(self, table, cols, rows, verb="INSERT"):
        if not rows:
            return
        sql = f"{verb} INTO {table}({','.join(cols)}) VALUES({','.join('?' * len(cols))})"
        self.con.executemany(sql, rows)

    def insert_one(self, table, cols, row) -> int:
        cur = self.con.execute(f"INSERT INTO {table}({','.join(cols)}) VALUES({','.join('?' * len(cols))})", row)
        return cur.lastrowid

    def commit(self):
        self.con.commit()

    def close(self):
        self.con.commit()
        self.con.close()
