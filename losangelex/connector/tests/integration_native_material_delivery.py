"""Actual native fragment delivery/reopen/lost-reply mechanics, zero model requests."""
import sys,asyncio,hashlib,json,os
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from aiohttp import web
from lax_connector.rpc import AppServer,RpcError
from lax_connector.material_transport import deliver,fragments,MaterialDeliveryUnknown
from lax_connector.native_context_rebuild import observe_history
from lax_connector.context_runtime import ContextRunner
from lax_connector.journal import saved
async def main():
 os.umask(0o077)
 root=Path(os.environ['MATERIAL_EVIDENCE'])
 assert not root.exists();root.mkdir(mode=0o700)
 (root/'work').mkdir();(root/'state').mkdir()
 requests=[];events=[]
 async def event(method,p):events.append({'method':method,'params':p})
 async def tool(method,p):raise AssertionError('No model tool/approval expected')
 async def trap(r):
  requests.append(r.path);return web.json_response({'error':'No inference in mechanism qualification'},status=500)
 app=web.Application();app.router.add_route('*','/{rest:.*}',trap)
 webserver=web.AppRunner(app);await webserver.setup();site=web.TCPSite(webserver,'127.0.0.1',18795);await site.start()
 settings={'cwd':str(root/'work'),'model':'gpt-6.1-sol','sandbox':'danger-full-access','approvalPolicy':'never','baseInstructions':'Transport mechanism fixture only; no inference','dynamicTools':[],'toolPolicy':{'allowedTools':[]},'config':{'model_provider':'material_probe','model_providers.material_probe':{'name':'No-inference mechanism trap','base_url':'http://127.0.0.1:18795/v1','wire_api':'responses','requires_openai_auth':False,'request_max_retries':0}}}
 binary=os.environ['MATERIAL_BINARY']
 rpc=AppServer(binary,root/'home',root/'native',event,tool,enterprise=True)
 encoded=json.dumps({'source':'Disclosed mechanical snapshot','body':'a\\b"c\n'*7000},sort_keys=True,separators=(',',':'))
 snapshot={'schema':'lax-context-material-snapshot/v1','reference':'role','revision':3,'sha256':hashlib.sha256(encoded.encode()).hexdigest(),'totalBytes':len(encoded.encode()),'chunks':[{'offset':i,'content':encoded[i:i+3072]} for i in range(0,len(encoded),3072)]}
 assert 38000<len(encoded)<98304
 try:
  await rpc.start();x=await rpc.call('thread/start',settings);thread=x['thread']['id']
  await rpc.call('thread/name/set',{'threadId':thread,'name':'Finite native material mechanism QA'})
  runner=SimpleNamespace(rpc=rpc,thread=thread,state=root/'state')
  receipt=await deliver(runner,snapshot,'native-material-r278:normal')
  assert receipt['allFragmentsObserved'] and receipt['fragments']>10 and not requests
  # A duplicate receipt lookup adds no native RPC or fragment.
  original_call=rpc.call
  async def forbid(*args,**kw):raise AssertionError('Original delivered receipt must not call native again')
  rpc.call=forbid
  assert await deliver(runner,snapshot,'native-material-r278:normal')==receipt
  rpc.call=original_call
  appends=0
  class LoseReply:
   async def call(self,method,args):
    nonlocal appends
    result=await original_call(method,args)
    if method=='thread/inject_items':
     appends+=1;raise RpcError('Qualification discarded accepted native append reply')
    return result
  runner.rpc=LoseReply()
  try:await deliver(runner,snapshot,'native-material-r278:lost-reply')
  except MaterialDeliveryUnknown:pass
  else:raise AssertionError('Unknown append must not be silently called delivered')
  assert appends==1
  recovered=await deliver(runner,snapshot,'native-material-r278:lost-reply')
  assert recovered['allFragmentsObserved'] and appends==1
  runner.rpc=rpc
  observed=await rpc.call('thread/read',{'threadId':thread,'includeTurns':False});path=observed['thread']['path']
  await rpc.close()
  rpc=AppServer(binary,root/'home',root/'native',event,tool,enterprise=True);await rpc.start()
  resumed=await rpc.call('thread/resume',{**settings,'threadId':thread,'excludeTurns':True})
  assert resumed['thread']['id']==thread
  for op in ['native-material-r278:normal','native-material-r278:lost-reply']:
   assert observe_history(resumed['thread']['path'],fragments(snapshot,op))['allFragmentsObserved']
  assert not requests
  # An ordinary approval callback without callId must not trigger read-failure cancellation.
  cancelled=[]
  async def cancel():cancelled.append(True)
  owner=SimpleNamespace(native_tools=None,cancel=cancel)
  await ContextRunner.submitted(owner,'item/commandExecution/requestApproval',{},True)
  assert not cancelled
  owner.material_delivery_failed_call='exact-failed-call'
  await ContextRunner.submitted(owner,'item/tool/call',{'callId':'other'},True);assert not cancelled
  await ContextRunner.submitted(owner,'item/tool/call',{'callId':'exact-failed-call'},True);assert len(cancelled)==1
  saved(root/'result.json',{'at':__import__('time').time(),'passed':True,'nativeThreadPreserved':True,'completeFragmentsDurableAcrossReopen':True,'lostReplyAppendCalls':appends,'originalUnknownObservedWithoutReplay':True,'modelRequests':len(requests),'businessEffects':0,'callbackCancellationBoundToExactFailedRead':True,'scope':'Actual native append/read/reopen plus disclosed callback regression fixture. No real model reasoning, self-assignment execution or semantic superiority claim.'})
  print(json.dumps({'passed':True,'fragments':len(snapshot['chunks']),'modelRequests':len(requests),'lostReplyAppendCalls':appends}),flush=True)
 finally:
  await rpc.close();await webserver.cleanup()
  saved(root/'events.json',events);saved(root/'model-trap.json',{'requests':requests})
if __name__=='__main__':asyncio.run(main())
