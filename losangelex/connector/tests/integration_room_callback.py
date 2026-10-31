"""Real HTTP/SSE human answer into original callback; no native/model claim."""
import asyncio,json,os
from pathlib import Path
from types import SimpleNamespace
from aiohttp import web,ClientSession
from hollywood_backbone.store import Store
from hollywood_backbone.server import application
from lax_connector.room_attention import RoomAttention
from lax_connector.room_runtime import RoomRuntime

async def main():
 os.umask(0o077);root=Path(os.environ['ROOM_CALLBACK_EVIDENCE']);root.mkdir(mode=0o700)
 fixture=json.load(open(os.environ['ROOM_CALLBACK_FIXTURE']));store=Store(json.load(open(os.environ['ROOM_NATIVE_DATABASE'])))
 owner=fixture['credentials']['Owner']['principalId'];room=fixture['room'];actor=fixture['agent']
 source=store.post(owner,room,'callback-integration-source',{'kind':'message','audience':'room','body':'A synthetic callback test; no external work.'})['event']
 runner=web.AppRunner(application(store),access_log=None);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start();base='http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])+'/hollywood/v3/'
 async with ClientSession() as session:
  async def request(who,method,path,payload=None):
   async with session.request(method,base+path,json=payload,headers={'Authorization':'Bearer '+(fixture['token'] if who=='agent' else fixture['credentials']['Owner']['token'])}) as response:
    value=await response.json();assert response.status==200,(response.status,value);return value
  async def http(method,path,payload=None):return await request('agent',method,path,payload)
  agent=SimpleNamespace(thread='native-callback-thread',config={'agentId':actor},state=root,http=http,turn_sources={'native-turn':source},native_items={},finished_turns=set())
  attention=RoomAttention(agent)
  class NoRpc:
   async def call(self,*args):raise AssertionError('Control response must not start a second native input')
  runtime=RoomRuntime(rpc=NoRpc(),session=session,base_url=base,token=fixture['token'],authority_id=fixture['authority'],agent_id=actor,room_id=room,thread_id=agent.thread,state=root/'stream',initial_cursor=source['seq'],on_room_event=attention.observe)
  stream=asyncio.create_task(runtime.run());callback=None
  try:
   await asyncio.wait_for(runtime.ready.wait(),10)
   params={'threadId':agent.thread,'turnId':'native-turn','itemId':'original-item','_rpcRequestId':'original-native-rpc','questions':[{'id':'choice','header':'Choice','question':'Which one?'}]}
   callback=asyncio.create_task(attention.wait('item/tool/requestUserInput',params))
   async def created():
    while not attention.pending or 'scope' not in next(iter(attention.pending.values())):await asyncio.sleep(.02)
   await asyncio.wait_for(created(),10);identity,entry=next(iter(attention.pending.items()))
   answer={'answers':{'choice':{'answers':['Exact original answer']}}}
   await request('human','POST','attention/'+identity+'/response',{'operationId':'original-human-answer','scope':entry['scope'],'response':answer})
   assert await asyncio.wait_for(callback,10)==answer
   await attention.submitted('item/tool/requestUserInput',params,True)
   agent.finished_turns.add('native-turn');await attention.finish('native-turn')
   final=await http('GET','attention/'+identity);assert final['attention']['state']=='closed'
   result={'passed':True,'realHttpSse':True,'originalCallbackGotExactAnswer':True,'responseDidNotStartAnotherTurn':True,'closedAfterOriginalNativeSubmissionSignal':True,'nativeRpcSimulated':True,'modelCalls':0,'productionChanged':False};(root/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
  finally:
   if callback:callback.cancel();await asyncio.gather(callback,return_exceptions=True)
   stream.cancel();await asyncio.gather(stream,return_exceptions=True);runtime.close()
 await runner.cleanup();store.close()
asyncio.run(main())
