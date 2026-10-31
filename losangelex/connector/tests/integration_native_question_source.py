import asyncio,json,os,signal
from pathlib import Path
from uuid import uuid4
from aiohttp import web
from lax_connector.rpc_shared import SharedAppServer
async def main():
 os.umask(0o077);root=Path(os.environ['QUESTION_SOURCE_EVIDENCE']);root.mkdir();home=root/'profile';home.mkdir();source=str(uuid4());seen=[];done=asyncio.Event()
 async def provider(req):
  body=await req.json();output=any(v.get('type')=='function_call_output' for v in body.get('input',[]))
  question={'sourceEventId':source,'questions':[{'id':'decision','header':'Decision','question':'Continue original task?','options':[{'label':'Yes','description':'Proceed'},{'label':'No','description':'Stop'}]}]}
  item=({'type':'message','role':'assistant','id':'answer','content':[{'type':'output_text','text':'Answered'}]} if output else {'type':'function_call','call_id':'original-question','name':'request_user_input','arguments':json.dumps(question)})
  events=[{'type':'response.created','response':{'id':'owned'}},{'type':'response.output_item.done','item':item},{'type':'response.completed','response':{'id':'owned','usage':{'input_tokens':0,'input_tokens_details':None,'output_tokens':0,'output_tokens_details':None,'total_tokens':0}}}]
  return web.Response(text=''.join('data: '+json.dumps(v)+'\n\n' for v in events),content_type='text/event-stream')
 app=web.Application();app.router.add_post('/v1/responses',provider);runner=web.AppRunner(app,access_log=None);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start();port=site._server.sockets[0].getsockname()[1]
 (home/'config.toml').write_text('model_provider="fixture"\nmodel="gpt-6.1-sol"\n[model_providers.fixture]\nname="Owned fixture"\nbase_url="http://127.0.0.1:'+str(port)+'/v1"\nwire_api="responses"\nrequires_openai_auth=false\n[features]\ncode_mode=false\ndefault_mode_request_user_input=true\n')
 binary=os.environ['SHARED_NATIVE_BINARY'];socket=root/'native.sock';authority=str(uuid4());host=str(uuid4())
 value={'schema':'lax-native-host/v1','runtimeMode':'room-conversation','authorityId':authority,'hostId':host,'binary':binary,'codexHome':str(home),'state':str(root/'native'),'socket':str(socket)};(root/'host.json').write_text(json.dumps(value))
 env=dict(os.environ,CODEX_HOME=str(home),LAX_NATIVE_ENTERPRISE='1',LAX_NATIVE_RUNTIME_MODE='room-conversation');env.pop('LAX_CANONICAL_NATIVE_CHANNEL',None)
 log=(root/'native.log').open('xb');process=await asyncio.create_subprocess_exec(binary,'--listen','unix://'+str(socket),env=env,stdout=log,stderr=log,start_new_session=True);log.close();client=None
 async def event(method,params):
  if method=='turn/completed':done.set()
 async def callback(method,params):
  seen.append({'method':method,'params':params});assert method=='item/tool/requestUserInput';assert params['sourceEventId']==source
  return {'answers':{'decision':{'answers':['Yes']}}}
 try:
  for _ in range(100):
   if socket.exists():break
   if process.returncode is not None:raise RuntimeError('Native exited')
   await asyncio.sleep(.1)
  config={'authorityId':authority,'hostId':host,'binary':binary,'codexHome':str(home),'state':str(root),'nativeServer':{'manifest':str(root/'host.json')}}
  client=SharedAppServer(config,event,callback);await client.start()
  reply=await client.call('thread/start',{'cwd':str(root),'model':'gpt-6.1-sol','modelProvider':'fixture','sandbox':'danger-full-access','approvalPolicy':'never','config':{'features.code_mode':False,'features.default_mode_request_user_input':True}})
  await client.call('turn/start',{'threadId':reply['thread']['id'],'input':[{'type':'text','text':'Ask owned question'}]});await asyncio.wait_for(done.wait(),45)
  assert len(seen)==1
  result={'state':'passed','nativeQuestionSourcePreserved':True,'realProviderCalls':0,'productionChanged':False};(root/'result.json').write_text(json.dumps(result));print(json.dumps(result))
 finally:
  if client:await client.close()
  if process.returncode is None:
   os.killpg(process.pid,signal.SIGTERM)
   try:await asyncio.wait_for(process.wait(),10)
   except asyncio.TimeoutError:os.killpg(process.pid,signal.SIGKILL);await process.wait()
  (root/'callbacks.json').write_text(json.dumps(seen));await runner.cleanup()
asyncio.run(main())
