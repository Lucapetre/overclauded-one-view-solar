"""Build fictional development accounts. No real data. Python standard library only."""
from pathlib import Path
import json,sqlite3,hashlib,secrets
ROOT=Path(__file__).parent
path=ROOT/'solarlenes-demo.sqlite'
if path.exists(): path.unlink()
db=sqlite3.connect(path)
db.executescript((ROOT/'schema.sql').read_text())
f=json.loads((ROOT/'fixtures.json').read_text())
for role in ['client','ceo','manager','dispatcher','technician','support']:
 db.execute('INSERT INTO roles VALUES (?)',(role,))
for u in f['users']:
 salt=secrets.token_hex(16)
 digest=hashlib.scrypt(b'SolarDemo2026!',salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
 hashed=f'scrypt$16384$8$1${salt}${digest}'
 db.execute('INSERT INTO users VALUES (?,?,?,?,?,?,?)',(u['id'],u['name'],u['email'],hashed,u['role'],u['area'],1))
for s in f['sites']:
 db.execute('INSERT INTO sites VALUES (?,?,?,?,?,?,?)',(s['id'],s['name'],s['area'],s['feeder'],s['capacity'],int(s['battery']),'synthetic'))
 index=int(s['id'][1:])-1
 group=index//8
 site_index=index%8
 map_x=([110,420,195][group]+(site_index%4)*48)/720
 map_y=([120,140,280][group]+(site_index//4)*54)/380
 manufacturer=['Huawei','Fronius','SolarEdge'][index%3]
 model=(f"SUN2000-{s['capacity']}KTL-M1" if manufacturer=='Huawei' else
        f"Primo {s['capacity']}.0-1" if manufacturer=='Fronius' else
        f"SE{s['capacity']}K")
 db.execute('INSERT INTO inverters VALUES (?,?,?,?,?,?,?,?,?,?)',(f"INV-{s['id']}",s['id'],manufacturer,model,f"DEMO-{s['id']}-2024",s['capacity'],map_x,map_y,'2024-06-15','synthetic'))
 if not s['stale']:
  db.execute('INSERT INTO telemetry(site_id,interval_start_utc,interval_end_utc,pv_kw,home_kw,import_kw,export_kw,battery_charge_kw,battery_discharge_kw,soc_percent,source_mode,quality,received_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',(s['id'],'2026-11-14T10:45:00Z','2026-11-14T11:00:00Z',4.8,1.6,0,2.4 if s['battery'] else 3.2,.8 if s['battery'] else 0,0,76 if s['battery'] else None,'synthetic','recent','2026-11-14T11:00:00Z'))
 db.execute('INSERT INTO tariff_intervals(site_id,start_utc,end_utc,import_ron_kwh,export_ron_kwh,contract_version) VALUES (?,?,?,?,?,?)',(s['id'],'2026-11-13T22:00:00Z','2026-11-14T22:00:00Z',1.3,.55,'DEMO-FIXED-1'))
for u in f['users']:
 for site in u['sites']: db.execute('INSERT INTO user_sites VALUES (?,?)',(u['id'],site))
for request in f['requestTypes']:
 db.execute('INSERT INTO request_types VALUES (?,?,?,?,?)',(request['id'],request['label'],request['family'],request['owner'],request['routeTo']))
for i in f['incidents']:
 db.execute('INSERT INTO incidents VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(i['id'],i['site'],i['family'],i['title'],i['tier'],i['status'],i['owner'],None,i['evidence'],i['value'],None,1))
for k,c in enumerate(f['crews']):
 db.execute('INSERT INTO crews VALUES (?,?,?,?,?,?,?)',(f'C{k+1}',c['name'],c['area'],c['owner'],json.dumps(c['skills']),'08:00','18:00'))
 for u in f['users']:
  if u.get('crew')==c['name']:db.execute('INSERT INTO crew_members VALUES (?,?)',(f'C{k+1}',u['id']))
db.commit()
assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
assert db.execute('SELECT count(*) FROM users').fetchone()[0]==15
assert db.execute("SELECT count(*) FROM users WHERE role='ceo'").fetchone()[0]==1
assert db.execute('SELECT count(*) FROM inverters').fetchone()[0]==24
assert db.execute('SELECT count(*) FROM request_types').fetchone()[0]==6
assert db.execute('SELECT count(*) FROM user_sites WHERE user_id IN (\'u11\',\'u12\',\'u13\')').fetchone()[0]==24
assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
db.close()
print('Seeded 15 accounts, 24 sites and inverters, 8 incidents, 6 request routes, 3 crews. Foreign keys and integrity verified.')
