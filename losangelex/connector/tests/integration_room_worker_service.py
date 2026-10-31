"""Explicit root-only isolated systemd provisioning qualification, no inference."""
import asyncio,hashlib,json,os,pwd,secrets,shutil,subprocess,sys,time
from pathlib import Path
from uuid import uuid4
from aiohttp import web
from hollywood_backbone.store import Store
from hollywood_backbone.server import application
from lax_connector.linux_worker import provision
from lax_connector.service_observer import directory
from lax_connector.journal import saved

async def main():
 if os.environ.get('ROOM_WORKER_SERVICE_QUALIFICATION')!='1' or os.geteuid()!=0:
  raise PermissionError('Explicit isolated root qualification required')
 release=Path(sys.executable).parents[2]
 if not release.is_relative_to('/var/lib/lax-releases') or not json.loads((release/'component.json').read_text()).get('qualificationOnly'):
  raise ValueError('Qualification-only installed release required')
 os.umask(0o077);root=Path(os.environ['ROOM_WORKER_SERVICE_EVIDENCE']);root.mkdir(mode=0o700)
 original=json.load(open(os.environ['ROOM_NATIVE_ORIGINAL_CONFIG']));authority,room,agent,owner=[str(uuid4()) for _ in range(4)]
 credentials={'Owner':{'principalId':owner,'token':secrets.token_urlsafe(40)},'Global':{'principalId':agent,'token':secrets.token_urlsafe(40)}}
 host=str(uuid4());unit='lax-worker-'+authority.replace('-','')[:8]+'-'+agent.replace('-','')[:12]
 user='hworker-'+authority.replace('-','')[:8]+'-'+agent.replace('-','')[:12]
 base=Path('/var/lib/harness')/authority;home=base/'workers'/agent/'home'
 unit_file=Path('/etc/systemd/system')/(unit+'.service')
 sudo_file=Path('/etc/sudoers.d')/('harness-worker-'+authority.replace('-','')[:8]+'-'+agent.replace('-','')[:12])
 if base.exists() or unit_file.exists() or sudo_file.exists():raise ValueError('Qualification namespace already exists')
 try:pwd.getpwnam(user);raise ValueError('Qualification account already exists')
 except KeyError:pass
 saved(root/'intent.private.json',{'authority':authority,'room':room,'agent':agent,'owner':owner,'host':host,'unit':unit,'user':user,'credentials':credentials})
 store=Store(json.load(open(os.environ['ROOM_NATIVE_DATABASE'])));runner=web.AppRunner(application(store),access_log=None)
 announcement=Path('/opt/hetzner-blue-team/coordination/announcements')/('nextcomp-room-worker-qa-'+authority+'.json')
 cleanup={'stoppedOwnedUnit':False,'removedOwnedAccount':False,'sourceAuthUntouched':True,'unrelatedServicesTouched':False}
 try:
  store.bootstrap(authority,'SYNTHETIC native room service QA',{'globalRoomId':room,'credentials':credentials})
  await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start();origin='http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])
  base.mkdir(mode=0o755);base.chmod(0o755)
  directory(authority,host,agent).parent.parent.mkdir(parents=True,mode=0o700)
  with store.pool.connection() as c:head=c.execute('SELECT next_seq FROM hb_authority WHERE id=%s',(authority,)).fetchone()['next_seq']
  spec={'runtimeMode':'room-conversation','authorityId':authority,'agentId':agent,'hostId':host,'credential':credentials['Global']['token'],
        'hollywoodUrl':origin,'nativeName':'Synthetic resident service','purpose':'Qualification only; wait for real human input',
        'rooms':[{'roomId':room,'after':head}],'machineIdentity':hashlib.sha256(Path('/etc/machine-id').read_bytes()).hexdigest(),
        'approvedModelAuthFile':str(Path(original['codexHome'])/'auth.json'),'binary':str(release/'native/bin/codex-app-server'),
        'interpreter':sys.executable,'model':original['model'],'effort':original['effort']}
  saved(root/'spec.private.json',spec)
  saved(announcement,{'owner':'01a0f2bc-ff5a-70c2-b682-10f0987dab80','purpose':'Finite synthetic room worker qualification, zero model requests','listener':origin,'unit':unit+'.service','credentialFiles':[str(root/'intent.private.json')],'productionChanged':False,'state':'qualifying'})
  accepted=await asyncio.to_thread(provision,spec);saved(root/'provision.accepted.json',accepted)
  async def connected():
   status=home/'state'/('room-'+room+'-status.json')
   for _ in range(450):
    if status.exists() and json.loads(status.read_text()).get('state')=='connected':return
    await asyncio.sleep(.1)
   raise AssertionError('Resident service did not connect to its authenticated room')
  await connected()
  assert accepted['executionRegistration']['ready']
  assert not (home/'state/conversation-native-status.json').exists(),'Unexpected native turn/error during idle service initialization'
  again=await asyncio.to_thread(provision,spec)
  assert again['reconciled'] and not again['modelOrServiceRestarted']
  with store.pool.connection() as c:
   counts={table:c.execute('SELECT count(*) AS n FROM '+table+' WHERE authority=%s',(authority,)).fetchone()['n'] for table in ('hb_delivery','hb_executor')}
  assert counts=={'hb_delivery':0,'hb_executor':0}
  saved(root/'result.json',{'passed':True,'actualSystemdWorker':True,'nativeInitializedAndAuthenticatedRoomConnected':True,'originalProvisioningReconciledWithoutRestart':True,'registrationReady':True,'modelTurnsRequested':0,'counts':counts,'productionChanged':False})
  print('PASS real isolated systemd worker: named native context, authenticated room, original install reconciliation, zero model requests/claims')
 finally:
  if unit_file.exists():
   content=unit_file.read_text()
   if str(home/'connector.json') not in content:raise RuntimeError('Owned unit definition changed; cleanup requires inspection')
   shutil.copyfile(unit_file,root/'retained-unit.txt')
   subprocess.run(['systemctl','stop',unit],check=True,capture_output=True)
   subprocess.run(['systemctl','disable','--no-reload',unit],check=True,capture_output=True)
   unit_file.unlink();subprocess.run(['systemctl','daemon-reload'],check=True,capture_output=True);cleanup['stoppedOwnedUnit']=True
  if sudo_file.exists():
   if sudo_file.read_text()!=user+' ALL=(ALL:ALL) NOPASSWD: ALL\n':raise RuntimeError('Owned sudo policy changed')
   sudo_file.unlink()
  try:account=pwd.getpwnam(user)
  except KeyError:account=None
  if account:
   active=subprocess.run(['pgrep','-u',str(account.pw_uid)],capture_output=True,text=True)
   if active.returncode==0:raise RuntimeError('Owned worker processes remain; account cleanup held')
   auth=home/'codex-home/auth.json'
   if auth.exists():auth.unlink()
   for parent,dirs,files in os.walk(home,followlinks=False):
    os.chown(parent,0,0,follow_symlinks=False)
    for name in dirs+files:os.chown(Path(parent)/name,0,0,follow_symlinks=False)
   subprocess.run(['userdel',user],check=True,capture_output=True);cleanup['removedOwnedAccount']=True
  await runner.cleanup();store.close()
  saved(root/'cleanup.json',cleanup)
  if announcement.exists():
   note=json.loads(announcement.read_text());note.update(state='closed',cleanup=cleanup);saved(announcement,note)
asyncio.run(main())
