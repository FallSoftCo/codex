"""Exact original-source outcomes; all external/native effects are stubbed."""
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4
from lax_connector.conversation_io import ConversationIO
from lax_connector.room_native_state import RoomNativeState
from lax_connector.room_output import RoomOutput
from lax_connector.room_tools import RoomTools


class ReplyOutcomes(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.authority,self.agent,self.human,self.a,self.b=[str(uuid4()) for _ in range(5)]
        self.binding=dict(authority=self.authority,agent=self.agent,thread='same-native-thread')
        self.io=ConversationIO(self.root/'io.sqlite',**self.binding);self.addCleanup(lambda:self.io.close())
        self.posts=[]
        async def request(method,path,payload=None):
            if method=='GET':return {'authorityId':self.authority,'room':{'id':self.a}}
            self.posts.append((path,payload))
            return {'accepted':True,'deliveries':[],'event':{
                'authority':self.authority,'author':self.agent,'room':path.split('/')[1],
                'kind':'message','body':payload['body'],'audience':payload['audience'],
                'recipient':payload.get('recipientId'),'source':payload.get('sourceEventId'),
                'data':{'responsePhase':payload.get('responsePhase')}}}
        self.tools=RoomTools(authority_id=self.authority,agent_id=self.agent,thread_id='same-native-thread',
            request=request,state=self.root/'publications',conversation_io=self.io)
        self.output=RoomOutput(self.io,self.tools)

    def source(self, room=None, *, private=False, turn='mixed'):
        event={'id':str(uuid4()),'authority':self.authority,'room':room or self.a,'author':self.human,
            'audience':'direct' if private else 'room','recipient':self.agent if private else None,
            'kind':'message','body':'PRIVATE CANARY' if private else 'Synthetic public original',
            'data':{'authorKind':'human','conversationRecipients':[self.agent]}}
        self.io.stage(event)
        if turn:self.io.bind(event,{'turn':{'id':turn}})
        return event

    async def test_historical_completed_mixed_final_is_diagnosed_not_disposed_or_replayed(self):
        a=self.source();self.source(self.b,private=True)
        self.io.final('mixed','old-item','Retain this original ambiguous final')
        self.io.ended('mixed','completed')
        original=dict(self.io.db.execute('SELECT * FROM output').fetchone())
        self.io.close();self.io=ConversationIO(self.root/'io.sqlite',**self.binding)
        self.tools.conversation_io=self.io;self.output=RoomOutput(self.io,self.tools)
        self.assertFalse(await self.output.deliver(self.io.pending()[0]))
        row=dict(self.io.db.execute('SELECT * FROM output').fetchone())
        self.assertEqual(row,original)
        self.assertEqual(row['state'],'queued')
        self.assertTrue(self.io.reply_status(self.a)['outcomes'][0]['heldFinals'][0]['reason'])
        audit=dict(self.io.db.execute('SELECT * FROM reply_delivery_hold').fetchone())
        self.assertEqual(json.loads(audit['original_metadata'])['reason'],None)
        self.assertEqual(self.io.pending(),[]);self.assertEqual(self.posts,[])
        outcome=self.io.reply_status(self.a)['outcomes'][0]
        self.assertEqual((outcome['sourceEventId'],outcome['nativeEnd'],outcome['responseState'],outcome['taskCompletion']),
            (a['id'],'completed','native_ended_without_source_answer','not_inferred'))
        self.assertNotIn('PRIVATE CANARY',json.dumps(self.io.reply_status(self.a)))

    async def test_legacy_scope_reclassification_never_releases_a_historical_final(self):
        import sqlite3
        request=self.source()
        context=self.source(self.b,private=True)
        context['data']['authorKind']='agent'
        context['data']['responsePhase']='message'
        self.io.db.execute('UPDATE input_source SET canonical=? WHERE event=?',
                           (json.dumps(context,sort_keys=True),context['id']))
        self.io.final('mixed','legacy-item','Historical mixed-audience output')
        self.io.ended('mixed','completed')
        original=dict(self.io.db.execute('SELECT * FROM output').fetchone())
        self.io.db.commit();self.io.close()
        # Exact pre-classification source schema used by the retained Mac runtime.
        with sqlite3.connect(self.root/'io.sqlite') as old:
            old.execute('DROP INDEX input_reply_turn')
            old.execute('DROP INDEX input_source_unclassified')
            old.execute('ALTER TABLE input_source DROP COLUMN reply_eligible')
        self.io=ConversationIO(self.root/'io.sqlite',**self.binding)
        self.tools.conversation_io=self.io;self.output=RoomOutput(self.io,self.tools)
        self.assertEqual(self.io.source('mixed')['id'],request['id'])
        self.assertEqual(self.io.pending(),[])
        self.assertFalse(await self.output.deliver(original))
        self.assertEqual(dict(self.io.db.execute('SELECT * FROM output').fetchone()),original)
        self.assertEqual(self.posts,[])
        # The migration fence is per historical item, not a ban on new replies.
        self.source(turn='new')
        self.io.final('new','new-item','New source-bound answer')
        self.io.ended('new','completed')
        self.assertTrue(await self.output.deliver(self.io.pending()[0]))
        self.assertEqual(len(self.posts),1)
        self.io.close();self.io=ConversationIO(self.root/'io.sqlite',**self.binding)
        self.assertEqual(self.io.pending(),[])
        self.assertEqual(dict(self.io.db.execute("SELECT * FROM output WHERE item='legacy-item'").fetchone()),original)

    async def test_explicit_public_private_outcomes_and_blocked_are_not_task_completion(self):
        a=self.source();b=self.source(self.b,private=True)
        self.io.final('mixed','unscoped','Cannot route');self.io.ended('mixed','completed')
        await self.output.deliver(self.io.pending()[0])
        public={'body':'Public answer','audience':'room','sourceEventId':a['id'],'responsePhase':'answer'}
        private={'body':'PRIVATE CANARY','audience':'direct','recipientId':self.human,
                 'sourceEventId':b['id'],'responsePhase':'blocked'}
        await self.tools.publish(self.a,public,'a',turn='mixed')
        await self.tools.publish(self.a,public,'a',turn='mixed')
        await self.tools.publish(self.b,private,'b',turn='mixed')
        self.assertEqual(len(self.posts),2)
        self.assertEqual(self.io.reply_status(self.a)['outcomes'][0]['responseState'],'answer_available')
        self.assertEqual(self.io.reply_status(self.b)['outcomes'][0]['responseState'],'blocked_reported')
        self.assertEqual(self.io.db.execute('SELECT state FROM output').fetchone()[0],'queued')
        with self.assertRaises(ValueError):
            await self.tools.publish(self.a,{**private,'audience':'room','recipientId':None},'widen',turn='mixed')
        self.assertEqual(len(self.posts),2)

    async def test_missing_input_receipt_can_bind_late_without_new_native_input(self):
        a=self.source(turn=None)
        self.io.final('late','late-final','Original result');self.io.ended('late','completed')
        await self.output.deliver(self.io.pending()[0]);self.assertTrue(self.io.pending())
        self.io.bind(a,{'turn':{'id':'late'}})
        self.assertTrue(await self.output.deliver(self.io.pending()[0]))
        self.assertEqual(len(self.posts),1)
        self.assertEqual(self.io.reply_status(self.a)['outcomes'][0]['responseState'],'answer_available')

    async def test_diagnosed_history_does_not_starve_later_original_unique_final(self):
        self.source();self.source(self.b)
        for i in range(35):self.io.final('mixed','hold-'+str(i),'Original ambiguous body')
        self.io.ended('mixed','completed')
        for row in self.io.pending():await self.output.deliver(row)
        for row in self.io.pending():await self.output.deliver(row)
        self.source(turn='unique');self.io.final('unique','last','A real unique answer');self.io.ended('unique','completed')
        self.assertTrue(await self.output.deliver(self.io.pending()[0]));self.assertEqual(len(self.posts),1)

    async def test_unknown_and_rejected_publications_stay_distinct(self):
        a=self.source()
        self.io.publication('mixed',a['id'],'unknown',self.a,'attempting',phase='answer')
        self.assertEqual(self.io.reply_status(self.a)['outcomes'][0]['responseState'],'publication_unknown')
        self.io.publication('mixed',a['id'],'unknown',self.a,'rejected',phase='answer')
        self.assertEqual(self.io.reply_status(self.a)['outcomes'][0]['responseState'],'publication_rejected')
        self.io.publication('mixed',a['id'],'legacy',self.a,'accepted')
        self.assertEqual(self.io.reply_status(self.a)['outcomes'][0]['responseState'],'accepted_final_phase_unrecorded')
        with self.assertRaises(ValueError):self.io.publication('mixed',a['id'],'unknown',self.a,'accepted',phase='blocked')

    async def test_owner_native_view_is_not_room_work_or_private_source_disclosure(self):
        async def no_send(*args):raise AssertionError('No HTTP allowed')
        state=RoomNativeState(state=self.root/'native',thread='same-native-thread',agent=self.agent,rooms=[],send=no_send)
        source=self.source(self.b,private=True)
        state.update({'type':'active','activeFlags':[]},source)
        view=state.own_view(self.a)
        self.assertEqual(view['sharedThreadStatus']['type'],'active')
        self.assertEqual(view['roomAttribution'],'active_elsewhere_or_unattributed')
        self.assertEqual(view['legacyRoomStatus']['type'],'unavailable')
        self.assertNotIn(source['id'],json.dumps(view));self.assertNotIn(self.b,json.dumps(view))

    async def test_inspector_reads_original_private_binding_without_schema_write(self):
        from lax_connector.inspect_reply_state import inspect
        import hashlib
        self.source()
        config=self.root/'config.json'
        config.write_text(json.dumps({'state':str(self.root),'authorityId':self.authority,
            'agentId':self.agent,'nativeThreadId':'same-native-thread'}));config.chmod(0o600)
        self.io.close()
        before=hashlib.sha256((self.root/'io.sqlite').read_bytes()).hexdigest()
        # Use the conventional exact original filename; this is owned QA only.
        (self.root/'io.sqlite').rename(self.root/'conversation-io.sqlite')
        result=inspect(config,self.a)
        self.assertEqual(result['outcomes'][0]['responseState'],'awaiting_source_answer')
        self.assertEqual(hashlib.sha256((self.root/'conversation-io.sqlite').read_bytes()).hexdigest(),before)
        config.write_text(json.dumps({'state':str(self.root),'authorityId':self.authority,
            'agentId':str(uuid4()),'nativeThreadId':'same-native-thread'}))
        with self.assertRaises(ValueError):inspect(config,self.a)


if __name__=='__main__':unittest.main()
