CREATE TABLE areas (
    area_id TEXT PRIMARY KEY,
    alias TEXT NOT NULL,
    topology_mode TEXT NOT NULL CHECK (topology_mode IN ('simulated','authorized','unknown'))
);
CREATE TABLE sites (
    site_id TEXT PRIMARY KEY,
    alias TEXT NOT NULL,
    area_id TEXT REFERENCES areas(area_id),
    topology_mode TEXT NOT NULL CHECK (topology_mode IN ('simulated','authorized','unknown')),
    reporting_interval_seconds INTEGER NOT NULL CHECK (reporting_interval_seconds > 0),
    stale_after_seconds INTEGER NOT NULL CHECK (stale_after_seconds > 0),
    capabilities TEXT NOT NULL,
    measurement_requirements TEXT NOT NULL
);
CREATE TABLE devices (
    device_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL REFERENCES sites(site_id),
    source_id TEXT NOT NULL,
    UNIQUE (device_id, site_id, source_id)
);
-- One designated aggregate energy stream prevents mixing meters or counting devices twice.
CREATE TABLE energy_streams (
    site_id TEXT PRIMARY KEY REFERENCES sites(site_id),
    device_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    FOREIGN KEY (device_id, site_id, source_id) REFERENCES devices(device_id, site_id, source_id)
);
CREATE TABLE users (
    user_id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('customer','dispatcher','technician','supervisor'))
);
CREATE TABLE user_sites (
    user_id TEXT NOT NULL REFERENCES users(user_id),
    site_id TEXT NOT NULL REFERENCES sites(site_id),
    PRIMARY KEY (user_id, site_id)
);
CREATE TABLE user_areas (
    user_id TEXT NOT NULL REFERENCES users(user_id),
    area_id TEXT NOT NULL REFERENCES areas(area_id),
    PRIMARY KEY (user_id, area_id)
);
CREATE TABLE sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id),
    csrf_token TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE login_attempts (
    client_key TEXT NOT NULL,
    attempted_at REAL NOT NULL
);
CREATE INDEX login_attempt_window ON login_attempts(client_key, attempted_at);
CREATE TABLE telemetry (
    id INTEGER PRIMARY KEY,
    record_id TEXT NOT NULL,
    site_id TEXT NOT NULL REFERENCES sites(site_id),
    device_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    interval_start TEXT NOT NULL,
    interval_end TEXT NOT NULL,
    received_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    UNIQUE(source_id, record_id),
    UNIQUE(site_id, device_id, source_id, interval_start, interval_end),
    FOREIGN KEY (device_id, site_id, source_id) REFERENCES devices(device_id, site_id, source_id)
);
CREATE INDEX telemetry_site_time ON telemetry(site_id, interval_end DESC, interval_start);
CREATE TABLE quarantine (
    id INTEGER PRIMARY KEY,
    received_at TEXT NOT NULL,
    request_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    reason TEXT NOT NULL
);
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE audit (
    id INTEGER PRIMARY KEY,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    subject TEXT NOT NULL,
    received_at TEXT NOT NULL,
    request_id TEXT NOT NULL
);
