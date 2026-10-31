"""Real HTTP/PG observation drain: captured source, lost ACK and restart, no model."""
import asyncio,json,os,secrets
from pathlib import Path
from uuid import uuid4
from aiohttp import web,ClientSession
from hollywood_backbone.store import Store
from hollywood_backbone.server import application
from lax_connector.room_activity import RoomActivity
from lax_connector.errors import HttpFailure

async def main():
    os.umask(0o077)
    root=Path(os.environ['ROOM_ACTIVITY_EVIDENCE']);root.mkdir(mode=0o700)
    store=Store(json.loads(Path(os.environ['ROOM_NATIVE_DATABASE']).read_text()))
    uid=lambda:str(uuid4())
    authority,room=uid(),uid()
    credentials={name:{'principalId':uid(),'token':secrets.token_urlsafe(40)} for name in ('Owner','Global')}
    store.bootstrap(authority,'SYNTHETIC native action outbox',{'globalRoomId':room,'credentials':credentials})
    owner,agent=(credentials[k]['principalId'] for k in ('Owner','Global'))
    original=store.post(owner,room,uid(),{'kind':'message','body':'Private original synthetic input','audience':'direct','recipientId':agent})['event']
    later=store.post(owner,room,uid(),{'kind':'message','body':'Later synthetic input','audience':'room'})['event']
    runner=web.AppRunner(application(store));await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
    base='http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])+'/hollywood/v3/'
    dropped=False;submissions=[];activity=None
    try:
        async with ClientSession() as session:
            async def send(method,path,payload):
                nonlocal dropped
                submissions.append(payload['operationId'])
                async with session.request(method,base+path,json=payload,headers={'Authorization':'Bearer '+credentials['Global']['token']}) as response:
                    value=await response.json()
                    if response.status!=200:raise HttpFailure(response.status,str(value))
                if not dropped:
                    dropped=True;raise ConnectionError('Synthetic ACK lost after real acceptance')
                return value
            params={'threadId':'same-native-thread','turnId':'same-native-turn','item':{'id':'one-native-command','type':'commandExecution','command':'PRIVATE_SENTINEL','status':'inProgress'}}
            activity=RoomActivity(state=root/'outbox',thread=params['threadId'],agent=agent,send=send)
            activity.record('item/started',params,original)
            # A steer must not move an already-started command into another
            # input's room/audience. Capture completion, then simulate restart.
            activity.record('item/completed',{**params,'item':{**params['item'],'status':'completed'}},later)
            activity=RoomActivity(state=root/'outbox',thread=params['threadId'],agent=agent,send=send)
            activity.start()
            async def settled():
                while activity.pending:await asyncio.sleep(.05)
            await asyncio.wait_for(settled(),15)
            events=store.history(owner,room,0,100,None,'activity')['events']
            assert len(events)==2 and {e['data']['phase'] for e in events}=={'started','completed'}
            assert len({e['data']['actionId'] for e in events})==1
            assert all(e['source']==original['id'] and e['audience']=='direct' and e['recipient']==owner for e in events)
            assert 'PRIVATE_SENTINEL' not in json.dumps(events)
            assert len(submissions)==3 and len(set(submissions))==2
            await activity.close()
            activity=RoomActivity(state=root/'outbox',thread=params['threadId'],agent=agent,send=send);activity.start()
            await asyncio.sleep(.1);assert not activity.pending and len(submissions)==3
            with store.pool.connection() as c:
                counts={t:c.execute('SELECT count(*) n FROM '+t+' WHERE authority=%s',(authority,)).fetchone()['n'] for t in ('hb_delivery','hb_executor')}
            assert not any(counts.values())
            (root/'result.json').write_text(json.dumps({'passed':True,'realHttpPg':True,'originalPrivateSourceRetainedAcrossSteer':True,'lostAckSameOperation':True,'restartNoDuplicate':True,'rawToolPayloadNotPublished':True,'counts':counts,'modelCalls':0,'productionChanged':False},indent=2))
            print('PASS native activity outbox + real HTTP/PG: source capture, lost ACK, restart, privacy; zero model calls')
    finally:
        if activity:await activity.close()
        await runner.cleanup();store.close()
asyncio.run(main())
