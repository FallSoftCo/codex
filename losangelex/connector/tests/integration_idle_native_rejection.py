"""Original captured native refusal recovery with explicit fake transports.

Only the disposable native-intent negative copies/appends history.
"""
from pathlib import Path
from types import SimpleNamespace
import argparse,asyncio,copy,hashlib,json,shutil,tempfile,time
from lax_connector.errors import HttpFailure
from lax_connector.idle_context_rebuild import IdleContextRebuild
from lax_connector.idle_context_rejection import inspect_rejected
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--operation',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
assert not args.output.exists()
op=args.operation;real=op.parent.parent;R=args.output.parent
original=json.loads(op.read_text())
localname='operation-'+hashlib.sha256(original['snapshotOperationId'].encode()).hexdigest()+'.json'
local=json.loads((real/localname).read_text())
class RPC:
 async def call(self,method,params,**kw):
  assert method in ('thread/turns/list','thread/contextWindow/read')
  if method=='thread/turns/list':
   return {'data':[{'id':original['request']['turnId'],'status':self.status}],'nextCursor':None}
  return {'state':self.cut}
async def case(name,edit=None,expect=True):
 with tempfile.TemporaryDirectory(dir=R,prefix='native-refusal-fixture-') as td:
  d=Path(td);j=copy.deepcopy(original);l=copy.deepcopy(local)
  rpc=RPC();rpc.status='completed';rpc.cut=copy.deepcopy(j['nativeState'])
  a=SimpleNamespace(rebuild_only=True,stop=asyncio.Event())
  installed=False
  if edit:installed=edit(j,l,rpc,a)
  (d/'original.json').write_text(json.dumps(j))
  (d/localname).write_text(json.dumps(l))
  async def http(purpose,method,path):
   assert method=='GET' and purpose=='writer'
   if path.endswith(j['snapshotOperationId']):return j['snapshot']
   assert path.endswith(j['installedOperationId'])
   if installed:return {'schema':'existing'}
   raise HttpFailure(404,'known absent',code='CONTEXT_OPERATION_NOT_FOUND')
  a.http=http
  async def request(action):
   assert action=='pending'
   return {'contextRebuild':{'requestedOperationId':j['requestOperationId']}}
  r=SimpleNamespace(agent=a,rpc=rpc,purpose='writer',thread=j['nativeThread'],
     config={'agentId':j['agentId'],'contextIds':{'writer':j['contextId']}},state=d,request=request)
  idle=SimpleNamespace(runner=r,owned=IdleContextRebuild.owned)
  try:
   proof=await inspect_rejected(idle,d/'original.json')
   assert expect,(name,'unexpected acceptance')
   assert proof['snapshot']==j['snapshot'] and proof['proof']['newInferenceAdmitted'] is False
   result='accepted_read_only'
  except Exception as e:
   if expect:raise
   result='refused:'+str(e)
  return {'case':name,'result':result}
async def main():
 cases=[]
 cases.append(await case('captured_actual_refusal_and_original_history'))
 cases.append(await case('structured_known_negative',lambda j,l,r,a:j.update(nativeRejection={'code':-32600,'message':j['holdReason'].split("'message': '")[1][:-2]})))
 cases.append(await case('stale_structured_negative_cannot_cover_unknown',lambda j,l,r,a:j.update(nativeRejection={'code':-32600,'message':'native idle replacement refused or held: native context cut changed or remains held'},holdReason='response timeout'),False))
 cases.append(await case('normal_start_does_not_retry',lambda j,l,r,a:setattr(a,'rebuild_only',False),False))
 cases.append(await case('unknown_native_outcome',lambda j,l,r,a:j.update(holdReason='response timeout'),False))
 cases.append(await case('already_installed_receipt',lambda j,l,r,a:True,False))
 cases.append(await case('changed_native_window',lambda j,l,r,a:r.cut.update(windowId='different'),False))
 cases.append(await case('original_turn_not_terminal',lambda j,l,r,a:setattr(r,'status','inProgress'),False))
 cases.append(await case('changed_snapshot_receipt',lambda j,l,r,a:l['receipt'].update(totalBytes=1),False))
 def has_intent(j,l,r,a):
  td=R/(args.output.stem+'-intent-negative.jsonl')
  assert not td.exists()
  shutil.copyfile(j['originalHistory']['path'],td)
  with td.open('ab') as f:f.write((json.dumps({'type':'event_msg','payload':{'type':'context_window_refill_intent','operationId':j['operationId']}})+'\n').encode())
  j['originalHistory'].update(path=str(td),device=td.stat().st_dev,inode=td.stat().st_ino)
 cases.append(await case('durable_native_intent_preserves_hold',has_intent,False))
 (R/(args.output.stem+'-intent-negative.jsonl')).unlink()
 receipt={'at':time.time(),'checks':cases,'readOnlyActualHistory':True,'fixtureTransports':'Explicit fake RPC/HTTP; no provider, live native process, business task or API mutation. First case scans original real35MiB history. Intent-negative appends only disposable copy.','source':'Actual SDK dispatcher; captured-history/fake-transport coverage, not live recovery or semantic proof'}
 args.output.write_text(json.dumps(receipt,indent=2)+'\n')
 print(json.dumps(receipt))
asyncio.run(main())
