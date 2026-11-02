"""Original ACK finish, loaded reconnect and unknown holds; no model sampling."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from lax_connector.journal import saved
from lax_connector.room_instruction_adoption import InstructionAdoption
from lax_connector.room_participation import VERSION, instructions_digest, release_patch, resume_overrides


class Adoption(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name).resolve()
        self.config = {'state': str(self.state), 'authorityId': str(uuid4()), 'hostId': str(uuid4()), 'agentId': str(uuid4()),
            'nativeThreadId': 'original-thread', 'runtimeMode': 'room-conversation',
            'conversationResumeInstructions': {'baseInstructions': 'Original owner role',
                                              'developerInstructions': 'Retain owner restriction'}}
        review = {'policy': VERSION, 'expectedResumeInstructionsSha256': instructions_digest(
            self.config['conversationResumeInstructions'])}
        delta, self.proof = release_patch(self.config, review, ['authority', 'host', 'agent'], 'c' * 64)
        self.config.update(delta)
        self.overrides, _ = resume_overrides(self.config)
        self.rpc = type('RPC', (), {'shared': True})()
        self.rpc.call = AsyncMock(return_value={'data': [], 'nextCursor': None})
        self.binding = self.enterContext(patch.object(InstructionAdoption, 'native_binding',
                                                      return_value={'socketIdentity': [1, 2, 3]}))

    def helper(self):
        return InstructionAdoption(self.config, self.rpc, self.overrides)

    def receipt(self, helper):
        return {'threadId': 'original-thread', 'resumed': True,
            'instructionOverridesSha256': instructions_digest(self.overrides), **helper.receipt_fields()}

    async def test_original_ack_finishes_without_resend_and_loaded_reconnect_reuses_policy(self):
        first = self.helper()
        self.assertEqual(await first.begin(), self.overrides)
        original_intent = first.intent.read_bytes()
        saved(self.state / 'conversation-resume.json', self.receipt(first))
        # Original native ACK exists; crash happened before acceptance only.
        self.rpc.call.return_value = {'data': ['original-thread'], 'nextCursor': None}
        second = self.helper()
        self.assertEqual(await second.begin(), {})
        self.assertEqual(second.mode, 'accepted-loaded')
        accepted = second.accepted.read_bytes()
        third = self.helper()
        self.assertEqual(await third.begin(), {})
        self.assertEqual(first.intent.read_bytes(), original_intent)
        self.assertEqual(third.accepted.read_bytes(), accepted)
        self.assertTrue(all(call.args[0] == 'thread/loaded/list' for call in self.rpc.call.await_args_list))

    async def test_unknown_original_is_not_retried_or_adopted_from_loaded_status(self):
        first = self.helper()
        await first.begin()
        before = first.intent.read_bytes()
        self.rpc.call.return_value = {'data': ['original-thread'], 'nextCursor': None}
        with self.assertRaisesRegex(ValueError, 'uncertain'):
            await self.helper().begin()
        self.assertEqual(first.intent.read_bytes(), before)
        self.assertFalse(first.accepted.exists())
        self.assertEqual(self.rpc.call.await_count, 1)

    async def test_unadopted_loaded_thread_and_changed_native_binding_hold(self):
        self.rpc.call.return_value = {'data': ['original-thread'], 'nextCursor': None}
        first = self.helper()
        with self.assertRaisesRegex(ValueError, 'released native thread'):
            await first.begin()
        self.assertFalse(first.intent.exists())
        self.rpc.call.return_value = {'data': [], 'nextCursor': None}
        await first.begin()
        first.complete(self.receipt(first))
        accepted = first.accepted.read_bytes()
        self.binding.return_value = {'socketIdentity': [1, 4, 5]}
        self.rpc.call.return_value = {'data': ['original-thread'], 'nextCursor': None}
        with self.assertRaisesRegex(ValueError, 'released native thread'):
            await self.helper().begin()
        self.assertEqual(first.accepted.read_bytes(), accepted)

    def test_review_cannot_change_other_owner_instructions_or_bypass_original_cas(self):
        original = {'runtimeMode': 'room-conversation', 'nativeThreadId': 'original-thread',
            'model': 'existing-model', 'sandbox': 'existing-restrictions',
            'conversationResumeInstructions': {'baseInstructions': 'Keep exact role',
                                              'developerInstructions': 'Keep exact owner restrictions'}}
        review = {'policy': VERSION, 'expectedResumeInstructionsSha256': instructions_digest(
            original['conversationResumeInstructions'])}
        delta, _ = release_patch(original, review, ['a', 'h', 'p'], 'a' * 64)
        self.assertEqual(delta['conversationResumeInstructions']['developerInstructions'], 'Keep exact owner restrictions')
        self.assertEqual(set(delta), {'conversationResumeInstructions', 'conversationParticipationPolicy',
                                     'conversationInstructionAdoptionId'})
        with self.assertRaisesRegex(ValueError, 'CAS changed'):
            release_patch(original, {**review, 'expectedResumeInstructionsSha256': '0' * 64}, ['a', 'h', 'p'], 'a' * 64)
        with self.assertRaises(ValueError):
            release_patch(original, {**review, 'baseInstructions': 'Unreviewed replacement'}, ['a', 'h', 'p'], 'a' * 64)


if __name__ == '__main__':
    unittest.main()
