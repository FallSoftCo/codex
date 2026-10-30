"""Fault injection at the actual launch boundary, with no model or service."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from lax_connector.execution_lifecycle import ExecutionLifecycle
from lax_connector.errors import HttpFailure

class PrelaunchWait(unittest.IsolatedAsyncioTestCase):
    def lifecycle(self, root, observations):
        value=object.__new__(ExecutionLifecycle)
        value.id='original-executor';value.root=root
        value.validate=lambda result:result['executor']
        value.reads=[]
        async def transport(method,path):
            value.reads.append((method,path))
            result=next(observations)
            if isinstance(result,Exception):raise result
            return result
        async def controller(row):return True
        value.transport=transport;value.current_controller=controller
        return value
    def observation(self,ready=False):
        return {'deliveryState':'claimed','executor':{'state':'unknown','controller':'owner',
            'evidence':{'reason':'registered-launch-pending' if ready else 'unverified-host-executor'}}}
    async def test_prolonged_timeout_retains_exact_reservation_and_later_admits(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            observations=iter([TimeoutError(),HttpFailure(503,'unavailable')]+[self.observation()]*10+[self.observation(True)])
            value=self.lifecycle(root,observations);delays=[]
            async def sleep(delay):delays.append(delay)
            with patch('lax_connector.execution_lifecycle.asyncio.sleep',sleep):
                await value.require_registered()
            self.assertGreater(sum(delays),120)
            self.assertLessEqual(max(delays),30)
            self.assertTrue((root/'guardian-registration-attestation.json').exists())
            self.assertEqual(set(value.reads),{('GET','executors/original-executor')})
    async def test_auth_and_revoked_claim_are_not_retried(self):
        for observation in [HttpFailure(403,'revoked'),{'deliveryState':'cancel_requested','executor':{'state':'unknown'}}]:
            with tempfile.TemporaryDirectory() as directory:
                value=self.lifecycle(Path(directory),iter([observation]))
                with self.assertRaises(RuntimeError):await value.require_registered()
                self.assertEqual(len(value.reads),1)
                self.assertFalse((Path(directory)/'guardian-registration-attestation.json').exists())
    async def test_task_cancellation_never_launches_or_swallows_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            value=self.lifecycle(Path(directory),iter([self.observation()]))
            async def sleep(delay):raise asyncio.CancelledError()
            with patch('lax_connector.execution_lifecycle.asyncio.sleep',sleep):
                with self.assertRaises(asyncio.CancelledError):await value.require_registered()
            self.assertFalse((Path(directory)/'guardian-registration-attestation.json').exists())
