CREATE TABLE provider_imports (
    import_id TEXT PRIMARY KEY,
    database_path TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    as_of_utc TEXT NOT NULL,
    synthetic INTEGER NOT NULL
);
CREATE TABLE provider_sites (
    site_id TEXT PRIMARY KEY REFERENCES sites(site_id),
    site_key TEXT NOT NULL UNIQUE,
    import_id TEXT NOT NULL REFERENCES provider_imports(import_id),
    identity TEXT NOT NULL
);
CREATE TABLE provider_frames (
    import_id TEXT NOT NULL REFERENCES provider_imports(import_id),
    site_id TEXT NOT NULL REFERENCES sites(site_id),
    endpoint_key TEXT NOT NULL,
    device_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    frame_start TEXT NOT NULL,
    frame_end TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY(import_id,site_id,endpoint_key,device_id,channel,metric_name,frame_start)
);
CREATE INDEX provider_frame_time ON provider_frames(site_id,import_id,frame_start,frame_end);
