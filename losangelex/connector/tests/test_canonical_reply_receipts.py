"""Canonical provenance/accounting, not model semantics or native exactly-once."""
import asyncio
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from uuid import uuid4
from lax_connector.conversation_io import ConversationIO
from lax_connector.conversational_agent import ConversationalAgent
from lax_connector.room_output import RoomOutput
from lax_connector.room_runtime import RoomRuntime
from lax_connector.room_tools import RoomTools


class CanonicalReplies(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.authority, self.agent, self.human, self.peer, self.a, self.b = [str(uuid4()) for _ in range(6)]
        self.binding = dict(authority=self.authority, agent=self.agent, thread='original-shared-thread')
        self.io = ConversationIO(self.root/'io.sqlite', **self.binding)
        self.addCleanup(lambda: self.io.close())
        self.posts = []

    def source(self, *, private=False, stage=True, turn='original-turn'):
        e = dict(id=str(uuid4()), authority=self.authority, author=self.human, room=self.b if private else self.a,
                 kind='message', seq=1, audience='direct' if private else 'room', recipient=self.agent if private else None,
                 body='PRIVATE_CANARY' if private else 'Original human request',
                 data={'authorKind':'human', 'conversationVersion':1, 'conversationRecipients':[self.agent]})
        if stage:
            self.io.stage(e)
            if turn: self.io.bind(e, {'turn':{'id':turn}})
        return e

    def reply(self, source, **changes):
        e = dict(id=str(uuid4()), authority=self.authority, author=self.agent, room=source['room'],
                 source=source['id'], kind='message', seq=2, audience=source['audience'],
                 recipient=self.human if source['audience']=='direct' else None, body='Original exact answer',
                 data={'authorKind':'agent', 'responsePhase':'answer', 'conversationRecipients':[]})
        e.update(changes)
        return e

    def state(self, source):
        return next(r for r in self.io.reply_status(source['room'])['outcomes'] if r['sourceEventId']==source['id'])

    def tools(self):
        async def send(method, path, payload=None):
            self.assertEqual(method, 'POST')
            source = self.io.input_event(payload['sourceEventId'])
            e = self.reply(source, body=payload['body'], audience=payload['audience'],
                           recipient=payload.get('recipientId'))
            e['data']['responsePhase'] = payload['responsePhase']
            self.posts.append(e)
            return {'accepted':True, 'event':e, 'deliveries':[]}
        return RoomTools(authority_id=self.authority, agent_id=self.agent, thread_id=self.binding['thread'],
                         request=send, state=self.root/'publications', conversation_io=self.io)

    async def test_existing_stream_observes_own_reply_without_native_submission_across_cursor_lag_restart(self):
        source = self.source(stage=False)
        calls = []
        async def rpc(method, params):
            calls.append(method); return {'turn':{'id':'original-turn'}}
        async def before(e): self.io.stage(e)
        async def bound(e, reply): self.io.bind(e, reply)
        async def attention(e): pass
        agent = SimpleNamespace(conversation_io=self.io, output=SimpleNamespace(wake=asyncio.Event()),
                                attention=SimpleNamespace(observe=attention))
        async def observed(e): await ConversationalAgent.observe_room_event(agent, e)
        args = dict(rpc=SimpleNamespace(call=rpc), session=None, base_url='http://unused.invalid', token='fixture',
                    authority_id=self.authority, agent_id=self.agent, room_id=self.a, thread_id=self.binding['thread'],
                    state=self.root/'receive', initial_cursor=0, on_room_event=observed,
                    before_native_input=before, on_native_receipt=bound)
        runtime = RoomRuntime(**args)
        await runtime.consume(source); await runtime.consume(source)
        own = self.reply(source)
        await runtime.consume(own)
        self.assertEqual(calls, ['turn/start'])
        self.assertTrue(agent.output.wake.is_set())
        runtime.close(); self.io.close()
        self.io = ConversationIO(self.root/'io.sqlite', **self.binding); agent.conversation_io=self.io
        # A retained old cursor emulates crash after receipt commit, before cursor replace.
        cursor=self.root/'receive/cursor.json'; value=json.loads(cursor.read_text()); value['cursor']=1
        cursor.write_text(json.dumps(value))
        runtime=RoomRuntime(**args)
        await runtime.consume(own); await runtime.consume(own)
        # Even malformed recipients cannot turn a self-authored event into native input.
        await runtime.consume(self.reply(source, seq=3, data={**own['data'], 'conversationRecipients':[self.agent]}))
        runtime.close()
        self.assertEqual(calls, ['turn/start'])
        self.assertEqual(self.io.db.execute('SELECT count(*) FROM input_source').fetchone()[0], 1)
        self.assertEqual(len(self.state(source)['canonicalReplies']), 2)

    async def test_tool_without_turn_then_tool_and_feed_deduplicate_exact_event(self):
        source=self.source(); tools=self.tools()
        args=dict(body='Source-specific answer', audience='room', sourceEventId=source['id'], responsePhase='answer')
        result=await tools.publish(self.a,args,'original-key')  # no turn metadata
        self.assertEqual(self.state(source)['responseState'],'answer_available')
        await tools.publish(self.a,args,'original-key',turn='original-turn')
        self.io.observe_own_reply(result['event'])
        state=self.state(source)
        self.assertEqual(len(self.posts),1); self.assertEqual(len(state['canonicalReplies']),1)
        self.assertEqual(state['canonicalReplies'][0]['localPublications'],[{'turn':'original-turn','key':'original-key'}])
        self.assertEqual(state['taskCompletion'],'not_inferred')
        self.io.final('original-turn','later-final','No duplicate recap'); self.io.ended('original-turn','completed')
        await RoomOutput(self.io,tools).deliver(self.io.pending()[0])
        self.assertEqual(len(self.posts),1)

    async def test_exact_private_counterpart_room_and_phase_are_required(self):
        public=self.source(); private=self.source(private=True)
        wrong=[self.reply(private,audience='room',recipient=None), self.reply(private,recipient=self.peer),
               self.reply(private,room=self.a), self.reply(public,audience='direct',recipient=self.peer)]
        for e in wrong:self.io.observe_own_reply(e)
        update=self.reply(public); update['data']['responsePhase']='update'
        self.assertFalse(self.io.observe_own_reply(update))
        self.assertEqual(self.state(public)['responseState'],'awaiting_source_answer')
        self.assertEqual(self.state(private)['responseState'],'awaiting_source_answer')
        correct=self.reply(private); correct['data']['responsePhase']='blocked'; self.io.observe_own_reply(correct)
        self.assertEqual(self.state(private)['responseState'],'blocked_reported')
        self.assertEqual(self.state(public)['canonicalReplies'],[])
        self.assertNotIn('PRIVATE_CANARY',json.dumps(self.io.reply_status(self.a)))
        for field, value in [('body','changed'),('author',self.peer),('source',public['id']),('audience','room')]:
            changed=copy.deepcopy(correct);changed[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):self.io.observe_own_reply(changed)

    async def test_canonical_acceptance_does_not_clear_unknown_command_or_repost(self):
        source=self.source(); self.io.publication('original-turn',source['id'],'lost-ack',self.a,'attempting',phase='answer')
        original=dict(self.io.db.execute('SELECT * FROM publication').fetchone())
        self.io.observe_own_reply(self.reply(source))
        self.assertEqual(self.state(source)['responseState'],'answer_available')
        self.assertEqual(self.state(source)['publications'][0]['state'],'attempting')
        self.io.final('original-turn','final','Do not guess command success'); self.io.ended('original-turn','completed')
        await RoomOutput(self.io,self.tools()).deliver(self.io.pending()[0])
        self.assertEqual(self.posts,[])
        self.assertEqual(dict(self.io.db.execute('SELECT * FROM publication').fetchone()),original)

    async def test_local_private_handoff_to_another_peer_does_not_answer_public_human(self):
        source=self.source();tools=self.tools()
        await tools.publish(self.a,dict(body='A separate private peer handoff',audience='direct',recipientId=self.peer,
            sourceEventId=source['id'],responsePhase='answer'),'peer-handoff',turn='original-turn')
        self.assertEqual(self.state(source)['responseState'],'awaiting_source_answer')
        self.io.final('original-turn','human-final','The actual human answer');self.io.ended('original-turn','completed')
        await RoomOutput(self.io,tools).deliver(self.io.pending()[0])
        self.assertEqual(len(self.posts),2)
        self.assertEqual(self.posts[-1]['audience'],'room')

    async def test_reply_before_input_keeps_original_late_binding_without_inventing_turn(self):
        source=self.source(stage=False); self.io.observe_own_reply(self.reply(source))
        self.assertEqual(self.io.db.execute('SELECT count(*) FROM input_source').fetchone()[0],0)
        self.io.stage(source)
        self.assertEqual(self.state(source)['nativeTurn'],None)
        self.assertEqual(self.state(source)['responseState'],'answer_available')
        self.io.bind(source,{'turn':{'id':'original-turn'}})
        self.assertEqual(self.state(source)['nativeTurn'],'original-turn')

    async def test_original_automatic_final_acceptance_is_not_reclassified_as_explicit_reply(self):
        source=self.source(); tools=self.tools(); output=RoomOutput(self.io,tools)
        self.io.final('original-turn','original-final','Native original final');self.io.ended('original-turn','completed')
        row=self.io.pending()[0]
        await output.deliver(row)
        # Re-enter same original output after an output-ack crash: tool accepted ledger wins without POST.
        await output.deliver(row)
        self.assertEqual(len(self.posts),1)
        self.assertEqual(self.io.db.execute('SELECT state FROM output').fetchone()[0],'accepted')

    async def test_old_read_only_projection_does_not_require_or_create_new_schema(self):
        import hashlib
        import sqlite3
        from lax_connector.room_reply_state import report
        source=self.source()
        self.io.publication('original-turn',source['id'],'legacy',self.a,'accepted',phase='answer')
        with self.io.db:
            self.io.db.execute('DROP TABLE canonical_reply');self.io.db.execute('DROP TABLE reply_publication_event')
        self.io.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        path=self.root/'io.sqlite';before=hashlib.sha256(path.read_bytes()).hexdigest()
        db=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
        try:
            state=report(SimpleNamespace(db=db,binding=self.binding),self.a)['outcomes'][0]
            self.assertEqual(state['responseState'],'answer_available');self.assertEqual(state['canonicalReplies'],[])
        finally:db.close()
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)


if __name__=='__main__':unittest.main()
