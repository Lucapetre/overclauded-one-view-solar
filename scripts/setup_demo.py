"""One command to rebuild the full local demo exactly as presented.

    python -m scripts.setup_demo --workspace D:/ovs-demo

Steps:
1. the four-scene component scenario (scripts.demo_scenes setup);
2. friendly account names (albert, maria, elena, andrei, mihai, ana, radu, ioana);
3. demo enrichment (enrich-demo: city demo, incidents, crews, offers, revenue, agenda, victor);
4. a frontend build;
5. a LOGINS.md sheet in the workspace (never in the repo).

The workspace must be a new, empty folder outside this checkout with about 2 GB free.
Everything is synthetic. Passwords stay in the workspace.
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRIENDLY = [
    (
        "laundry-owner",
        "albert",
        "Albert, laundry owner (business customer, site F1)",
        "/consumer",
    ),
    ("h2-resident", "maria", "Maria, home customer (site H2)", "/consumer"),
    (
        "scenario-dispatcher",
        "andrei",
        "Andrei, PPC dispatcher (applies crew plans)",
        "/ops",
    ),
    ("scenario-supervisor", "elena", "Elena, PPC manager (view only)", "/ops"),
    ("tech-battery-1", "mihai", "Mihai, technician (battery + PV crews)", "/ops"),
    ("tech-battery-2", "ana", "Ana, technician (battery crew)", "/ops"),
    ("tech-pv-1", "radu", "Radu, technician (PV crew)", "/ops"),
    ("desk-operator", "ioana", "Ioana, technician (remote desk)", "/ops"),
]


# Public demo password (synthetic local data only), the same one the classic demo shows.
DEMO_PASSWORD = "SolarDemo2026!"


def apply_demo_password(database_path, credentials_path, password):
    sys.path.insert(0, str(ROOT))
    from backend.db import Database
    from backend.provisioning import set_password

    database = Database(Path(database_path))
    with sqlite3.connect(database_path) as db:
        usernames = [row[0] for row in db.execute("SELECT username FROM users")]
    for username in usernames:
        set_password(database, username, password)
    credentials_path = Path(credentials_path)
    creds = (
        json.loads(credentials_path.read_text()) if credentials_path.exists() else {}
    )
    creds.update({username: password for username in usernames})
    credentials_path.write_text(json.dumps(creds, indent=2))
    return usernames


def run(command, env):
    print("$", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--skip-frontend", action="store_true")
    parser.add_argument(
        "--password",
        default=os.getenv("SOLAR_DEMO_PASSWORD", DEMO_PASSWORD),
        help="Password given to every synthetic demo account (default: public demo password)",
    )
    parser.add_argument(
        "--passwords-only",
        action="store_true",
        help="Only reset every account in an existing workspace to the demo password",
    )
    args = parser.parse_args(argv)
    workspace = args.workspace.resolve()
    database = workspace / "api.sqlite3"
    credentials = workspace / "demo-credentials.json"
    temp = workspace.parent / (workspace.name + "-tmp")
    temp.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, TEMP=str(temp), TMP=str(temp))
    if args.passwords_only:
        users = apply_demo_password(database, credentials, args.password)
        print(f"Demo password applied to {len(users)} accounts in {database}")
        return

    run(
        [
            sys.executable,
            "-m",
            "scripts.demo_scenes",
            "--workspace",
            str(workspace),
            "setup",
        ],
        env,
    )

    creds = json.loads(credentials.read_text())
    with sqlite3.connect(database) as db:
        for old, new, _, _ in FRIENDLY:
            db.execute("UPDATE users SET username=? WHERE username=?", (new, old))
            if old in creds:
                creds[new] = creds.pop(old)
    credentials.write_text(json.dumps(creds, indent=2))

    env_db = dict(
        env,
        SOLAR_DATABASE=str(database),
        SOLAR_MEDIA_DIR=str(workspace / "media"),
        SOLAR_OFFER_WORKER="false",
    )
    run([sys.executable, "-m", "backend", "enrich-demo"], env_db)

    if not args.skip_frontend:
        npm = "npm.cmd" if os.name == "nt" else "npm"
        run([npm, "--prefix", "frontend", "ci"], env)
        run([npm, "--prefix", "frontend", "run", "build"], env)

    # Same public demo password for every synthetic account, so all machines match.
    apply_demo_password(database, credentials, args.password)
    creds = json.loads(credentials.read_text())
    lines = [
        "# Demo logins (local, synthetic; do not commit)",
        "",
        "One-click sign-in: open /demo/ (server started with SOLAR_DEMO_LOGIN=true).",
        "",
        "| Person | Username | Password | Open |",
        "|---|---|---|---|",
    ]
    for _, new, who, page in FRIENDLY:
        lines.append(f"| {who} | `{new}` | `{creds.get(new, '?')}` | {page} |")
    if "victor" in creds:
        lines.append(
            f"| Victor, area manager (Ilfov) | `victor` | `{creds['victor']}` | /ops |"
        )
    (workspace / "LOGINS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(
        "\nDone. Start the app (laptop only):\n"
        f"  SOLAR_DATABASE={database} SOLAR_MEDIA_DIR={workspace / 'media'} "
        "SOLAR_OFFER_WORKER=false SOLAR_DEMO_LOGIN=true "
        "python -m uvicorn backend.main:app --host 127.0.0.1 --port 8020\n"
        "Phones on the same Wi-Fi: add SOLAR_DEMO_LAN=true and use --host 0.0.0.0, "
        "then open http://<laptop Wi-Fi IP>:8020/demo/\n"
        f"Logins: {workspace / 'LOGINS.md'}"
    )


if __name__ == "__main__":
    main()
