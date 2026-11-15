"""Build fictional development accounts. No real data. Python standard library only."""
from pathlib import Path
import json,sqlite3,hashlib,secrets
ROOT=Path(__file__).parent
path=ROOT/'solarlenes-demo.sqlite'
if path.exists(): path.unlink()
db=sqlite3.connect(path)
db.executescript((ROOT/'schema.sql').read_text(encoding='utf-8'))
f=json.loads((ROOT/'fixtures.json').read_text(encoding='utf-8'))
for role in ['client','ceo','manager','dispatcher','technician']:
 db.execute('INSERT INTO roles VALUES (?)',(role,))
for u in f['users']:
 salt=secrets.token_hex(16)
 digest=hashlib.scrypt(b'SolarDemo2026!',salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
 hashed=f'scrypt$16384$8$1${salt}${digest}'
 db.execute('INSERT INTO users VALUES (?,?,?,?,?,?,?)',(u['id'],u['name'],u['email'],hashed,u['role'],u['area'],1))
inverters={i['site']:i for i in f['inverters']}
for s in f['sites']:
 db.execute('INSERT INTO sites VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(s['id'],s['name'],s['area'],s['feeder'],s['capacity'],int(s['battery']),'synthetic',s['zone'],s['segment'],s['businessType'],s['latitude'],s['longitude'],s['monthly_import_kwh'],s['monthly_export_kwh'],s['service_fee_ron'],s['cluster']))
 inv=inverters[s['id']]
 db.execute('INSERT INTO inverters VALUES (?,?,?,?,?,?,?,?,?,?)',(inv['id'],s['id'],inv['manufacturer'],inv['model'],inv['serial'],inv['ratedKw'],inv['mapX'],inv['mapY'],'2024-06-15','synthetic'))
 if not s['stale']:
  db.execute('INSERT INTO telemetry(site_id,interval_start_utc,interval_end_utc,pv_kw,home_kw,import_kw,export_kw,battery_charge_kw,battery_discharge_kw,soc_percent,source_mode,quality,received_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',(s['id'],'2026-11-14T10:45:00Z','2026-11-14T11:00:00Z',4.8,1.6,0,2.4 if s['battery'] else 3.2,.8 if s['battery'] else 0,0,76 if s['battery'] else None,'synthetic','recent','2026-11-14T11:00:00Z'))
 db.execute('INSERT INTO tariff_intervals(site_id,start_utc,end_utc,import_ron_kwh,export_ron_kwh,contract_version) VALUES (?,?,?,?,?,?)',(s['id'],'2026-11-13T22:00:00Z','2026-11-14T22:00:00Z',1.3,.55,'DEMO-FIXED-1'))
for u in f['users']:
 for site in u['sites']: db.execute('INSERT INTO user_sites VALUES (?,?)',(u['id'],site))
for request in f['requestTypes']:
 db.execute('INSERT INTO request_types VALUES (?,?,?,?,?)',(request['id'],request['label'],request['family'],request['owner'],request['routeTo']))
for i in f['incidents']:
 db.execute('INSERT INTO incidents VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(i['id'],i['site'],i['family'],i['title'],i['tier'],i['status'],i['owner'],None,i['evidence'],i['value'],None,1))
 for entry in i['timeline']:
  db.execute('INSERT INTO incident_log(incident_id,actor,text,created_utc) VALUES (?,?,?,?)',(i['id'],entry['actor'],entry['text'],entry['time']))
for c in f['crews']:
 db.execute('INSERT INTO crews VALUES (?,?,?,?,?,?,?,?)',(c['id'],c['name'],c['area'],c['owner'],json.dumps(c['skills']),json.dumps(c['members'],ensure_ascii=False),'08:00','18:00'))
 for u in f['users']:
  if u.get('crew')==c['name']:db.execute('INSERT INTO crew_members VALUES (?,?)',(c['id'],u['id']))
db.commit()
assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
assert db.execute('SELECT count(*) FROM users').fetchone()[0]==13
assert db.execute("SELECT count(*) FROM users WHERE role='ceo'").fetchone()[0]==1
assert db.execute('SELECT count(*) FROM inverters').fetchone()[0]==60
assert db.execute('SELECT count(*) FROM request_types').fetchone()[0]==13
assert db.execute("SELECT count(*) FROM roles WHERE name='support'").fetchone()[0]==0
assert db.execute("SELECT count(*) FROM request_types WHERE route_to='Supplier Support'").fetchone()[0]==0
assert db.execute("SELECT count(*) FROM sites WHERE segment='business'").fetchone()[0]==25
AREAS=['Sector 1','Sector 2','Sector 3','Sector 4','Sector 5','Sector 6','Ilfov']
assert sorted(r[0] for r in db.execute('SELECT DISTINCT area FROM sites'))==sorted(AREAS)
assert sorted(r[0] for r in db.execute('SELECT area FROM crews'))==sorted(AREAS)
assert db.execute("SELECT count(*) FROM users WHERE area NOT IN ('All','Sector 1','Sector 2','Sector 3','Sector 4','Sector 5','Sector 6','Ilfov')").fetchone()[0]==0
assert db.execute('SELECT count(*) FROM incidents').fetchone()[0]==12
assert db.execute("SELECT count(*) FROM incidents WHERE tier='P0'").fetchone()[0]==1
assert db.execute('SELECT count(DISTINCT cluster) FROM sites').fetchone()[0]==15
assert db.execute('SELECT count(*) FROM crew_members').fetchone()[0]==3
assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
db.close()
print('Seeded 13 accounts, 60 sites (25 business) in Sectors 1-6 and Ilfov with inverters, 15 clusters, 12 incidents, 13 request routes, 7 crews (one per area). Foreign keys and integrity verified.')
