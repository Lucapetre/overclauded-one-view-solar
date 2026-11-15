-- Component extension (phase b): immutable component snapshot imports (meters, batteries,
-- irradiance) bridged to decisions. The snapshot file itself stays read-only next to the API
-- database; only what decisions need is copied here. Importing never grants access.
CREATE TABLE component_imports (
    import_id TEXT PRIMARY KEY,
    database_path TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    as_of_utc TEXT NOT NULL,
    scenario_version TEXT NOT NULL,
    synthetic INTEGER NOT NULL,
    meta TEXT NOT NULL
);
-- Atomic active-snapshot switch per provider site.
CREATE TABLE component_sites (
    site_id TEXT PRIMARY KEY REFERENCES sites(site_id),
    site_key TEXT NOT NULL UNIQUE,
    demo_site_key TEXT,
    import_id TEXT NOT NULL REFERENCES component_imports(import_id),
    updated_at TEXT NOT NULL
);
-- Production assets per site (a shared area station appears once per explicitly linked site).
CREATE TABLE component_assets (
    import_id TEXT NOT NULL REFERENCES component_imports(import_id),
    asset_id TEXT NOT NULL,
    site_id TEXT NOT NULL REFERENCES sites(site_id),
    source_site_key TEXT NOT NULL,
    family TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    boundary TEXT,
    mounting TEXT,
    shared_resource INTEGER NOT NULL CHECK (shared_resource IN (0,1)),
    link_basis TEXT,
    details TEXT NOT NULL,
    PRIMARY KEY (import_id, asset_id, site_id)
);
-- Capability declarations (separate from a claim that a value was recently observed).
CREATE TABLE component_capabilities (
    import_id TEXT NOT NULL REFERENCES component_imports(import_id),
    site_id TEXT NOT NULL REFERENCES sites(site_id),
    capability TEXT NOT NULL,
    declared INTEGER NOT NULL,
    state TEXT NOT NULL,
    reason TEXT,
    assets TEXT,
    PRIMARY KEY (import_id, site_id, capability)
);
-- Authoritative PCC grid energy per 15 minutes (one selected source; mirrors never summed).
CREATE TABLE component_grid_frames (
    import_id TEXT NOT NULL REFERENCES component_imports(import_id),
    site_id TEXT NOT NULL REFERENCES sites(site_id),
    metric TEXT NOT NULL CHECK (metric IN ('grid_import','grid_export')),
    frame_start TEXT NOT NULL,
    frame_end TEXT NOT NULL,
    value_kwh REAL CHECK (value_kwh IS NULL OR value_kwh >= 0),
    value_origin TEXT,
    authority_status TEXT NOT NULL,
    selected_asset_id TEXT,
    selected_endpoint_key TEXT,
    selected_basis TEXT,
    selected_coverage REAL,
    reason TEXT,
    mirrors_excluded TEXT,
    PRIMARY KEY (import_id, site_id, metric, frame_start)
);
CREATE INDEX component_grid_frames_time ON component_grid_frames(site_id, import_id, metric, frame_end);
