"""Fresh zero-input startup, setup reconciliation and deliberate stop boundary."""
import json,time,subprocess,sys
from pathlib import Path
from lax_connector.first_global import provision
from lax_connector.purpose_install import protected,directory
from lax_connector import host
sys.path.insert(0,'/aosp/development/lax-three-context-20261018-r01/qualification')
import psycopg
from psycopg.rows import dict_row
def connect():
 return psycopg.connect(**json.loads(Path("/var/lib/lax-three-context-20261018-r01/database.json").read_text()),row_factory=dict_row)
base=Path('/var/lib/lax-three-context-20261018-r01/fresh-global-r47');out=base/'startup-lifecycle-proof.json'
if out.exists() or (base/'lifecycle-proof-intent.json').exists():raise RuntimeError('Inspect original lifecycle receipt; no replay')
profile=protected(base/'native-profile.json');setup=protected(base/'installation-intent.json');authority=setup['authorityId'];agent=setup['credentials']['Global']['principalId']
m=protected(directory(authority,agent)/'installation.json');cfg=protected(Path(m['config']))
def props(unit):
 return dict(l.split('=',1) for l in subprocess.check_output(['systemctl','show',unit,'-p','MainPID','-p','ActiveState'],text=True).splitlines())
def state(p):return json.loads((Path(cfg['state'])/('status-'+p+'.json')).read_text())
def histories():
 with connect() as c:
  rows=c.execute("SELECT purpose,context_id,native_thread FROM hb_purpose_context WHERE agent=%s ORDER BY purpose",(agent,)).fetchall()
  permits=c.execute('SELECT count(*) AS n FROM hb_context_permit WHERE agent=%s',(agent,)).fetchone()['n']
  deliveries=c.execute('SELECT count(*) AS n FROM hb_delivery WHERE authority=%s',(authority,)).fetchone()['n']
  rooms=c.execute('SELECT count(*) AS n FROM hb_room WHERE authority=%s',(authority,)).fetchone()['n']
  c.rollback()
 return json.loads(json.dumps(rows,default=str)),permits,deliveries,rooms
before={p:props(u) for p,u in m['units'].items()};threads,nperm,nd,rooms=histories()
assert rooms==1 and nperm==0 and nd==0 and len(threads)==3 and len({r['native_thread'] for r in threads})==3
assert all(x['native_thread'] for x in threads)
assert all(v['ActiveState']=='active' for v in before.values())
for p in m['units']:
 s=state(p);assert time.time()-s['at']<5 and not s['contexts'][p]['active'] and not s['contexts'][p]['held']
protected_units=['hollywood-backbone.service','nextcomp-native-core.service','lax-host-f96e5615-f1c9b594-r17.service','lax-collaboration-f96e5615-f1c9b594.service']
protected_pids={u:props(u)['MainPID'] for u in protected_units}
(base/'lifecycle-proof-intent.json').write_text(json.dumps({'at':time.time(),'scope':m['units'],'before':before,'histories':threads,'steps':['Reconcile already activated original factory; expect unchanged PIDs','Stop ONLY new QA responder with no inputs/inferences','Reconcile factory --activate; must preserve responder deliberate stop','Explicitly restore only this test-owned responder and verify same native history'],'requestsAllowed':0,'modelsAllowed':0},indent=2)+'\n')
r=provision(profile,activate=True);assert r['activation']['activationRepeated'] is False
assert {p:props(u) for p,u in m['units'].items()}==before
controller_path=Path('/var/lib/harness')/authority/'hosts'/profile['hostId']/'controller.json'
controller_before=controller_path.read_bytes();assert 'nativeCollaborationCaptureConfig' in json.loads(controller_before)
policy={**profile['hostPolicy'],'controlAgentIds':[agent]}
host.enroll({'authorityId':authority,'hostId':profile['hostId'],'hollywoodUrl':profile['hollywoodUrl'],'administratorCredential':setup['credentials']['Owner'],'policy':policy})
assert controller_path.read_bytes()==controller_before
responder=m['units']['responder'];stopped=False
try:
 subprocess.run(['systemctl','stop',responder],check=True,capture_output=True);stopped=True
 assert props(responder)['ActiveState']=='inactive'
 r=provision(profile,activate=True);assert r['activation']['units']['responder']=='inactive'
 assert props(responder)['ActiveState']=='inactive'
 assert all(props(m['units'][p])==before[p] for p in ('reader','writer'))
finally:
 if stopped:
  # Explicit restoration belongs to this original QA test, not setup reconciliation.
  (base/'test-responder-restoration-intent.json').write_text(json.dumps({'at':time.time(),'unit':responder,'originalTestIntent':str(base/'lifecycle-proof-intent.json'),'reason':'Restore only the exact newly created QA responder stopped by this test; no historical/user stop is resumed'})+'\n')
  subprocess.run(['systemctl','start',responder],check=True,capture_output=True)
deadline=time.monotonic()+30
while True:
 try:
  s=state('responder');v=s['contexts']['responder']
  if s['at']>json.loads((base/'test-responder-restoration-intent.json').read_text())['at'] and time.time()-s['at']<5 and not v['held'] and not v['active'] and v['nativeThread']==next(x['native_thread'] for x in threads if x['purpose']=='responder'):break
 except (FileNotFoundError,KeyError):pass
 if time.monotonic()>deadline:raise RuntimeError('Original responder restoration unqualified; inspect its same unit/history')
 time.sleep(.5)
assert histories()==(threads,0,0,1)
assert {u:props(u)['MainPID'] for u in protected_units}==protected_pids
proof={'schema':'fresh-native-global-startup-lifecycle/v1','at':time.time(),'authorityId':authority,'agentId':agent,'hostId':profile['hostId'],'oneInitialRoom':True,'threeDistinctNativeHistories':threads,'firstActivationStartedOnlyNewAgent':True,'noAcceptedInputNoNativeInference':True,'taskSubmissions':0,'modelInferencePermits':0,'reconcilePreservedLivePids':True,'reenrollmentPreservedNativeCaptureConfiguration':True,'factoryReconcilePreservedDeliberateResponderStop':True,'explicitTestOnlyRestorationPreservedSameHistory':True,'beforePids':before,'afterPids':{p:props(u) for p,u in m['units'].items()},'protectedPidsUnchanged':protected_pids,'scope':'Fresh local authority native setup/startup/reconcile/stop only. No ordinary human-task completion, provider-model response, Git/SSH environment profile, phone or enterprise boot desired-state proof implied.'}
out.write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps({k:v for k,v in proof.items() if k not in ('beforePids','afterPids','threeDistinctNativeHistories','protectedPidsUnchanged')},indent=2))

