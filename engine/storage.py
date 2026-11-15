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


# ------------------------------------------------------------------ component (extended) snapshot only
# Extra canonical-meaning columns of observations. They exist ONLY in component snapshots (Store(extended=True));
# provider snapshots keep the original schema unchanged.
OBS_EXTRA_COLS = ["family", "profile_version", "physical_asset_id", "mounting", "sensor_position", "phase",
                  "aggregation", "interval_start_ms", "interval_end_ms", "scenario_version", "source_role",
                  "exact_value_text", "state_label"]
_EXTRA_TYPES = {"interval_start_ms": "INTEGER", "interval_end_ms": "INTEGER"}

FRAME_COLS = ["site_key", "demo_site_key", "endpoint_key", "provider_profile_id", "family", "physical_asset_id",
              "device_key", "metric_name", "channel", "phase", "boundary", "mounting", "sensor_position",
              "source_aggregation", "frame_aggregation", "rule_id", "basis", "frame_start_utc", "frame_end_utc",
              "frame_start_local", "frame_start_ms", "value", "value_time_utc", "unit", "n_obs",
              "original_cadence_s", "coverage_ratio", "value_origin", "frame_status", "scenario_version"]
AUTH_COLS = ["site_key", "demo_site_key", "boundary", "metric_name", "frame_start_utc", "frame_end_utc",
             "frame_start_ms", "value_kwh", "selected_rank", "selected_role", "selected_basis",
             "selected_asset_id", "selected_endpoint_key", "selected_rule_id", "selected_coverage", "value_origin",
             "authority_status", "reason", "mirrors_excluded", "candidates_json", "policy_version"]

COMPONENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS component_meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS site_registry(
  site_key TEXT PRIMARY KEY, kind TEXT, demo_site_key TEXT, backend_site_id TEXT, timezone TEXT, json TEXT);
CREATE TABLE IF NOT EXISTS asset_registry(
  asset_id TEXT PRIMARY KEY, site_key TEXT, demo_site_key TEXT, family TEXT, profile_id TEXT, device_id TEXT,
  source_role TEXT, boundary TEXT, mounting TEXT, json TEXT);
CREATE TABLE IF NOT EXISTS component_frames(
  site_key TEXT, demo_site_key TEXT, endpoint_key TEXT, provider_profile_id TEXT, family TEXT,
  physical_asset_id TEXT, device_key TEXT, metric_name TEXT, channel TEXT, phase TEXT, boundary TEXT, mounting TEXT,
  sensor_position TEXT, source_aggregation TEXT, frame_aggregation TEXT, rule_id TEXT, basis TEXT,
  frame_start_utc TEXT, frame_end_utc TEXT, frame_start_local TEXT, frame_start_ms INTEGER, value REAL,
  value_time_utc TEXT, unit TEXT, n_obs INTEGER, original_cadence_s INTEGER, coverage_ratio REAL,
  value_origin TEXT, frame_status TEXT, scenario_version TEXT);
CREATE INDEX IF NOT EXISTS cf_series ON component_frames(site_key, metric_name, frame_start_ms);
CREATE TABLE IF NOT EXISTS authority_frames(
  site_key TEXT, demo_site_key TEXT, boundary TEXT, metric_name TEXT, frame_start_utc TEXT, frame_end_utc TEXT,
  frame_start_ms INTEGER, value_kwh REAL, selected_rank INTEGER, selected_role TEXT, selected_basis TEXT,
  selected_asset_id TEXT, selected_endpoint_key TEXT, selected_rule_id TEXT, selected_coverage REAL,
  value_origin TEXT, authority_status TEXT, reason TEXT, mirrors_excluded TEXT, candidates_json TEXT,
  policy_version TEXT, PRIMARY KEY(site_key, boundary, metric_name, frame_start_ms));
CREATE TABLE IF NOT EXISTS authority_conflicts(
  site_key TEXT, boundary TEXT, metric_name TEXT, frame_start_utc TEXT, frame_start_ms INTEGER,
  primary_value REAL, other_role TEXT, other_asset_id TEXT, other_endpoint_key TEXT, other_basis TEXT,
  other_value REAL, abs_diff REAL, tolerance REAL, resolution TEXT);
CREATE TABLE IF NOT EXISTS capability_registry(
  site_key TEXT, demo_site_key TEXT, capability TEXT, declared INTEGER, declared_basis TEXT, assets TEXT,
  observed_valid INTEGER, first_valid_utc TEXT, last_valid_utc TEXT, state TEXT, reason TEXT,
  PRIMARY KEY(site_key, capability));
CREATE TABLE IF NOT EXISTS state_episodes(
  site_key TEXT, physical_asset_id TEXT, metric_name TEXT, channel TEXT, state_value TEXT, state_label TEXT,
  start_utc TEXT, last_seen_utc TEXT, start_ms INTEGER, last_seen_ms INTEGER, n_obs INTEGER,
  active_at_as_of INTEGER, first_obs_id INTEGER, last_obs_id INTEGER);
CREATE TABLE IF NOT EXISTS limit_history(
  site_key TEXT, physical_asset_id TEXT, metric_name TEXT, value REAL, unit TEXT, start_utc TEXT,
  last_seen_utc TEXT, start_ms INTEGER, last_seen_ms INTEGER, n_obs INTEGER, declared_nominal REAL,
  below_declared_nominal INTEGER, first_obs_id INTEGER, last_obs_id INTEGER);
CREATE TABLE IF NOT EXISTS battery_status(
  site_key TEXT, demo_site_key TEXT, physical_asset_id TEXT, profile_id TEXT, as_of_utc TEXT,
  soc_pct REAL, soc_time_utc TEXT, soc_obs_id INTEGER, soc_age_s REAL, limits_available INTEGER,
  max_charge_current_a REAL, max_discharge_current_a REAL, max_charge_voltage_v REAL,
  min_discharge_voltage_v REAL, limits_time_utc TEXT, active_alarms TEXT, battery_state_raw TEXT,
  capacity_ah REAL, declared_json TEXT, capability_json TEXT);
CREATE TABLE IF NOT EXISTS collector_outages(
  collector_id TEXT, start_utc TEXT, end_utc TEXT, start_ms INTEGER, end_ms INTEGER, affected_site_keys TEXT,
  endpoints TEXT, failed_attempts INTEGER, failure_classes TEXT, evidence_delivery_hashes TEXT, detail TEXT);
"""

COMPONENT_VIEW = """
CREATE VIEW IF NOT EXISTS component_observations AS
SELECT o.obs_id, r.provider, r.provider_profile_id, o.profile_version, r.mapping_version, r.endpoint_key,
       r.variant AS profile_variant, o.family, o.site_key, o.device_id, o.device_key, o.physical_asset_id,
       o.entity_scope, o.channel, o.phase, o.raw_record_id, r.content_hash,
       strftime('%Y-%m-%dT%H:%M:%fZ', r.measurement_time_ms/1000.0, 'unixepoch') AS measurement_time_utc,
       strftime('%Y-%m-%dT%H:%M:%fZ', r.capture_time_ms/1000.0, 'unixepoch') AS capture_time_utc,
       strftime('%Y-%m-%dT%H:%M:%fZ', r.received_at_ms/1000.0, 'unixepoch') AS received_at_utc,
       strftime('%Y-%m-%dT%H:%M:%fZ', o.effective_time_ms/1000.0, 'unixepoch') AS effective_time_utc,
       o.effective_time_ms,
       strftime('%Y-%m-%dT%H:%M:%fZ', o.interval_start_ms/1000.0, 'unixepoch') AS interval_start_utc,
       strftime('%Y-%m-%dT%H:%M:%fZ', o.interval_end_ms/1000.0, 'unixepoch') AS interval_end_utc,
       r.effective_time_basis, o.metric_name, o.canonical_value, o.exact_value_text, o.canonical_text,
       o.state_label, o.canonical_unit, o.metric_kind, o.boundary, o.mounting, o.sensor_position, o.aggregation,
       o.value_origin, o.availability_status, o.quality_flags, o.is_conflicted, o.assumption_basis,
       o.requirement_class, o.transform_log, o.field_rule_id, o.scenario_version, o.source_role,
       r.status AS record_status
FROM observations o JOIN raw_records r ON r.raw_record_id = o.raw_record_id;
"""


class Store:
    def __init__(self, path: Path, extended: bool = False):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(self.path))
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA synchronous=NORMAL")
        self.con.execute("PRAGMA cache_size=-262144")
        self.con.execute("PRAGMA temp_store=MEMORY")
        self.con.executescript(SCHEMA)
        self.con.executescript(CANONICAL_VIEW)
        self.extended = extended
        self.obs_cols = list(OBS_COLS)
        if extended:
            have = {r[1] for r in self.con.execute("PRAGMA table_info(observations)")}
            for c in OBS_EXTRA_COLS:
                if c not in have:
                    self.con.execute(f"ALTER TABLE observations ADD COLUMN {c} {_EXTRA_TYPES.get(c, 'TEXT')}")
            self.con.executescript(COMPONENT_SCHEMA)
            self.con.executescript(COMPONENT_VIEW)
            self.con.execute("CREATE INDEX IF NOT EXISTS obs_asset ON observations(physical_asset_id, metric_name, "
                             "effective_time_ms)")
            self.obs_cols += OBS_EXTRA_COLS

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
