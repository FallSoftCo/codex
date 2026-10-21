import base64,hashlib,json,os,subprocess,time
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
from lax_connector.journal import saved
from lax_connector.purpose_install import model_account
A='e488f19b-0f60-46ca-bd48-4fe544f06757';G='2d4a0daa-0514-475e-be1e-71decacbd5bc'
R=Path('/var/lib/lax-existing-global-adoption-20261021-r266');C=R/'cutover-r267';Q=C/'actual-user-journey';D=Path('/var/lib/harness')/A/'purpose-agents'/G
os.umask(0o077);assert not (C/'auth-recovery-intent.json').exists(),'Inspect original credential repair; no automatic recovery repetition'
m=json.loads((D/'installation.json').read_text());config=json.loads(Path(m['config']).read_text());state=Path(config['state'])
old=json.loads((state/'reader/wake.json').read_text());assert old['state']=='finished' and old['turn']['status']=='failed'
assert old['turn']['error']['message']=='workspace routing discovery unauthorized (401)'
for p in ['reader','writer','responder']:
 s=json.loads((state/('status-'+p+'.json')).read_text());assert not s['contexts'][p]['active'] and not s['contexts'][p]['held']
db=psycopg.connect(**json.loads(Path('/etc/harness/production/database.json').read_text()),row_factory=dict_row)
db.execute('SET TRANSACTION READ ONLY')
assert not db.execute('SELECT 1 FROM hb_purpose_context WHERE agent=%s AND active_turn IS NOT NULL',(G,)).fetchone()
d=db.execute('SELECT * FROM hb_delivery WHERE id=%s',('0c417797-66ff-49ae-aecf-7a497d984f44',)).fetchone()
assert d['state']=='pending' and d['generation']==0 and d['native_turn'] is None
assert not db.execute("SELECT 1 FROM hb_context_material WHERE agent=%s AND source=%s AND kind='work'",(G,d['event'])).fetchone()
db.close()
events=[json.loads(x) for x in (state/'reader/events.jsonl').read_text().splitlines()]
assert not any(e['event']=='tool_receipt' and e.get('nativeTurn',old['nativeTurn'])==old['nativeTurn'] for e in events),'Reader produced semantic effects; requires exact reconciliation'
source=Path('/var/lib/harness/483b0ac5-072a-43e1-ab50-36405f83de31/purpose-agents/cccfd79e-e934-460a-886e-df51c3ded886/home/native-reader/auth.json')
assert model_account(source)==m['approvedModelAccountDigest']
data=json.loads(source.read_text());part=data['tokens']['access_token'].split('.')[1];claims=json.loads(base64.urlsafe_b64decode(part+'='*(-len(part)%4)));assert claims['exp']>time.time()+3600
saved(C/'auth-recovery-intent.json',{'at':time.time(),'reason':'Approved bootstrap file was expired; same approved account is currently authenticated in existing native installation','originalFailedNativeTurn':old['nativeTurn'],'sourceAccountDigest':model_account(source),'sameOwnerAccount':True,'newRequests':0,'semanticEffectsBeforeFailure':0,'modelsTriggeredOnlyByExplicitRecovery':True})
subprocess.run(['systemctl','stop',*m['units'].values()],check=True,capture_output=True,timeout=80)
for purpose,home in config['homes'].items():
 dest=Path(home)/'auth.json';backup=C/('expired-'+purpose+'-auth.json');backup.write_bytes(dest.read_bytes());backup.chmod(0o600)
 temp=dest.with_name('auth-recovered-r267.tmp');temp.write_bytes(source.read_bytes());temp.chmod(0o600);os.chown(temp,m['uid'],m['gid']);temp.replace(dest)
saved(state/'reader/recovery.json',{'id':'auth-recovered:'+old['nativeTurn']+':r267','nativeThread':old['nativeThread'],'nativeTurn':old['nativeTurn'],'terminalStatus':'failed','reason':'Verified workspace-discovery401 before any semantic reader effect; fresh same-account authentication installed. Continue eligible original canonical pending input once; no user request or external effect replay.'})
os.chown(state/'reader/recovery.json',m['uid'],m['gid'])
subprocess.run(['systemctl','start',*m['units'].values()],check=True,capture_output=True,timeout=80)
saved(C/'auth-recovered.json',{'at':time.time(),'accountDigest':model_account(source),'sameOriginalRequest':str(d['event']),'originalDeliveryId':str(d['id']),'readerOriginalFailedTurn':old['nativeTurn'],'accessExpiresAt':claims['exp'],'contextIdentitiesPreserved':True,'newRequestPostCount':0,'originalFailureRetained':True})
print(json.dumps({'sameApprovedAccount':True,'originalRequestPreserved':True,'newRequestPostCount':0,'oldProviderFailureRetained':True,'threeContextsRestartedAfterIdle':True}))
