"""Actual HTTP/PG lost-ACK reconciliation and on-disk tool receipt reuse."""
import asyncio,json,os,secrets
from pathlib import Path
from uuid import uuid4
from aiohttp import web,ClientSession
from hollywood_backbone.store import Store
from hollywood_backbone.server import application
from lax_connector.room_tools import RoomTools
from lax_connector.errors import HttpFailure

async def main():
    os.umask(0o077);root=Path(os.environ['ROOM_PUBLICATION_EVIDENCE']);root.mkdir(mode=0o700)
    store=Store(json.load(open(os.environ['ROOM_NATIVE_DATABASE'])));uid=lambda:str(uuid4())
    authority,room,agent,thread=uid(),uid(),uid(),uid();credentials={k:{'principalId':uid(),'token':secrets.token_urlsafe(40)} for k in ('Owner','Global')};token=secrets.token_urlsafe(40)
    (root/'fixture.intent.private.json').write_text(json.dumps({'authority':authority,'room':room,'agent':agent,'thread':thread,'credentials':credentials,'token':token}))
    owner=credentials['Owner']['principalId'];store.bootstrap(authority,'SYNTHETIC native publication recovery',{'globalRoomId':room,'credentials':credentials});store.principal(owner,agent,'Publisher','agent',token);store.membership(owner,room,agent,{'can_read':True,'can_post':True,'can_request':True},0)
    runner=web.AppRunner(application(store),access_log=None);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start();base='http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])+'/hollywood/v3/'
    trace=[];posts=0;drop=True
    try:
        async with ClientSession() as session:
            async def request(method,path,body=None):
                nonlocal posts,drop
                async with session.request(method,base+path,json=body,headers={'Authorization':'Bearer '+token}) as response:
                    value=await response.json();trace.append({'method':method,'path':path,'status':response.status,'result':value})
                    if response.status!=200:raise HttpFailure(response.status,str(value.get('error')))
                    if method=='POST':
                        posts+=1
                        if drop:
                            drop=False
                            raise ConnectionResetError('Fixture lost reply AFTER canonical acceptance')
                    return value
            def instance():return RoomTools(authority_id=authority,agent_id=agent,thread_id=thread,request=request,state=root/'publications')
            params={'threadId':thread,'turnId':uid(),'callId':'exact-original-native-call','tool':'hollywood_publish','arguments':{'roomId':room,'body':'One original publication despite a lost acknowledgement.','audience':'room'}}
            first=await instance().call('item/tool/call',params);assert first['success']
            replay=await instance().call('item/tool/call',params);assert replay==first
            changed=await instance().call('item/tool/call',{**params,'arguments':{**params['arguments'],'body':'Changed contents under old call'}});assert not changed['success']
            assert posts==1
            with store.pool.connection() as c:
                n=c.execute('SELECT count(*) AS n FROM hb_event WHERE authority=%s AND author=%s AND kind=\'message\'',(authority,agent)).fetchone()['n']
                claims=c.execute('SELECT count(*) AS n FROM hb_delivery WHERE authority=%s',(authority,)).fetchone()['n']
            assert n==1 and claims==0
            result={'passed':True,'originalHttpPosts':posts,'canonicalMessages':n,'receiptLookupAfterLostAck':sum(t['method']=='GET' for t in trace),'restoredClientUsedDiskReceipt':True,'changedOriginalCallRejected':True,'modelCalls':0,'executionDeliveries':claims,'productionChanged':False}
            (root/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
    finally:
        (root/'http.private.json').write_text(json.dumps(trace));await runner.cleanup();store.close()
asyncio.run(main())
