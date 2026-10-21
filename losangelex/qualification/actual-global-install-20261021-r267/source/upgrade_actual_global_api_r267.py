import hashlib,json,os,subprocess,time,urllib.request
from pathlib import Path
from hollywood_backbone.store import Store
ROOT=Path('/var/lib/lax-existing-global-adoption-20261021-r266');CUT=ROOT/'cutover-r267'
RT='/opt/harness/native-existing-realm-20261021-r265/venv/bin/python'
A='e488f19b-0f60-46ca-bd48-4fe544f06757'
def save(p,v):p.write_text(json.dumps(v,indent=2)+'\n');p.chmod(0o600)
def idle():
 s=Store(json.loads(Path('/etc/harness/production/database.json').read_text()))
 try:
  with s.pool.connection() as c:
   c.execute('SET TRANSACTION READ ONLY')
   assert not c.execute("SELECT 1 FROM hb_delivery WHERE authority=%s AND state IN ('claimed','running','unknown','cancel_requested')",(A,)).fetchone(),'Original work unsettled; no cutover'
   assert not c.execute("SELECT 1 FROM hb_executor WHERE authority=%s AND state<>'stopped'",(A,)).fetchone(),'Original executor undrained'
 finally:s.close()
def main():
 os.umask(0o077);assert not (CUT/'api-transition-intent.json').exists(),'Inspect original transition status, do not repeat'
 plan=json.loads((CUT/'plan.json').read_text());before=json.loads((CUT/'units.before.json').read_text())
 assert subprocess.check_output(['systemctl','show','hollywood-backbone.service','-p','MainPID','--value'],text=True).strip()==before['hollywood-backbone.service']['MainPID']
 idle()
 for unit in plan['legacyAgentUnits']:
  state=dict(x.split('=',1) for x in subprocess.check_output(['systemctl','show',unit,'-p','MainPID','-p','ActiveState','-p','ControlGroup'],text=True).splitlines() if '=' in x)
  assert state['MainPID']==before[unit]['MainPID'] and state['ActiveState']=='active','Legacy unit changed'
  cg=Path('/sys/fs/cgroup')/state['ControlGroup'].lstrip('/');pids=set()
  for file in cg.rglob('cgroup.procs'):
   try:pids.update(file.read_text().split())
   except FileNotFoundError:pass
  assert pids=={state['MainPID']},'New work arrived before drain'
 save(CUT/'api-transition-intent.json',{'at':time.time(),'planSha256':hashlib.sha256((CUT/'plan.json').read_bytes()).hexdigest(),'workAndExecutorsSettled':True,'action':'Stop exact obsolete agent supervisors; same-endpoint compatible API upgrade. No business cancellation or replay.'})
 subprocess.run(['systemctl','stop',*plan['legacyAgentUnits']],check=True,capture_output=True)
 subprocess.run(['systemctl','disable',*plan['legacyAgentUnits']],check=True,capture_output=True)
 idle()
 for unit in plan['legacyAgentUnits']:
  assert subprocess.check_output(['systemctl','show',unit,'-p','MainPID','--value'],text=True).strip()=='0'
 save(CUT/'legacy-supervisors-stopped.json',{'at':time.time(),'units':plan['legacyAgentUnits'],'bootDisabled':True,'businessWorkCancelled':False})
 drop=Path('/etc/systemd/system/hollywood-backbone.service.d/zzzz-native-existing-global-20261021-r267.conf')
 assert not drop.exists()
 text='[Service]\nExecStart=\nExecStart='+RT+' -I -B -m hollywood_backbone.server --database-config /etc/harness/production/database.json --port 18776\n'
 drop.write_text(text);drop.chmod(0o644)
 subprocess.run(['systemctl','daemon-reload'],check=True,capture_output=True)
 subprocess.run(['systemctl','restart','hollywood-backbone.service'],check=True,capture_output=True)
 deadline=time.monotonic()+25;healthy=False
 while time.monotonic()<deadline:
  try:
   with urllib.request.urlopen('http://127.0.0.1:18776/health',timeout=2) as response:
    if response.status==200:healthy=True;break
  except (OSError,urllib.error.URLError):pass
  time.sleep(.25)
 assert healthy,'Inspect original API journal/receipt; old agents remain stopped, do not replay'
 s=Store(json.loads(Path('/etc/harness/production/database.json').read_text()))
 try:
  with s.pool.connection() as c:
   c.execute('SET TRANSACTION READ ONLY')
   schema=c.execute('SELECT max(version) AS n FROM hb_schema').fetchone()['n'];assert schema==34
 finally:s.close()
 binding=json.loads((CUT/'binding.before.json').read_text())
 assert hashlib.sha256(Path(binding['path']).read_bytes()).hexdigest()==binding['sha256']
 assert subprocess.check_output(['systemctl','show','nextcomp-native-core.service','-p','MainPID','--value'],text=True).strip()==binding['nextcompPid']
 code="""import {loadHollywood,HollywoodClient} from '/home/aosp/.local/share/nextcomp-backend/releases/20261017-native-core-alpha110-r03/server/hollywood.mjs';
 const cfg=loadHollywood('/home/aosp/.local/share/nextcomp-backend/data');
 const b=cfg.devices.get('owner')||cfg.defaultBinding||cfg.devices.values().next().value;
 const c=new HollywoodClient(b);const identity=await c.verify();const catalog=await c.call('rooms');
 if(identity.authorityId!=='e488f19b-0f60-46ca-bd48-4fe544f06757'||identity.principalId!=='301c8b83-8cdb-5b9a-9d7f-3b2fa6f0b3f6'||catalog.rooms.length!==12)throw Error('Actual identity/catalog differs');
 console.log(JSON.stringify({authorityId:identity.authorityId,principalId:identity.principalId,defaultRoomId:identity.defaultRoomId,rooms:catalog.rooms.length}));"""
 actual=json.loads(subprocess.check_output(['runuser','-u','aosp','--','node','--input-type=module','-e',code],text=True,stderr=subprocess.PIPE,timeout=30))
 result={'schema':'lax-global-api-upgrade-receipt/v1','at':time.time(),'apiPid':subprocess.check_output(['systemctl','show','hollywood-backbone.service','-p','MainPID','--value'],text=True).strip(),'schemaVersion':schema,'runtime':RT,'health':200,'actualGatewayReadback':actual,'nextcompPidUnchanged':True,'bindingBytesUnchanged':True,'legacyAgentUnitsStoppedAndDisabled':len(plan['legacyAgentUnits']),'modelsStarted':0,'phase':'Modern API active; original Global identity not yet purpose-enrolled/activated. Continue exact staged installation.'}
 save(CUT/'api-upgraded.json',result)
 print(json.dumps(result))
if __name__=='__main__':main()
