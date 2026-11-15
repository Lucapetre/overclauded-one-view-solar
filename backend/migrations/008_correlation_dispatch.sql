-- Component extension (phase c): correlated incident episodes, rank explanations, priority
-- overrides, synthetic planning inputs, crew plans and assignment revisions. Existing incident,
-- log and assignment tables are reused; correlated episodes ARE incidents (work orders).

-- One monotonic operations revision shared by queue, detail, map and planner.
CREATE TABLE ops_revisions (
    id INTEGER PRIMARY KEY,
    reason TEXT NOT NULL,
    subject TEXT,
    created_at TEXT NOT NULL,
    created_as_of TEXT NOT NULL
);
INSERT INTO ops_revisions(reason, subject, created_at, created_as_of)
    VALUES ('migration_008', NULL, strftime('%Y-%m-%dT%H:%M:%fZ','now'),
            strftime('%Y-%m-%dT%H:%M:%fZ','now'));

CREATE TABLE rule_revisions (
    rule_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    ruleset_version TEXT NOT NULL,
    rule_hash TEXT NOT NULL,
    definition TEXT NOT NULL,
    first_used_as_of TEXT NOT NULL,
    PRIMARY KEY (rule_id, revision)
);

CREATE TABLE correlation_runs (
    run_id TEXT PRIMARY KEY,
    as_of TEXT NOT NULL,
    ruleset_version TEXT NOT NULL,
    source TEXT NOT NULL,
    site_results TEXT NOT NULL,
    counts TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX correlation_runs_as_of ON correlation_runs(as_of);

CREATE TABLE episodes (
    incident_id TEXT PRIMARY KEY REFERENCES incidents(incident_id),
    identity TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    rule_id TEXT NOT NULL,
    rule_revision INTEGER NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('active','resolved')),
    confidence TEXT NOT NULL CHECK (confidence IN ('reported','corroborated','suspected','insufficient')),
    confidence_basis TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('monitor','remote_review','remote_troubleshooting','field_visit','external_review')),
    responsibility TEXT NOT NULL CHECK (responsibility IN ('customer_installation_service','distributor_network_review','monitoring_provider','unknown')),
    responsibility_basis TEXT NOT NULL,
    service_key TEXT,
    hypothesis TEXT NOT NULL,
    metrics TEXT NOT NULL,
    impact TEXT NOT NULL,
    reason_codes TEXT NOT NULL,
    site_ids TEXT NOT NULL,
    asset_ids TEXT NOT NULL,
    parent_incident_id TEXT REFERENCES incidents(incident_id),
    first_observed_at TEXT,
    last_observed_at TEXT,
    window_start TEXT,
    window_end TEXT,
    opened_as_of TEXT NOT NULL,
    updated_as_of TEXT NOT NULL,
    resolved_as_of TEXT,
    resolution_kind TEXT CHECK (resolution_kind IS NULL OR resolution_kind IN ('recovery_rule','authorized_closure')),
    resolution_detail TEXT,
    resolved_by TEXT,
    hold_note TEXT,
    acknowledged_by TEXT,
    acknowledged_as_of TEXT,
    repeat_count INTEGER NOT NULL DEFAULT 0,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
    UNIQUE (identity, sequence)
);
-- Deduplication: at most one active episode per asset/condition identity.
CREATE UNIQUE INDEX episodes_one_active ON episodes(identity) WHERE state = 'active';
CREATE TABLE episode_sites (
    incident_id TEXT NOT NULL REFERENCES incidents(incident_id),
    site_id TEXT NOT NULL REFERENCES sites(site_id),
    role TEXT NOT NULL CHECK (role IN ('primary','affected')),
    PRIMARY KEY (incident_id, site_id)
);
CREATE INDEX episode_sites_site ON episode_sites(site_id);
CREATE TABLE episode_evidence (
    id INTEGER PRIMARY KEY,
    incident_id TEXT NOT NULL REFERENCES incidents(incident_id),
    evidence_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    source_id TEXT NOT NULL,
    independent_group TEXT NOT NULL,
    mirror_of TEXT,
    observed_from TEXT,
    observed_to TEXT,
    summary TEXT NOT NULL,
    added_revision INTEGER NOT NULL,
    added_as_of TEXT NOT NULL,
    UNIQUE (incident_id, evidence_id)
);
-- Parent-child impact attribution (physical loss stays on the children; counted once).
CREATE TABLE episode_links (
    parent_incident_id TEXT NOT NULL REFERENCES incidents(incident_id),
    child_incident_id TEXT NOT NULL REFERENCES incidents(incident_id),
    relation_id TEXT NOT NULL,
    basis TEXT NOT NULL,
    attribution TEXT NOT NULL,
    created_as_of TEXT NOT NULL,
    PRIMARY KEY (parent_incident_id, child_incident_id)
);

CREATE TABLE rank_snapshots (
    id INTEGER PRIMARY KEY,
    incident_id TEXT NOT NULL REFERENCES incidents(incident_id),
    ops_revision INTEGER NOT NULL,
    context TEXT NOT NULL CHECK (context IN ('correlation','plan','override')),
    policy_version TEXT NOT NULL,
    band TEXT NOT NULL,
    computed_band TEXT NOT NULL,
    score REAL NOT NULL,
    digest TEXT NOT NULL,
    explanation TEXT NOT NULL,
    rank_as_of TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX rank_snapshots_incident ON rank_snapshots(incident_id, id);

CREATE TABLE priority_overrides (
    override_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL REFERENCES incidents(incident_id),
    band TEXT NOT NULL CHECK (band IN ('P0','P1','P2','P3')),
    original_band TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_by TEXT NOT NULL REFERENCES users(user_id),
    created_at TEXT NOT NULL,
    created_as_of TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_by TEXT,
    revoked_at TEXT,
    revoked_as_of TEXT
);
CREATE INDEX priority_overrides_incident ON priority_overrides(incident_id, created_as_of);

-- SYNTHETIC planning inputs (demo_components/operations_inputs.json), provisioned locally.
CREATE TABLE crew_profiles (
    crew_id TEXT PRIMARY KEY REFERENCES crews(crew_id),
    kind TEXT NOT NULL CHECK (kind IN ('field','remote_desk')),
    organisation TEXT NOT NULL,
    authorised_services TEXT NOT NULL,
    qualifications TEXT NOT NULL,
    tools TEXT NOT NULL,
    areas TEXT NOT NULL,
    base_node TEXT,
    location_reported_at TEXT,
    location_basis TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    provenance TEXT NOT NULL
);
CREATE TABLE crew_shifts (
    crew_id TEXT NOT NULL REFERENCES crews(crew_id),
    shift_start TEXT NOT NULL,
    shift_end TEXT NOT NULL,
    breaks TEXT NOT NULL,
    PRIMARY KEY (crew_id, shift_start)
);
CREATE TABLE member_unavailability (
    user_id TEXT NOT NULL REFERENCES users(user_id),
    start_at TEXT NOT NULL,
    end_at TEXT NOT NULL,
    reason TEXT NOT NULL,
    PRIMARY KEY (user_id, start_at)
);
CREATE TABLE planning_nodes (
    node_id TEXT PRIMARY KEY,
    site_id TEXT REFERENCES sites(site_id),
    latitude REAL NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude REAL NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    label TEXT NOT NULL,
    fictional INTEGER NOT NULL CHECK (fictional = 1)
);
CREATE TABLE travel_times (
    from_node TEXT NOT NULL REFERENCES planning_nodes(node_id),
    to_node TEXT NOT NULL REFERENCES planning_nodes(node_id),
    minutes INTEGER NOT NULL CHECK (minutes >= 0),
    source TEXT NOT NULL,
    as_of TEXT NOT NULL,
    PRIMARY KEY (from_node, to_node)
);
CREATE TABLE job_templates (
    rule_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    activity TEXT NOT NULL,
    spec TEXT NOT NULL,
    PRIMARY KEY (rule_id, seq)
);
CREATE TABLE site_access_windows (
    site_id TEXT PRIMARY KEY REFERENCES sites(site_id),
    windows TEXT NOT NULL,
    basis TEXT NOT NULL
);
CREATE TABLE service_boundaries (
    scope TEXT NOT NULL,
    boundary TEXT NOT NULL,
    category TEXT NOT NULL,
    service TEXT NOT NULL,
    PRIMARY KEY (scope, boundary)
);
CREATE TABLE collector_declarations (
    collector_id TEXT NOT NULL,
    site_id TEXT NOT NULL REFERENCES sites(site_id),
    endpoint_key TEXT NOT NULL,
    basis TEXT NOT NULL,
    PRIMARY KEY (collector_id, site_id, endpoint_key)
);
-- Optional EXPLICITLY supplied topology relationships (none in the demo scenario).
CREATE TABLE topology_relations (
    relation_id TEXT NOT NULL,
    site_id TEXT NOT NULL REFERENCES sites(site_id),
    kind TEXT NOT NULL,
    basis TEXT NOT NULL,
    PRIMARY KEY (relation_id, site_id)
);

-- Crew plans: draft -> reviewed -> applied | superseded.
CREATE TABLE crew_plans (
    plan_id TEXT PRIMARY KEY,
    ops_revision INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('draft','reviewed','applied','superseded')),
    created_by TEXT NOT NULL REFERENCES users(user_id),
    created_at TEXT NOT NULL,
    created_as_of TEXT NOT NULL,
    horizon_start TEXT NOT NULL,
    horizon_end TEXT NOT NULL,
    scope_digest TEXT NOT NULL,
    input_digest TEXT NOT NULL,
    input_snapshot TEXT NOT NULL,
    travel_source TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    result TEXT NOT NULL,
    reviewed_by TEXT,
    reviewed_at TEXT,
    applied_by TEXT,
    applied_at TEXT,
    applied_as_of TEXT,
    apply_idempotency_key TEXT,
    superseded_reason TEXT,
    superseded_by TEXT
);
CREATE INDEX crew_plans_created ON crew_plans(created_as_of, plan_id);
CREATE TABLE crew_plan_items (
    plan_id TEXT NOT NULL REFERENCES crew_plans(plan_id),
    seq INTEGER NOT NULL,
    crew_id TEXT NOT NULL REFERENCES crews(crew_id),
    incident_id TEXT NOT NULL REFERENCES incidents(incident_id),
    job_id TEXT NOT NULL,
    activity TEXT NOT NULL,
    depends_on TEXT NOT NULL,
    depart_at TEXT NOT NULL,
    arrive_at TEXT NOT NULL,
    start_at TEXT NOT NULL,
    finish_at TEXT NOT NULL,
    travel_minutes INTEGER NOT NULL,
    service_minutes INTEGER NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('proposed','assigned','deferred','cancelled')),
    assignment_id TEXT,
    PRIMARY KEY (plan_id, seq)
);

ALTER TABLE assignments ADD COLUMN plan_id TEXT;
ALTER TABLE assignments ADD COLUMN activity TEXT;
ALTER TABLE assignments ADD COLUMN progress TEXT
    CHECK (progress IS NULL OR progress IN ('en_route','on_site','done'));
ALTER TABLE assignments ADD COLUMN revision INTEGER NOT NULL DEFAULT 1;
ALTER TABLE assignments ADD COLUMN eta_arrival TEXT;
ALTER TABLE assignments ADD COLUMN travel_minutes INTEGER;
-- Which baseline an accepted business-task plan was compared with (run now vs usual time).
ALTER TABLE planner_commitments ADD COLUMN baseline_kind TEXT
    CHECK (baseline_kind IS NULL OR baseline_kind IN ('usual_time','run_now'));
ALTER TABLE planner_commitments ADD COLUMN baseline_start TEXT;
CREATE TABLE assignment_revisions (
    id INTEGER PRIMARY KEY,
    assignment_id TEXT NOT NULL REFERENCES assignments(assignment_id),
    incident_id TEXT NOT NULL REFERENCES incidents(incident_id),
    crew_id TEXT NOT NULL REFERENCES crews(crew_id),
    revision INTEGER NOT NULL,
    status TEXT NOT NULL,
    progress TEXT,
    plan_id TEXT,
    scheduled_start TEXT,
    scheduled_end TEXT,
    changed_by TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    changed_as_of TEXT NOT NULL,
    reason TEXT NOT NULL,
    UNIQUE (assignment_id, revision)
);
