"""Real HTTP/PG: rejected metadata can recover, revoked work cannot restart."""
import asyncio,json,os,secrets
from pathlib import Path
from uuid import uuid4
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer
from hollywood_backbone.store import Store
from hollywood_backbone.server import application
from lax_connector.room_native_state import RoomNativeState
from lax_connector.errors import HttpFailure


async def main():
    os.umask(0o077)
    root=Path(os.environ['ROOM_RECOVERY_EVIDENCE']);root.mkdir(mode=0o700)
    store=Store(json.loads(Path(os.environ['ROOM_NATIVE_DATABASE']).read_text()))
    authority,room,agent=[str(uuid4()) for _ in range(3)]
    credentials={k:{'principalId':str(uuid4()),'token':secrets.token_urlsafe(40)} for k in ('Owner','Global')}
    store.migrate();store.bootstrap(authority,'SYNTHETIC observation recovery',{'globalRoomId':room,'credentials':credentials})
    owner=credentials['Owner']['principalId'];token=secrets.token_urlsafe(40)
    store.principal(owner,agent,'Synthetic observer','agent',token)
    grants={'can_read':True,'can_post':False,'can_request':False}
    store.membership(owner,room,agent,grants,0)
    revision=1;clock=[1000.0];calls=[];bad_token=False;bad_scope=False
    source=store.post(owner,room,str(uuid4()),{'kind':'message','body':'Synthetic original','audience':'direct','recipientId':agent})['event']
    server=TestServer(application(store),host='127.0.0.1');await server.start_server()
    try:
        async with ClientSession() as session:
            async def send(method,path,payload):
                calls.append((method,path,payload))
                async with session.request(method,server.make_url('/hollywood/v3/'+path),json=payload,
                        headers={'Authorization':'Bearer '+('rejected' if bad_token else token)}) as response:
                    value=await response.json()
                    if response.status!=200:raise HttpFailure(response.status,str(value.get('error')))
                if bad_scope and method=='GET':value['authorityId']=str(uuid4())
                return value
            def observer():
                value=RoomNativeState(state=root/'status',thread='same-synthetic-thread',agent=agent,
                    authority=authority,rooms=[{'roomId':room,'membershipRevision':revision}],send=send,now=lambda:clock[0])
                value.update({'type':'active','activeFlags':[]},source)
                return value
            value=observer();await value.flush()
            assert len(calls)==1 and json.loads((root/'status'/f'{room}.json').read_text())['rejected']['status']==403
            await value.flush();assert len(calls)==1
            grants['can_post']=True;store.membership(owner,room,agent,grants,revision);revision+=1
            value.set_rooms([{'roomId':room,'membershipRevision':revision}]);await value.flush()
            assert [c[0] for c in calls]==['POST','GET','POST']
            assert store.room_detail(owner,room)['nativeState']['agents'][0]['status']['type']=='active'
            # Another observer receipt is not permission to repeat an old revision.
            await send('POST','rooms/'+room+'/activity',{'observationType':'nativeState',
                'nativeThread':value.thread,'revision':100,'status':{'type':'idle','activeFlags':[]}})
            await value.flush();assert json.loads((root/'status'/f'{room}.json').read_text())['rejected']['status']==409
            clock[0]+=26;await value.flush()
            assert store.room_detail(owner,room)['nativeState']['agents'][0]['revision']==101
            # Real 401, then same authenticated identity repaired. No POST storms.
            bad_token=True;await value.flush();before=len(calls)
            await value.flush();assert len(calls)==before
            clock[0]+=26;await value.flush();assert calls[-1][0]=='GET'
            bad_token=False;clock[0]+=301;await value.flush()
            assert 'rejected' not in json.loads((root/'status'/f'{room}.json').read_text())
            # Real 400 invalid active source, followed by current native change.
            value.update({'type':'active','activeFlags':[]},{'id':source['id'],'room':str(uuid4())})
            # desired() correctly suppresses another room's active state.
            await value.flush()
            assert store.room_detail(owner,room)['nativeState']['agents'][0]['status']['type']=='unavailable'
            value.status={'type':'idle','activeFlags':['waitingOnApproval']};await value.flush()
            assert json.loads((root/'status'/f'{room}.json').read_text())['rejected']['status']==400
            clock[0]+=301;before=len(calls);await value.flush();assert len(calls)==before
            value.update({'type':'systemError','activeFlags':[]},None);await value.flush()
            assert store.room_detail(owner,room)['nativeState']['agents'][0]['status']['type']=='systemError'
            # Scope mismatch is a failed reconciliation, never fresh Idle.
            bad_token=True;await value.flush();bad_token=False;bad_scope=True;clock[0]+=26
            before=len(calls);await value.flush();assert len(calls)==before+1 and calls[-1][0]=='GET'
            bad_scope=False
            grants['can_post']=False;store.membership(owner,room,agent,grants,revision);revision+=1
            value=observer();clock[0]+=301;before=len(calls);await value.flush()
            assert len(calls)==before+1 and calls[-1][0]=='GET'  # Restart still respects revocation.
            rejected=list((root/'status').glob('*-rejected-*.json'));assert len(rejected)>=4
            assert all(json.loads(p.read_text())['nativeWorkReplayed'] is False for p in rejected)
            with store.pool.connection() as c:
                counts={t:c.execute('SELECT count(*) n FROM '+t+' WHERE authority=%s',(authority,)).fetchone()['n'] for t in ('hb_delivery','hb_executor')}
            assert not any(counts.values())
            result={'realHttpPg':True,'httpCalls':len(calls),'rejectedReceipts':len(rejected),'counts':counts,
                    'cases':['403 grant repair while existing listener lives','409 canonical revision rebase',
                    '401 identity repair with bounded backoff','400 unchanged bad payload held',
                    'native unavailable for another room','current systemError preserved',
                    'wrong authority rejects recovery','restart retains actual revocation'],
                    'modelCalls':0,'nativeRpcCalls':0,'productionChanged':False}
            (root/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    finally:
        await server.close();store.close()


asyncio.run(main())
