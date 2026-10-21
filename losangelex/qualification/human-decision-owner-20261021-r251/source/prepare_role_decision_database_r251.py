"""Create one owned private QA database, never alter the live database/schema."""
import json,time,subprocess,os
from pathlib import Path
import psycopg
from psycopg import sql
from lax_connector.journal import saved
from hollywood_backbone.store import Store
root=Path('/var/lib/lax-role-decision-owner-20261020-r251')
assert not root.exists(),'Inspect original QA database/provisioning receipts; no repeat create'
root.mkdir(mode=0o700);os.umask(0o077)
pilot=Path('/var/lib/harness-deployments/ozzz-native-20261019-r01/database.json')
cfg=json.loads(pilot.read_text());appuser=cfg['user'];live=cfg['dbname'];name='harness_role_decision_20261020_r251'
assert name!=live
env=dict(x.split('=',1) for x in json.loads(subprocess.check_output(['docker','inspect','--format','{{json .Config.Env}}','harness-postgres'],text=True)) if '=' in x)
admin={**cfg,'dbname':'postgres','user':env['POSTGRES_USER'],'password':env['POSTGRES_PASSWORD'],'application_name':'role-decision-qa-create-r251'}
saved(root/'database-intent.json',{'at':time.time(),'database':name,'owner':appuser,'liveDatabaseUnchanged':live,'scope':'Fresh disposable private QA database in existing PostgreSQL instance only; no new DB service, production DDL, defaults or model work','operation':'create-database-r251','rollback':'Stop only owned QA listeners/workers; retain exact evidence/state. No implicit model/job resume.'})
with psycopg.connect(**admin,autocommit=True) as c:
 assert not c.execute('SELECT 1 FROM pg_database WHERE datname=%s',(name,)).fetchone()
 c.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(name),sql.Identifier(appuser)))
 assert c.execute('SELECT 1 FROM pg_database WHERE datname=%s',(name,)).fetchone()
new={**cfg,'dbname':name,'application_name':'role-decision-qa-r251'}
saved(root/'database.json',new)
saved(root/'database-created.json',{'at':time.time(),'database':name,'owner':appuser,'verified':True,'productionDatabase':live,'productionDdlPerformed':False})
s=Store(new)
try:
 s.migrate()
 with s.pool.connection() as c:
  columns=c.execute("SELECT column_name FROM information_schema.columns WHERE table_name='hb_agent_role'").fetchall()
  assert any(r['column_name']=='decision_owner' for r in columns)
  assert c.execute('SELECT count(*) AS n FROM hb_authority').fetchone()['n']==0
 saved(root/'schema-ready.json',{'at':time.time(),'database':name,'schemaVersion':34,'decisionOwnerColumn':True,'authoritiesBeforeQualification':0,'modelsStarted':0})
finally:s.close()
print(json.dumps({'privateDatabase':name,'schemaVersion':34,'liveDatabaseSchemaChanged':False,'modelsStarted':0}))
