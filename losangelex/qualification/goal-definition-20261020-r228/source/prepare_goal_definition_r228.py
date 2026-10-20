"""Prepare two isolated authorities with maintained native installation paths; no task submissions."""
import contextlib,json,time,secrets,subprocess
from pathlib import Path
from uuid import uuid4
import psycopg
from psycopg.rows import dict_row
from psycopg import sql
from hollywood_backbone.store import Store
from lax_connector.host import request,enroll,machine_identity
from lax_connector.linux_admin import provision as provision_single
from lax_connector.first_global import provision as provision_three,start_once
from lax_connector.purpose_install import protected,file_once,checksum
from lax_connector.journal import saved
from lax_connector.collaboration_capture import administrative_put
from lax_connector import collaboration_install

root=Path('/var/lib/lax-operating-model-comparison-20261020-r228')
assert not root.exists(),'Original setup exists; reconcile original phases, no setup replay'
root.mkdir(mode=0o700)
pilot=Path('/var/lib/harness-deployments/ozzz-native-20261019-r01')
m=protected(Path('/var/lib/harness/483b0ac5-072a-43e1-ab50-36405f83de31/purpose-agents/cccfd79e-e934-460a-886e-df51c3ded886/installation.json'));cfg=protected(m['config'])
auth=str(Path(cfg['homes']['writer'])/'auth.json')
native='/opt/lax-native-pilot-20261020-r172/native/bin/codex-app-server';python='/opt/lax-three-context-20261018-r01/venv-r212/bin/python';pythonroot=str(Path(python).parent.parent)
keep=['hollywood-backbone.service','nextcomp-native-core.service','harness-postgres.service','hollywood-native-pilot-20261019-r01.service',*m['units'].values()]
pid=lambda u:subprocess.check_output(['systemctl','show',u,'-p','MainPID','--value'],text=True).strip()
before={u:pid(u) for u in keep}
env=dict(x.split('=',1) for x in json.loads(subprocess.check_output(['docker','inspect','--format','{{json .Config.Env}}','harness-postgres'],text=True)) if '=' in x)
dbconfig=protected(pilot/'database.json');role=dbconfig['user'];dbconfig.update(user=env['POSTGRES_USER'],password=env['POSTGRES_PASSWORD'],application_name='goal-definition-preparation-r228')
policy={'maxConcurrent':6,'reservedInteractive':1,'memoryPerTurnBytes':256*1024**2,'reserveMemoryBytes':4*1024**3,'sampleMaxAgeSeconds':15,'connectorMaxAgeSeconds':15}
saved(root/'setup-intent.json',{'at':time.time(),'scope':'Two fresh private QA authority namespaces on the existing H77 API; both agents use identical SDK111 three-context runtimes. Compare explicit goal definition with the capable existing workflow. No old QA task replay. No existing authority/model/work changes.','native':native,'nativeSha256':checksum(native),'sdk':111,'hollywood':77,'model':'gpt-6.1-sol','effort':'xhigh','approvedAccountAuthSha256':checksum(auth),'aggregateCpuQuota':'200%','aggregateMemoryMaxBytes':8*1024**3,'modelsAuthorizedBySetup':0,'taskSubmissionsAuthorizedBySetup':0,'protectedPids':before})
results={}
for arm in ['definition','ordinary']:
 out=root/arm;out.mkdir(mode=0o700);(out/'administration').mkdir(mode=0o700)
 plan={'authorityId':str(uuid4()),'globalRoomId':str(uuid4()),'name':'Goal definition pilot r228 '+arm,'credentials':{label:{'principalId':str(uuid4()),'token':secrets.token_urlsafe(40)} for label in ['Owner','Global']}}
 saved(out/'installation-intent.json',plan)
 with psycopg.connect(**dbconfig,row_factory=dict_row) as c:
  c.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(role)))
  class Borrow:
   @contextlib.contextmanager
   def connection(self):
    with c.transaction():yield c
  store=Store.__new__(Store);store.pool=Borrow()
  res=store.bootstrap(plan['authorityId'],plan['name'],plan);c.commit()
 saved(out/'bootstrap-result.json',res)
 host=str(uuid4());url='http://127.0.0.1:18783';agent=plan['credentials']['Global']['principalId'];owner=plan['credentials']['Owner']['token']
 call=lambda method,path,value=None:request(url,owner,method,path,value)
 administrative_put(out,call,'agents/'+agent+'/role',{'operationId':'comparison-r228:'+arm+':role','primary':'global','purpose':'Deliver the authorized local enterprise language-practice intake report. Preserve the actual outcome, relevant human decisions and verified engineering facts through questions and execution. Use existing Hollywood Goal/Work and native tools when useful. This is finite disposable qualification only: no production, credentials, customers, historical work or new agents.','homeRoomId':plan['globalRoomId'],'revision':1})
 spec={'installationIntent':str(out/'installation-intent.json'),'hollywoodUrl':url,'hostId':host,'hostName':'OZZZ-OS operating-model '+arm,'binary':native,'interpreter':python,'pythonRoot':pythonroot,'approvedModelAuthFile':auth,'model':'gpt-6.1-sol','effort':'xhigh','enablePortfolioSupervision':False,'serviceMemoryMaxBytes':8*1024**3,'hostPolicy':policy}
 saved(out/'profile.json',spec)
 if arm in ('definition','ordinary'):
  installed=provision_three({'schema':'lax-first-global-install/v1',**spec},activate=False,startup_enabled=False)
  record=Path('/var/lib/harness')/plan['authorityId']/'purpose-agents'/agent
  manifest=protected(record/'installation.json');config=protected(manifest['config'])
  result={'authority':plan['authorityId'],'agent':agent,'host':host,'room':plan['globalRoomId'],'config':manifest['config'],'workspace':config['workspace'],'linuxUser':manifest['linuxUser'],'units':manifest['units'],'installation':str(record/'installation.json'),'infrastructure':[x['unit'] for x in installed['infrastructure']],'state':'prepared-stopped','runtime':'SDK111/H77'}
 else:
  administrative_put(out,call,'placements',{'operationId':'comparison-r228:single:placement','hostId':host,'name':spec['hostName'],'identityFingerprint':machine_identity(),'capabilities':{'localProvisioning':True,'model':spec['model']},'agentId':agent},method='POST')
  installed=provision_single(spec);saved(out/'single-install-result.json',installed)
  enrollment=enroll({'authorityId':plan['authorityId'],'hostId':host,'hollywoodUrl':url,'administratorCredential':plan['credentials']['Owner'],'policy':{**policy,'controlAgentIds':[agent]}})
  admin=out/'collaboration-administrator.json';saved(admin,{'authorityId':plan['authorityId'],'hostId':host,'hollywoodUrl':url,'token':owner})
  worker_config=Path(installed['connectorConfig']);config=json.loads(worker_config.read_text())
  prepared=out/'collaboration-prepared'
  collaboration_install.prepare({'schema':'lax-collaboration-install/v1','controllerConfig':enrollment['configPath'],'administratorConfig':str(admin),'interpreter':python,'resources':[{'name':'global-private','root':config['workspace'],'environmentId':'local'}],'agents':{agent:{'resources':['global-private'],'defaultResource':'global-private'}}},prepared)
  bridge=collaboration_install.apply(prepared);saved(out/'collaboration-result.json',bridge)
  observer='lax-host-'+plan['authorityId'].replace('-','')[:8]+'-'+host.replace('-','')[:8]+'.service'
  text='[Unit]\nDescription=LAX native host observer '+host+'\nAfter=network-online.target\n[Service]\nType=simple\nUser=root\nExecStart='+python+' -I -B -m lax_connector.host --serve '+enrollment['configPath']+'\nRestart=on-failure\nRestartSec=5\nMemoryMax=512M\nCPUQuota=50%\nUMask=0077\nKillMode=control-group\n'
  file_once(Path('/etc/systemd/system')/observer,text);subprocess.run(['systemctl','daemon-reload'],check=True,capture_output=True)
  infra=[start_once(out,observer),start_once(out,Path(bridge['unitPath']).name)]
  result={'authority':plan['authorityId'],'agent':agent,'host':host,'room':plan['globalRoomId'],'config':str(worker_config),'workspace':config['workspace'],'linuxUser':installed['linuxUser'],'units':{'single':installed['unit']},'installation':str(Path('/var/lib/harness')/plan['authorityId']/'global-admin-receipt.json'),'infrastructure':[x['unit'] for x in infra],'state':'prepared-stopped','runtime':'SDK111/H77'}
 assert all(pid(u)=='0' for u in result['units'].values())
 assert call('GET','rooms')['rooms'][0]['id']==plan['globalRoomId']
 saved(out/'public.json',result);results[arm]=result
assert {u:pid(u) for u in keep}==before
infra_pids={pid(u) for result in results.values() for u in result['infrastructure']}
tcp=subprocess.check_output(['ss','-H','-ltnp'],text=True)
listeners=[line for line in tcp.splitlines() if any('pid='+v+',' in line for v in infra_pids)]
assert not listeners,listeners
saved(root/'setup-result.json',{'at':time.time(),'observedNewInfraTcpListeners':listeners,'state':'candidate-prepared-no-model-input','arms':results,'modelsStarted':0,'tasksSubmitted':0,'existingProtectedPids':before,'noNewTcpListenersOwnedByNewInfra':len(listeners)==0})
print(json.dumps({'state':'candidate-prepared-no-model-input','arms':results,'modelsStarted':0,'tasksSubmitted':0}),flush=True)
