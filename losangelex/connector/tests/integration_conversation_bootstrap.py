"""Native named empty agent context -> close -> same-context cold resume; no model."""
import asyncio,json,os,uuid
from pathlib import Path
from lax_connector.rpc import AppServer
from lax_connector.room_tools import TOOLS
from aiohttp import web,ClientSession
from hollywood_backbone.store import Store
from hollywood_backbone.server import application
from lax_connector.conversational_agent import ConversationalAgent

async def main():
 os.umask(0o077);root=Path(os.environ['ROOM_BOOTSTRAP_EVIDENCE']);root.mkdir(mode=0o700)
 original=json.load(open(os.environ['ROOM_NATIVE_ORIGINAL_CONFIG']))
 worker_home=root/'worker-home';workspace=worker_home/'work';workspace.mkdir(parents=True,mode=0o700)
 home=worker_home/'codex-home';home.mkdir(mode=0o700);(home/'auth.json').symlink_to(Path(original['codexHome'])/'auth.json')
 from lax_connector.room_bootstrap import initialize
 from lax_connector.linux_worker import expected_configuration
 notes=[]
 async def event(method,params):notes.append({'method':method,'params':params})
 async def unsupported(*args):raise AssertionError('No model or tool callback expected')
 fixture=json.load(open(os.environ['ROOM_BOOTSTRAP_FIXTURE']));authority=fixture['authority'];agent=fixture['credentials']['Global']['principalId']
 store=Store(json.load(open(os.environ['ROOM_NATIVE_DATABASE'])));runner=web.AppRunner(application(store),access_log=None)
 await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start();origin='http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])
 with store.pool.connection() as c:head=c.execute('SELECT next_seq FROM hb_authority WHERE id=%s',(authority,)).fetchone()['next_seq']
 spec={'runtimeMode':'room-conversation','nativeName':'Synthetic resident agent','purpose':'Bounded local implementation',
       'hollywoodUrl':origin,'credential':fixture['credentials']['Global']['token'],'hostId':'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
       'rooms':[{'roomId':fixture['room'],'after':head}],
       'binary':original['binary'],'model':original['model'],'effort':original['effort'],'executionProfile':'restricted'}
 config=expected_configuration(spec,authority,agent,worker_home)
 record=await initialize(config);thread=record['nativeThreadId']
 completed_config=expected_configuration(spec,authority,agent,worker_home,native_context=record)
 assert completed_config['nativeThreadId']==thread and completed_config['sandbox']=='workspace-write'
 assert await initialize(config)==record
 class Observed(ConversationalAgent):
  async def event(self,method,params):
   notes.append({'method':method,'params':params});await super().event(method,params)
 completed_config['conversationResumeInstructions']={'baseInstructions':completed_config['instructions']+'\nSynthetic explicit cold-resume instruction adoption.'}
 resident=Observed(completed_config);task=asyncio.create_task(resident.serve())
 try:
  async def ready():
   while not resident.listeners:
    if task.done():task.result()
    await asyncio.sleep(.02)
   await resident.listeners[0].ready.wait()
  await asyncio.wait_for(ready(),45)
  assert resident.thread==thread
  async def observed():
   path=worker_home/'state/native-observations'/(fixture['room']+'.json')
   while not path.exists() or 'accepted' not in json.loads(path.read_text()):
    if task.done():task.result()
    await asyncio.sleep(.05)
  await asyncio.wait_for(observed(),15)
  room=next(r for r in store.catalog(fixture['credentials']['Owner']['principalId'])['rooms'] if r['id']==fixture['room'])
  state=next(a for a in room['nativeState']['agents'] if a['agentId']==agent and a['nativeThread']==thread)
  assert state['status']['type']=='idle',state
  # Administrator visibility is not membership. Joining a new room attaches
  # another authenticated SSE listener to this SAME native process/context.
  owner=fixture['credentials']['Owner']['principalId'];peer=fixture['actors']['A']
  foreign=str(uuid.uuid4());joined=str(uuid.uuid4())
  store.create_room(owner,foreign,'Synthetic unjoined '+root.name,'Not a member',peer['id'])
  store.create_room(owner,joined,'Synthetic joined '+root.name,'Native membership journey',peer['id'])
  await resident.subscriptions.refresh()
  assert foreign not in resident.subscriptions.live and joined not in resident.subscriptions.live
  store.membership(owner,joined,agent,{'can_read':True,'can_post':True,'can_request':True},0)
  pid=resident.rpc.process.pid
  await resident.subscriptions.refresh();listener=resident.subscriptions.live[joined][0]
  await asyncio.wait_for(listener.ready.wait(),10)
  async with ClientSession() as session:
   async with session.post(origin+'/hollywood/v3/rooms/'+joined+'/messages',json={
     'operationId':'passive-native-membership-context:'+root.name,'kind':'message','audience':'room',
     'body':'Synthetic passive shared context only. No task or response requested.'},
     headers={'Authorization':'Bearer '+peer['token']}) as response:
    published=await response.json();assert response.status==200,published
  async def received():
   while listener.cursor<published['event']['seq']:
    if task.done():task.result()
    await asyncio.sleep(.05)
  await asyncio.wait_for(received(),10)
  assert resident.thread==thread and resident.rpc.process.pid==pid
  with store.pool.connection() as c:revision=c.execute('SELECT revision FROM hb_membership WHERE room=%s AND principal=%s',(joined,agent)).fetchone()['revision']
  store.membership(owner,joined,agent,{'can_read':False,'can_post':False,'can_request':False},revision)
  await resident.subscriptions.refresh()
  assert joined not in resident.subscriptions.live and fixture['room'] in resident.subscriptions.live
  assert not task.done() and resident.rpc.process.pid==pid
  with store.pool.connection() as c:revision=c.execute('SELECT revision FROM hb_membership WHERE room=%s AND principal=%s',(joined,agent)).fetchone()['revision']
  store.membership(owner,joined,agent,{'can_read':True,'can_post':True,'can_request':True},revision)
  await resident.subscriptions.refresh();rejoined=resident.subscriptions.live[joined][0]
  await asyncio.wait_for(rejoined.ready.wait(),10)
  assert rejoined.cursor>=published['event']['seq'] and resident.rpc.process.pid==pid


 finally:
  task.cancel();await asyncio.gather(task,return_exceptions=True)
 resumed=AppServer(original['binary'],home,worker_home/'state/native',event,unsupported,enterprise=True)
 await resumed.start()
 try:
  response=await resumed.call('thread/resume',{'threadId':thread,'excludeTurns':True,'dynamicTools':TOOLS})
  assert response['thread']['id']==thread and response['thread']['name']=='Synthetic resident agent'
  assert not any(n['method']=='turn/started' for n in notes)
  result={'passed':True,'sameOriginalEmptyContextResumed':True,'supportedNativeNameApi':True,'originalRuntimeStatePreserved':True,'repeatInitializationReturnsOriginalReceipt':True,'actualWorkerConfigurationUsesOriginalContext':True,'maintainedResidentColdResumeAndAuthenticatedRoom':True,'actualNativeIdleStatusInCanonicalCatalog':True,'dynamicJoinPassiveNativeInputRevokeAndRejoin':True,'administratorVisibilityNotMembership':True,'sameNativeProcessAcrossMembershipChanges':True,'explicitSupportedColdResumeInstructionAdoption':True,'dummyMessagesInjected':0,'modelTurns':0,'productionChanged':False}
  (root/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
 finally:
  await resumed.close();await runner.cleanup();store.close();(root/'notifications.private.json').write_text(json.dumps(notes))
asyncio.run(main())
