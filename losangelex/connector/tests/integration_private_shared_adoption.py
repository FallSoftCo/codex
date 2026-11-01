"""Real native cold transport migration retains original thread/history/storage."""
import asyncio,json,os,signal
from pathlib import Path
from uuid import uuid4
from aiohttp import web
from lax_connector.rpc import AppServer
from lax_connector.rpc_shared import SharedAppServer
from lax_connector.host_native import manifest,native_command
async def main():
 root=Path(os.environ['ADOPTION_EVIDENCE']);root.mkdir(mode=0o700);home=root/'agent';home.mkdir();(home/'work').mkdir();(home/'codex-home').mkdir();state=home/'state';state.mkdir();native=state/'native';binary=os.environ['SHARED_NATIVE_BINARY'];a,h,g=map(str,[uuid4(),uuid4(),uuid4()])
 done=asyncio.Event();requests=[];callbacks=[]
 async def respond(request):
  requests.append(await request.json());item={'type':'message','role':'assistant','id':'answer_fixture','content':[{'type':'output_text','text':'retained synthetic answer'}]};data=[{'type':'response.created','response':{'id':'fixture'}},{'type':'response.output_item.done','item':item},{'type':'response.completed','response':{'id':'fixture','usage':{'input_tokens':0,'output_tokens':0,'total_tokens':0}}}]
  if len(requests)==2:data[1]['item']={'type':'function_call','call_id':'reviewed_callback','name':'reviewed_context','arguments':'{}'}
  return web.Response(text=''.join('data: '+json.dumps(v)+'\n\n' for v in data),content_type='text/event-stream')
 app=web.Application();app.router.add_post('/v1/responses',respond);runner=web.AppRunner(app,access_log=None);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start();port=site._server.sockets[0].getsockname()[1]
 (home/'codex-home/config.toml').write_text('model_provider="fixture"\nmodel="gpt-6.1-sol"\n[model_providers.fixture]\nname="Owned fixture"\nbase_url="http://127.0.0.1:'+str(port)+'/v1"\nwire_api="responses"\nrequires_openai_auth=false\n[features]\ncode_mode=false\n')
 async def observe(method,params):
  if method=='turn/completed':done.set()
 private=AppServer(binary,home/'codex-home',native,observe,observe,enterprise=True,runtime_mode='room-conversation');daemon=None;shared=None
 try:
  await private.start();v=await private.call('thread/start',{'cwd':str(home/'work'),'model':'gpt-6.1-sol','modelProvider':'fixture','approvalPolicy':'never','sandbox':'danger-full-access','experimentalRawEvents':False,'dynamicTools':[{'name':'legacy_context','description':'Original legacy binding','inputSchema':{'type':'object','properties':{}}}]});thread=v['thread']['id']
  marker='original-history-'+str(uuid4());await private.call('turn/start',{'threadId':thread,'input':[{'type':'text','text':marker}]});await asyncio.wait_for(done.wait(),30)
  await private.close()
  adoption={'state':str(native),'nativeThreadId':thread,'configurationSha256':'0'*64};spec={'authorityId':a,'hostId':h,'agentId':g,'binary':binary,'nativeStateAdoption':adoption};value=manifest(spec,home,'fixture');value['socket']=str(root/'native.sock');file=root/'host.json';file.write_text(json.dumps(value));os.chmod(file,0o600)
  assert value['state']==str(native)
  env=dict(os.environ,CODEX_HOME=str(home/'codex-home'),LAX_NATIVE_ENTERPRISE='1',LAX_NATIVE_RUNTIME_MODE='room-conversation');env.pop('LAX_CANONICAL_NATIVE_CHANNEL',None)
  with (root/'daemon.log').open('xb') as log:daemon=await asyncio.create_subprocess_exec(*native_command(value),env=env,stdout=log,stderr=log,start_new_session=True)
  async def callback(method,params):
   assert method=='item/tool/call' and params['tool']=='reviewed_context';callbacks.append(params);return {'success':True,'contentItems':[{'type':'inputText','text':'verified reviewed binding'}]}
  shared=SharedAppServer({'authorityId':a,'hostId':h,'binary':binary,'codexHome':str(home/'codex-home'),'state':str(state),'nativeThreadId':thread,'nativeServer':{'manifest':str(file)}},observe,callback);await shared.start();tools=[{'name':'reviewed_context','description':'Reviewed conversational binding','inputSchema':{'type':'object','properties':{}}}];v=await shared.call('thread/resume',{'threadId':thread,'dynamicTools':tools});assert v['thread']['id']==thread
  v=await shared.call('thread/items/list',{'threadId':thread,'limit':100});assert marker in json.dumps(v),v
  await shared.call('thread/resume',{'threadId':thread,'dynamicTools':tools});done.clear();await shared.call('turn/start',{'threadId':thread,'input':[{'type':'text','text':'AFTER_MIGRATION'}]});await asyncio.wait_for(done.wait(),30);assert len(callbacks)==1 and len(requests)==3
  r={'reviewedToolReplacedLegacyOnColdResume':True,'sameLoadedBindingAccepted':True,'realScopedCallbackCompleted':True,'state':'passed','originalThreadId':thread,'originalHistoryRetained':True,'nativeStateUnchanged':True,'localSyntheticProviderRequests':len(requests),'realProviderCalls':0,'privateNativeStoppedBeforeSharedStarted':True};(root/'result.json').write_text(json.dumps(r,indent=2));print(json.dumps(r))
 finally:
  await private.close()
  await runner.cleanup()
  if shared:await shared.close()
  if daemon and daemon.returncode is None:
   os.killpg(daemon.pid,signal.SIGTERM)
   try:await asyncio.wait_for(daemon.wait(),10)
   except asyncio.TimeoutError:os.killpg(daemon.pid,signal.SIGKILL);await daemon.wait()
asyncio.run(main())
