-- Power Block Offers: time-limited energy commitments, settlement ledger, savings counter,
-- in-app notifications. Prices and kWh are TEXT decimal strings; money is INTEGER bani.
ALTER TABLE audit ADD COLUMN detail TEXT;
CREATE INDEX audit_subject ON audit(subject, id);
CREATE TABLE offers (
    offer_id TEXT PRIMARY KEY,
    type TEXT NOT NULL CHECK (type IN ('consume','export')),
    title TEXT,
    energy_kwh TEXT NOT NULL,
    offer_price_ron_per_kwh TEXT NOT NULL,
    window_minutes INTEGER NOT NULL CHECK (window_minutes BETWEEN 15 AND 1440),
    penalty_type TEXT NOT NULL
        CHECK (penalty_type IN ('per_unfulfilled_kwh','percent_of_unfulfilled_value','flat')),
    penalty_value TEXT NOT NULL,
    offer_expires_at TEXT NOT NULL,
    area_id TEXT NOT NULL REFERENCES areas(area_id),
    status TEXT NOT NULL CHECK (status IN ('draft','available','cancelled','expired')),
    target_mode TEXT NOT NULL CHECK (target_mode IN ('all','segment','clients')),
    target_segment TEXT CHECK (target_segment IS NULL OR target_segment IN ('consumers','prosumers')),
    target_min_kwp TEXT,
    target_zone TEXT,
    linked_incident_id TEXT REFERENCES incidents(incident_id),
    max_takers INTEGER CHECK (max_takers IS NULL OR max_takers > 0),
    max_total_kwh TEXT,
    created_by TEXT NOT NULL REFERENCES users(user_id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    published_at TEXT,
    cancelled_at TEXT
);
CREATE INDEX offers_area_status ON offers(area_id, status, offer_expires_at);
-- Hand-picked clients for target_mode='clients'.
CREATE TABLE offer_targets (
    offer_id TEXT NOT NULL REFERENCES offers(offer_id),
    user_id TEXT NOT NULL REFERENCES users(user_id),
    PRIMARY KEY (offer_id, user_id)
);
-- One acceptance per client and offer. Terms are copied so later edits never change them.
CREATE TABLE user_offers (
    user_offer_id TEXT PRIMARY KEY,
    offer_id TEXT NOT NULL REFERENCES offers(offer_id),
    user_id TEXT NOT NULL REFERENCES users(user_id),
    site_id TEXT NOT NULL REFERENCES sites(site_id),
    type TEXT NOT NULL CHECK (type IN ('consume','export')),
    energy_kwh TEXT NOT NULL,
    offer_price_ron_per_kwh TEXT NOT NULL,
    window_minutes INTEGER NOT NULL,
    penalty_type TEXT NOT NULL,
    penalty_value TEXT NOT NULL,
    reference_price_ron_per_kwh TEXT NOT NULL,
    reference_price_source TEXT NOT NULL CHECK (reference_price_source IN ('contract','default_tariff')),
    status TEXT NOT NULL CHECK (status IN
        ('accepted','active','completed','partial','expired_unfulfilled','cancelled')),
    accepted_at TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    cancelled_at TEXT,
    metered_kwh TEXT NOT NULL DEFAULT '0',
    coverage_ratio REAL NOT NULL DEFAULT 0,
    progress_at TEXT,
    reminded_30_at TEXT,
    reminded_10_at TEXT,
    settled_at TEXT,
    idempotency_key TEXT,
    UNIQUE (offer_id, user_id)
);
CREATE UNIQUE INDEX user_offers_idempotency ON user_offers(user_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
CREATE INDEX user_offers_status ON user_offers(status, window_end);
CREATE INDEX user_offers_user ON user_offers(user_id, accepted_at DESC);
CREATE INDEX user_offers_site ON user_offers(site_id, type, window_start);
-- Settlement ledger: exactly one row per user offer, with every input and result.
CREATE TABLE offer_settlements (
    settlement_id INTEGER PRIMARY KEY,
    user_offer_id TEXT NOT NULL UNIQUE REFERENCES user_offers(user_offer_id),
    offer_id TEXT NOT NULL REFERENCES offers(offer_id),
    user_id TEXT NOT NULL REFERENCES users(user_id),
    site_id TEXT NOT NULL REFERENCES sites(site_id),
    type TEXT NOT NULL CHECK (type IN ('consume','export')),
    outcome TEXT NOT NULL CHECK (outcome IN ('completed','partial','expired_unfulfilled','cancelled')),
    energy_kwh TEXT NOT NULL,
    metered_kwh TEXT NOT NULL,
    fulfilled_kwh TEXT NOT NULL,
    unfulfilled_kwh TEXT NOT NULL,
    excess_kwh TEXT NOT NULL,
    coverage_ratio REAL NOT NULL,
    offer_price_ron_per_kwh TEXT NOT NULL,
    reference_price_ron_per_kwh TEXT NOT NULL,
    penalty_type TEXT NOT NULL,
    penalty_value TEXT NOT NULL,
    penalty_before_waiver_bani INTEGER NOT NULL,
    penalty_waived_reason TEXT CHECK (penalty_waived_reason IS NULL OR
        penalty_waived_reason IN ('meter_data_incomplete','cancelled_by_distributor')),
    energy_value_bani INTEGER NOT NULL,
    penalty_bani INTEGER NOT NULL,
    amount_bani INTEGER NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('charge','credit')),
    savings_bani INTEGER NOT NULL,
    settled_at TEXT NOT NULL
);
CREATE INDEX offer_settlements_user ON offer_settlements(user_id, settled_at DESC);
CREATE INDEX offer_settlements_offer ON offer_settlements(offer_id);
-- Savings/Earnings counter, updated in the settlement transaction; reconcilable from the ledger.
CREATE TABLE savings_totals (
    user_id TEXT PRIMARY KEY REFERENCES users(user_id),
    lifetime_bani INTEGER NOT NULL DEFAULT 0,
    consume_bani INTEGER NOT NULL DEFAULT 0,
    export_bani INTEGER NOT NULL DEFAULT 0,
    penalties_bani INTEGER NOT NULL DEFAULT 0,
    settled_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
CREATE TABLE notifications (
    notification_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id),
    kind TEXT NOT NULL CHECK (kind IN
        ('offer_new','offer_accepted','offer_reminder_30','offer_reminder_10','offer_settled')),
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    link TEXT,
    created_at TEXT NOT NULL,
    read_at TEXT
);
CREATE INDEX notifications_user ON notifications(user_id, created_at DESC);
