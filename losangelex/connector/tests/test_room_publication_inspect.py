"""Actual rejected outbox/SQLite metadata, no network, model or recovery write."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from lax_connector.conversation_io import ConversationIO
from lax_connector.errors import HttpFailure
from lax_connector.room_publication_inspect import inspect_original
from lax_connector.room_tools import RoomTools


class PublicationInspection(unittest.TestCase):
    def test_private_source_broadening_is_undispatched_not_silently_rewritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            authority, agent, room, sender, source, outsider = [str(uuid4()) for _ in range(6)]
            io = ConversationIO(root / 'conversation.sqlite', authority=authority,
                                agent=agent, thread='original-thread')
            event = {'id': source, 'authority': authority, 'room': room, 'author': sender,
                     'recipient': agent, 'audience': 'direct', 'data': {
                         'authorKind': 'agent', 'conversationRecipients': [agent]}}
            io.stage(event)
            io.bind(event, {'turn': {'id': 'original-turn'}})
            posts = []
            async def accepted(method, path, payload=None):
                posts.append((method, path, payload))
                return {'accepted': True, 'deliveries': [], 'event': {'id': str(uuid4()),
                    'authority': authority, 'author': agent, 'room': room, 'kind': 'message',
                    'body': payload['body'], 'audience': payload['audience'],
                    'recipient': payload.get('recipientId'), 'source': source,
                    'data': {'responsePhase': 'answer'}}}
            tools = RoomTools(authority_id=authority, agent_id=agent, thread_id='original-thread',
                request=accepted, state=root / 'publications', conversation_io=io)
            initial_entries = list((root / 'publications').iterdir())
            args = {'body': 'Private answer', 'audience': 'room', 'recipientId': sender,
                    'sourceEventId': source, 'responsePhase': 'answer'}
            async def exercise():
                for changed in ({}, {'audience': 'direct', 'recipientId': outsider}):
                    with self.assertRaisesRegex(ValueError, 'No HTTP publication was dispatched'):
                        await tools.publish(room, {**args, **changed},
                            hashlib.sha256(json.dumps(changed).encode()).hexdigest(), turn='original-turn')
                self.assertEqual(posts, [])
                self.assertEqual(list((root / 'publications').iterdir()), initial_entries)
                self.assertEqual(io.publications('original-turn', source), [])
                corrected = {**args, 'audience': 'direct'}
                key = hashlib.sha256(b'new-corrected-semantic-call').hexdigest()
                result = await tools.publish(room, corrected, key, turn='original-turn')
                self.assertTrue(result['accepted'])
                self.assertEqual(posts[0][2]['audience'], 'direct')
                self.assertEqual(posts[0][2]['recipientId'], sender)
                # Accepted repeated calls still reconcile their original receipt.
                self.assertEqual(await tools.publish(room, corrected, key, turn='original-turn'), result)
                self.assertEqual(len(posts), 1)
            asyncio.run(exercise())
            io.close()

    def test_actual_rejection_is_inspectable_but_not_retried_or_exposed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            authority, agent, room, sender, source = [str(uuid4()) for _ in range(5)]
            config = root / 'config.json'
            state = root / 'state'
            state.mkdir(mode=0o700)
            config.write_text(json.dumps({'state': str(state), 'authorityId': authority,
                'agentId': agent, 'nativeThreadId': 'original-thread', 'token': 'TOKEN-CANARY'}))
            config.chmod(0o600)
            io = ConversationIO(state / 'conversation-io.sqlite', authority=authority,
                                agent=agent, thread='original-thread')
            event = {'id': source, 'authority': authority, 'room': room, 'author': sender, 'recipient': agent,
                     'audience': 'direct', 'data': {'authorKind': 'agent', 'expectsReply': True,
                                                   'conversationRecipients': [agent]}}
            io.stage(event)
            io.bind(event, {'turn': {'id': 'original-turn'}})
            io.ended('original-turn', 'completed')
            posts = []
            async def denied(method, path, payload=None):
                posts.append((method, path))
                raise HttpFailure(403, 'PRIVATE-ERROR-CANARY', code='AGENT_ACCESS_DENIED')
            tools = RoomTools(authority_id=authority, agent_id=agent, thread_id='original-thread',
                request=denied, state=state / 'publications', conversation_io=io)
            key = hashlib.sha256(b'original-call').hexdigest()
            async def reject():
                with self.assertRaises(HttpFailure):
                    await tools.publish(room, {'body': 'BODY-CANARY', 'audience': 'direct',
                        'recipientId': sender, 'sourceEventId': source, 'responsePhase': 'answer'},
                        key, turn='original-turn')
            asyncio.run(reject())
            receipt = state / 'publications' / (key + '.json')
            before = receipt.read_bytes()
            result = inspect_original(config, key, 'original-turn')
            encoded = json.dumps(result)
            self.assertEqual((result['localState'], result['httpStatus'], result['errorCode'],
                result['nativePhase'], result['mutationDispatched']),
                ('rejected', 403, 'AGENT_ACCESS_DENIED', 'completed', False))
            self.assertEqual(result['bodySha256'], hashlib.sha256(b'BODY-CANARY').hexdigest())
            for canary in ('BODY-CANARY', 'TOKEN-CANARY', 'PRIVATE-ERROR-CANARY'):
                self.assertNotIn(canary, encoded)
            self.assertEqual(receipt.read_bytes(), before)
            self.assertEqual(posts, [('POST', 'rooms/' + room + '/messages')])
            self.assertEqual(io.publications('original-turn', source)[0]['state'], 'rejected')
            with self.assertRaises(ValueError):
                inspect_original(config, '../other', 'original-turn')
            with self.assertRaises(ValueError):
                inspect_original(config, key, 'different-turn')
            config_data = json.loads(config.read_text())
            config.write_text(json.dumps({**config_data, 'nativeThreadId': 'other-thread'}))
            with self.assertRaises(ValueError):
                inspect_original(config, key, 'original-turn')
            config.write_text(json.dumps(config_data))
            altered = json.loads(before)
            altered['payload']['body'] = 'changed'
            receipt.write_text(json.dumps(altered))
            with self.assertRaises(ValueError):
                inspect_original(config, key, 'original-turn')
            receipt.write_bytes(before)
            if os.name != 'nt':
                alias = root / 'config-alias.json'
                alias.symlink_to(config)
                with self.assertRaises(ValueError):
                    inspect_original(alias, key, 'original-turn')
            io.close()


if __name__ == '__main__':
    unittest.main()
