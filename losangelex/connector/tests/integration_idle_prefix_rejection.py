"""Captured accepted snapshot/rollout with explicitly simulated RPC/HTTP replies.

This checks recovery admission and fail-closed controls, not a live refresh.
"""
import argparse,asyncio,copy,hashlib,importlib.util,json,shutil,tempfile,time
from pathlib import Path
from types import SimpleNamespace
from lax_connector.errors import HttpFailure
from lax_connector.idle_context_rebuild import IdleContextRebuild

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--operation",type=Path,required=True)
parser.add_argument("--candidate-module",type=Path,required=True)
parser.add_argument("--output",type=Path,required=True)
args=parser.parse_args();assert not args.output.exists()
spec=importlib.util.spec_from_file_location("lax_connector.idle_prefix_rejection",args.candidate_module)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
original_bytes=args.operation.read_bytes();original=json.loads(original_bytes)
localname="operation-"+hashlib.sha256(original["snapshotOperationId"].encode()).hexdigest()+".json"
original_local=json.loads((args.operation.parent.parent/localname).read_text())

async def case(name,edit=None,expect=True):
 with tempfile.TemporaryDirectory(dir=args.output.parent,prefix="prefix-recovery-fixture-") as tmp:
  root=Path(tmp);op=copy.deepcopy(original);local=copy.deepcopy(original_local)
  flags={"installed":False,"snapshotChanged":False,"unavailable":False,"pending":op["requestOperationId"],"turn":"completed"}
  cut=copy.deepcopy(op["nativeState"]);agent=SimpleNamespace(rebuild_only=True,stop=asyncio.Event())
  if edit:edit(op,local,cut,agent,flags,root)
  journal=root/"original.json";journal.write_text(json.dumps(op));(root/localname).write_text(json.dumps(local))
  calls=[]
  async def http(purpose,method,path):
   calls.append(("http",method,path));assert purpose=="writer" and method=="GET"
   if flags["unavailable"]:raise HttpFailure(503,"fixture unavailable")
   if path.endswith(op["snapshotOperationId"]):
    value=copy.deepcopy(original_local["receipt"])
    if flags["snapshotChanged"]:value["totalBytes"]+=1
    return value
   assert path.endswith(op["installedOperationId"])
   if flags["installed"]:return {"state":"installed"}
   raise HttpFailure(404,"known absent",code="CONTEXT_OPERATION_NOT_FOUND")
  async def request(action):
   calls.append(("context",action));assert action=="pending"
   return {"contextRebuild":{"requestedOperationId":flags["pending"]}}
  async def rpc(method,params,**kwargs):
   calls.append(("native",method));assert method in ("thread/turns/list","thread/contextWindow/read")
   if method=="thread/turns/list":return {"data":[{"id":op["request"]["turnId"],"status":flags["turn"]}],"nextCursor":None}
   return {"state":cut}
  agent.http=http
  r=SimpleNamespace(agent=agent,rpc=SimpleNamespace(call=rpc),purpose="writer",thread=op["nativeThread"],
   config={"agentId":op["agentId"],"contextIds":{"writer":op["contextId"]}},state=root,request=request)
  idle=IdleContextRebuild(r)
  try:
   proof=await module.inspect_prefix_rejected(idle,journal)
   assert expect,"Broken control accepted: "+name
   assert proof["snapshot"]==original_local["receipt"] and proof["selected"]==original_local["request"]["value"]["materialIds"]
   assert proof["proof"]["canonicalSnapshotCommitted"] and not proof["proof"]["nativeDurableIntentObserved"]
   result="admitted_read_only"
  except Exception as error:
   if expect:raise
   result="refused:"+str(error)
  assert not any(v in ("POST","turn/start","thread/contextWindow/replaceIdle") for call in calls for v in call)
  return {"case":name,"result":result}
async def main():
 results=[await case("actual_captured_prefix_refusal_and_accepted_snapshot")]
 def mutate(key,value):
  return lambda op,local,cut,agent,flags,root:op.update({key:value})
 cases=[
  ("ordinary_start",lambda o,l,c,a,f,r:setattr(a,"rebuild_only",False)),
  ("unknown_outcome",mutate("holdReason","response timeout")),
  ("prepared_packet",mutate("response",{})),
  ("preflight_exists",mutate("preflight",{})),
  ("native_result_exists",mutate("nativeResult",{})),
  ("accepted_journal_changed",lambda o,l,c,a,f,r:l.update(state="pending")),
  ("snapshot_receipt_changed",lambda o,l,c,a,f,r:f.update(snapshotChanged=True)),
  ("already_installed",lambda o,l,c,a,f,r:f.update(installed=True)),
  ("receipt_unavailable",lambda o,l,c,a,f,r:f.update(unavailable=True)),
  ("request_changed",lambda o,l,c,a,f,r:f.update(pending="other")),
  ("native_window_changed",lambda o,l,c,a,f,r:c.update(windowId="other")),
  ("inference_not_terminal",lambda o,l,c,a,f,r:f.update(turn="inProgress")),
 ]
 for name,edit in cases:results.append(await case(name,edit,False))
 def native_intent(o,l,c,a,f,r):
  dest=r/"intent-negative.jsonl";shutil.copyfile(o["originalHistory"]["path"],dest)
  with dest.open("ab") as stream:stream.write((json.dumps({"type":"event_msg","payload":{"type":"context_window_refill_intent","operationId":o["operationId"]}})+"\n").encode())
  info=dest.stat();o["originalHistory"].update(path=str(dest),device=info.st_dev,inode=info.st_ino)
 results.append(await case("native_durable_intent_retains_hold",native_intent,False))
 assert args.operation.read_bytes()==original_bytes
 receipt={"at":time.time(),"checks":results,"modelsStarted":0,"canonicalWrites":0,"scope":"Actual captured48MB rollout and accepted snapshot journal scanned. RPC/HTTP responses explicitly simulated; no live recovery or semantic proof."}
 args.output.write_text(json.dumps(receipt,indent=2)+"\n");print(json.dumps(receipt))
asyncio.run(main())

