"""Real HTTP/PG/SSE original-cursor repair; recording RPC stub, zero models."""
import asyncio,json,os,secrets
from pathlib import Path
from uuid import uuid4
from aiohttp import ClientSession,web
from aiohttp.test_utils import TestServer
from hollywood_backbone.store import Store
from hollywood_backbone.server import application
from lax_connector.errors import HttpFailure
from lax_connector.room_runtime import RoomRuntime
from lax_connector.room_subscriptions import RoomSubscriptions
from lax_connector.room_input import peer_context


async def main():
    os.umask(0o077);root=Path(os.environ['ROOM_SUBSCRIPTION_EVIDENCE']);root.mkdir(mode=0o700)
    store=Store(json.loads(Path(os.environ['ROOM_NATIVE_DATABASE']).read_text()))
    authority,room,agent=[str(uuid4()) for _ in range(3)]
    credentials={k:{'principalId':str(uuid4()),'token':secrets.token_urlsafe(40)} for k in ('Owner','Global')}
    store.migrate();store.bootstrap(authority,'SYNTHETIC receive recovery',{'globalRoomId':room,'credentials':credentials})
    owner=credentials['Owner']['principalId'];peer=credentials['Global']['principalId'];token=secrets.token_urlsafe(40)
    store.principal(owner,agent,'Synthetic receiver','agent',token)
    store.membership(owner,room,agent,{'can_read':True,'can_post':True,'can_request':True},0)
    # Model the observed GPU cursor without importing any actual transcript.
    with store.pool.connection() as c:c.execute('UPDATE hb_authority SET next_seq=4344 WHERE id=%s',(authority,))
    event=store.post(peer,room,'one-original-peer-request',{'kind':'message','body':'Synthetic bounded peer input','audience':'direct','recipientId':agent})['event']
    denied=[True];wrong_scope=[False];opens=[];clock=[1000.0];rpc_calls=[];received=asyncio.Event()
    @web.middleware
    async def auth_boundary(request,handler):
        if request.path.endswith('/events'):
            opens.append(request.query.get('after'))
            if denied[0]:return web.json_response({'error':'Synthetic pre-repair route denial'},status=403)
        return await handler(request)
    app=application(store);app.middlewares.append(auth_boundary)
    server=TestServer(app,host='127.0.0.1',shutdown_timeout=0.1);await server.start_server()
    subscriptions=None
    try:
        async with ClientSession() as session:
            async def request(method,path):
                async with session.request(method,server.make_url('/hollywood/v3/'+path),headers={'Authorization':'Bearer '+token}) as response:
                    value=await response.json()
                    if response.status!=200:raise HttpFailure(response.status,str(value.get('error')))
                if wrong_scope[0] and path!='rooms':value['authorityId']=str(uuid4())
                return value
            class RPC:
                async def call(self,method,params):
                    rpc_calls.append({'method':method,'params':params});received.set()
                    return {'turn':{'id':'synthetic-original-turn'}}
            def setup(name):
                value=None
                async def status(row):value.note(row)
                def create(identity,after):
                    return RoomRuntime(rpc=RPC(),session=session,base_url=str(server.make_url('/hollywood/v3/')),
                        token=token,authority_id=authority,agent_id=agent,room_id=identity,thread_id='same-original-thread',
                        state=root/name/'rooms'/identity,initial_cursor=after,on_status=status)
                value=RoomSubscriptions(state=root/name/'subscriptions',authority=authority,agent=agent,
                    thread='same-original-thread',rooms=[{'roomId':room,'after':4344}],request=request,create=create,
                    on_rooms=lambda rooms:None,now=lambda:clock[0])
                return value,create
            subscriptions,_=setup('live')
            await subscriptions.refresh();first=subscriptions.live[room]
            await asyncio.wait_for(first[1],2)
            assert subscriptions.status[room]['httpStatus']==403 and subscriptions.known[room]['revision']==1
            assert not rpc_calls and first[0].cursor==4344
            denied[0]=False;wrong_scope[0]=True;clock[0]+=26
            await subscriptions.refresh();await asyncio.gather(*list(subscriptions.recovering.values()))
            assert not rpc_calls and subscriptions.live[room][1].done()
            wrong_scope[0]=False;clock[0]+=301
            await subscriptions.refresh();await asyncio.gather(*list(subscriptions.recovering.values()))
            await asyncio.wait_for(received.wait(),3)
            listener=subscriptions.live[room][0]
            assert listener.cursor==event['seq'] and len(rpc_calls)==1
            assert rpc_calls[0]['method']=='hollywood/agentMessage' and rpc_calls[0]['params']['eventId']==event['id']
            assert rpc_calls[0]['params']['authorId']==peer and rpc_calls[0]['params']['threadId']=='same-original-thread'
            assert subscriptions.known[room]['revision']==1  # No grant edit/restart-only repair.
            await subscriptions.close();subscriptions,_=setup('live')
            subscriptions.start_room(room);await asyncio.wait_for(subscriptions.live[room][0].ready.wait(),3)
            assert len(rpc_calls)==1 and subscriptions.live[room][0].cursor==event['seq']
            await subscriptions.close();subscriptions=None
            # An unknown original handoff blocks before SSE/native resubmission,
            # including across refreshes and an explicit listener-owner restart.
            held,create=setup('held');original=create(room,4344)
            payload={'method':'hollywood/agentMessage','params':peer_context(event,authority_id=authority,agent_id=agent,thread_id='same-original-thread')}
            original.journal.stage(authority=authority,agent=agent,event=event['id'],thread='same-original-thread',seq=event['seq'],payload=payload)
            original.journal.begin_handoff(authority,agent,event['id']);original.close()
            before=len(opens);held.start_room(room);assert held.status[room]['state']=='needs_reconciliation'
            await held.refresh();clock[0]+=601;await held.refresh()
            assert len(opens)==before and len(rpc_calls)==1;await held.close()
            held,_=setup('held');held.start_room(room);assert not held.live;await held.close()
            # Actual canonical revocation remains denied; absence from a catalog
            # never fabricates a new membership or an idle runtime.
            store.membership(owner,room,agent,{'can_read':False,'can_post':False,'can_request':False},1)
            subscriptions,_=setup('live');subscriptions.start_room(room)
            await asyncio.wait_for(subscriptions.live[room][1],2)
            assert subscriptions.status[room]['httpStatus']==403
            await subscriptions.refresh();clock[0]+=601;await subscriptions.refresh()
            assert len(rpc_calls)==1
            result={'realHttpPgSse':True,'originalCursor':4344,'sameMembershipRevision':1,
                'nativeAdmissionStubCalls':len(rpc_calls),'modelCalls':0,'nativeProcessesStarted':0,
                'sameOriginalEventOnce':True,'wrongScopeHeld':True,'unknownHandoffNeverRestartedByRefresh':True,
                'revocationHeld':True,'streamOpenCursors':opens,'actualGpuReference':'92738049-51a7-4641-8599-67c1f3f96f0d (synthetic reproduction, not production action)'}
            (root/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    finally:
        if subscriptions:await subscriptions.close()
        await server.close();store.close()


asyncio.run(main())
