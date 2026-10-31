"""Native named empty agent context -> close -> same-context cold resume; no model."""
import asyncio,json,os
from pathlib import Path
from lax_connector.rpc import AppServer
from lax_connector.room_tools import TOOLS
from aiohttp import web
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
 resident=ConversationalAgent(completed_config);task=asyncio.create_task(resident.serve())
 try:
  async def ready():
   while not resident.listeners:
    if task.done():task.result()
    await asyncio.sleep(.02)
   await resident.listeners[0].ready.wait()
  await asyncio.wait_for(ready(),45)
  assert resident.thread==thread
 finally:
  task.cancel();await asyncio.gather(task,return_exceptions=True)
 resumed=AppServer(original['binary'],home,worker_home/'state/native',event,unsupported,enterprise=True)
 await resumed.start()
 try:
  response=await resumed.call('thread/resume',{'threadId':thread,'excludeTurns':True,'dynamicTools':TOOLS})
  assert response['thread']['id']==thread and response['thread']['name']=='Synthetic resident agent'
  assert not any(n['method']=='turn/started' for n in notes)
  result={'passed':True,'sameOriginalEmptyContextResumed':True,'supportedNativeNameApi':True,'originalRuntimeStatePreserved':True,'repeatInitializationReturnsOriginalReceipt':True,'actualWorkerConfigurationUsesOriginalContext':True,'maintainedResidentColdResumeAndAuthenticatedRoom':True,'dummyMessagesInjected':0,'modelTurns':0,'productionChanged':False}
  (root/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
 finally:
  await resumed.close();await runner.cleanup();store.close();(root/'notifications.private.json').write_text(json.dumps(notes))
asyncio.run(main())
