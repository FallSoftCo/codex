"""Actual PG/HTTP workflows, lost ACK and retained unknowns; no model/process."""
import asyncio,json,os
from pathlib import Path
from aiohttp import web,ClientSession
from hollywood_backbone.store import Store
from hollywood_backbone.server import application
from lax_connector.room_tools import RoomTools
from lax_connector.errors import HttpFailure

async def main():
 os.umask(0o077);root=Path(os.environ['ROOM_ADMIN_EVIDENCE']);root.mkdir(mode=0o700)
 fixture=json.load(open(os.environ['ROOM_ADMIN_FIXTURE']));authority=fixture['authority'];actor=fixture['credentials']['Global']['principalId']
 store=Store(json.load(open(os.environ['ROOM_NATIVE_DATABASE'])));runner=web.AppRunner(application(store),access_log=None)
 await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start();origin='http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])+'/hollywood/v3/'
 trace=[];lose_ack=True;before_dispatch=False;hold_receipt=False
 try:
  async with ClientSession() as session:
   async def request(method,path,payload=None):
    nonlocal lose_ack,hold_receipt
    trace.append({'method':method,'path':path})
    if hold_receipt and method=='GET' and path.startswith('administration/commands/'):
     hold_receipt=False;raise ConnectionError('Original receipt temporarily unavailable')
    if before_dispatch and method!='GET':raise ConnectionError('Synthetic unknown before transport readback')
    async with session.request(method,origin+path,json=payload,headers={'Authorization':'Bearer '+fixture['credentials']['Global']['token']}) as response:
     value=await response.json()
     if response.status!=200:raise HttpFailure(response.status,str(value.get('error')))
     if lose_ack and method=='POST' and path=='principals':
      lose_ack=False;raise ConnectionError('Actual accepted HTTP reply deliberately withheld')
     return value
   def tools():return RoomTools(authority_id=authority,agent_id=actor,thread_id='original-native-admin-context-'+root.name,request=request,state=root/'tools')
   async def call(tool,name,args,call_id):
    value=await tool.call('item/tool/call',{'threadId':'original-native-admin-context-'+root.name,'turnId':'original-turn','callId':call_id,'tool':name,'arguments':args})
    return value,json.loads(value['contentItems'][0]['text'])
   agent_args={'name':'Native workflow peer '+root.name,'primary':'developer','purpose':'Bounded synthetic implementation'}
   first,result=await call(tools(),'hollywood_create_agent',agent_args,'create-peer-original');assert first['success'],result
   child=result['principalId'];assert not result['executionProvisioned']
   assert len([x for x in trace if x=={'method':'POST','path':'principals'}])==1
   count=len([x for x in trace if x['method']!='GET'])
   replay,replayed=await call(tools(),'hollywood_create_agent',agent_args,'create-peer-original');assert replay['success'] and replayed==result
   assert len([x for x in trace if x['method']!='GET'])==count
   room_call,room=await call(tools(),'hollywood_create_room',{'name':'Native workflow room '+root.name,'purpose':'Human room collaboration','ownerId':child},'create-room-original');assert room_call['success'],room
   # An actually accepted principal whose receipt was temporarily unreadable
   # resumes the original workflow after reopening; principal POST stays once.
   lose_ack=True;hold_receipt=True
   interrupted,_=await call(tools(),'hollywood_create_agent',{**agent_args,'name':'Recovered original peer '+root.name},'recover-original');assert not interrupted['success']
   original=next(json.loads(p.read_text()) for p in (root/'tools/administration').glob('workflow-*.json') if json.loads(p.read_text())['state']=='unconfirmed')
   principal_posts=len([x for x in trace if x=={'method':'POST','path':'principals'}])
   resumed,recovered=await call(tools(),'hollywood_admin_reconcile',{'operationId':original['operationId']},'recover-same-workflow')
   assert resumed['success'],recovered
   assert recovered['operationId']==original['operationId']
   assert len([x for x in trace if x=={'method':'POST','path':'principals'}])==principal_posts
   # Unknown delivery remains unknown, blocks replacement mutation, and
   # explicit same-operation reconciliation sends no second POST.
   before_dispatch=True
   unknown,error=await call(tools(),'hollywood_create_agent',{**agent_args,'name':'Unknown native peer '+root.name},'unknown-original');assert not unknown['success']
   workflows=[json.loads(p.read_text()) for p in (root/'tools/administration').glob('workflow-*.json')]
   pending=next(w for w in workflows if w['state']=='unconfirmed')
   attempts=len([x for x in trace if x['method']!='GET'])
   blocked,_=await call(tools(),'hollywood_create_room',{'name':'Must not replace','purpose':'No duplicate work','ownerId':child},'replacement');assert not blocked['success']
   inspected,_=await call(tools(),'hollywood_admin_reconcile',{'operationId':pending['operationId']},'inspect-original');assert not inspected['success']
   assert len([x for x in trace if x['method']!='GET'])==attempts
   with store.pool.connection() as c:
    counts={table:c.execute('SELECT count(*) AS n FROM '+table+' WHERE authority=%s',(authority,)).fetchone()['n'] for table in ('hb_delivery','hb_executor')}
   assert counts=={'hb_delivery':0,'hb_executor':0},counts
   # No credential returned to model-facing tool output.
   assert 'token' not in result and 'enrollmentCredential' not in result
   output={'passed':True,'realPgHttp':True,'sharedAdministrativeWorkflows':True,'lostAckSinglePost':True,'restoredCallSameReceiptNoWrites':True,'unknownBlocksReplacementAndNoResend':True,'reopenedAcceptedWorkflowContinuesWithoutDuplicatePrincipal':True,'counts':counts,'modelsStarted':0,'hostWorkersCreated':0,'productionChanged':False}
   (root/'result.json').write_text(json.dumps(output,indent=2));print(json.dumps(output))
 finally:
  (root/'trace.json').write_text(json.dumps(trace,indent=2));await runner.cleanup();store.close()
asyncio.run(main())
