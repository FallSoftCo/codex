"""Actual shared native SDK -> authenticated HTTP -> PostgreSQL repair and lost-reply recovery."""
import asyncio,contextlib,json,time
from pathlib import Path
from uuid import uuid4
from types import SimpleNamespace
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer
import psycopg
from psycopg.rows import dict_row
def connect():
 return psycopg.connect(**json.loads(Path("/var/lib/lax-three-context-20261018-r01/database.json").read_text()),row_factory=dict_row)
from hollywood_backbone.store import Store,json_value
from hollywood_backbone.server import application
from lax_connector.native_tool_session import NativeToolSession
from lax_connector.administration import administer
from lax_connector.errors import HttpFailure,ToolValidationError
from lax_connector.resource_routing import query
base=Path('/var/lib/lax-three-context-20261018-r01');q=Path('/aosp/development/lax-three-context-20261018-r01/qualification')
out=q/'native-input-repair-sdk-r41.json'
if out.exists():raise RuntimeError('Inspect existing qualification, no replay')
setup=json.loads((base/'setup-intent.json').read_text());agent=setup['credentials']['Global']['principalId']
cfg=json.loads((Path('/var/lib/harness')/setup['authorityId']/'purpose-agents'/agent/'home/agent.json').read_text())
# This watches real already-authorized activity, never starts a native turn.
deadline=time.monotonic()+600
while True:
 with connect() as c:
  b=c.execute("SELECT active_turn FROM hb_purpose_context WHERE agent=%s AND purpose='writer' AND accepting",(agent,)).fetchone()
  ready=bool(b and b['active_turn']);c.rollback()
 if ready:break
 if time.monotonic()>deadline:raise RuntimeError('No actual writer inference observed; no test/native admission fabricated')
 time.sleep(3)
proof={'schema':'native-inbox-repair-sdk-http/v1','at':time.time(),'mode':'Shared NativeToolSession administrative handler and Effects journals against actual authenticated HTTP/PostgreSQL. Uses current real accepted writer binding/permit, no native launch/process facts inserted. Disposable inbox fixtures roll back. This is a substrate SDK test, not a model-chosen tool call.','modelsStarted':0}
with connect() as c:
 class Borrow:
  @contextlib.contextmanager
  def connection(self):
   with c.transaction():yield c
 store=Store.__new__(Store);store.pool=Borrow()
 owner=store.actor(c,setup['credentials']['Owner']['principalId'])
 b=c.execute("SELECT active_turn FROM hb_purpose_context WHERE agent=%s AND purpose='writer' AND accepting",(agent,)).fetchone();assert b and b['active_turn']
 begin=c.execute("SELECT result FROM hb_context_operation WHERE agent=%s AND purpose='writer' AND operation=%s",(agent,'context-begin:'+b['active_turn'])).fetchone()
 scopes=begin['result']['executionScopes'];assert len(scopes)==1
 scope=scopes[0]
 d=c.execute("SELECT * FROM hb_delivery WHERE id=%s",(scope['deliveryId'],)).fetchone()
 e=c.execute("SELECT * FROM hb_event WHERE id=%s",(d['event'],)).fetchone()
 accepted=json_value({'delivery':d,'request':e})
 role=store.execution_context(agent,str(d['id']))
 source=store.event(c,owner,str(e['room']),'request','Rollback-only inbox fixture, never a worker/model request',recipient=agent)
 delivery=str(uuid4())
 c.execute('INSERT INTO hb_delivery(id,authority,event,agent) VALUES(%s,%s,%s,%s)',(delivery,setup['authorityId'],source,agent))
 state=q/('sdk-r41-journal-'+str(uuid4()));state.mkdir(mode=0o700)
 async def run():
  async with TestServer(application(store),host='127.0.0.1') as server:
   async with ClientSession() as client:
    calls=[];drop=True
    async def transport(method,path,payload=None,native_source=None):
     nonlocal drop
     headers={'Authorization':'Bearer '+cfg['tokens']['writer']}
     if native_source:headers['X-Hollywood-Native-Source']=json.dumps(native_source)
     calls.append({'method':method,'path':path})
     async with client.request(method,server.make_url('/hollywood/v3/'+path),json=payload,headers=headers) as response:
      result=await response.json()
      if response.status>=400:raise HttpFailure(response.status,json.dumps(result))
     if method=='PUT' and drop:
      drop=False;raise TimeoutError('Owned test proxy dropped original accepted response')
     return result
    session=NativeToolSession(accepted=accepted,scope=scope,config=cfg,state=state,rpc=None,role=role,transport=transport)
    params={'threadId':scope['nativeThread'],'turnId':scope['nativeTurn'],'callId':'sdk-r41-'+str(uuid4()),'tool':'hollywood_reconcile_pending_inputs','arguments':{'agentId':agent,'deliveryIds':[delivery]}}
    result=await session.call('item/tool/call',params)
    assert result['success'],result
    material=c.execute("SELECT * FROM hb_context_material WHERE agent=%s AND id=%s AND kind='input'",(agent,source)).fetchone()
    assert material and material['state']=='pending'
    after=c.execute('SELECT state,generation,claim_id,native_thread,native_turn FROM hb_delivery WHERE id=%s',(delivery,)).fetchone()
    assert after=={'state':'pending','generation':0,'claim_id':None,'native_thread':None,'native_turn':None}
    puts=[x for x in calls if x['method']=='PUT'];recovery=[x for x in calls if 'administration/commands/' in x['path']]
    assert len(puts)==1 and len(recovery)==1,(puts,recovery)
    assert await session.call('item/tool/call',params)==result
    assert len([x for x in calls if x['method']=='PUT'])==1
    proof['acceptedLostReplyRecoveredByOriginalAdministrativeReceiptWithoutSecondPut']=True
    proof['sameNativeCallReturnsOriginalResultWithoutReplay']=True
    proof['oneOriginalInputIngestedNoDeliveryClaimOrModelAdmission']=True
    readonly=SimpleNamespace(role_context=SimpleNamespace(value={'communicationAdministrator':False}))
    try:await administer(readonly,'hollywood_reconcile_pending_inputs',{'agentId':agent,'deliveryIds':[delivery]},'no-authority')
    except PermissionError:proof['nonAdministratorRejectedBeforeDispatch']=True
    else:raise AssertionError('Non-admin repair')
    c.execute("UPDATE hb_delivery SET state='cancelled',cancellation_requested=true WHERE id=%s",(delivery,))
    params={**params,'callId':'sdk-r41-cancel-'+str(uuid4())}
    refused=await session.call('item/tool/call',params)
    assert not refused['success']
    assert json.loads(refused['contentItems'][0]['text'])['status']==409
    assert not session.uncertain_tools
    proof['cancelledOriginalKnown409DoesNotLeaveUnknownToolEffect']=True
 asyncio.run(run())
 c.rollback()
 assert not c.execute('SELECT 1 FROM hb_delivery WHERE id=%s',(delivery,)).fetchone()
for bad in (25,True,0):
 try:query({'limit':bad})
 except ToolValidationError as error:assert error.public_details()['code']=='invalid_resource_page_limit'
 else:raise AssertionError('Invalid page limit')
proof['invalidResourceLimitActionableBeforeDispatch']=True
proof['allFixturesRolledBack']=True;proof['journal']=str(state)
out.write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps(proof,indent=2))

