"""Real private SQLite + actual consume, frozen old renderer; no native/model."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock
from uuid import UUID

from legacy_room_input_fixture import human_input as legacy_human_input
from lax_connector.room_input import human_input
from lax_connector.room_input import peer_context, peer_request
from lax_connector.room_receive import ReceiveConflict, NativeReceiptUnresolved
from lax_connector.room_runtime import RoomRuntime


def uid(n):
    return str(UUID(int=n))


class UpgradeIdentity(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.authority, self.agent, self.room = uid(1), uid(2), uid(3)
        self.event = {'id': uid(4), 'authority': self.authority, 'room': self.room,
            'seq': 7, 'author': uid(5), 'recipient': None, 'source': uid(6),
            'kind': 'request', 'audience': 'room', 'body': 'Original immutable human content',
            'data': {'authorKind': 'human', 'conversationVersion': 1,
                     'conversationRecipients': [self.agent]}}
        self.rpc = AsyncMock()
        self.ack = {'turn': {'id': 'same-original-turn'}}
        self.rpc.call.return_value = self.ack
        self.before = AsyncMock()
        self.receipt = AsyncMock()
        self.runtime = RoomRuntime(rpc=self.rpc, session=None, base_url='https://fixture.invalid/',
            token='not-a-credential', authority_id=self.authority, agent_id=self.agent,
            room_id=self.room, thread_id='same-original-thread', state=Path(self.tmp.name),
            initial_cursor=0, before_native_input=self.before, on_native_receipt=self.receipt)
        self.addCleanup(self.runtime.close)
        self.args = dict(authority=self.authority, agent=self.agent, event=self.event['id'],
                         thread='same-original-thread', seq=7)
        self.render_args = dict(authority_id=self.authority, agent_id=self.agent,
                                thread_id='same-original-thread')
        self.original = {'method': 'turn/start', 'params': legacy_human_input(self.event, **self.render_args)}
        self.assertNotEqual(self.original['params'], human_input(self.event, **self.render_args))

    def seed(self, state='received', canonical=False):
        journal = self.runtime.journal
        journal.stage(**self.args, payload=self.original, **({'canonical': self.event} if canonical else {}))
        if state != 'received':
            self.assertTrue(journal.begin_handoff(self.authority, self.agent, self.event['id']))
        if state == 'acknowledged':
            journal.acknowledge(self.authority, self.agent, self.event['id'], self.ack)
        return journal.read(self.authority, self.agent, self.event['id'])

    def row(self):
        return self.runtime.journal.read(self.authority, self.agent, self.event['id'])

    async def test_legacy_ack_and_lagging_cursor_reuse_exact_original_without_native_call(self):
        original = self.seed('acknowledged')
        await self.runtime.consume(copy.deepcopy(self.event))
        self.assertEqual(self.row(), original)
        self.assertEqual(self.runtime.cursor, 7)
        self.rpc.call.assert_not_called()
        self.before.assert_not_called()
        self.receipt.assert_awaited_once_with(self.event, self.ack)
        identity = self.runtime.journal.db.execute('select * from room_input_identity').fetchone()
        self.assertEqual(identity['basis'], 'legacy-rendered-content-v1')
        self.assertEqual(json.loads(identity['canonical']), self.event)

    async def test_unhanded_legacy_stage_submits_exact_old_payload_once_not_current_guidance(self):
        original = self.seed()
        await self.runtime.consume(self.event)
        self.rpc.call.assert_awaited_once_with('turn/start', self.original['params'])
        self.assertEqual(self.row()['payload'], original['payload'])
        self.assertEqual(self.row()['digest'], original['digest'])
        self.assertEqual(self.row()['state'], 'acknowledged')
        await self.runtime.consume(self.event)
        self.assertEqual(self.rpc.call.await_count, 1)

    async def test_lost_ack_handoff_stays_reconciliation_only_and_preserves_cursor(self):
        original = self.seed('handoff')
        with self.assertRaises(NativeReceiptUnresolved):
            await self.runtime.consume(self.event)
        self.assertEqual(self.row(), original)
        self.assertEqual(self.runtime.cursor, 0)
        self.rpc.call.assert_not_called()
        self.before.assert_not_called()
        self.receipt.assert_not_called()

    async def test_legacy_changed_body_author_source_audience_still_conflict(self):
        original = self.seed('acknowledged')
        for field, value in [('body', 'Changed text'), ('author', uid(91)), ('source', uid(92)),
                             ('audience', 'direct')]:
            changed = copy.deepcopy(self.event)
            changed[field] = value
            if field == 'audience':
                changed['recipient'] = self.agent
            with self.assertRaises(ReceiveConflict):
                await self.runtime.consume(changed)
            self.assertEqual(self.row(), original)
        self.assertEqual(self.runtime.journal.db.execute('select count(*) from room_input_identity').fetchone()[0], 0)
        self.assertEqual(self.runtime.cursor, 0)
        self.rpc.call.assert_not_called()

    async def test_canonical_identity_survives_renderer_change_but_binds_full_event(self):
        original = self.seed('acknowledged', canonical=True)
        for field, value in [('body', 'Changed text'), ('author', uid(91)), ('source', uid(92)),
                             ('kind', 'message'), ('audience', 'direct')]:
            changed = copy.deepcopy(self.event)
            changed[field] = value
            if field == 'audience':
                changed['recipient'] = self.agent
            with self.assertRaises(ReceiveConflict):
                await self.runtime.consume(changed)
        await self.runtime.consume(self.event)
        self.assertEqual(self.row(), original)
        self.rpc.call.assert_not_called()

    async def test_corrupted_original_rendered_digest_is_not_bypassed_by_canonical_record(self):
        self.seed('acknowledged', canonical=True)
        db = self.runtime.journal.db
        with db:
            db.execute("update room_input set payload='{}'")
        with self.assertRaises(ReceiveConflict):
            await self.runtime.consume(self.event)
        self.rpc.call.assert_not_called()
        self.assertEqual(self.runtime.cursor, 0)

    async def test_original_direct_peer_context_dispatch_and_authorship_remain_exact(self):
        peer = copy.deepcopy(self.event)
        peer.update(author=uid(71), recipient=self.agent, audience='direct', kind='message')
        peer['data']['authorKind'] = 'agent'
        context = peer_context(peer, **self.render_args)
        staged = {'method': 'hollywood/agentMessage', 'params': context}
        original = self.runtime.journal.stage(**self.args, payload=staged)
        await self.runtime.consume(peer)
        request = peer_request(context, agent_id=self.agent)
        self.rpc.call.assert_awaited_once_with('hollywood/agentMessage', request)
        self.assertEqual(request['authorId'], peer['author'])
        self.assertEqual(request['audience'], 'direct')
        self.assertFalse(request['expectsReply'])
        self.assertEqual(self.row()['payload'], original['payload'])


if __name__ == '__main__':
    unittest.main()
