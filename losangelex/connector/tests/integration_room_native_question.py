"""Actual model/native request_user_input -> real human HTTP answer -> same turn."""
import asyncio,json,os
from pathlib import Path
from aiohttp import web,ClientSession
from hollywood_backbone.store import Store
from hollywood_backbone.server import application
from lax_connector.rpc import AppServer
from lax_connector.conversational_agent import ConversationalAgent
from lax_connector.room_tools import TOOLS

async def main():
 os.umask(0o077);root=Path(os.environ['ROOM_NATIVE_QUESTION_EVIDENCE']);root.mkdir(mode=0o700)
 fixture=json.load(open(os.environ['ROOM_CALLBACK_FIXTURE']));original=json.load(open(os.environ['ROOM_NATIVE_ORIGINAL_CONFIG']))
 store=Store(json.load(open(os.environ['ROOM_NATIVE_DATABASE'])));room=fixture['room'];authority=fixture['authority'];actor=fixture['agent'];owner=fixture['credentials']['Owner']['principalId']
 runner=web.AppRunner(application(store),access_log=None);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start();origin='http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])
 home=root/'codex-home';home.mkdir(mode=0o700);(home/'auth.json').symlink_to(Path(original['codexHome'])/'auth.json');(home/'config.toml').write_text('[features]\ndefault_mode_request_user_input = true\n')
 async def ignore(*args):pass
 async def unsupported(*args):raise AssertionError('No callback expected before human input')
 creator=AppServer(original['binary'],home,root/'native-create',ignore,unsupported,enterprise=True)
 await creator.start()
 try:
  created=await creator.call('thread/start',{'cwd':str(root),'model':original['model'],'sandbox':'workspace-write','approvalPolicy':'never','dynamicTools':TOOLS,'baseInstructions':'You are a participant in a synthetic qualification room. Before choosing any label, use request_user_input to ask the human which label they want, with two choices. After the answer, write the chosen label to selected-label.txt using native execution and publish the exact chosen label in the room using hollywood_publish. Ordinary final text is private. Do not ask by plain chat, poll, provision agents or perform unrelated work. Room '+room+'.','config':{'model_reasoning_effort':original['effort'],'agents.enabled':False,'features.multi_agent':False,'features.multi_agent_v2':False}})
  thread=created['thread']['id'];(root/'thread.private.json').write_text(json.dumps(created))

 except BaseException:
  await creator.close();raise
 with store.pool.connection() as c:head=c.execute('SELECT next_seq FROM hb_authority WHERE id=%s',(authority,)).fetchone()['next_seq']
 cfg={'runtimeMode':'room-conversation','nativeThreadId':thread,'conversationDynamicTools':TOOLS,'authorityId':authority,'agentId':actor,'token':fixture['token'],'binary':original['binary'],'codexHome':str(home),'state':str(root/'agent'),'rooms':[{'roomId':room,'after':head}],'hollywoodUrl':origin}
 notes=[];complete=asyncio.Event();callbacks=[]
 class Observed(ConversationalAgent):
  async def event(self,method,params):
   notes.append({'method':method,'params':params});await super().event(method,params)
   if method=='turn/completed':complete.set()
  async def tool(self,method,params):
   callbacks.append({'method':method,'params':params});return await super().tool(method,params)
 agent=Observed(cfg)
 # Hand the already-running owned transport to its conversation owner. This
 # avoids closing a newly-created lazy thread before its first human message.
 agent.rpc=creator;creator.on_event=agent.event;creator.on_request=agent.tool;creator.on_submission=agent.attention.submitted
 task=asyncio.create_task(agent.serve())
 try:
  async def ready():
   while not agent.listeners:
    if task.done():task.result()
    await asyncio.sleep(.02)
   await agent.listeners[0].ready.wait()
  await asyncio.wait_for(ready(),30)
  human=store.post(owner,room,'native-question-'+root.name,{'kind':'message','audience':'room','body':'Please create the label artifact. Ask me to choose the label before you write it, then report the result here.'})
  (root/'human.accepted.json').write_text(json.dumps(human))
  async def asked():
   while not agent.attention.pending or 'scope' not in next(iter(agent.attention.pending.values())):
    if complete.is_set():raise AssertionError('Native turn ended without an actionable question')
    if task.done():task.result()
    await asyncio.sleep(.05)
  await asyncio.wait_for(asked(),120)
  identity,entry=next(iter(agent.attention.pending.items()));questions=entry['payload']['request']['questions'];answers={q['id']:{'answers':['ORCHID']} for q in questions}
  async with ClientSession() as session:
   async with session.post(origin+'/hollywood/v3/attention/'+identity+'/response',json={'operationId':'original-human-choice','scope':entry['scope'],'response':{'answers':answers}},headers={'Authorization':'Bearer '+fixture['credentials']['Owner']['token']}) as response:
    value=await response.json();assert response.status==200,(response.status,value);(root/'answer.accepted.json').write_text(json.dumps(value))
  await asyncio.wait_for(complete.wait(),150)
  assert (root/'selected-label.txt').read_text().strip()=='ORCHID'
  started=[n for n in notes if n['method']=='turn/started'];assert len(started)==1,'Answer started another turn'
  assert any(c['method']=='item/tool/requestUserInput' for c in callbacks)
  posts=[c for c in callbacks if c['method']=='item/tool/call' and c['params'].get('tool')=='hollywood_publish'];assert posts
  current=store.attention_read(actor,identity);assert current['attention']['state']=='closed'
  result={'passed':True,'actualNativeQuestion':True,'sameNativeTurnAfterHumanAnswer':True,'nativeLocalArtifact':'ORCHID','deliberateRoomPublication':True,'closedOriginalCallback':True,'model':original['model'],'effort':original['effort'],'productionChanged':False};(root/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
 finally:
  task.cancel();await asyncio.gather(task,return_exceptions=True);await runner.cleanup();store.close();(root/'notifications.private.json').write_text(json.dumps(notes));(root/'callbacks.private.json').write_text(json.dumps(callbacks))
asyncio.run(main())
