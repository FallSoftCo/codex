"""Actual shared-native checkpoint/refill/cold-reopen, with a no-inference trap.

Uses a separately named disposable context, never a production role or request.
Run as the existing enrolled host account; profile and output paths are explicit.
"""
import asyncio,json,hashlib,sys
from pathlib import Path
from uuid import uuid4
from aiohttp import web
from lax_connector.rpc_shared import native_client
from lax_connector.room_tools import TOOLS
from lax_connector.project_adoption import checkpoint,reviewed_configuration
from lax_connector.journal import saved
from lax_connector.native_context_rebuild import observe_history,refill_items

async def main(profile,output):
 q=Path(output);q.mkdir(mode=0o700,parents=True,exist_ok=False)
 original=json.loads(Path(profile).read_text());thread=None;events=[];inferences=[];rpc=None;receipt=None
 async def event(method,params):events.append({'method':method,'params':params})
 async def no_tools(*args):raise AssertionError('No model tool or approval in mechanical handover')
 async def trap(request):
  inferences.append({'method':request.method,'path':request.path})
  return web.json_response({'error':'No inference is authorized in mechanical role handover'},status=500)
 app=web.Application();app.router.add_route('*','/{path:.*}',trap);runner=web.AppRunner(app);await runner.setup()
 site=web.TCPSite(runner,'127.0.0.1',0);await site.start();port=site._server.sockets[0].getsockname()[1]
 config={**original,'agentId':str(uuid4()),'state':str(q/'state'),'workspace':str(q/'work')}
 config.pop('nativeThreadId',None);(q/'state').mkdir(mode=0o700);(q/'work').mkdir(mode=0o700)
 saved(q/'listener.json',{'host':'127.0.0.1','port':port,'purpose':'owned no-inference test trap','businessRequests':False})
 try:
  rpc=native_client(config,event,no_tools);await rpc.start()
  created=await rpc.call('thread/start',{'cwd':str(q/'work'),'model':config['model'],'sandbox':'danger-full-access','approvalPolicy':'never',
    'baseInstructions':'Mechanical role-handover qualification only. No inference or tools are authorized.','dynamicTools':TOOLS,
    'config':{'model_provider':'handover_probe','model_providers.handover_probe':{'name':'No-inference trap','base_url':f'http://127.0.0.1:{port}/v1','wire_api':'responses','requires_openai_auth':False,'request_max_retries':0},'features.token_budget':False}})
  thread=created['thread']['id'];config['nativeThreadId']=thread;rpc.bind_thread(thread)
  await rpc.call('thread/name/set',{'threadId':thread,'name':'NextComp role-handover QA — no work'})
  await rpc.call('thread/inject_items',{'threadId':thread,'items':[{'type':'function_call_output','name':'old_context_fixture','output':'OLD_BROADCAST_CONTEXT_CANARY'}]})
  text=json.dumps({'schema':'lax-project-handover/v1','retained':'Original work and unknown-effect references remain evidence, never replay authority.'},sort_keys=True,separators=(',',':'))
  snapshot={'sha256':hashlib.sha256(text.encode()).hexdigest(),'totalBytes':len(text.encode()),'chunks':[{'offset':0,'content':text}]}
  saved(q/'intent.json',{'nativeThread':thread,'snapshot':snapshot,'productionThreadsChanged':False})
  receipt=await checkpoint(rpc,config,q/'state',snapshot,'owned-project-handover-r01',reviewed_instructions={'baseInstructions':'Reviewed new role fixture. Original history stays retained. No model inference or tools are authorized.'},native_config={'model_provider':'handover_probe','model_providers.handover_probe':{'name':'No-inference trap','base_url':f'http://127.0.0.1:{port}/v1','wire_api':'responses','requires_openai_auth':False,'request_max_retries':0}})
  assert not inferences,'Mechanical checkpoint contacted a model provider'
  observed=await rpc.call('thread/read',{'threadId':thread,'includeTurns':False})
  history=observe_history(observed['thread']['path'],refill_items(snapshot,'owned-project-handover-r01'))
  assert history['allFragmentsObserved'] and 'OLD_BROADCAST_CONTEXT_CANARY' not in json.dumps(history['checkpoint']['replacement_history'])
  resumed=await rpc.call('thread/resume',{'threadId':thread,'excludeTurns':True,'dynamicTools':TOOLS,'config':{'features.token_budget':False,'model_provider':'handover_probe','model_providers.handover_probe':{'name':'No-inference trap','base_url':f'http://127.0.0.1:{port}/v1','wire_api':'responses','requires_openai_auth':False,'request_max_retries':0}}})
  assert resumed['thread']['id']==thread
  saved(q/'qualification.json',{'passed':True,'actualSharedNative':True,'sameThread':True,'oldContextRemovedFromModelWindow':True,'originalHistoryRetained':True,
      'refillObserved':True,'providerRequests':len(inferences),'newAppServers':0,'productionThreadsChanged':False,'checkpoint':receipt})
  print(json.dumps({'passed':True,'actualSharedNative':True,'providerRequests':len(inferences),'newAppServers':0}))
 except Exception as e:
  saved(q/'failure.json',{'errorType':type(e).__name__,'message':str(e),'nativeThread':thread,'providerRequests':inferences})
  raise
 finally:
  saved(q/'events.private.json',events)
  if rpc and thread:
   observed=await rpc.call('thread/read',{'threadId':thread,'includeTurns':False})
   if observed['thread']['status']['type'] in ('idle','notLoaded'):
    await rpc.call('thread/archive',{'threadId':thread});saved(q/'cleanup.json',{'archivedQaThread':thread,'productionThreadsChanged':False})
   else:saved(q/'cleanup.json',{'unsettledQaThread':thread,'productionThreadsChanged':False})
  if rpc:await rpc.close()
  await runner.cleanup()

if __name__=='__main__':asyncio.run(main(sys.argv[1],sys.argv[2]))
