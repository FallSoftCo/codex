"""Real PG/HTTP room output, exact receive ACK, private audience and no replay."""
import asyncio,json,os,secrets
from pathlib import Path
from uuid import uuid4
from aiohttp import web,ClientSession
from hollywood_backbone.store import Store
from hollywood_backbone.server import application
from lax_connector.conversation_io import ConversationIO
from lax_connector.room_runtime import RoomRuntime
from lax_connector.room_tools import RoomTools
from lax_connector.room_output import RoomOutput

async def main():
    os.umask(0o077)
    root=Path(os.environ['ROOM_OUTPUT_EVIDENCE']);root.mkdir(mode=0o700)
    uid=lambda:str(uuid4())
    authority,room,agent=uid(),uid(),uid()
    credentials={k:{'principalId':uid(),'token':secrets.token_urlsafe(40)} for k in ('Owner','Global')}
    token=secrets.token_urlsafe(40)
    store=Store(json.load(open(os.environ['ROOM_NATIVE_DATABASE'])))
    store.bootstrap(authority,'Synthetic final output QA',{'globalRoomId':uid(),'credentials':credentials})
    owner=credentials['Owner']['principalId']
    store.principal(owner,agent,'Synthetic native adapter','agent',token)
    store.create_room(owner,room,'Final output QA','No model or production messages',agent)
    runner=web.AppRunner(application(store),access_log=None);await runner.setup()
    site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
    base='http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])+'/hollywood/v3/'
    trace=[];native=[]
    try:
        async with ClientSession() as session:
            async def request(method,path,payload=None):
                async with session.request(method,base+path,json=payload,headers={'Authorization':'Bearer '+token}) as response:
                    value=await response.json();assert response.status==200,value
                trace.append({'method':method,'path':path})
                if method=='POST':raise ConnectionError('deliberate lost HTTP reply AFTER server acceptance')
                return value
            io=ConversationIO(root/'io.sqlite',authority=authority,agent=agent,thread='synthetic-native-thread')
            class Native:
                async def call(self,method,payload):
                    native.append(method)
                    return {'turn':{'id':'exact-native-turn'}}
            async def before(event):io.stage(event)
            async def receipt(event,reply):io.bind(event,reply)
            with store.pool.connection() as c:head=c.execute('SELECT next_seq FROM hb_authority WHERE id=%s',(authority,)).fetchone()['next_seq']
            runtime=RoomRuntime(rpc=Native(),session=session,base_url=base,token=token,authority_id=authority,
                agent_id=agent,room_id=room,thread_id='synthetic-native-thread',state=root/'receive',initial_cursor=head,
                before_native_input=before,on_native_receipt=receipt)
            original=store.post(owner,room,'synthetic-private-original',{'kind':'message','body':'Synthetic private question','audience':'direct','recipientId':agent})
            await runtime.consume(original['event'])
            # Same canonical event cannot resubmit a native turn.
            await runtime.consume(original['event'])
            assert native==['turn/start'],native
            io.final('exact-native-turn','native-final-item','Risposta privata conservata.')
            io.ended('exact-native-turn','completed');io.close()
            io=ConversationIO(root/'io.sqlite',authority=authority,agent=agent,thread='synthetic-native-thread')
            tools=RoomTools(authority_id=authority,agent_id=agent,thread_id='synthetic-native-thread',request=request,
                state=root/'publications',conversation_io=io)
            output=RoomOutput(io,tools);await output.deliver(io.pending()[0])
            assert io.pending()==[]
            async with session.get(base+'rooms/'+room+'/history',params={'before':9007199254740991,'limit':100,'view':'conversation'},headers={'Authorization':'Bearer '+credentials['Owner']['token']}) as response:
                history=await response.json();assert response.status==200,history
            events=history.get('events',history.get('items',[]))
            answers=[e for e in events if e.get('author')==agent]
            assert len(answers)==1,history
            answer=answers[0]
            assert answer['source']==original['event']['id'] and answer['audience']=='direct' and answer['recipient']==owner
            assert sum(x['method']=='POST' for x in trace)==1
            assert any(x['path'].startswith('commands/') for x in trace)
            io.close();runtime.close()
            # Production reproduction: an explicit peer request followed by a
            # same-turn passive review used to select the review and suppress
            # the already-completed answer. Restore only that original final.
            peer,peer_token=uid(),secrets.token_urlsafe(40)
            store.principal(owner,peer,'Synthetic passive reviewer','agent',peer_token)
            with store.pool.connection() as c:
                c.execute('INSERT INTO hb_membership(authority,room,principal,can_read,can_post,can_request) VALUES(%s,%s,%s,true,true,true)',(authority,room,peer))
            owed=store.post(peer,room,'synthetic-explicit-peer-original',{'kind':'request','body':'Synthetic peer work request','audience':'room','recipientId':agent,'expectsReply':True})['event']
            passive=store.post(peer,room,'synthetic-passive-review',{'kind':'message','body':'Synthetic passive review','audience':'room','recipientId':agent,'expectsReply':False})['event']
            io=ConversationIO(root/'io.sqlite',authority=authority,agent=agent,thread='synthetic-native-thread')
            for e in (owed,passive):io.stage(e);io.bind(e,{'turn':{'id':'completed-peer-turn'}})
            io.final('completed-peer-turn','original-peer-final-item','Original peer result retained.')
            io.ended('completed-peer-turn','completed')
            io.finish('original-peer-final-item','suppressed','Peer publication remains explicit')
            io.close();io=ConversationIO(root/'io.sqlite',authority=authority,agent=agent,thread='synthetic-native-thread')
            assert io.pending()==[], 'Startup cannot sweep historical suppressed results'
            recovery=io.recover_passive_suppression('original-peer-final-item',owed['id'])
            assert recovery['state']=='queued' and not recovery['reconciled']
            tools=RoomTools(authority_id=authority,agent_id=agent,thread_id='synthetic-native-thread',request=request,
                state=root/'publications',conversation_io=io)
            await RoomOutput(io,tools).deliver(io.pending()[0]);assert io.pending()==[]
            assert io.recover_passive_suppression('original-peer-final-item',owed['id'])['state']=='accepted'
            io.close();io=ConversationIO(root/'io.sqlite',authority=authority,agent=agent,thread='synthetic-native-thread')
            assert io.pending()==[]
            async with session.get(base+'rooms/'+room+'/history',params={'before':9007199254740991,'limit':100,'view':'conversation'},headers={'Authorization':'Bearer '+credentials['Owner']['token']}) as response:
                recovered_history=await response.json();assert response.status==200,recovered_history
            recovered=[e for e in recovered_history['events'] if e.get('author')==agent and e.get('source')==owed['id']]
            assert len(recovered)==1 and recovered[0]['body']=='Original peer result retained.'
            assert recovered[0]['audience']=='room' and recovered[0]['data']['responsePhase']=='answer'
            assert sum(x['method']=='POST' for x in trace)==2
            assert native==['turn/start'], 'Final recovery must not rerun work'
            io.close()
            (root/'result.json').write_text(json.dumps({'passed':True,'authority':authority,'originalEvent':original['event']['id'],
                'answerEvent':answer['id'],'nativeSubmissions':len(native),'postAttempts':2,'lostAckReconciled':True,'passiveReviewPreservesOriginalReply':True,'knownSuppressedFinalRecoveredOnce':True,'recoveredAnswerEvent':recovered[0]['id'],'recoveryReranNativeInput':False,'startupDoesNotReplayHistory':True,
                'durableReopen':True,'privateAudiencePreserved':True,'modelCalls':0,'productionMessages':0},indent=2))
            print((root/'result.json').read_text())
    finally:
        await runner.cleanup()
        store.pool.close()

asyncio.run(main())
