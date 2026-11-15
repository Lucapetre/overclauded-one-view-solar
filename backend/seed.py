"""Idempotent SYNTHETIC demo: Bucharest Sectors 1-6 and Ilfov, ~60 fictional sites.

Sites, profiles and clusters come from `backend/fixtures/site_profiles.json`.
Telemetry special cases (all in Sector 6 unless noted, on the replay clock):

- s6-01 (customer's home): full record, the compact telemetry example
- s6-02: stale feed (last interval ended 75 minutes before the replay clock)
- s6-03: registered but no telemetry at all
- s6-04: only the mandatory PV value is reported
- s6-09: mandatory PV value missing
- s3-01 (Sector 3): battery state of charge only; s3-02: SoC plus battery power
"""

import json
import secrets
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

from backend.db import Database, stamp
from backend.errors import ApiError
from backend.ingestion import ingest
from backend.models import Metric
from backend.offers import publish
from backend.ops import open_incident, profile_source
from backend.security import hash_password

REPLAY_AT = datetime(2026, 7, 15, 12, 15, tzinfo=UTC)
SHIFT = "08:00-18:00"
# Areas of the retired three-area demo; such a database must be recreated, not mixed.
LEGACY_AREAS = ("north", "central", "south")
NO_TELEMETRY = "s6-03"
STALE = "s6-02"
PV_ONLY = "s6-04"
PV_MISSING = "s6-09"
SOC_ONLY = "s3-01"
BATTERY = "s3-02"
SKILLS = [
    "Production",
    "Temperature",
    "Telemetry",
    "Voltage",
    "Area event",
    "Local issue",
    "Other",
]
# (crew_id, name, area, members): one crew per area with every technical skill.
CREWS = (
    ("sector-1-solar-care", "Sector 1 Solar Care", "sector-1", ["technician-s1"]),
    ("sector-2-solar-care", "Sector 2 Solar Care", "sector-2", ["technician-s2"]),
    ("sector-3-solar-care", "Sector 3 Solar Care", "sector-3", ["technician-s3"]),
    ("sector-4-solar-care", "Sector 4 Solar Care", "sector-4", ["technician-s4"]),
    ("sector-5-solar-care", "Sector 5 Solar Care", "sector-5", ["technician-s5"]),
    ("sector-6-solar-care", "Sector 6 Solar Care", "sector-6", ["technician"]),
    ("ilfov-field-service", "Ilfov Field Service", "ilfov", ["technician-ilfov"]),
)
# (username, role, account_type, site grants, area grants)
ACCOUNTS = (
    ("customer", "customer", "home", ["s6-01"], []),
    ("other-customer", "customer", "home", ["s4-01"], []),
    ("business-customer", "customer", "business", ["s3-06"], []),
    ("dispatcher", "dispatcher", "home", [], ["sector-6"]),
    ("technician", "technician", "home", ["s6-01", "s6-02"], []),
    *(
        (f"technician-{suffix}", "technician", "home", [], [])
        for suffix in ("s1", "s2", "s3", "s4", "s5", "ilfov")
    ),
    ("area-manager", "supervisor", "home", [], ["sector-6"]),
    (
        "supervisor",
        "supervisor",
        "home",
        [],
        [f"sector-{n}" for n in range(1, 7)] + ["ilfov"],
    ),
)
POLICY = "Synthetic demo policy rule on replayed demo data; not an equipment diagnosis."
# (incident_id, site, tier, family, title, evidence, minutes before the replay clock)
INCIDENTS = (
    (
        "demo-inc-s3-04-area",
        "s3-04",
        "P0",
        "Area event",
        "Synthetic area event: several demo feeds dropped together",
        "Replay policy marks a simultaneous drop across demo feeds near this site.",
        50,
    ),
    (
        "demo-inc-s6-09-production",
        PV_MISSING,
        "P1",
        "Production",
        "Synthetic rule: mandatory PV value missing in the latest interval",
        "The latest replayed record reports PV power as missing.",
        95,
    ),
    (
        "demo-inc-s3-09-voltage",
        "s3-09",
        "P1",
        "Voltage",
        "Synthetic voltage-band policy flag",
        "Replay policy flags a demo voltage value outside its configured band.",
        80,
    ),
    (
        "demo-inc-s4-07-temperature",
        "s4-07",
        "P1",
        "Temperature",
        "Synthetic temperature-threshold policy flag",
        "Replay policy flags a demo temperature value above its configured threshold.",
        70,
    ),
    (
        "demo-inc-ilfov-01-voltage",
        "ilfov-01",
        "P1",
        "Voltage",
        "Synthetic voltage-band policy flag",
        "Replay policy flags a demo voltage value outside its configured band.",
        40,
    ),
    (
        "demo-inc-s6-02-telemetry",
        STALE,
        "P2",
        "Telemetry",
        "Synthetic rule: demo feed is stale",
        "The latest replayed interval ended more than 30 minutes before the replay clock.",
        60,
    ),
    (
        "demo-inc-s4-06-production",
        "s4-06",
        "P2",
        "Production",
        "Synthetic rule: production below the demo expectation band",
        "Replay policy compares PV power with a fixed demo band for this profile.",
        45,
    ),
    (
        "demo-inc-s1-10-temperature",
        "s1-10",
        "P2",
        "Temperature",
        "Synthetic temperature-threshold policy flag",
        "Replay policy flags a demo temperature value above its configured threshold.",
        35,
    ),
    (
        "demo-inc-s6-03-telemetry",
        NO_TELEMETRY,
        "P3",
        "Telemetry",
        "Synthetic rule: no telemetry received for this demo site",
        "The registered demo site has no replayed record.",
        120,
    ),
    (
        "demo-inc-s5-01-local",
        "s5-01",
        "P3",
        "Local issue",
        "Synthetic follow-up: scheduled demo inspection reminder",
        "Replay policy schedules a periodic demo inspection reminder.",
        30,
    ),
    (
        "demo-inc-s2-04-local",
        "s2-04",
        "P3",
        "Local issue",
        "Synthetic follow-up: scheduled demo inspection reminder",
        "Replay policy schedules a periodic demo inspection reminder.",
        25,
    ),
)
PROFILE_FIELDS = (
    "latitude",
    "longitude",
    "zone",
    "character",
    "segment",
    "business_type",
    "installed_kwp",
    "monthly_import_kwh",
    "monthly_export_kwh",
    "service_fee_ron",
    "cluster",
)


def seed_operations(connection, as_of: datetime | None = None):
    """Synthetic site profiles, crews and incidents. Idempotent.

    `as_of` places the incident times relative to a scenario clock instead of the fixed replay time."""
    for profile in profile_source()["profiles"]:
        connection.execute(
            f"INSERT OR IGNORE INTO site_profiles(site_id,{','.join(PROFILE_FIELDS)}) "
            f"SELECT ?,{','.join('?' * len(PROFILE_FIELDS))} "
            "WHERE EXISTS (SELECT 1 FROM sites WHERE site_id=?)",
            (
                profile["site_id"],
                *(profile.get(field) for field in PROFILE_FIELDS),
                profile["site_id"],
            ),
        )
    for crew_id, name, area, members in CREWS:
        connection.execute(
            "INSERT OR IGNORE INTO crews(crew_id,name,area_id,skills,shift) VALUES (?,?,?,?,?)",
            (crew_id, name, area, json.dumps(SKILLS), SHIFT),
        )
        for member in members:
            connection.execute(
                "INSERT OR IGNORE INTO crew_members(crew_id,user_id) "
                "SELECT ?, user_id FROM users WHERE username=?",
                (crew_id, member),
            )
    for incident_id, site_id, tier, family, title, evidence, minutes in INCIDENTS:
        opened = stamp((as_of or REPLAY_AT) - timedelta(minutes=minutes))
        open_incident(
            connection,
            incident_id=incident_id,
            site_id=site_id,
            title=title,
            family=family,
            tier=tier,
            source="synthetic_replay",
            evidence=f"{evidence} {POLICY}",
            actor="system",
            detail="Opened by the synthetic replay policy",
            now=opened,
        )


# Power Block Offers by the supervisor in area sector-6: two published, one draft.
OFFER_AREA = "sector-6"
DEMO_OFFERS = (
    (
        "demo-offer-s6-consume",
        True,
        (
            "consume",
            "Midday solar surplus",
            "10",
            "0.55",
            120,
            "per_unfulfilled_kwh",
            "0.3",
        ),
    ),
    (
        "demo-offer-s6-export",
        True,
        (
            "export",
            "Evening peak support",
            "10",
            "0.7",
            120,
            "percent_of_unfulfilled_value",
            "20",
        ),
    ),
    (
        "demo-offer-s6-draft",
        False,
        ("consume", "Weekend load shift", "5", "0.45", 60, "flat", "5"),
    ),
)
OFFER_FIELDS = (
    "type",
    "title",
    "energy_kwh",
    "offer_price_ron_per_kwh",
    "window_minutes",
    "penalty_type",
    "penalty_value",
)


def seed_offers(database: Database, connection, now: datetime | None = None):
    """Demo offers expiring 7 days after seeding (wall clock, or `now`). Idempotent; no acceptances."""
    now = now or datetime.now(UTC)
    for offer_id, published, terms in DEMO_OFFERS:
        offer = dict(zip(OFFER_FIELDS, terms, strict=True)) | {
            "offer_id": offer_id,
            "offer_expires_at": stamp(now + timedelta(days=7)),
            "area_id": OFFER_AREA,
            "status": "draft",
            "target_mode": "all",
            "created_by": "supervisor",
            "created_at": stamp(now),
            "updated_at": stamp(now),
        }
        columns = list(offer)
        if not connection.execute(
            f"INSERT OR IGNORE INTO offers({','.join(columns)}) "
            f"SELECT {','.join('?' * len(columns))} "
            "WHERE EXISTS (SELECT 1 FROM users WHERE user_id='supervisor')",
            [offer[column] for column in columns],
        ).rowcount:
            continue
        database.audit(
            connection,
            "supervisor",
            "offer.created",
            offer_id,
            "seed-demo",
            {"seed": True},
        )
        if published:
            offer |= {
                "target_segment": None,
                "target_min_kwp": None,
                "target_zone": None,
            }
            publish(database, connection, offer, "supervisor", "seed-demo", now)


def _capabilities(site_id: str) -> list[str]:
    capabilities = [
        Metric.pv.value,
        Metric.load.value,
        Metric.grid_import.value,
        Metric.grid_export.value,
    ]
    if site_id in (SOC_ONLY, BATTERY):
        capabilities.append(Metric.soc.value)
    if site_id == BATTERY:
        capabilities += [Metric.battery_charge.value, Metric.battery_discharge.value]
    return capabilities


def _refuse_legacy_geography(connection, database: Database):
    legacy = connection.execute(
        f"SELECT area_id FROM areas WHERE area_id IN ({','.join('?' * len(LEGACY_AREAS))})",
        LEGACY_AREAS,
    ).fetchall()
    if legacy:
        raise ApiError(
            409,
            "legacy_demo_geography",
            "This database was seeded with the retired three-area demo geography "
            f"({', '.join(row['area_id'] for row in legacy)}). The demo now uses "
            "Bucharest Sectors 1-6 and Ilfov. It only holds synthetic demo data: delete "
            f"{database.path} (with its -wal and -shm files) and run seed-demo again.",
        )


def _telemetry(base: dict, site_id: str) -> dict:
    record = deepcopy(base)
    record.update(
        site_id=site_id,
        device_id=f"meter-{site_id}",
        record_id=f"{site_id}-20260715T1215",
        raw_record_ref=f"fixture://summer-2026/{site_id}/1215",
    )
    measurements = record["measurements"]
    if site_id == STALE:
        record.update(
            interval_start="2026-07-15T10:45:00Z",
            interval_end="2026-07-15T11:00:00Z",
            received_at="2026-07-15T11:00:00Z",
        )
    if site_id == PV_ONLY:
        record["measurements"] = {"pv_power": measurements["pv_power"]}
    if site_id == PV_MISSING:
        measurements["pv_power"].update(value=None, availability="missing")
    if site_id in (SOC_ONLY, BATTERY):
        measurements["battery_soc"] = {
            "value": 65,
            "unit": "%",
            "requirement": "optional",
            "boundary": "not_applicable",
        }
    if site_id == BATTERY:
        for metric, value in (("battery_charge", 1.5), ("battery_discharge", 0)):
            measurements[metric] = {
                "value": value,
                "unit": "kW",
                "requirement": "optional",
                "boundary": "ac",
            }
        measurements["grid_export"]["value"] = 2.5
    return record


def seed_demo(
    database: Database, password: str | None = None, *, as_of: datetime | None = None
) -> dict[str, str]:
    """Idempotent, explicitly synthetic demo. Existing passwords are never reset.

    `as_of` (the scenario clock) re-times the demo incidents and offers; telemetry stays as fixtured."""
    database.migrate()
    base = json.loads(
        (Path(__file__).parent / "fixtures" / "telemetry.json").read_text()
    )
    source = profile_source()
    credentials = {}
    with database.connect() as connection:
        _refuse_legacy_geography(connection, database)
        for area_id, area in source["areas"].items():
            connection.execute(
                "INSERT OR IGNORE INTO areas VALUES (?,?,?)",
                (area_id, area["label"], "simulated"),
            )
        for profile in source["profiles"]:
            site_id = profile["site_id"]
            capabilities = _capabilities(site_id)
            requirements = {
                metric: "mandatory" if metric == Metric.pv else "optional"
                for metric in capabilities
            }
            connection.execute(
                "INSERT OR IGNORE INTO sites VALUES (?,?,?,?,?,?,?,?)",
                (
                    site_id,
                    profile["name"],
                    profile["area_id"],
                    "simulated",
                    900,
                    1800,
                    json.dumps(capabilities),
                    json.dumps(requirements),
                ),
            )
            connection.execute(
                "INSERT OR IGNORE INTO devices VALUES (?,?,?)",
                (f"meter-{site_id}", site_id, "synthetic-demo"),
            )
            connection.execute(
                "INSERT OR IGNORE INTO energy_streams VALUES (?,?,?)",
                (site_id, f"meter-{site_id}", "synthetic-demo"),
            )
        for username, role, account_type, sites, areas in ACCOUNTS:
            if not connection.execute(
                "SELECT 1 FROM users WHERE username=?", (username,)
            ).fetchone():
                secret = password or secrets.token_urlsafe(18)
                connection.execute(
                    "INSERT INTO users(user_id,username,password_hash,role,account_type) VALUES (?,?,?,?,?)",
                    (username, username, hash_password(secret), role, account_type),
                )
                credentials[username] = secret
            for site_id in sites:
                connection.execute(
                    "INSERT OR IGNORE INTO user_sites VALUES (?,?)", (username, site_id)
                )
            for area_id in areas:
                connection.execute(
                    "INSERT OR IGNORE INTO user_areas VALUES (?,?)", (username, area_id)
                )
        connection.execute(
            "INSERT OR IGNORE INTO settings VALUES ('replay_at',?)", (stamp(REPLAY_AT),)
        )
        seed_operations(connection, as_of)
        seed_offers(database, connection, as_of)
        # One transaction for every feed: a commit per record is slow on Windows.
        for profile in source["profiles"]:
            if profile["site_id"] != NO_TELEMETRY:  # A registered but unavailable feed.
                ingest(
                    database,
                    _telemetry(base, profile["site_id"]),
                    "seed-demo",
                    within=connection,
                )
    return credentials


# ---------------------------------------------------------------- component scenario (phase b)

COMPONENT_SCENARIO = "components-2026-07"
PLACEMENT_PROVENANCE = (
    "Fictional demo planning coordinates provisioned locally for the component scenario; "
    "not a real address and not derived from any import."
)
# (provider site key, area, fictional latitude, longitude, label)
PLACEMENTS = (
    ("H1", "sector-1", 44.4935, 26.0855, "Fictional demo point, Baneasa (Sector 1)"),
    ("H2", "sector-1", 44.4952, 26.0889, "Fictional demo point, Baneasa (Sector 1)"),
    ("H3", "sector-1", 44.4921, 26.0903, "Fictional demo point, Baneasa (Sector 1)"),
    ("F1", "sector-1", 44.4898, 26.0951, "Fictional demo point, Aviatiei (Sector 1)"),
    ("F2", "sector-1", 44.4911, 26.0987, "Fictional demo point, Aviatiei (Sector 1)"),
    ("F3", "ilfov", 44.5465, 26.0790, "Fictional demo point, Otopeni (Ilfov)"),
    ("S1", "ilfov", 44.5482, 26.0832, "Fictional demo point, Otopeni (Ilfov)"),
    ("S2", "ilfov", 44.5450, 26.1305, "Fictional demo point, Tunari (Ilfov)"),
    ("S3", "ilfov", 44.5501, 26.1342, "Fictional demo point, Tunari (Ilfov)"),
)
BUSINESS_SITE = "F1"
BUSINESS_TYPE = "Self-service laundry (fictional)"
RESIDENTIAL_SITE = "H2"
# (username, role, account_type, provider site keys, areas)
SCENARIO_ACCOUNTS = (
    ("laundry-owner", "customer", "business", [BUSINESS_SITE], []),
    ("h2-resident", "customer", "home", [RESIDENTIAL_SITE], []),
    ("scenario-supervisor", "supervisor", "home", [], ["sector-1", "ilfov"]),
    ("scenario-dispatcher", "dispatcher", "home", [], ["sector-1", "ilfov"]),
)
# Demo-assumption time-of-use contract for the business site (fictional supplier and rates).
SCENARIO_BANDS = (
    ("weekday-night", "Night", [1, 2, 3, 4, 5], 22 * 60, 7 * 60, 0.92, 0.45),
    ("weekday-morning", "Morning", [1, 2, 3, 4, 5], 7 * 60, 11 * 60, 1.52, 0.45),
    ("weekday-midday", "Midday", [1, 2, 3, 4, 5], 11 * 60, 17 * 60, 1.12, 0.45),
    ("weekday-peak", "Evening peak", [1, 2, 3, 4, 5], 17 * 60, 22 * 60, 1.69, 0.45),
    ("weekend-night", "Weekend night", [6, 7], 22 * 60, 7 * 60, 0.92, 0.45),
    ("weekend-day", "Weekend day", [6, 7], 7 * 60, 22 * 60, 1.15, 0.45),
)
SCENARIO_CONTRACT_FROM = datetime(2026, 6, 30, 21, 0, tzinfo=UTC)  # 2026-07-01 local
# The illustrative laundry batch (spec 9.1): 4 kW for two contiguous hours on 2026-07-17.
LAUNDRY_TASK = {
    "task_id": "f1-laundry-batch-2026-07-17",
    "label": "Laundry batch (demo assumption: 4 kW, 2 h)",
    "kind": "laundry_batch",
    "power_kw": 4.0,
    "energy_kwh": 8.0,
    "earliest_start": "2026-07-17T05:00:00.000000+00:00",  # 08:00 local
    "deadline": "2026-07-17T17:00:00.000000+00:00",  # 20:00 local
    "allowed_start_minute": 8 * 60,  # overlay allowed window 08:00-20:00 local
    "allowed_end_minute": 20 * 60,
    "usual_start": "2026-07-17T05:00:00.000000+00:00",
    "assumption_note": "Illustrative demo task values, not an appliance specification",
}


def _overlay_capacity(assets_path: Path, site_id: str) -> float | None:
    """Contracted PCC capacity of the declared business overlay (asset registry), if any."""
    if not assets_path.is_file():
        return None
    registry = json.loads(assets_path.read_text(encoding="utf-8"))
    for overlay in registry.get("business_overlays", []):
        if overlay.get("backend_site_id") == site_id:
            return (overlay.get("pcc") or {}).get("contracted_capacity_kw")
    return None


def seed_component_scenario(
    database: Database,
    password: str | None = None,
    sites_path: Path = Path("demo_data/sites.json"),
    assets_path: Path = Path("demo_components/assets.json"),
) -> dict[str, str]:
    """Idempotent local provisioning of the nine provider sites for the component scenario.

    Places them (fictional, labelled) in sector-1 / ilfov, creates explicit customer and
    staff accounts with explicit grants, a demo time-of-use contract and the illustrative
    laundry task for the business site. Imports never grant access; only this does.
    The compact 60-site demo is not touched.
    """
    from backend.customer import store_contract
    from backend.customer_models import Contract, TariffBand
    from backend.providers import backend_site_id

    database.migrate()
    registry = json.loads(sites_path.read_text(encoding="utf-8"))
    sites = {
        site["demo_site_key"]: (
            backend_site_id(
                "|".join(str(site[k]) for k in ("provider", "account_id", "site_id"))
            ),
            site,
        )
        for site in registry["sites"]
    }
    source = profile_source()
    credentials = {}
    now = stamp()
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        missing = [
            key
            for key, (site_id, _) in sites.items()
            if not connection.execute(
                "SELECT 1 FROM sites WHERE site_id=?", (site_id,)
            ).fetchone()
        ]
        if missing:
            raise ApiError(
                409,
                "provider_sites_missing",
                "Import the provider sites first (import-provider); missing: "
                + ", ".join(sorted(missing)),
            )
        for area_id in ("sector-1", "ilfov"):
            connection.execute(
                "INSERT OR IGNORE INTO areas VALUES (?,?,?)",
                (area_id, source["areas"][area_id]["label"], "simulated"),
            )
        for key, area_id, latitude, longitude, label in PLACEMENTS:
            site_id, site = sites[key]
            current = connection.execute(
                "SELECT area_id FROM sites WHERE site_id=?", (site_id,)
            ).fetchone()["area_id"]
            if current not in (None, area_id):
                raise ApiError(
                    409, "placement_conflict", f"Site {key} is already in {current}"
                )
            arrays = [
                {"kwp": a["kwp"], "tilt": a["tilt"], "az": a["az"]}
                for a in site.get("arrays", [])
            ]
            connection.execute(
                "INSERT INTO site_placements(site_id,area_id,latitude,longitude,"
                "location_label,coordinates_fictional,segment,business_type,installed_kwp,"
                "module_arrays,scenario_id,provenance,provisioned_at) "
                "VALUES (?,?,?,?,?,1,?,?,?,?,?,?,?) ON CONFLICT(site_id) DO NOTHING",
                (
                    site_id,
                    area_id,
                    latitude,
                    longitude,
                    label,
                    "business" if key == BUSINESS_SITE else "home",
                    BUSINESS_TYPE if key == BUSINESS_SITE else None,
                    site.get("pv_kwp"),
                    json.dumps(arrays),
                    COMPONENT_SCENARIO,
                    PLACEMENT_PROVENANCE,
                    now,
                ),
            )
            connection.execute(
                "UPDATE sites SET area_id=? WHERE site_id=? AND area_id IS NULL",
                (area_id, site_id),
            )
        for username, role, account_type, keys, areas in SCENARIO_ACCOUNTS:
            if not connection.execute(
                "SELECT 1 FROM users WHERE username=?", (username,)
            ).fetchone():
                secret = password or secrets.token_urlsafe(18)
                connection.execute(
                    "INSERT INTO users(user_id,username,password_hash,role,account_type) "
                    "VALUES (?,?,?,?,?)",
                    (username, username, hash_password(secret), role, account_type),
                )
                credentials[username] = secret
            for key in keys:
                connection.execute(
                    "INSERT OR IGNORE INTO user_sites VALUES (?,?)",
                    (username, sites[key][0]),
                )
            for area_id in areas:
                connection.execute(
                    "INSERT OR IGNORE INTO user_areas VALUES (?,?)", (username, area_id)
                )
        business_id, business = sites[BUSINESS_SITE]
        if not connection.execute(
            "SELECT 1 FROM contracts WHERE site_id=?", (business_id,)
        ).fetchone():
            contract = Contract(
                supplier="Demo Supply (fictional)",
                pricing="time_of_use",
                import_price_ron_kwh=1.28,
                export_price_ron_kwh=0.45,
                installed_kwp=business.get("pv_kwp"),
                export_compensation="payment",
                bands=[
                    TariffBand(
                        band_id=band_id,
                        label=label,
                        days=days,
                        start_minute=start,
                        end_minute=end,
                        import_rate_ron_kwh=rate,
                        export_value_ron_kwh=value,
                    )
                    for band_id, label, days, start, end, rate, value in SCENARIO_BANDS
                ],
            )
            store_contract(
                connection,
                business_id,
                contract,
                "laundry-owner",
                SCENARIO_CONTRACT_FROM,
                effective_from=SCENARIO_CONTRACT_FROM,
            )
        task = dict(LAUNDRY_TASK)
        task_id = task.pop("task_id")
        connection.execute(
            "INSERT OR IGNORE INTO planner_tasks(task_id,site_id,created_by,label,kind,"
            "power_kw,energy_kwh,earliest_start,deadline,latest_start,allowed_start_minute,"
            "allowed_end_minute,usual_start,site_import_limit_kw,status,revision,"
            "assumption_note,created_at,created_as_of,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,NULL,?,?,?,?,'suggested',1,?,?,?,?)",
            (
                task_id,
                business_id,
                "laundry-owner",
                task["label"],
                task["kind"],
                task["power_kw"],
                task["energy_kwh"],
                task["earliest_start"],
                task["deadline"],
                task["allowed_start_minute"],
                task["allowed_end_minute"],
                task["usual_start"],
                _overlay_capacity(assets_path, business_id)
                or business.get("grid_connection_kw"),
                task["assumption_note"],
                now,
                stamp(SCENARIO_CONTRACT_FROM),
                now,
            ),
        )
        database.audit(
            connection,
            "local-admin",
            "scenario.provisioned",
            COMPONENT_SCENARIO,
            "local-provisioning",
            {"sites": len(PLACEMENTS), "new_accounts": sorted(credentials)},
        )
    return credentials


# ---------------------------------------------------------------- scenario operations (phase c)

OPERATIONS_INPUTS = Path("demo_components/operations_inputs.json")
OPERATIONS_PROVENANCE = (
    "SYNTHETIC planning inputs from demo_components/operations_inputs.json, provisioned "
    "locally; fictional crews, shifts, depots, windows and travel times"
)


def _local_utc(day: str, clock: str) -> datetime:
    from zoneinfo import ZoneInfo

    hours, minutes = map(int, clock.split(":"))
    year, month, date = map(int, day.split("-"))
    local = datetime(
        year, month, date, hours, minutes, tzinfo=ZoneInfo("Europe/Bucharest")
    )
    return local.astimezone(UTC)


def seed_scenario_operations(
    database: Database,
    password: str | None = None,
    inputs_path: Path = OPERATIONS_INPUTS,
    sites_path: Path = Path("demo_data/sites.json"),
    assets_path: Path = Path("demo_components/assets.json"),
) -> dict[str, str]:
    """Idempotent local provisioning of the provider scenario field operations: crews and
    technician accounts, the remote triage desk, shifts, breaks, depots, member availability,
    job templates, customer access windows, the approximate travel matrix, the service-boundary
    registry and the declared collectors. Never done by an import; never grants dispatch."""
    from backend.providers import backend_site_id

    database.migrate()
    doc = json.loads(inputs_path.read_text(encoding="utf-8"))
    if not doc.get("synthetic"):
        raise ApiError(
            422, "inputs_not_synthetic", "Planning inputs must be labelled synthetic"
        )
    registry = json.loads(sites_path.read_text(encoding="utf-8"))
    keys = {
        site["demo_site_key"]: "|".join(
            str(site[k]) for k in ("provider", "account_id", "site_id")
        )
        for site in registry["sites"]
    }
    sites = {key: backend_site_id(site_key) for key, site_key in keys.items()}
    by_key = {site_key: sites[key] for key, site_key in keys.items()}
    credentials: dict[str, str] = {}
    now = stamp()
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        placed = {
            row["site_id"]
            for row in connection.execute("SELECT site_id FROM site_placements")
        }
        if not set(sites.values()) <= placed:
            raise ApiError(
                409,
                "scenario_not_provisioned",
                "Run provision-component-scenario first (placements and accounts)",
            )
        for crew in doc["crews"]:
            for member in crew["members"]:
                username = member["username"]
                if not connection.execute(
                    "SELECT 1 FROM users WHERE username=?", (username,)
                ).fetchone():
                    secret = password or secrets.token_urlsafe(18)
                    connection.execute(
                        "INSERT INTO users(user_id,username,password_hash,role,account_type) "
                        "VALUES (?,?,?,?,?)",
                        (
                            username,
                            username,
                            hash_password(secret),
                            "technician",
                            "home",
                        ),
                    )
                    credentials[username] = secret
            connection.execute(
                "INSERT OR IGNORE INTO crews(crew_id,name,area_id,skills,shift) VALUES (?,?,?,?,?)",
                (
                    crew["crew_id"],
                    crew["name"],
                    crew["home_area"],
                    json.dumps(crew["families"]),
                    f"{crew['shift']['start']}-{crew['shift']['end']}",
                ),
            )
            for member in crew["members"]:
                connection.execute(
                    "INSERT OR IGNORE INTO crew_members(crew_id,user_id) "
                    "SELECT ?, user_id FROM users WHERE username=?",
                    (crew["crew_id"], member["username"]),
                )
            connection.execute(
                "INSERT INTO crew_profiles VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(crew_id) "
                "DO UPDATE SET kind=excluded.kind, organisation=excluded.organisation, "
                "authorised_services=excluded.authorised_services, "
                "qualifications=excluded.qualifications, tools=excluded.tools, "
                "areas=excluded.areas, base_node=excluded.base_node, "
                "location_basis=excluded.location_basis",
                (
                    crew["crew_id"],
                    crew["kind"],
                    crew["organisation"],
                    json.dumps(sorted(crew["authorised_services"])),
                    json.dumps(sorted(crew["qualifications"])),
                    json.dumps(sorted(crew["tools"])),
                    json.dumps(sorted(crew["areas"])),
                    crew["base_node"],
                    stamp(_local_utc(doc["dates"][0], "07:30"))
                    if crew["base_node"]
                    else None,
                    crew["location_basis"],
                    doc["scenario_id"],
                    OPERATIONS_PROVENANCE,
                ),
            )
            for day in doc["dates"]:
                breaks = [
                    [
                        stamp(_local_utc(day, b["start"])),
                        stamp(_local_utc(day, b["end"])),
                    ]
                    for b in crew["breaks"]
                ]
                connection.execute(
                    "INSERT OR IGNORE INTO crew_shifts VALUES (?,?,?,?)",
                    (
                        crew["crew_id"],
                        stamp(_local_utc(day, crew["shift"]["start"])),
                        stamp(_local_utc(day, crew["shift"]["end"])),
                        json.dumps(breaks),
                    ),
                )
        for item in doc["member_unavailability"]:
            connection.execute(
                "INSERT OR IGNORE INTO member_unavailability "
                "SELECT user_id, ?, ?, ? FROM users WHERE username=?",
                (
                    stamp(_local_utc(item["date"], item["start"])),
                    stamp(_local_utc(item["date"], item["end"])),
                    item["reason"],
                    item["username"],
                ),
            )
        travel = doc["travel"]
        for node, info in travel["nodes"].items():
            connection.execute(
                "INSERT OR IGNORE INTO planning_nodes VALUES (?,?,?,?,?,1)",
                (
                    sites.get(node, node),
                    sites.get(node),
                    info["latitude"],
                    info["longitude"],
                    info["label"],
                ),
            )
        for edge in travel["minutes"]:
            connection.execute(
                "INSERT INTO travel_times VALUES (?,?,?,?,?) ON CONFLICT(from_node, to_node) "
                "DO UPDATE SET minutes=excluded.minutes, source=excluded.source",
                (
                    sites.get(edge["from"], edge["from"]),
                    sites.get(edge["to"], edge["to"]),
                    edge["minutes"],
                    f"{travel['source']} ({travel['method']})",
                    stamp(_local_utc(doc["dates"][0], "00:00")),
                ),
            )
        for rule_id, templates in doc["job_templates"].items():
            for seq, template in enumerate(templates, start=1):
                connection.execute(
                    "INSERT INTO job_templates VALUES (?,?,?,?) ON CONFLICT(rule_id, seq) "
                    "DO UPDATE SET activity=excluded.activity, spec=excluded.spec",
                    (
                        rule_id,
                        seq,
                        template["activity"],
                        json.dumps(template, sort_keys=True),
                    ),
                )
        windows = doc["access_windows"]
        for key, site_id in sites.items():
            connection.execute(
                "INSERT INTO site_access_windows VALUES (?,?,?) ON CONFLICT(site_id) "
                "DO UPDATE SET windows=excluded.windows, basis=excluded.basis",
                (
                    site_id,
                    json.dumps(windows["sites"].get(key, windows["default"])),
                    windows["basis"],
                ),
            )
        boundaries = doc["service_boundaries"]
        for boundary, (category, service) in boundaries["default"].items():
            connection.execute(
                "INSERT OR IGNORE INTO service_boundaries VALUES ('*',?,?,?)",
                (boundary, category, service),
            )
        for name, (category, service) in boundaries["asset_services"].items():
            connection.execute(
                "INSERT OR IGNORE INTO service_boundaries VALUES ('asset_service',?,?,?)",
                (name, category, service),
            )
        if assets_path.is_file():
            assets = json.loads(assets_path.read_text(encoding="utf-8"))
            for collector in assets.get("collectors", []):
                served = [
                    s for s in collector.get("serves", []) if s["site_key"] in by_key
                ]
                if len({s["site_key"] for s in served}) < 2:
                    continue  # a single-site collector is not a shared monitoring path
                for item in served:
                    connection.execute(
                        "INSERT OR IGNORE INTO collector_declarations VALUES (?,?,?,?)",
                        (
                            collector["collector_id"],
                            by_key[item["site_key"]],
                            item["endpoint_key"],
                            collector.get("note")
                            or "declared collector (asset registry)",
                        ),
                    )
        connection.execute(
            "INSERT INTO ops_revisions(reason,subject,created_at,created_as_of) "
            "VALUES ('operations.provisioned',?,?,?)",
            (doc["scenario_id"], now, now),
        )
        database.audit(
            connection,
            "local-admin",
            "scenario.operations_provisioned",
            doc["scenario_id"],
            "local-provisioning",
            {"crews": len(doc["crews"]), "new_accounts": len(credentials)},
        )
    return credentials
