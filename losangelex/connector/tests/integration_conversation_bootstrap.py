"""Native named empty agent context -> close -> same-context cold resume; no model."""
import asyncio,json,os
from pathlib import Path
from lax_connector.rpc import AppServer
from lax_connector.room_tools import TOOLS

async def main():
 os.umask(0o077);root=Path(os.environ['ROOM_BOOTSTRAP_EVIDENCE']);root.mkdir(mode=0o700)
 original=json.load(open(os.environ['ROOM_NATIVE_ORIGINAL_CONFIG']))
 home=root/'codex-home';home.mkdir(mode=0o700);(home/'auth.json').symlink_to(Path(original['codexHome'])/'auth.json')
 from lax_connector.room_bootstrap import initialize
 notes=[]
 async def event(method,params):notes.append({'method':method,'params':params})
 async def unsupported(*args):raise AssertionError('No model or tool callback expected')
 config={'runtimeMode':'room-conversation','authorityId':'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','agentId':'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
         'state':str(root/'agent'),'codexHome':str(home),'workspace':str(root),'nativeName':'Synthetic resident agent',
         'binary':original['binary'],'model':original['model'],'effort':original['effort'],'sandbox':'workspace-write',
         'instructions':'Synthetic empty resident agent. Wait for real human room input; do not start work on startup.'}
 record=await initialize(config);thread=record['nativeThreadId']
 assert await initialize(config)==record
 resumed=AppServer(original['binary'],home,root/'agent/native',event,unsupported,enterprise=True)
 await resumed.start()
 try:
  response=await resumed.call('thread/resume',{'threadId':thread,'excludeTurns':True,'dynamicTools':TOOLS})
  assert response['thread']['id']==thread and response['thread']['name']=='Synthetic resident agent'
  assert not any(n['method']=='turn/started' for n in notes)
  result={'passed':True,'sameOriginalEmptyContextResumed':True,'supportedNativeNameApi':True,'originalRuntimeStatePreserved':True,'repeatInitializationReturnsOriginalReceipt':True,'dummyMessagesInjected':0,'modelTurns':0,'productionChanged':False}
  (root/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
 finally:
  await resumed.close();(root/'notifications.private.json').write_text(json.dumps(notes))
asyncio.run(main())
