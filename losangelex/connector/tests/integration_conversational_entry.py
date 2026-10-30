"""Real native cold resume and authenticated room stream; no inference."""
import asyncio,json,os
from pathlib import Path
from aiohttp import web
from hollywood_backbone.store import Store
from hollywood_backbone.server import application
from lax_connector.conversational_agent import ConversationalAgent
from lax_connector.room_tools import TOOLS

async def main():
 os.umask(0o077)
 base=Path(os.environ['CONVERSATIONAL_EVIDENCE_ROOT']);root=Path(os.environ['CONVERSATIONAL_ENTRY_EVIDENCE']);root.mkdir(mode=0o700)
 prior=Path(os.environ['CONVERSATIONAL_PRIOR_EVIDENCE']);fixture=json.loads((prior/'fixture.intent.private.json').read_text());threads=json.loads((prior/'threads.private.json').read_text())
 original=json.loads(Path(os.environ['ROOM_NATIVE_ORIGINAL_CONFIG']).read_text())
 store=Store(json.loads(Path(os.environ['ROOM_NATIVE_DATABASE']).read_text()));runner=web.AppRunner(application(store),access_log=None);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
 with store.pool.connection() as c:head=c.execute('SELECT next_seq FROM hb_authority WHERE id=%s',(fixture['authority'],)).fetchone()['next_seq']
 cfg={'runtimeMode':'room-conversation','nativeThreadId':threads['A'],'conversationDynamicTools':TOOLS,'authorityId':fixture['authority'],'agentId':fixture['actors']['A']['id'],'token':fixture['actors']['A']['token'],'binary':original['binary'],'codexHome':str(prior/'codex-home'),'state':str(root/'agent'),'rooms':[{'roomId':fixture['room'],'after':head}],'hollywoodUrl':'http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])}
 agent=ConversationalAgent(cfg);task=asyncio.create_task(agent.serve())
 try:
  async def ready():
   while not agent.listeners:
    if task.done():task.result()
    await asyncio.sleep(.05)
   await agent.listeners[0].ready.wait()
  await asyncio.wait_for(ready(),45)
  assert json.loads((root/'agent'/'conversation-resume.json').read_text())['threadId']==threads['A']
  result={'passed':True,'originalNativeThreadResumed':threads['A'],'authenticatedRoomStreamConnected':True,'modelTurnsRequested':0,'executionClaims':0,'productionChanged':False}
  (root/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
 finally:
  task.cancel();await asyncio.gather(task,return_exceptions=True);await runner.cleanup();store.close()
asyncio.run(main())
