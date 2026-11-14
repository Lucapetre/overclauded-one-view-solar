-- Operations: synthetic site profiles, crews, incidents with their log, assignments and support videos.
CREATE TABLE site_profiles (
    site_id TEXT PRIMARY KEY REFERENCES sites(site_id),
    latitude REAL NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude REAL NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    zone TEXT NOT NULL,
    character TEXT NOT NULL,
    segment TEXT NOT NULL CHECK (segment IN ('home','business')),
    business_type TEXT,
    installed_kwp REAL NOT NULL CHECK (installed_kwp > 0),
    monthly_import_kwh REAL NOT NULL CHECK (monthly_import_kwh >= 0),
    monthly_export_kwh REAL NOT NULL CHECK (monthly_export_kwh >= 0),
    service_fee_ron REAL NOT NULL CHECK (service_fee_ron >= 0)
);
CREATE TABLE crews (
    crew_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    area_id TEXT NOT NULL REFERENCES areas(area_id),
    skills TEXT NOT NULL,
    shift TEXT NOT NULL
);
CREATE TABLE crew_members (
    crew_id TEXT NOT NULL REFERENCES crews(crew_id),
    user_id TEXT NOT NULL REFERENCES users(user_id),
    PRIMARY KEY (crew_id, user_id)
);
CREATE TABLE incidents (
    incident_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL REFERENCES sites(site_id),
    title TEXT NOT NULL,
    family TEXT NOT NULL,
    tier TEXT NOT NULL CHECK (tier IN ('P0','P1','P2','P3')),
    status TEXT NOT NULL CHECK (status IN ('new','assigned','team_sent','meeting_scheduled','resolved')),
    source TEXT NOT NULL CHECK (source IN ('synthetic_replay','customer_request')),
    support_request_id TEXT REFERENCES support_requests(request_id),
    evidence TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX incidents_site ON incidents(site_id, status);
CREATE UNIQUE INDEX incidents_support_request ON incidents(support_request_id)
    WHERE support_request_id IS NOT NULL;
-- Every state change on an incident is appended here; this is the operations audit trail.
CREATE TABLE incident_log (
    id INTEGER PRIMARY KEY,
    incident_id TEXT NOT NULL REFERENCES incidents(incident_id),
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX incident_log_incident ON incident_log(incident_id, id);
CREATE TABLE assignments (
    assignment_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL REFERENCES incidents(incident_id),
    crew_id TEXT NOT NULL REFERENCES crews(crew_id),
    kind TEXT NOT NULL CHECK (kind IN ('dispatch','meeting')),
    status TEXT NOT NULL CHECK (status IN ('assigned','team_sent','meeting_scheduled','completed','cancelled')),
    scheduled_start TEXT,
    scheduled_end TEXT,
    created_by TEXT NOT NULL REFERENCES users(user_id),
    created_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX assignments_incident ON assignments(incident_id, status);
CREATE INDEX assignments_crew ON assignments(crew_id, status);
-- At most one active assignment per incident.
CREATE UNIQUE INDEX assignments_one_active ON assignments(incident_id)
    WHERE status IN ('assigned','team_sent','meeting_scheduled');
CREATE TABLE support_media (
    media_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL UNIQUE REFERENCES support_requests(request_id),
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL CHECK (content_type IN ('video/mp4','video/webm')),
    size_bytes INTEGER NOT NULL CHECK (size_bytes > 0),
    stored_name TEXT NOT NULL UNIQUE,
    uploaded_by TEXT NOT NULL REFERENCES users(user_id),
    created_at TEXT NOT NULL
);
