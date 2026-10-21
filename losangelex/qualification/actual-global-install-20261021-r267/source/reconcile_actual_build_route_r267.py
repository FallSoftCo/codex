import fcntl,hashlib,json,os,subprocess,time
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
from lax_connector import environment,purpose_readiness
from lax_connector.host import request
from lax_connector.collaboration_capture import administrative_put
from lax_connector.journal import saved
from lax_connector.service_observer import properties,members
A='e488f19b-0f60-46ca-bd48-4fe544f06757';G='2d4a0daa-0514-475e-be1e-71decacbd5bc';HOST='ec32d149-b563-589f-87c9-d5f468df1e79'
R=Path('/var/lib/lax-existing-global-adoption-20261021-r266');C=R/'cutover-r267';O=C/'build-route-reconciliation';D=Path('/var/lib/harness')/A/'purpose-agents'/G
os.umask(0o077);assert not O.exists(),'Inspect original route transition before any retry';O.mkdir(mode=0o700);(O/'administration').mkdir(mode=0o700)
m=json.loads((D/'installation.json').read_text());config=json.loads(Path(m['config']).read_text());admin=json.loads((R/'administrator.json').read_text());api=lambda method,path,body=None:request(admin['hollywoodUrl'],admin['token'],method,path,body)
profile=Path('/etc/harness')/A/'environment.json';accepted=Path('/etc/harness')/A/'agent-environments'/(G+'.json');readiness=D/'readiness.json'
before=json.loads(profile.read_text());enrolled=json.loads(accepted.read_text())
assert enrolled['profileSha256']==hashlib.sha256(profile.read_bytes()).hexdigest()
assert before['build']['entrypoint']=='/aosp/development/lax-upstream-20261013/build-backbone-20261014.sh'
candidate=json.loads(profile.read_text());candidate['build']['entrypoint']='/usr/local/bin/storage-build'
candidate['build']['path']=':'.join(['/home/aosp/.local/state/losangelex-maintainer/tools/bin','/home/aosp/.local/state/losangelex-maintainer/tools/cargo/bin','/home/aosp/.local/state/losangelex-maintainer/tools/venv/bin','/home/aosp/.local/state/losangelex-maintainer/tools/sysroot/usr/bin','/usr/local/bin','/usr/bin','/bin'])
environment.validate(candidate,A)
for directory in candidate['build']['path'].split(':'):assert Path(directory).is_dir(),directory
saved(O/'candidate.json',candidate)
for key,path in [('profile',profile),('accepted-environment',accepted),('readiness',readiness)]:
 (O/(key+'.before.json')).write_bytes(path.read_bytes())
place=api('GET','placements/'+G)['placement'];assert place['enabled'] and place['host']==HOST
db=psycopg.connect(**json.loads(Path('/etc/harness/production/database.json').read_text()),row_factory=dict_row,autocommit=True);db.execute('SET default_transaction_read_only=on')
def quiet():
 assert not db.execute('SELECT 1 FROM hb_purpose_context WHERE agent=%s AND active_turn IS NOT NULL',(G,)).fetchone(),'Active native inference; defer route cutover'
 assert not db.execute("SELECT 1 FROM hb_delivery WHERE agent=%s AND state IN ('pending','claimed','running','cancel_requested','unknown')",(G,)).fetchone(),'Unsettled or new user input; defer route cutover'
quiet()
saved(O/'intent.json',{'at':time.time(),'scope':'Non-secret build route and matching verified installation profile hash only; retain model/runtime/account/source/tool/room/worker identities','oldEntry':before['build']['entrypoint'],'newEntry':candidate['build']['entrypoint'],'buildsStarted':0,'otherAgentsResumed':0,'placementBeforeRevision':place['revision']})
paused=administrative_put(O,api,'placements/'+G,{'operationId':'actual-native-r267:pause-for-build-route','hostId':HOST,'revision':place['revision'],'enabled':False})
quiet()
subprocess.run(['systemctl','stop',*m['units'].values()],check=True,capture_output=True,timeout=80)
for unit in m['units'].values():
 s=properties(unit);assert s['ActiveState']=='inactive' and s['MainPID']=='0' and (not s['ControlGroup'] or not members(s['ControlGroup']))
lock=os.open(Path(config['state'])/'agent.lock',os.O_RDWR)
try:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 assert profile.read_bytes()==(O/'profile.before.json').read_bytes()
 saved(profile,candidate);profile.chmod(0o644)
 updated={**enrolled,'profileSha256':hashlib.sha256(profile.read_bytes()).hexdigest()}
 saved(accepted,updated);accepted.chmod(0o644)
 verified=purpose_readiness.verify(m)
 saved(readiness,verified)
 saved(O/'verified.json',{'at':time.time(),'profileSha256':updated['profileSha256'],'readinessSha256':hashlib.sha256(readiness.read_bytes()).hexdigest(),'actualReadinessVerified':True,'nativeHistoriesAndTokensChanged':False,'buildsStarted':0})
finally:os.close(lock)
resumed=administrative_put(O,api,'placements/'+G,{'operationId':'actual-native-r267:restore-global-after-build-route','hostId':HOST,'revision':paused['placement']['revision'],'enabled':True})
subprocess.run(['systemctl','start',*m['units'].values()],check=True,capture_output=True,timeout=80)
saved(O/'accepted.json',{'at':time.time(),'state':'accepted','newEntry':candidate['build']['entrypoint'],'buildToolOwner':'aosp','toolVersions':{'cargo':'1.95.0','just':'1.47.1'},'placementRevision':resumed['placement']['revision'],'globalOnlyRestartedAtFreshQuietBoundary':True,'otherAgentsResumed':0,'buildsStarted':0,'pairingChanged':False})
db.close()
print((O/'accepted.json').read_text())
