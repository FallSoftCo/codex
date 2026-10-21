import hashlib,json,os,subprocess,time
from pathlib import Path
from hollywood_backbone.store import Store,digest
from lax_connector.purpose_install import model_account
ROOT=Path('/var/lib/lax-existing-global-adoption-20261021-r266')
CUT=ROOT/'cutover-r267'
A='e488f19b-0f60-46ca-bd48-4fe544f06757';G='2d4a0daa-0514-475e-be1e-71decacbd5bc';H='301c8b83-8cdb-5b9a-9d7f-3b2fa6f0b3f6'
RT='/opt/harness/native-existing-realm-20261021-r265/venv/bin/python'
def save(p,v):p.write_text(json.dumps(v,indent=2,default=str)+'\n');p.chmod(0o600)
def main():
 assert not CUT.exists(),'Inspect existing transition; no repeat snapshot or stop'
 os.umask(0o077);CUT.mkdir(mode=0o700)
 staged=json.loads((ROOT/'prepared.json').read_text())
 for name,sha in staged['stagedFiles'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha,name
 probe=subprocess.run(['runuser','-u','harness-hollywood','--',RT,'-I','-B','-c',"import hollywood_backbone.server,lax_connector.context_runtime"],capture_output=True,timeout=20);assert probe.returncode==0,'Candidate API not readable by real UID'
 cfg=json.loads(Path('/etc/harness/production/database.json').read_text());s=Store(cfg)
 with s.pool.connection() as c:
  c.execute('SET TRANSACTION READ ONLY')
  assert c.execute('SELECT max(version) AS n FROM hb_schema').fetchone()['n']==21
  actor=c.execute('SELECT * FROM hb_principal WHERE id=%s',(G,)).fetchone();assert actor['administrator'] and actor['active'] and actor['kind']=='agent'
  role=c.execute('SELECT * FROM hb_agent_role WHERE principal=%s',(G,)).fetchone()
  assert role['revision']==staged['legacyRoleRevision']
  busy=c.execute("SELECT id,state,agent FROM hb_delivery WHERE authority=%s AND state IN ('claimed','running','cancel_requested','unknown')",(A,)).fetchall();assert not busy,'Unsettled original realm execution'
  executors=c.execute("SELECT id,state,agent FROM hb_executor WHERE authority=%s AND state<>'stopped'",(A,)).fetchall();assert not executors,'Undrained original realm executor'
  placements=c.execute('SELECT * FROM hb_placement WHERE authority=%s ORDER BY agent',(A,)).fetchall()
  save(CUT/'placements.before.json',placements)
 s.close()
 units=[]
 for path in Path('/etc/systemd/system').glob('lax-*.service'):
  if path.is_file() and A in path.read_text() and ('worker-' in path.name or path.name=='lax-global-e488f19b0f60.service'):
   units.append(path.name)
 assert len(units)==12,(len(units),'Exact legacy agent supervisor inventory changed')
 allunits=sorted(units+['hollywood-backbone.service','lax-host-e488f19b0f60.service'])
 states={};backup=CUT/'unit-backups';backup.mkdir()
 for unit in allunits:
  state=dict(line.split('=',1) for line in subprocess.check_output(['systemctl','show',unit,'-p','MainPID','-p','ActiveState','-p','UnitFileState','-p','ControlGroup','-p','PartOf','-p','BoundBy','-p','ConsistsOf'],text=True).splitlines() if '=' in line)
  states[unit]=state
  cg=Path('/sys/fs/cgroup')/state['ControlGroup'].lstrip('/')
  pids=set()
  if cg.is_dir():
   for f in cg.rglob('cgroup.procs'):
    try:pids.update(int(n) for n in f.read_text().split())
    except FileNotFoundError:pass
  if unit in units:assert pids=={int(state['MainPID'])},'Legacy supervisor has live children: '+unit
  source=Path('/etc/systemd/system')/unit
  if source.exists(): (backup/unit).write_bytes(source.read_bytes())
  drop=source.with_name(unit+'.d')
  if drop.exists():
   target=backup/(unit+'.d');target.mkdir()
   for p in drop.iterdir():
    if p.is_file():(target/p.name).write_bytes(p.read_bytes())
 save(CUT/'units.before.json',states)
 for name,path in [('controller',Path('/var/lib/harness')/A/'hosts/ec32d149-b563-589f-87c9-d5f468df1e79/controller.json'),('environment',Path('/etc/harness')/A/'environment.json')]:
  (CUT/(name+'.before.json')).write_bytes(path.read_bytes())
 paired=Path('/home/aosp/.local/share/nextcomp-backend/data/hollywood.json')
 save(CUT/'binding.before.json',{'path':str(paired),'sha256':hashlib.sha256(paired.read_bytes()).hexdigest(),'nextcompPid':subprocess.check_output(['systemctl','show','nextcomp-native-core.service','-p','MainPID','--value'],text=True).strip()})
 owner=json.loads((ROOT/'role-owner-request.json').read_text())
 owner['operationId']='adopt-role-owner:'+G+':r267'
 owner['purpose']+='\nCurrent authorized installation phase: complete and qualify Hollywood-native LAX on this host. Preserve deliberately stopped product agents, previous sessions, schedules and reservation jobs; neither room observation nor this startup authorizes their resumption. Additional product/session migration requires the user\'s direction. Current platform test work is permitted. Retain fully empowered Global administration; these are work-scope instructions, not reduced host authority.'
 assert len(owner['purpose'])<=4000
 from hollywood_backbone.server import Role
 Role.model_validate(owner);save(CUT/'role-owner-request.json',owner)
 plan={'schema':'lax-global-application-transition/v1','at':time.time(),'actor':'01a12c58-d21a-79b0-a512-0c3bc6dc0ee4','host':'ozzz-aosp','authorityId':A,'agentId':G,'legacyAgentUnits':sorted(units),'apiUnit':'hollywood-backbone.service','observerUnit':'lax-host-e488f19b0f60.service','candidate':RT,'fallback':'/opt/harness/native-existing-realm-20261021-r263/fallback-h81/bin/python','scope':'Owned application runtime transition and preservation of user-stopped product agents. No host security maintenance, package/OS/kernel, SSH/firewall, container recreation or unrelated workload changes. Existing API stays loopback18776; only new local native collaboration Unix socket.','newGlobalAuthority':'Existing active administrator, new native UID verified full passwordless sudo per user direction. Existing providers retained.','rollback':'Keep modern compatible API/schema and original receipts after new purpose effects; pause affected native execution and use H81 fallback. No stale database restore or task replay.','stops':'Old product supervisors remain stopped/disabled after this transition; they are not automatically restored or resumed by Global startup. Original work and identity records retained.'}
 save(CUT/'plan.json',plan)
 env=dict(x.split('=',1) for x in json.loads(subprocess.check_output(['docker','inspect','--format','{{json .Config.Env}}','harness-postgres'],text=True)) if '=' in x)
 with (CUT/'before-schema21.dump').open('wb') as out,(CUT/'backup.log').open('wb') as err:
  subprocess.run(['docker','exec','-e','PGPASSWORD','harness-postgres','pg_dump','--format=custom','--username='+env['POSTGRES_USER'],'--dbname='+cfg['dbname']],env={**os.environ,'PGPASSWORD':env['POSTGRES_PASSWORD']},stdout=out,stderr=err,check=True)
 receipt={'schema':'lax-global-application-preflight/v1','at':time.time(),'planSha256':hashlib.sha256((CUT/'plan.json').read_bytes()).hexdigest(),'databaseBackupSha256':hashlib.sha256((CUT/'before-schema21.dump').read_bytes()).hexdigest(),'legacyAgentUnits':units,'liveMutations':0,'modelsStarted':0,'metadataAndConfigBackupComplete':True,'allObservedWorkAndExecutorsSettled':True,'exactLegacySupervisorsHaveNoChildren':True,'candidateReadableByActualApiUid':True,'root':str(CUT)}
 save(CUT/'preflight.json',receipt)
 notice=Path('/opt/hetzner-blue-team/coordination/notices');notice.mkdir(mode=0o700,exist_ok=True)
 save(notice/'lax-global-native-adoption-20261021-r267.json',{**plan,'receiptPath':str(CUT/'preflight.json'),'credentials':'Protected original provider/spec paths only; no values in this notice.','securityOwnerWoken':False,'ownerAcknowledgementsFabricated':False})
 print(json.dumps({'root':str(CUT),'backups':True,'settled':True,'legacyUnits':len(units),'actualApiUidImport':True,'modelsStarted':0,'liveMutations':0}))
if __name__=='__main__':main()
