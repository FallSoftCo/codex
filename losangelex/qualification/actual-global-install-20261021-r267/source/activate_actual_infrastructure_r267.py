import hashlib,json,os,subprocess,time
from pathlib import Path
from lax_connector.journal import saved
from lax_connector import purpose_install
A='e488f19b-0f60-46ca-bd48-4fe544f06757';G='2d4a0daa-0514-475e-be1e-71decacbd5bc'
R=Path('/var/lib/lax-existing-global-adoption-20261021-r266');C=R/'cutover-r267'
os.umask(0o077)
assert not (C/'native-infrastructure-start-intent.json').exists(),'Inspect same service status/receipt; do not restart again'
collab=json.loads((C/'collaboration-applied.json').read_text())
unit=Path(collab['unitPath']).name;observer='lax-host-e488f19b0f60.service'
def status(u):
 return dict(line.split('=',1) for line in subprocess.check_output(['systemctl','show',u,'-p','MainPID','-p','ActiveState','-p','NRestarts'],text=True).splitlines())
old=status(observer)
assert old['MainPID']=='1342392' and old['ActiveState']=='active','Host observer changed since preserved preflight'
unitfile=Path('/etc/systemd/system')/(observer+'.d')/'zzzz-native-existing-global-20261021-r267.conf'
assert not unitfile.exists()
text='[Service]\nExecStart=\nExecStart=/opt/harness/native-existing-realm-20261021-r265/venv/bin/python -I -B -m lax_connector.host --serve /var/lib/harness/'+A+'/hosts/ec32d149-b563-589f-87c9-d5f468df1e79/controller.json\n'
saved(C/'native-infrastructure-start-intent.json',{'at':time.time(),'newBridge':unit,'observer':observer,'before':old,'dropinSha256':hashlib.sha256(text.encode()).hexdigest(),'otherAgentsRemainPaused':True})
unitfile.write_text(text);unitfile.chmod(0o644)
subprocess.run(['systemctl','daemon-reload'],check=True,capture_output=True)
subprocess.run(['systemctl','start',unit],check=True,capture_output=True,timeout=25)
subprocess.run(['systemctl','restart',observer],check=True,capture_output=True,timeout=25)
result={'at':time.time(),'bridge':status(unit),'observer':status(observer),'nextcomp':status('nextcomp-native-core.service')}
assert result['bridge']['ActiveState']=='active' and result['observer']['ActiveState']=='active'
saved(C/'native-infrastructure-active.json',result)
sealed=purpose_install.install(json.loads((R/'purpose-spec.json').read_text()))
saved(C/'purpose-sealed.json',sealed)
print(json.dumps({'infrastructure':result,'phase':sealed['phase'],'sudoVerifiedUid':sealed['sudoVerifiedUid'],'modelsStarted':0,'nativeServicesStarted':False}))
