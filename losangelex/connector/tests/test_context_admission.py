"""Admission must precede inference; no semantic-model behavior is simulated."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from lax_connector.context_runtime import ContextRunner


class ContextAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_capacity_deferral_never_submits_or_marks_a_model_wake(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls = []
            async def request(action, value=None, **kwargs):
                calls.append((action, value, kwargs))
                return {"delivery": None, "admission": {"reason": "host_capacity_exhausted"}}
            async def rpc(*args, **kwargs):
                self.fail("A deferred work item reached native RPC")
            runner = ContextRunner.__new__(ContextRunner)
            runner.purpose = "writer"
            runner.state = root
            runner.admitted = asyncio.Event()
            runner.request = request
            runner.rpc = SimpleNamespace(call=rpc)
            await runner.run("same-original-work", [{"id": "work-reference"}])
            self.assertEqual([v[0] for v in calls], ["admit"])
            self.assertEqual(calls[0][2], {
                "operation": "context-admit:work-reference", "turn": "admission"})
            self.assertFalse(runner.active)
            self.assertFalse((root / "wake.json").exists())
            self.assertEqual(json.loads((root / "admission-wait.json").read_text()),
                {"delivery": None, "admission": {"reason": "host_capacity_exhausted"}})

    async def test_unconfirmed_admission_holds_without_submitting_inference(self):
        with tempfile.TemporaryDirectory() as tmp:
            async def request(*args, **kwargs):
                raise RuntimeError("Original admission receipt unavailable")
            async def rpc(*args, **kwargs):
                self.fail("An uncertain admission reached native RPC")
            runner = ContextRunner.__new__(ContextRunner)
            runner.purpose = "writer"
            runner.state = Path(tmp)
            runner.admitted = asyncio.Event()
            runner.request = request
            runner.rpc = SimpleNamespace(call=rpc)
            with self.assertRaisesRegex(RuntimeError, "Original admission"):
                await runner.run("original", [{"id": "work"}])
            self.assertTrue(runner.failed)
            self.assertFalse(runner.active)
            self.assertFalse((runner.state / "wake.json").exists())

    async def test_cached_acceptance_cannot_bypass_current_authorization(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            async def request(action, value=None, **kwargs):
                calls.append(action)
                if action == "admit":
                    return {"delivery": {"id": "original", "claim_id": "accepted"}}
                if action == "ready":
                    raise PermissionError("Current original work cancelled")
                self.fail("Unexpected context request")
            async def rpc(*args, **kwargs):
                self.fail("Revoked current authorization reached native RPC")
            runner = ContextRunner.__new__(ContextRunner)
            runner.purpose = "writer"
            runner.state = Path(tmp)
            runner.admitted = asyncio.Event()
            runner.request = request
            runner.rpc = SimpleNamespace(call=rpc)
            with self.assertRaisesRegex(PermissionError, "cancelled"):
                await runner.run("original", [{"id": "work"}])
            self.assertEqual(calls, ["admit", "ready"])
            self.assertTrue(runner.failed)
            self.assertFalse(runner.active)
            self.assertFalse((runner.state / "wake.json").exists())

    async def test_reader_and_responder_cannot_bypass_queued_inference_capacity(self):
        for purpose in ("reader", "responder"):
            with self.subTest(purpose=purpose), tempfile.TemporaryDirectory() as tmp:
                calls = []
                async def request(action, value=None, **kwargs):
                    calls.append(action)
                    return {"permit": {"id": "original-permit", "state": "queued"},
                            "admission": {"reason": "host_capacity_exhausted"}}
                async def rpc(*args, **kwargs):
                    self.fail("A queued communication context reached inference")
                runner = ContextRunner.__new__(ContextRunner)
                runner.purpose = purpose
                runner.state = Path(tmp)
                runner.admitted = asyncio.Event()
                runner.request = request
                runner.rpc = SimpleNamespace(call=rpc)
                await runner.run("frozen-material", [{"id": "original-material"}])
                self.assertEqual(calls, ["reserve"])
                self.assertFalse(runner.active)
                self.assertFalse((runner.state / "wake.json").exists())

    async def test_exact_permit_precedes_submission_and_survives_begin_and_terminal_callbacks(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            runner = ContextRunner.__new__(ContextRunner)
            async def request(action, value=None, **kwargs):
                calls.append(action)
                if action == "reserve":
                    return {"permit": {"id": "original-permit", "state": "reserved"}}
                self.assertEqual(value["permitId"], "original-permit")
                return {}
            async def rpc(method, params, **kwargs):
                calls.append(method)
                self.assertEqual(calls[:2], ["reserve", "turn/start"])
                runner.finished.set_result({"id": "original-turn", "status": "completed"})
                return {"turn": {"id": "original-turn"}}
            runner.purpose = "reader"
            runner.thread = "original-reader-thread"
            runner.config = {"model": "unchanged", "effort": "unchanged"}
            runner.state = Path(tmp)
            runner.admitted = asyncio.Event()
            runner.effect_lock = asyncio.Lock()
            runner.request = request
            runner.rpc = SimpleNamespace(call=rpc)
            runner.trace = lambda *_: None
            runner.activity = None
            await runner.run("material", [{"id": "original-material"}])
            self.assertEqual(calls, ["reserve", "turn/start", "begin", "end"])
            self.assertFalse(runner.active)
            self.assertEqual(json.loads((runner.state / "wake.json").read_text())["state"], "finished")

    async def test_confirmed_deferral_can_retry_same_admission_then_retains_accepted_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            responses = iter((
                {"delivery": None, "admission": {"reason": "host_capacity_stale"}},
                {"delivery": {"id": "original", "generation": 1, "claim_id": "admit:original"}},
            ))
            async def http(purpose, method, path, payload=None):
                calls.append((purpose, method, path, payload))
                return next(responses)
            runner = ContextRunner.__new__(ContextRunner)
            runner.purpose = "writer"
            runner.thread = "original-writer-thread"
            runner.turn = None
            runner.config = {"agentId": "original-agent"}
            runner.state = Path(tmp)
            runner.agent = SimpleNamespace(http=http)
            args = ("admit", {"workId": "original-work", "capabilities": []})
            key = {"operation": "admit:original", "turn": "admission"}
            deferred = await runner.request(*args, **key)
            self.assertIsNone(deferred["delivery"])
            self.assertEqual(list(runner.state.glob("operation-*.json")), [])
            accepted = await runner.request(*args, **key)
            replay = await runner.request(*args, **key)
            self.assertEqual(accepted, replay)
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0], calls[1])
            self.assertEqual(len(list(runner.state.glob("operation-*.json"))), 1)


if __name__ == "__main__":
    unittest.main()
