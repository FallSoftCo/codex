"""Focused real HTTP/PostgreSQL scope/status journey; no native or model calls."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
from uuid import uuid4
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer
from hollywood_backbone.store import Store
from hollywood_backbone.server import application
from lax_connector.conversation_io import ConversationIO
from lax_connector.errors import HttpFailure
from lax_connector.room_native_state import RoomNativeState
from lax_connector.room_output import RoomOutput
from lax_connector.room_tools import RoomTools
from lax_connector.room_subscriptions import RoomSubscriptions


async def main():
    os.umask(0o077)
    root=Path(os.environ['ROOM_REPLY_EVIDENCE']);root.mkdir(mode=0o700)
    uid=lambda:str(uuid4())
    authority,a,b,agent,viewer=[uid() for _ in range(5)]
    credentials={k:{'principalId':uid(),'token':secrets.token_urlsafe(40)} for k in ('Owner','Global')}
    store=Store(json.loads(Path(os.environ['ROOM_NATIVE_DATABASE']).read_text()))
    store.migrate();store.bootstrap(authority,'Synthetic mixed-room outcome fixture',{'globalRoomId':uid(),'credentials':credentials})
    owner=credentials['Owner']['principalId'];token=secrets.token_urlsafe(40);viewer_token=secrets.token_urlsafe(40)
    store.principal(owner,agent,'Synthetic single native owner','agent',token)
    store.principal(owner,viewer,'Synthetic public-room viewer','agent',viewer_token)
    for i,room in enumerate((a,b)):store.create_room(owner,room,'Synthetic room '+str(i),'No production data',agent)
    store.membership(owner,a,viewer,{'can_read':True,'can_post':True,'can_request':True},0)
    public=store.post(owner,a,'original-public',{'kind':'message','body':'Synthetic public request','audience':'room'})['event']
    private=store.post(owner,b,'original-private',{'kind':'message','body':'PRIVATE_B_CANARY','audience':'direct','recipientId':agent})['event']
    server=TestServer(application(store),host='127.0.0.1');await server.start_server()
    io=ConversationIO(root/'io.sqlite',authority=authority,agent=agent,thread='same-shared-native-thread')
    calls=[]
    try:
        async with ClientSession() as session:
            async def send(method,path,payload=None,*,as_viewer=False,expected=200):
                async with session.request(method,server.make_url('/hollywood/v3/'+path),json=payload,
                    headers={'Authorization':'Bearer '+(viewer_token if as_viewer else token)}) as response:
                    value=await response.json();status=response.status
                calls.append({'method':method,'path':path,'status':status})
                if expected!=200:assert status==expected,(status,value);return value
                if status!=200:raise HttpFailure(status,str(value.get('error')))
                return value
            for event in (public,private):
                io.stage(event);io.bind(event,{'turn':{'id':'recorded-shape-completed-mixed-turn'}})
                io.stage(event)  # no duplicate original source
            io.final('recorded-shape-completed-mixed-turn','original-final','Unscoped private/public text must remain retained')
            io.ended('recorded-shape-completed-mixed-turn','completed')
            tools=RoomTools(authority_id=authority,agent_id=agent,thread_id='same-shared-native-thread',request=send,
                state=root/'publications',conversation_io=io)
            output=RoomOutput(io,tools)
            before=len(calls);assert not await output.deliver(io.pending()[0]);assert len(calls)==before
            assert io.db.execute('SELECT state FROM output').fetchone()[0]=='queued'
            assert io.reply_status(a)['outcomes'][0]['responseState']=='native_ended_without_source_answer'
            for event,phase in ((public,'answer'),(private,'blocked')):
                args={'body':'Public answer' if event==public else 'PRIVATE_B_CANARY',
                    'sourceEventId':event['id'],'audience':event['audience'],'responsePhase':phase}
                if event==private:args['recipientId']=owner
                await tools.publish(event['room'],args,'source-'+event['id'],turn='recorded-shape-completed-mixed-turn')
                await tools.publish(event['room'],args,'source-'+event['id'],turn='recorded-shape-completed-mixed-turn')
            assert sum(x['method']=='POST' and x['path'].endswith('/messages') for x in calls)==2
            assert io.reply_status(a)['outcomes'][0]['responseState']=='answer_available'
            assert io.reply_status(b)['outcomes'][0]['responseState']=='blocked_reported'
            with store.pool.connection() as c:
                answers=c.execute("SELECT room,audience,recipient,body FROM hb_event WHERE authority=%s AND author=%s AND kind='message'",(authority,agent)).fetchall()
            assert len(answers)==2
            assert all(r['body']!='PRIVATE_B_CANARY' for r in answers if str(r['room'])==a)
            observer=RoomNativeState(state=root/'observations',thread='same-shared-native-thread',agent=agent,
                authority=authority,rooms=[{'roomId':a,'membershipRevision':1}],send=send)
            observer.update({'type':'active','activeFlags':['waitingOnApproval']},private)
            assert observer.desired(a)['status']['type']=='unavailable' # old API fallback
            detail=await send('GET','rooms/'+a)
            assert detail['nativeState']['capabilities']=={'sharedThreadStatus':1}
            subscriptions=RoomSubscriptions(state=root/'subscriptions',authority=authority,agent=agent,
                thread='same-shared-native-thread',rooms=[{'roomId':a,'after':0}],request=send,
                create=lambda *args:None,on_rooms=observer.set_rooms)
            starts=[];subscriptions.start_room=starts.append # receive side is unchanged; no native input here
            await subscriptions.refresh()
            assert any(r['roomId']==a and r['sharedThreadStatus'] is True for r in observer.rooms)
            await observer.flush()
            visible=await send('GET','rooms/'+a,as_viewer=True)
            status=visible['nativeState']['agents'][0]['status']
            assert status=={'type':'activeElsewhere','activeFlags':[]},status
            assert private['id'] not in json.dumps(visible) and 'PRIVATE_B_CANARY' not in json.dumps(visible)
            restarted=RoomSubscriptions(state=root/'subscriptions',authority=authority,agent=agent,
                thread='same-shared-native-thread',rooms=[],request=send,create=lambda *args:None,on_rooms=lambda rooms:None)
            assert all(not v.get('sharedThreadStatus') for v in restarted.known.values())
            invalid={'observationType':'nativeState','nativeThread':'invalid-fixture-thread','revision':1,
                'sourceEventId':public['id'],'status':{'type':'activeElsewhere','activeFlags':[]}}
            await send('POST','rooms/'+a+'/activity',invalid,expected=400)
            invalid['sourceEventId']=None;invalid['status']['activeFlags']=['waitingOnApproval']
            await send('POST','rooms/'+a+'/activity',invalid,expected=400)
            # Existing TTL remains authoritative; shared busy must expire too.
            with store.pool.connection() as c:c.execute("UPDATE hb_conversation_state SET observed_at=statement_timestamp()-interval '76 seconds' WHERE authority=%s",(authority,))
            expired=await send('GET','rooms/'+a,as_viewer=True)
            assert expired['nativeState']['agents'][0]['status']['type']=='unavailable'
            store.membership(owner,a,agent,{'can_read':True,'can_post':False,'can_request':True},1)
            await observer.flush()
            original_rejection=json.loads((root/'observations'/(a+'.json')).read_text())
            assert original_rejection['rejected']['status']==403
            assert io.db.execute('SELECT count(*) FROM input_source').fetchone()[0]==2
            result={'passed':True,'realHttpPg':True,'nativeEndEvidence':'synthetic reproduction of retained completed mixed-turn shape',
                'nativeRpcCalls':0,'modelCalls':0,'originalSources':2,'originalAnswerPosts':2,'unscopedFinalStillQueued':True,
                'activeElsewhereHasNoSourceOrPrivateFlags':True,'expiryAndRevocationPreserved':True,
                'calls':calls,'publicReplyState':io.reply_status(a),'privateReplyState':io.reply_status(b)}
            (root/'result.json').write_text(json.dumps(result,indent=2)+'\n')
            print(json.dumps({k:v for k,v in result.items() if k not in ('calls','publicReplyState','privateReplyState')}))
    finally:
        io.close();await server.close();store.close()


if __name__=='__main__':asyncio.run(main())
