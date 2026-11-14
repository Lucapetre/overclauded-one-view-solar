-- Customer-facing features: home/business account type, supply contract, support requests, lessons.
ALTER TABLE users ADD COLUMN account_type TEXT NOT NULL DEFAULT 'home'
    CHECK (account_type IN ('home','business'));
CREATE TABLE contracts (
    site_id TEXT PRIMARY KEY REFERENCES sites(site_id),
    supplier TEXT NOT NULL,
    pricing TEXT NOT NULL CHECK (pricing IN ('fixed')),
    import_price_ron_kwh REAL NOT NULL CHECK (import_price_ron_kwh > 0),
    export_price_ron_kwh REAL NOT NULL CHECK (export_price_ron_kwh >= 0),
    installed_kwp REAL CHECK (installed_kwp IS NULL OR installed_kwp > 0),
    updated_by TEXT NOT NULL REFERENCES users(user_id),
    updated_at TEXT NOT NULL
);
CREATE TABLE support_requests (
    request_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL REFERENCES sites(site_id),
    user_id TEXT NOT NULL REFERENCES users(user_id),
    request_type TEXT NOT NULL,
    priority TEXT NOT NULL CHECK (priority IN ('standard','immediate_danger')),
    routed_to TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('awaiting_review','answered')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX support_requests_site ON support_requests(site_id, created_at DESC);
CREATE TABLE support_replies (
    id INTEGER PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES support_requests(request_id),
    author_id TEXT NOT NULL REFERENCES users(user_id),
    kind TEXT NOT NULL CHECK (kind IN ('customer','staff')),
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX support_replies_request ON support_replies(request_id, id);
-- One reward per account and lesson; the amount is a simulated bill credit, not money.
CREATE TABLE lesson_completions (
    user_id TEXT NOT NULL REFERENCES users(user_id),
    lesson_id TEXT NOT NULL,
    reward_ron REAL NOT NULL,
    completed_at TEXT NOT NULL,
    PRIMARY KEY (user_id, lesson_id)
);
