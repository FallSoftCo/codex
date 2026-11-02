"""Instruction assembly/adoption and original fanout invariants; no model claim."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from lax_connector.room_bootstrap import initialize
from lax_connector.room_input import human_input
from lax_connector.room_participation import POLICY, VERSION, PRIVATE_FINAL_LEGACY, FINAL_DELIVERY, require_cold_boundary, resume_overrides, with_policy
from lax_connector.room_permissions import requested
from lax_connector.room_tools import TOOLS


class Participation(unittest.IsolatedAsyncioTestCase):
    async def test_existing_connector_uses_reviewed_policy_in_supported_cold_resume(self):
        from lax_connector.conversational_agent import ConversationalAgent
        from lax_connector.journal import saved as real_saved
        class AfterResume(Exception):
            pass
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            config = {'runtimeMode': 'room-conversation', 'authorityId': str(uuid4()), 'hostId': str(uuid4()), 'agentId': str(uuid4()),
                'nativeThreadId': 'same-original', 'state': str(root / 'state'), 'codexHome': str(root / 'home'),
                'conversationDynamicTools': TOOLS, 'rooms': [{'roomId': str(uuid4()), 'after': 0}],
                'conversationParticipationPolicy': VERSION,
                'conversationInstructionAdoptionId': 'a' * 64,
                'conversationResumeInstructions': {'baseInstructions': 'Reviewed original role'},
                'hollywoodUrl': 'http://127.0.0.1:1', 'token': 'NO-NETWORK-FIXTURE'}
            rpc = type('RPC', (), {})()
            rpc.home, rpc.state, rpc.shared, rpc.has_started = Path(config['codexHome']), root / 'native', True, False
            rpc.start, rpc.close = AsyncMock(), AsyncMock()
            rpc.call = AsyncMock(side_effect=[{'data': [], 'nextCursor': None}, {
                'thread': {'id': config['nativeThreadId'], 'status': {'type': 'idle', 'activeFlags': []}},
                'sandbox': {'type': 'readOnly'}, 'approvalPolicy': 'never'}])
            receipts = []
            def checkpoint(path, value):
                if path.name == 'conversation-resume.json':
                    receipts.append(value)
                    raise AfterResume()
                return real_saved(path, value)
            with patch('lax_connector.conversational_agent.native_client', return_value=rpc), \
                 patch('lax_connector.conversational_agent.saved', side_effect=checkpoint), \
                 patch('lax_connector.room_instruction_adoption.InstructionAdoption.native_binding', return_value={'fixture': 'original'}):
                agent = ConversationalAgent(config)
                with self.assertRaises(AfterResume):
                    await agent.serve()
            self.assertEqual([call.args[0] for call in rpc.call.await_args_list],
                             ['thread/loaded/list', 'thread/resume'])
            resume = rpc.call.await_args_list[1].args[1]
            self.assertEqual(resume['threadId'], 'same-original')
            self.assertEqual(resume['baseInstructions'], with_policy('Reviewed original role'))
            self.assertEqual(resume['dynamicTools'], TOOLS)
            self.assertNotIn('model', resume)
            self.assertNotIn('sandbox', resume)
            self.assertEqual((receipts[0]['participationPolicy'], receipts[0]['instructionAdoptionColdBoundary']),
                             (VERSION, True))

    def test_only_known_obsolete_final_clause_is_reconciled(self):
        restriction = 'Do not expose private customer records or resume a deliberate stop.'
        before = 'Original owner role. ' + PRIVATE_FINAL_LEGACY + ' ' + restriction
        after = with_policy(before)
        self.assertEqual(after, 'Original owner role. ' + FINAL_DELIVERY + ' ' + restriction + '\n\n' + POLICY)
        self.assertNotIn(PRIVATE_FINAL_LEGACY, after)
        self.assertEqual(with_policy(after), after)

    def test_factory_changes_only_new_prompt_not_original_identity_or_permissions(self):
        from lax_connector.linux_worker import expected_configuration
        authority, agent, host, room = [str(uuid4()) for _ in range(4)]
        spec = {'runtimeMode': 'room-conversation', 'nativeName': 'CPU fixture', 'purpose': 'Local read only',
                'hollywoodUrl': 'http://127.0.0.1:1', 'credential': 'SYNTHETIC', 'hostId': host,
                'binary': '/fixture/bin/codex', 'model': 'gpt-6.1-sol', 'effort': 'xhigh',
                'rooms': [{'roomId': room, 'after': 0}]}
        for profile in ('restricted', 'unrestricted'):
            original = expected_configuration(spec, authority, agent, Path('/fixture/home'), profile, participation=False)
            updated = expected_configuration(spec, authority, agent, Path('/fixture/home'), profile)
            self.assertEqual(updated, {**original, 'instructions': with_policy(original['instructions'])})

    def test_explicit_adoption_preserves_original_overrides_and_is_idempotent(self):
        existing = {'baseInstructions': 'Original role and deliberate-stop contract',
                    'developerInstructions': 'Original owner restrictions'}
        config = {'conversationResumeInstructions': existing}
        self.assertEqual(resume_overrides(config), (existing, None))
        adopted, revision = resume_overrides({**config, 'conversationParticipationPolicy': VERSION})
        self.assertEqual(with_policy(existing['baseInstructions']), adopted['baseInstructions'])
        self.assertEqual(existing['developerInstructions'], adopted['developerInstructions'])
        self.assertEqual(with_policy(adopted['baseInstructions']), adopted['baseInstructions'])
        self.assertEqual(revision, VERSION)
        self.assertEqual(config['conversationResumeInstructions'], existing)
        with self.assertRaises(ValueError):
            resume_overrides({'conversationParticipationPolicy': 'unreviewed'})
        with self.assertRaisesRegex(ValueError, 'reviewed original baseInstructions'):
            resume_overrides({'conversationParticipationPolicy': VERSION})

    def test_original_human_delivery_is_not_filtered_or_rewritten(self):
        authority, agent, human, room, event = [str(uuid4()) for _ in range(5)]
        canonical = {'id': event, 'authority': authority, 'room': room, 'author': human,
            'kind': 'request', 'audience': 'room', 'body': 'ok continue team',
            'data': {'authorKind': 'human', 'conversationVersion': 1, 'conversationRecipients': [agent]}}
        result = human_input(canonical, authority_id=authority, agent_id=agent, thread_id='original-thread')
        self.assertEqual((result['clientUserMessageId'], result['input'][0]['text']), (event, canonical['body']))
        metadata = json.loads(result['additionalContext']['laxRoomMessage']['value'])
        self.assertEqual((metadata['eventId'], metadata['audience']), (event, 'room'))
        private = human_input({**canonical, 'audience': 'direct', 'recipient': agent},
                              authority_id=authority, agent_id=agent, thread_id='original-thread')
        self.assertEqual(private['input'], result['input'])
        self.assertNotEqual(private['additionalContext'], result['additionalContext'])

    async def test_loaded_thread_and_incomplete_inspection_hold_adoption(self):
        rpc = type('RPC', (), {})()
        rpc.call = AsyncMock(side_effect=[{'data': ['other'], 'nextCursor': 'next'},
                                          {'data': ['original'], 'nextCursor': None}])
        with self.assertRaisesRegex(ValueError, 'released native thread'):
            await require_cold_boundary(rpc, 'original')
        self.assertEqual(rpc.call.await_count, 2)
        rpc.call = AsyncMock(return_value={'data': [], 'nextCursor': 'stuck'})
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            await require_cold_boundary(rpc, 'original')
        rpc.call = AsyncMock(return_value={'data': [], 'nextCursor': None})
        await require_cold_boundary(rpc, 'original')
        self.assertEqual(rpc.call.await_count, 1)

    async def test_ready_legacy_initialization_is_returned_without_rewrite_or_rpc(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            state, work = root / 'state', root / 'work'
            state.mkdir(mode=0o700)
            work.mkdir()
            cfg = {'runtimeMode': 'room-conversation', 'authorityId': str(uuid4()), 'agentId': str(uuid4()),
                'state': str(state), 'codexHome': str(root / 'home'), 'workspace': str(work),
                'nativeName': 'Original QA owner', 'model': 'gpt-6.1-sol', 'effort': 'xhigh',
                'sandbox': 'danger-full-access', 'approvalPolicy': 'never', 'instructions': 'Original role'}
            binding = {'authorityId': cfg['authorityId'], 'agentId': cfg['agentId'],
                       'codexHome': cfg['codexHome'], 'nativeState': str(state / 'native')}
            request = {'cwd': str(work), 'model': cfg['model'], **requested(cfg), 'dynamicTools': TOOLS,
                'baseInstructions': cfg['instructions'], 'config': {
                    'model_reasoning_effort': cfg['effort'], 'features.default_mode_request_user_input': True}}
            fingerprint = hashlib.sha256(json.dumps({'binding': binding, 'name': cfg['nativeName'],
                'request': request}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            prior = {'state': 'ready', 'binding': binding, 'requestDigest': fingerprint,
                     'nativeThreadId': 'original'}
            path = state / 'native-context.json'
            path.write_text(json.dumps(prior))
            before = path.read_bytes()
            with patch('lax_connector.room_bootstrap.native_client', side_effect=AssertionError('No native start')):
                self.assertEqual(await initialize(cfg), prior)
            self.assertEqual(path.read_bytes(), before)
            # Changed owner instructions still require explicit adoption, not an
            # initialization replay or new context hidden behind compatibility.
            with self.assertRaisesRegex(ValueError, 'explicit upgrade'):
                await initialize({**cfg, 'instructions': 'Changed role'})


if __name__ == '__main__':
    unittest.main()
