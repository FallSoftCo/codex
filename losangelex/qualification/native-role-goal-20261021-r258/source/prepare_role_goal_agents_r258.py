"""Prepare a fresh standing-responsibility cohort; no old workers or tasks resumed."""
import contextlib,json,time,secrets,subprocess,argparse
from pathlib import Path
from uuid import uuid4
import psycopg
from psycopg.rows import dict_row
from psycopg import sql
from hollywood_backbone.store import Store
from lax_connector.host import request,machine_identity
from lax_connector.first_global import provision as provision_three
from lax_connector.purpose_install import protected,checksum
from lax_connector.collaboration_capture import administrative_put
from lax_connector.journal import saved

ROOT=Path('/var/lib/lax-role-goal-20261021-r258')
p=argparse.ArgumentParser();p.add_argument('arm',choices=['role-goal-r258']);p.add_argument('--python',default='/opt/lax-three-context-20261018-r01/venv-r212/bin/python');p.add_argument('--url',default='http://127.0.0.1:18783');args=p.parse_args()
ROOT.mkdir(mode=0o700,exist_ok=True);out=ROOT/args.arm
assert not out.exists(),'Original cohort exists: inspect receipts, do not replay installation'
out.mkdir(mode=0o700);(out/'administration').mkdir(mode=0o700)
base=protected('/var/lib/harness/483b0ac5-072a-43e1-ab50-36405f83de31/purpose-agents/cccfd79e-e934-460a-886e-df51c3ded886/installation.json')
auth=str(Path(protected(base['config'])['homes']['writer'])/'auth.json')
native='/opt/lax-native-pilot-20261020-r172/native/bin/codex-app-server'
plan={'authorityId':str(uuid4()),'globalRoomId':str(uuid4()),'name':'Standing responsibility finite QA r242 '+args.arm,'credentials':{label:{'principalId':str(uuid4()),'token':secrets.token_urlsafe(40)} for label in ['Owner','Global']}}
saved(out/'installation-intent.json',plan)
pilot=Path('/var/lib/harness-deployments/ozzz-native-20261019-r01')
env=dict(x.split('=',1) for x in json.loads(subprocess.check_output(['docker','inspect','--format','{{json .Config.Env}}','harness-postgres'],text=True)) if '=' in x)
db=protected(ROOT/'database.json');role=db['user'];db.update(user=env['POSTGRES_USER'],password=env['POSTGRES_PASSWORD'],application_name='standing-responsibility-preparation-r242')
with psycopg.connect(**db,row_factory=dict_row) as c:
 c.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(role)))
 class Borrow:
  @contextlib.contextmanager
  def connection(self):
   with c.transaction():yield c
 store=Store.__new__(Store);store.pool=Borrow()
 saved(out/'bootstrap-result.json',store.bootstrap(plan['authorityId'],plan['name'],plan));c.commit()
host=str(uuid4());agent=plan['credentials']['Global']['principalId']
call=lambda method,path,value=None:request(args.url,plan['credentials']['Owner']['token'],method,path,value)
roletext=(ROOT/'protocol/role.txt').read_text()
administrative_put(out,call,'agents/'+agent+'/role',{'operationId':'standing-r242:'+args.arm+':role','primary':'global','purpose':roletext,'homeRoomId':plan['globalRoomId'],'revision':1,'nativeGoalScope':'role'})
spec={'schema':'lax-first-global-install/v1','installationIntent':str(out/'installation-intent.json'),'hollywoodUrl':args.url,'hostId':host,'hostName':'OZZZ-OS bounded standing-role QA '+args.arm,'binary':native,'interpreter':args.python,'pythonRoot':str(Path(args.python).parent.parent),'approvedModelAuthFile':auth,'model':'gpt-6.1-sol','effort':'xhigh','enablePortfolioSupervision':False,'serviceMemoryMaxBytes':4*1024**3,'hostPolicy':{'maxConcurrent':4,'reservedInteractive':1,'memoryPerTurnBytes':256*1024**2,'reserveMemoryBytes':4*1024**3,'sampleMaxAgeSeconds':15,'connectorMaxAgeSeconds':15}}
saved(out/'profile.json',spec)
installed=provision_three(spec,activate=False,startup_enabled=False)
record=Path('/var/lib/harness')/plan['authorityId']/'purpose-agents'/agent
manifest=protected(record/'installation.json');config=protected(manifest['config'])
result={'authority':plan['authorityId'],'agent':agent,'host':host,'room':plan['globalRoomId'],'config':manifest['config'],'workspace':config['workspace'],'linuxUser':manifest['linuxUser'],'uid':manifest['uid'],'gid':manifest['gid'],'units':manifest['units'],'installation':str(record/'installation.json'),'infrastructure':[x['unit'] for x in installed['infrastructure']],'url':args.url}
saved(out/'public.json',result)
print(json.dumps({'state':'prepared-stopped','arm':args.arm,'consumer':result,'modelsStarted':0}),flush=True)
