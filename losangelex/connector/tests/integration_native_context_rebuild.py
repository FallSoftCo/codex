"""Real native checkpoint/refill/reopen mechanics. A trap rejects any model request."""
import asyncio,hashlib,json,os
from pathlib import Path
from types import SimpleNamespace
from aiohttp import web
from lax_connector.rpc import AppServer
from lax_connector.native_context_rebuild import install,observe_history,refill_items
from lax_connector.journal import saved

async def main():
 os.umask(0o077)
 root=Path(os.environ["REBUILD_EVIDENCE"]);root.mkdir(mode=0o700)
 (root/"runner").mkdir(mode=0o700)
 work=root/"work";work.mkdir()
 events=[];inferences=[]
 async def event(method,params):
  events.append({"method":method,"params":params})
  saved(root/"events.json",events)
 async def tool(method,params):raise AssertionError("No tools or approvals expected")
 async def trap(request):
  inferences.append({"path":request.path})
  return web.json_response({"error":"No model inference allowed in mechanical checkpoint test"},status=500)
 app=web.Application();app.router.add_route("*","/{path:.*}",trap)
 server=web.AppRunner(app);await server.setup()
 site=web.TCPSite(server,"127.0.0.1",0);await site.start()
 base="http://127.0.0.1:"+str(site._server.sockets[0].getsockname()[1])+"/v1"
 binary=os.environ["REBUILD_BINARY"]
 rpc=AppServer(binary,root/"home",root/"native",event,tool,enterprise=True)
 thread=None
 try:
  await rpc.start()
  await rpc.call("experimentalFeature/enablement/set",{"enablement":{"token_budget":True}})
  settings={
    "cwd":str(work),"model":"gpt-6.1-sol","sandbox":"danger-full-access","approvalPolicy":"never",
    "baseInstructions":"Mechanical protocol qualification only; no inference is allowed.",
    "dynamicTools":[],"toolPolicy":{"allowedTools":[]},
    "config":{"features.token_budget":True,"features.retain_client_tool_outputs":False,
      "features.retain_client_developer_messages":False,"model_provider":"context_probe",
      "model_providers.context_probe":{"name":"No-inference trap","base_url":base,
        "wire_api":"responses","requires_openai_auth":False,"request_max_retries":0}}}
  started=await rpc.call("thread/start",settings)
  thread=started["thread"]["id"]
  await rpc.call("thread/name/set",{"threadId":thread,"name":"Disposable native context rebuild proof"})
  await rpc.call("thread/inject_items",{"threadId":thread,"items":[{
    "type":"function_call_output","name":"old_unselected_history","output":"UNSELECTED_CONTEXT_CANARY_R270"}]})
  encoded=json.dumps({"schema":"lax-context-rebuild/v1","role":"writer","objective":"Retain unfinished task identity; do not execute it","pendingOriginalId":"original-disposable-obligation"},sort_keys=True,separators=(",",":"))
  snapshot={"sha256":hashlib.sha256(encoded.encode()).hexdigest(),"totalBytes":len(encoded),
    "chunks":[{"offset":0,"content":encoded}],"meaning":"Disclosed mechanical manifest fixture, not model-selected content or semantic work"}
  runner=SimpleNamespace(rpc=rpc,thread=thread,state=root/"runner",trace=lambda event,value:saved(root/(event+".json"),value))
  receipt=await install(runner,snapshot,"mechanical-context-rebuild-r270")
  assert not inferences,"Native checkpoint attempted a model request"
  observed=await rpc.call("thread/read",{"threadId":thread,"includeTurns":False})
  path=observed["thread"]["path"]
  history=observe_history(path,refill_items(snapshot,"mechanical-context-rebuild-r270"))
  replacement=json.dumps(history["checkpoint"]["replacement_history"])
  assert "UNSELECTED_CONTEXT_CANARY_R270" not in replacement
  assert history["allFragmentsObserved"]
  await rpc.close()
  rpc=AppServer(binary,root/"home",root/"native",event,tool,enterprise=True)
  await rpc.start()
  resumed=await rpc.call("thread/resume",{**settings,"threadId":thread,"excludeTurns":True})
  assert resumed["thread"]["id"]==thread
  again=observe_history(resumed["thread"]["path"],refill_items(snapshot,"mechanical-context-rebuild-r270"))
  assert again["allFragmentsObserved"] and again["checkpoint"]==history["checkpoint"]
  assert not inferences
  saved(root/"result.json",{"passed":True,"nativeThreadPreserved":True,"unselectedOldHistoryAbsentFromReplacement":True,"exactRefillDurableAcrossReopen":True,"modelRequests":len(inferences),"businessEffects":0,"manifest":"Disclosed mechanical fixture; no semantic/model proof","receipt":receipt})
  print(json.dumps({"passed":True,"nativeThread":thread,"modelRequests":len(inferences)}),flush=True)
 finally:
  await rpc.close();await server.cleanup()
  saved(root/"model-trap-observation.json",{"requests":inferences})
if __name__=="__main__":asyncio.run(main())
