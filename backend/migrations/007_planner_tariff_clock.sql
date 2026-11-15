-- Component extension (phase b): forward-only scenario clock, versioned contract tariff
-- bands, the backend business task planner and explicit fictional placement of provider sites.

-- Scenario runs. The current analytical time lives in settings.replay_at and the active run in
-- settings.scenario; these tables keep the run identity and every forward step.
CREATE TABLE scenario_runs (
    run_id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL,
    start_at TEXT NOT NULL,
    started_received_at TEXT NOT NULL
);
CREATE TABLE scenario_clock_events (
    id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES scenario_runs(run_id),
    from_at TEXT,
    to_at TEXT NOT NULL,
    received_at TEXT NOT NULL
);
CREATE INDEX scenario_clock_events_run ON scenario_clock_events(run_id, id);

-- Contracts may now be time-of-use. SQLite cannot widen a CHECK, so rebuild the table.
-- The flat rates stay the reference prices used by Power Block Offers (unchanged rule).
CREATE TABLE contracts_v7 (
    site_id TEXT PRIMARY KEY REFERENCES sites(site_id),
    supplier TEXT NOT NULL,
    pricing TEXT NOT NULL CHECK (pricing IN ('fixed','time_of_use')),
    import_price_ron_kwh REAL NOT NULL CHECK (import_price_ron_kwh > 0),
    export_price_ron_kwh REAL NOT NULL CHECK (export_price_ron_kwh >= 0),
    installed_kwp REAL CHECK (installed_kwp IS NULL OR installed_kwp > 0),
    updated_by TEXT NOT NULL REFERENCES users(user_id),
    updated_at TEXT NOT NULL,
    export_compensation TEXT NOT NULL DEFAULT 'unspecified'
        CHECK (export_compensation IN ('payment','credit','unspecified')),
    current_version_id TEXT
);
INSERT INTO contracts_v7(site_id,supplier,pricing,import_price_ron_kwh,export_price_ron_kwh,
    installed_kwp,updated_by,updated_at)
    SELECT site_id,supplier,pricing,import_price_ron_kwh,export_price_ron_kwh,installed_kwp,
        updated_by,updated_at FROM contracts;
DROP TABLE contracts;
ALTER TABLE contracts_v7 RENAME TO contracts;

-- Immutable contract versions. A save creates a new version effective from the analytical
-- time of the save; decisions record the version id they priced with.
CREATE TABLE contract_versions (
    version_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL REFERENCES sites(site_id),
    version_no INTEGER NOT NULL CHECK (version_no > 0),
    supplier TEXT NOT NULL,
    pricing TEXT NOT NULL CHECK (pricing IN ('fixed','time_of_use')),
    timezone TEXT NOT NULL CHECK (timezone = 'Europe/Bucharest'),
    export_compensation TEXT NOT NULL
        CHECK (export_compensation IN ('payment','credit','unspecified')),
    effective_from TEXT NOT NULL,
    valid_to TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_as_of TEXT NOT NULL,
    UNIQUE (site_id, version_no)
);
CREATE INDEX contract_versions_site ON contract_versions(site_id, effective_from);
-- Band occurrences start on a listed ISO weekday (1 = Monday) at local start_minute and end at
-- end_minute; end_minute <= start_minute crosses local midnight. Optional local-date validity.
CREATE TABLE contract_bands (
    version_id TEXT NOT NULL REFERENCES contract_versions(version_id),
    band_id TEXT NOT NULL,
    label TEXT,
    days TEXT NOT NULL,
    start_minute INTEGER NOT NULL CHECK (start_minute BETWEEN 0 AND 1439),
    end_minute INTEGER NOT NULL CHECK (end_minute BETWEEN 1 AND 1440),
    import_rate_ron_kwh REAL NOT NULL CHECK (import_rate_ron_kwh > 0),
    export_value_ron_kwh REAL NOT NULL CHECK (export_value_ron_kwh >= 0),
    valid_from TEXT,
    valid_to TEXT,
    PRIMARY KEY (version_id, band_id)
);
-- Existing fixed contracts become version 1 with one all-day band, valid for all history.
INSERT INTO contract_versions
    SELECT 'cv-' || site_id || '-1', site_id, 1, supplier, 'fixed', 'Europe/Bucharest',
        'unspecified', '1970-01-01T00:00:00.000000+00:00', NULL, updated_by, updated_at,
        updated_at
    FROM contracts;
INSERT INTO contract_bands
    SELECT 'cv-' || site_id || '-1', 'all-day', 'All day', '[1,2,3,4,5,6,7]', 0, 1440,
        import_price_ron_kwh, export_price_ron_kwh, NULL, NULL
    FROM contracts;
UPDATE contracts SET current_version_id = 'cv-' || site_id || '-1';

-- Business task planner: flexible, non-interruptible tasks for one authorized site.
CREATE TABLE planner_tasks (
    task_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL REFERENCES sites(site_id),
    created_by TEXT NOT NULL REFERENCES users(user_id),
    label TEXT NOT NULL,
    kind TEXT NOT NULL,
    power_kw REAL NOT NULL CHECK (power_kw > 0),
    energy_kwh REAL NOT NULL CHECK (energy_kwh > 0),
    earliest_start TEXT NOT NULL,
    deadline TEXT NOT NULL,
    latest_start TEXT,
    allowed_start_minute INTEGER CHECK (allowed_start_minute BETWEEN 0 AND 1439),
    allowed_end_minute INTEGER CHECK (allowed_end_minute BETWEEN 1 AND 1440),
    usual_start TEXT,
    site_import_limit_kw REAL CHECK (site_import_limit_kw IS NULL OR site_import_limit_kw > 0),
    status TEXT NOT NULL CHECK (status IN ('suggested','accepted','cancelled')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
    assumption_note TEXT,
    created_at TEXT NOT NULL,
    created_as_of TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX planner_tasks_site ON planner_tasks(site_id, status, earliest_start);
-- Accepted commitments are immutable snapshots; an explicit review releases one (kept here).
CREATE TABLE planner_commitments (
    commitment_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES planner_tasks(task_id),
    task_revision INTEGER NOT NULL,
    site_id TEXT NOT NULL REFERENCES sites(site_id),
    user_id TEXT NOT NULL REFERENCES users(user_id),
    start_at TEXT NOT NULL,
    end_at TEXT NOT NULL,
    power_kw REAL NOT NULL,
    energy_kwh REAL NOT NULL,
    recommendation_revision TEXT NOT NULL,
    contract_version_id TEXT,
    estimated_cost_ron REAL,
    baseline_cost_ron REAL,
    estimated_difference_ron REAL,
    decision TEXT NOT NULL,
    accepted_at TEXT NOT NULL,
    accepted_received_at TEXT NOT NULL,
    released_at TEXT,
    released_received_at TEXT,
    release_reason TEXT,
    idempotency_key TEXT
);
CREATE UNIQUE INDEX planner_commitment_active ON planner_commitments(task_id)
    WHERE released_at IS NULL;
CREATE INDEX planner_commitments_site ON planner_commitments(site_id, start_at);
CREATE UNIQUE INDEX planner_commitments_idempotency ON planner_commitments(user_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

-- Explicit, labelled fictional placement of provider-scenario sites (never set by an import).
CREATE TABLE site_placements (
    site_id TEXT PRIMARY KEY REFERENCES sites(site_id),
    area_id TEXT NOT NULL REFERENCES areas(area_id),
    latitude REAL NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude REAL NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    location_label TEXT NOT NULL,
    coordinates_fictional INTEGER NOT NULL CHECK (coordinates_fictional = 1),
    segment TEXT NOT NULL CHECK (segment IN ('home','business')),
    business_type TEXT,
    installed_kwp REAL CHECK (installed_kwp IS NULL OR installed_kwp > 0),
    -- JSON [{kwp, tilt, az}] copied from the provider site registry (planning input only).
    module_arrays TEXT,
    scenario_id TEXT NOT NULL,
    provenance TEXT NOT NULL,
    provisioned_at TEXT NOT NULL
);
CREATE INDEX site_placements_area ON site_placements(area_id);
