import json,time,subprocess,argparse
from types import SimpleNamespace
from pathlib import Path
from uuid import uuid4
from lax_connector.host import request
from lax_connector.first_global import provision as provision_three
from lax_connector.purpose_install import protected
from lax_connector.collaboration_capture import administrative_put
from lax_connector.journal import saved
import psycopg
from psycopg.rows import dict_row
ROOT=Path('/var/lib/lax-role-goal-20261021-r258')
out=ROOT/'role-goal-r258'
args=SimpleNamespace(arm='role-goal-r258',python='/opt/lax-three-context-20261018-r01/venv-r258/bin/python',url='http://127.0.0.1:18786')
assert not (out/'profile.json').exists() and not (out/'public.json').exists()
plan=protected(out/'installation-intent.json')
agent=plan['credentials']['Global']['principalId']
with psycopg.connect(**protected(ROOT/'database.json'),row_factory=dict_row) as c:
 assert c.execute('SELECT count(*) AS n FROM hb_administrative_command WHERE authority=%s',(plan['authorityId'],)).fetchone()['n']==0
 assert c.execute('SELECT count(*) AS n FROM hb_delivery WHERE authority=%s',(plan['authorityId'],)).fetchone()['n']==0
 assert c.execute('SELECT revision FROM hb_agent_role WHERE principal=%s',(agent,)).fetchone()['revision']==1
call=lambda method,path,value=None:request(args.url,plan['credentials']['Owner']['token'],method,path,value)
assert call('GET','agents/'+agent+'/role')['revision']==1
host=str(uuid4())
saved(out/'listener-race-recovery-intent.json',{'at':time.time(),'originalOperation':'standing-r242:role-goal-r258:role','originalState':'pre-dispatch connection refused; no server receipt/role change/delivery/context','freshOperation':'role-goal-r258:role-after-ready','hostId':host,'noBootstrapReplay':True,'modelsStarted':0})
roletext=(ROOT/'protocol/role.txt').read_text()
administrative_put(out,call,'agents/'+agent+'/role',{'operationId':'role-goal-r258:role-after-ready','primary':'global','purpose':roletext,'homeRoomId':plan['globalRoomId'],'revision':1,'nativeGoalScope':'role'})
base=protected('/var/lib/harness/483b0ac5-072a-43e1-ab50-36405f83de31/purpose-agents/cccfd79e-e934-460a-886e-df51c3ded886/installation.json')
auth=str(Path(protected(base['config'])['homes']['writer'])/'auth.json')
native='/opt/lax-native-pilot-20261020-r172/native/bin/codex-app-server'
spec={'schema':'lax-first-global-install/v1','installationIntent':str(out/'installation-intent.json'),'hollywoodUrl':args.url,'hostId':host,'hostName':'OZZZ-OS bounded standing-role QA '+args.arm,'binary':native,'interpreter':args.python,'pythonRoot':str(Path(args.python).parent.parent),'approvedModelAuthFile':auth,'model':'gpt-6.1-sol','effort':'xhigh','enablePortfolioSupervision':False,'serviceMemoryMaxBytes':4*1024**3,'hostPolicy':{'maxConcurrent':4,'reservedInteractive':1,'memoryPerTurnBytes':256*1024**2,'reserveMemoryBytes':4*1024**3,'sampleMaxAgeSeconds':15,'connectorMaxAgeSeconds':15}}
saved(out/'profile.json',spec)
installed=provision_three(spec,activate=False,startup_enabled=False)
record=Path('/var/lib/harness')/plan['authorityId']/'purpose-agents'/agent
manifest=protected(record/'installation.json');config=protected(manifest['config'])
result={'authority':plan['authorityId'],'agent':agent,'host':host,'room':plan['globalRoomId'],'config':manifest['config'],'workspace':config['workspace'],'linuxUser':manifest['linuxUser'],'uid':manifest['uid'],'gid':manifest['gid'],'units':manifest['units'],'installation':str(record/'installation.json'),'infrastructure':[x['unit'] for x in installed['infrastructure']],'url':args.url}
saved(out/'public.json',result)
print(json.dumps({'state':'prepared-stopped','arm':args.arm,'consumer':result,'modelsStarted':0}),flush=True)
