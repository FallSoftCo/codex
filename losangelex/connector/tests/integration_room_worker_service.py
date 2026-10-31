"""Explicit root-only isolated systemd provisioning qualification, no inference."""
import asyncio,hashlib,json,os,pwd,secrets,shutil,subprocess,sys,time
from pathlib import Path
from uuid import uuid4
from aiohttp import web,ClientSession
from hollywood_backbone.store import Store
from hollywood_backbone.server import application
from lax_connector.room_tools import RoomTools
from lax_connector.errors import HttpFailure
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
 parent=str(uuid4());child_token=secrets.token_urlsafe(40)
 credentials={'Owner':{'principalId':owner,'token':secrets.token_urlsafe(40)},'Global':{'principalId':parent,'token':secrets.token_urlsafe(40)}}
 host=str(uuid4());unit='lax-worker-'+authority.replace('-','')[:8]+'-'+agent.replace('-','')[:12]
 user='hworker-'+authority.replace('-','')[:8]+'-'+agent.replace('-','')[:12]
 base=Path('/var/lib/harness')/authority;home=base/'workers'/agent/'home'
 unit_file=Path('/etc/systemd/system')/(unit+'.service')
 sudo_file=Path('/etc/sudoers.d')/('harness-worker-'+authority.replace('-','')[:8]+'-'+agent.replace('-','')[:12])
 if base.exists() or unit_file.exists() or sudo_file.exists():raise ValueError('Qualification namespace already exists')
 try:pwd.getpwnam(user);raise ValueError('Qualification account already exists')
 except KeyError:pass
 saved(root/'intent.private.json',{'authority':authority,'room':room,'agent':agent,'owner':owner,'host':host,'unit':unit,'user':user,'credentials':credentials,'childCredential':{'agentId':agent,'authorityId':authority,'token':child_token}})
 store=Store(json.load(open(os.environ['ROOM_NATIVE_DATABASE'])));runner=web.AppRunner(application(store),access_log=None)
 announcement=Path('/opt/hetzner-blue-team/coordination/announcements')/('nextcomp-room-worker-qa-'+authority+'.json')
 session=None
 cleanup={'stoppedOwnedUnit':False,'removedOwnedAccount':False,'sourceAuthUntouched':True,'unrelatedServicesTouched':False}
 try:
  store.bootstrap(authority,'SYNTHETIC native room service QA',{'globalRoomId':room,'credentials':credentials,'childCredential':{'agentId':agent,'authorityId':authority,'token':child_token}})
  await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start();origin='http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])
  base.mkdir(mode=0o755);base.chmod(0o755)
  directory(authority,host,agent).parent.parent.mkdir(parents=True,mode=0o700)
  store.principal(parent,agent,'Synthetic host-tool peer','agent',child_token)
  role=store.role_read(parent,agent)
  store.role(parent,agent,'developer','Qualification only; wait for real human input',room,role['revision'])
  store.membership(parent,room,agent,{'can_read':True,'can_post':True,'can_request':True},0)
  session=ClientSession()
  async def request(method,path,payload=None):
   async with session.request(method,origin+'/hollywood/v3/'+path,json=payload,
          headers={'Authorization':'Bearer '+credentials['Global']['token']}) as response:
    value=await response.json()
    if response.status!=200:raise HttpFailure(response.status,str(value.get('error')))
    return value
  host_config={'runtimeMode':'room-conversation','authorityId':authority,'agentId':parent,'hostId':host,
               'hollywoodUrl':origin,'codexHome':original['codexHome'],'binary':str(release/'native/bin/codex-app-server'),
               'model':original['model'],'effort':original['effort'],'provisionInterpreter':sys.executable}
  tools=RoomTools(authority_id=authority,agent_id=parent,thread_id='original-qualified-parent-context',request=request,state=root/'parent-tools',host_config=host_config)
  credential_file=root/'parent-tools/administration'/('agent-credential-'+agent+'.json')
  original_credential={'agentId':agent,'authorityId':authority,'token':child_token}
  saved(credential_file,{**original_credential,'token':'deliberately-invalid-synthetic-credential'})
  async def invoke(call_id):
   value=await tools.call('item/tool/call',{'threadId':'original-qualified-parent-context','turnId':'original-turn',
             'callId':call_id,'tool':'lax_provision_room_agent','arguments':{'agentId':agent,'roomId':room}})
   return value,json.loads(value['contentItems'][0]['text'])
  rejected,error=await invoke('reject-invalid-enrollment')
  assert not rejected['success'] and not (base/'workers'/agent).exists()
  saved(credential_file,original_credential)
  saved(announcement,{'owner':'01a0f2bc-ff5a-70c2-b682-10f0987dab80','purpose':'Finite synthetic room host-tool qualification, zero model requests','listener':origin,'unit':unit+'.service','credentialFiles':[str(root/'intent.private.json')],'productionChanged':False,'state':'qualifying'})
  value,result=await invoke('provision-existing-peer-original')
  assert value['success'],result
  assert result['executionProvisioned'] and result['executionReady']
  accepted=result['worker'];saved(root/'provision.accepted.json',result)
  assert (await invoke('provision-existing-peer-original'))[1]==result
  async def connected():
   status=home/'state'/('room-'+room+'-status.json')
   for _ in range(450):
    if status.exists() and json.loads(status.read_text()).get('state')=='connected':return
    await asyncio.sleep(.1)
   raise AssertionError('Resident service did not connect to its authenticated room')
  await connected()
  assert accepted['executionRegistration']['ready']
  assert not (home/'state/conversation-native-status.json').exists(),'Unexpected native turn/error during idle service initialization'
  repeated,second=await invoke('inspect-existing-installation-new-call');assert repeated['success'],second
  again=second['worker']
  assert again['reconciled'] and not again['modelOrServiceRestarted']
  with store.pool.connection() as c:
   counts={table:c.execute('SELECT count(*) AS n FROM '+table+' WHERE authority=%s',(authority,)).fetchone()['n'] for table in ('hb_delivery','hb_executor')}
  assert counts=={'hb_delivery':0,'hb_executor':0}
  saved(root/'result.json',{'passed':True,'actualSystemdWorker':True,'nativeInitializedAndAuthenticatedRoomConnected':True,'originalProvisioningReconciledWithoutRestart':True,'registrationReady':True,'nativeHostToolInvoked':True,'invalidEnrollmentRejectedBeforeOsEffects':True,'sameCallCachedReceipt':True,'modelTurnsRequested':0,'counts':counts,'productionChanged':False})
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
  if session is not None:await session.close()
  await runner.cleanup();store.close()
  saved(root/'cleanup.json',cleanup)
  if announcement.exists():
   note=json.loads(announcement.read_text());note.update(state='closed',cleanup=cleanup);saved(announcement,note)
asyncio.run(main())
