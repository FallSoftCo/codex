"""Actual authenticated HTTP/PG/SSE receipts; native effects are explicitly fake."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
from types import SimpleNamespace
from uuid import uuid4
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer
from hollywood_backbone.store import Store
from hollywood_backbone.server import application
from lax_connector.conversation_io import ConversationIO
from lax_connector.conversational_agent import ConversationalAgent
from lax_connector.errors import HttpFailure
from lax_connector.room_output import RoomOutput
from lax_connector.room_runtime import RoomRuntime
from lax_connector.room_tools import RoomTools


async def main():
    os.umask(0o077)
    root=Path(os.environ['CANONICAL_REPLY_EVIDENCE']);root.mkdir(mode=0o700)
    uid=lambda:str(uuid4())
    authority,a,b,agent,peer=[uid() for _ in range(5)]
    credentials={k:{'principalId':uid(),'token':secrets.token_urlsafe(40)} for k in ('Owner','Global')}
    store=Store(json.loads(Path(os.environ['ROOM_NATIVE_DATABASE']).read_text()))
    store.migrate();store.bootstrap(authority,'Synthetic canonical receipt QA',{'globalRoomId':uid(),'credentials':credentials})
    owner=credentials['Owner']['principalId'];token=secrets.token_urlsafe(40);peer_token=secrets.token_urlsafe(40)
    store.principal(owner,agent,'Synthetic one-context agent','agent',token)
    store.principal(owner,peer,'Synthetic peer','agent',peer_token)
    for index,room in enumerate((a,b)):store.create_room(owner,room,'Synthetic receipt room '+str(index),'No production inputs',agent)
    store.membership(owner,a,peer,{'can_read':True,'can_post':True,'can_request':True},0)
    store.membership(owner,b,peer,{'can_read':True,'can_post':True,'can_request':True},0)
    public=store.post(owner,a,uid(),{'kind':'message','body':'Original public human request','audience':'room'})['event']
    private=store.post(owner,b,uid(),{'kind':'message','body':'PRIVATE_QA_CANARY','audience':'direct','recipientId':agent})['event']
    passive=store.post(peer,a,uid(),{'kind':'message','body':'Ordinary history-only peer context','audience':'room'})['event']
    server=TestServer(application(store),host='127.0.0.1');await server.start_server()
    binding=dict(authority=authority,agent=agent,thread='original-shared-fixture-thread')
    io=ConversationIO(root/'io.sqlite',**binding)
    calls=[];native=[];runtimes=[];tasks=[];received={}
    try:
        async with ClientSession() as session:
            async def send(method,path,payload=None):
                async with session.request(method,server.make_url('/hollywood/v3/'+path),json=payload,
                    headers={'Authorization':'Bearer '+token}) as response:
                    value=await response.json();status=response.status
                calls.append({'method':method,'path':path,'status':status})
                if status!=200:raise HttpFailure(status,str(value.get('error')))
                return value
            async def fake_native(method,params):
                native.append(method);return {'turn':{'id':'original-mixed-turn'}}
            async def before(e):io.stage(e)
            async def bound(e,r):io.bind(e,r)
            async def attention(e):pass
            shell=SimpleNamespace(conversation_io=io,output=SimpleNamespace(wake=asyncio.Event()),
                                  attention=SimpleNamespace(observe=attention))
            async def observed(e):
                await ConversationalAgent.observe_room_event(shell,e)
                if e['id'] in received:received[e['id']].set()
            # External legitimate HTTP path: no RoomTools/native-turn callback.
            io.publication('original-mixed-turn',public['id'],'original-unknown-command',a,'attempting',phase='answer')
            external=await send('POST','rooms/'+a+'/messages',{'operationId':uid(),'kind':'message','body':'External exact public answer',
                'audience':'room','sourceEventId':public['id'],'responsePhase':'answer'})
            received[external['event']['id']]=asyncio.Event()
            tools=RoomTools(authority_id=authority,agent_id=agent,thread_id=binding['thread'],request=send,
                            state=root/'publications',conversation_io=io)
            # Source is staged now solely for private-public tool scope checking.
            io.stage(private)
            local=await tools.publish(b,{'body':'PRIVATE_QA_CANARY','audience':'direct','recipientId':owner,
                'sourceEventId':private['id'],'responsePhase':'blocked'},'original-tool-key',turn='original-mixed-turn')
            try:
                await send('POST','rooms/'+b+'/messages',{'operationId':uid(),'kind':'message','body':'Must not broaden private input',
                    'audience':'room','sourceEventId':private['id'],'responsePhase':'answer'})
                raise AssertionError('Private-source public expansion was accepted')
            except HttpFailure as error:assert error.status==403
            async with session.get(server.make_url('/hollywood/v3/rooms/'+b+'/history?view=conversation&limit=100'),
                    headers={'Authorization':'Bearer '+peer_token}) as response:
                assert response.status==200
                peer_history=await response.json()
            assert 'PRIVATE_QA_CANARY' not in json.dumps(peer_history)
            received[local['event']['id']]=asyncio.Event()
            for source in (public,private):
                runtime=RoomRuntime(rpc=SimpleNamespace(call=fake_native),session=session,
                    base_url=str(server.make_url('/hollywood/v3/')),token=token,authority_id=authority,agent_id=agent,
                    room_id=source['room'],thread_id=binding['thread'],state=root/('receive-'+source['room']),
                    initial_cursor=source['seq']-1,on_room_event=observed,before_native_input=before,on_native_receipt=bound)
                runtimes.append(runtime);tasks.append(asyncio.create_task(runtime.run()))
            await asyncio.wait_for(asyncio.gather(*(e.wait() for e in received.values())),10)
            # Self-authored canonical events deliberately exclude self from native recipients.
            assert agent not in external['event']['data']['conversationRecipients']
            assert native.count('turn/start')==2 and native.count('thread/inject_items')==1,native
            assert io.db.execute('SELECT count(*) FROM input_source').fetchone()[0]==2
            io.final('original-mixed-turn','retained-unscoped-final','Do not route this generic final')
            io.ended('original-mixed-turn','completed')
            output=RoomOutput(io,tools);assert not await output.deliver(io.pending()[0])
            states={room:io.reply_status(room)['outcomes'][0] for room in (a,b)}
            assert states[a]['responseState']=='answer_available'
            assert states[b]['responseState']=='blocked_reported'
            assert states[a]['publications'][0]['state']=='attempting'
            assert len(states[b]['canonicalReplies'])==1 and len(states[b]['canonicalReplies'][0]['localPublications'])==1
            assert 'PRIVATE_QA_CANARY' not in json.dumps(io.reply_status(a))
            # Actual publication retry + canonical duplicate are both original-receipt-only.
            await tools.publish(b,{'body':'PRIVATE_QA_CANARY','audience':'direct','recipientId':owner,
                'sourceEventId':private['id'],'responsePhase':'blocked'},'original-tool-key',turn='original-mixed-turn')
            for runtime,event in ((runtimes[0],external['event']),(runtimes[1],local['event'])):
                await runtime.consume(event)
                assert runtime.journal.db.execute('SELECT count(*) FROM room_input WHERE event=?',(event['id'],)).fetchone()[0]==0
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True);tasks=[]
            for runtime in runtimes:runtime.close()
            runtimes=[]
            before_unknown=dict(io.db.execute("SELECT * FROM publication WHERE key='original-unknown-command'").fetchone())
            io.close();io=ConversationIO(root/'io.sqlite',**binding);shell.conversation_io=io
            # Same authenticated original events after reopen: no new native/tool/HTTP call.
            for event in (external['event'],local['event'],external['event']):await observed(event)
            assert dict(io.db.execute("SELECT * FROM publication WHERE key='original-unknown-command'").fetchone())==before_unknown
            assert io.db.execute('SELECT count(*) FROM canonical_reply').fetchone()[0]==2
            assert io.db.execute('SELECT state FROM output').fetchone()[0]=='queued'
            assert sum(x['method']=='POST' and x['status']==200 for x in calls)==2
            with store.pool.connection() as c:
                answer_count=c.execute("SELECT count(*) AS n FROM hb_event WHERE authority=%s AND author=%s AND kind='message'",(authority,agent)).fetchone()['n']
            assert answer_count==2
            result={'passed':True,'realAuthenticatedHttpPgSse':True,'nativeEffects':'stubbed, original two human inputs once plus one history-only peer',
                'fakeNativeMethods':native,'ownReplyNativeInputs':0,'canonicalFinals':2,'httpAnswerPosts':answer_count,
                'unknownOriginalUnchanged':True,'mixedOriginalFinalRetainedQueued':True,'toolCanonicalDedup':True,
                'publicState':io.reply_status(a),'privateState':io.reply_status(b),'calls':calls,
                'taskCompletion':'not_inferred'}
            (root/'result.json').write_text(json.dumps(result,indent=2)+'\n')
            print(json.dumps({k:v for k,v in result.items() if k not in ('publicState','privateState','calls')}))
    finally:
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        for runtime in runtimes:runtime.close()
        io.close();await server.close();store.close()


if __name__=='__main__':asyncio.run(main())
