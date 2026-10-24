"""Deterministic control/transport tests, not actual-model evidence."""

import asyncio
import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from lax_connector.automatic_context_refill import (
    AutomaticContextRefill,
    PREPARE,
    INSTALL,
)
from lax_connector.automatic_refill_data import CUT, IDENTITY, wire
from lax_connector.context_runtime import ContextRunner
from lax_connector.reader_inbox import ReaderInbox


class AutomaticRefillTests(unittest.IsolatedAsyncioTestCase):
    def runner(self, directory):
        r = ContextRunner.__new__(ContextRunner)
        r.state = Path(directory)
        r.config = {
            "agentId": "agent",
            "contextIds": {"reader": "context"},
            "automaticContextRefill": {"type": "canonical"},
        }
        r.purpose, r.thread, r.turn, r.permit = "reader", "thread", "turn", "permit"
        r.material_ids, r.permit_material_ids = ["input"], ("input",)
        r.active, r.accepting, r.closing, r.failed = True, True, False, False
        r.finished = asyncio.get_running_loop().create_future()
        r.admitted = asyncio.Event()
        r.admitted.set()
        r.effect_lock = asyncio.Lock()
        r.agent = SimpleNamespace(stop=asyncio.Event())
        r.execution_scope = None
        r.trace = lambda *_: None
        r.native = Path(directory) / "original.jsonl"
        r.native.write_bytes(b'{"type":"session_meta","payload":{"id":"thread"}}\n')
        r.calls = []

        async def rpc(method, params, **_kwargs):
            r.calls.append(method)
            if method == "turn/interrupt":
                return {}
            self.assertEqual(method, "thread/read")
            return {
                "thread": {"id": "thread", "path": str(r.native), "ephemeral": False}
            }

        async def request(action, value=None, **kwargs):
            r.calls.append(action)
            if action == "active_installed":
                return {"operationId": "op", "status": "recorded"}
            if action == "close":
                return {}
            self.assertEqual(action, "active_snapshot")
            text = wire(
                {
                    "agentId": "agent",
                    "contextId": "context",
                    "purpose": "reader",
                    "nativeThread": "thread",
                    "nextMaterialIds": ["input"],
                }
            )
            return {
                "chunks": [{"offset": 0, "content": text}],
                "sha256": hashlib.sha256(text.encode()).hexdigest(),
                "totalBytes": len(text.encode()),
                "snapshotReadPoint": "cut",
                "selectionRevision": 0,
            }

        r.request, r.rpc = request, SimpleNamespace(call=rpc)
        r.inbox = ReaderInbox(r)
        r.automatic = AutomaticContextRefill(r)
        self.addCleanup(
            lambda: r.automatic.timer.cancel() if r.automatic.timer else None
        )
        return r

    def params(self):
        return {
            "threadId": "thread",
            "turnId": "turn",
            "operationId": "op",
            "contextId": "context",
            "purpose": "reader",
            "windowId": "old",
            "historyVersion": 1,
            "reason": "contextLimit",
            "phase": "midTurn",
            "_rpcRequestId": 7,
        }

    def install_native(self, r, response):
        intent = {
            k: response[k] for k in IDENTITY | CUT | {"windowId", "historyVersion"}
        }
        intent.update(reason="contextLimit", phase="midTurn", nextWindowId="new")
        checkpoint = {
            "type": "compacted",
            "payload": {
                "message": "",
                "previous_window_id": "old",
                "window_id": "new",
                "replacement_history": response["items"],
            },
        }
        prefix = (
            r.native.read_bytes()
            + (
                wire(
                    {
                        "type": "event_msg",
                        "payload": {"type": "context_window_refill_intent", **intent},
                    }
                )
                + "\n"
                + wire(checkpoint)
                + "\n"
            ).encode()
        )
        installed = {k: response[k] for k in IDENTITY | CUT}
        installed.update(
            previousWindowId="old",
            windowId="new",
            nativeHistoryBytes=len(prefix),
            nativeHistorySha256=hashlib.sha256(prefix).hexdigest(),
        )
        r.native.write_bytes(
            prefix
            + (
                wire(
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "context_window_refill_installed",
                            **installed,
                        },
                    }
                )
                + "\n"
            ).encode()
        )
        return {**installed, "_rpcRequestId": 8}

    async def test_gate_spans_native_write_and_host_ack_without_drop_or_deadlock(self):
        with tempfile.TemporaryDirectory() as directory:
            r = self.runner(directory)
            p = self.params()
            response = await r.tool(PREPARE, p)
            self.assertFalse(r.effect_lock.locked())
            self.assertTrue(r.automatic.blocked)
            self.assertEqual(r.automatic.pending["state"], "response_prepared")
            await r.automatic.submitted(PREPARE, p, True)
            await r.inbox.receive([{"id": "later", "revision": 1}])
            self.assertEqual(r.inbox.delivered, {})
            self.assertEqual(r.material_ids, ["input"])
            installed = self.install_native(r, response)
            self.assertEqual(
                await r.tool(INSTALL, installed),
                {"operationId": "op", "status": "recorded"},
            )
            self.assertTrue(r.automatic.blocked)
            await r.automatic.submitted(INSTALL, installed, True)
            self.assertFalse(r.automatic.blocked)
            self.assertEqual(
                r.calls,
                ["thread/read", "active_snapshot", "thread/read", "active_installed"],
            )
            self.assertFalse((r.state / "context-rebuild-generation.json").exists())
            self.assertEqual(r.inbox.delivered, {})

    async def test_lost_response_holds_original_on_restart_without_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            r = self.runner(directory)
            p = self.params()
            await r.tool(PREPARE, p)
            await r.automatic.submitted(PREPARE, p, False)
            before = list(r.calls)
            self.assertTrue(AutomaticContextRefill(r).held)
            with self.assertRaises(RuntimeError):
                await r.tool(PREPARE, p)
            self.assertEqual(r.calls, before)

    async def test_cancel_is_accepted_before_lock_and_rechecked_after_http(self):
        with tempfile.TemporaryDirectory() as directory:
            r = self.runner(directory)
            entered, release = asyncio.Event(), asyncio.Event()
            original = r.request

            async def request(action, *args, **kwargs):
                if action == "active_snapshot":
                    entered.set()
                    await release.wait()
                return await original(action, *args, **kwargs)

            r.request = request
            prepare = asyncio.create_task(r.tool(PREPARE, self.params()))
            await entered.wait()
            cancel = asyncio.create_task(r.cancel())
            await asyncio.sleep(0)
            self.assertFalse(r.accepting)
            self.assertTrue(r.closing)
            release.set()
            with self.assertRaises(RuntimeError):
                await prepare
            await asyncio.wait_for(cancel, 1)
            self.assertTrue(r.automatic.held)
            self.assertNotIn("active_installed", r.calls)

    async def test_unknown_append_and_wrong_identity_never_dispatch_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            r = self.runner(directory)
            r.inbox.uncertain = True
            with self.assertRaises(RuntimeError):
                await r.tool(PREPARE, self.params())
            r.inbox.uncertain = False
            with self.assertRaises(RuntimeError):
                await r.tool(PREPARE, {**self.params(), "turnId": "wrong"})
            self.assertEqual(r.calls, [])

    async def stage(self, r, action):
        p = self.params()
        if action == "active_snapshot":
            return PREPARE, p
        response = await r.tool(PREPARE, p)
        await r.automatic.submitted(PREPARE, p, True)
        return INSTALL, self.install_native(r, response)

    async def assert_gate_without_mutex(self, r):
        await asyncio.wait_for(r.effect_lock.acquire(), 0.5)
        r.effect_lock.release()
        before = list(r.calls)
        await asyncio.wait_for(r.inbox.receive([{"id": "later", "revision": 1}]), 0.5)
        self.assertEqual(r.calls, before)
        self.assertEqual(r.inbox.delivered, {})
        self.assertEqual(r.material_ids, ["input"])
        self.assertTrue(r.automatic.blocked)
        durable = json.loads(r.automatic.path.read_text())
        self.assertNotEqual(durable["state"], "ack_written")
        self.assertEqual(durable["request"]["operationId"], "op")

    async def test_both_http_waits_release_mutex_gate_arrivals_and_allow_prompt_cancel(
        self,
    ):
        for action in ("active_snapshot", "active_installed"):
            with (
                self.subTest(action=action),
                tempfile.TemporaryDirectory() as directory,
            ):
                r = self.runner(directory)
                method, params = await self.stage(r, action)
                entered, release = asyncio.Event(), asyncio.Event()
                original = r.request

                async def request(name, *args, **kwargs):
                    if name == action:
                        entered.set()
                        await release.wait()
                    return await original(name, *args, **kwargs)

                r.request = request
                task = asyncio.create_task(r.tool(method, params))
                try:
                    await asyncio.wait_for(entered.wait(), 2)
                    await self.assert_gate_without_mutex(r)
                    # Complete close/interrupt while HTTP is STILL suspended.
                    await asyncio.wait_for(r.cancel(), 0.5)
                    self.assertIn("close", r.calls)
                    self.assertIn("turn/interrupt", r.calls)
                    self.assertFalse(task.done())
                finally:
                    release.set()
                    await asyncio.gather(task, return_exceptions=True)
                with self.assertRaises(RuntimeError):
                    task.result()
                self.assertEqual(r.automatic.pending["state"], "held")
                self.assertNotIn("hostReceipt", r.automatic.pending)
                self.assertTrue(AutomaticContextRefill(r).held)

    async def test_reentry_rejects_changed_owner_epoch_material_phase_or_append(self):
        for action in ("active_snapshot", "active_installed"):
            for change in (
                "agent",
                "context",
                "thread",
                "turn",
                "permit",
                "material",
                "epoch",
                "phase",
                "append",
            ):
                with (
                    self.subTest(action=action, change=change),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    r = self.runner(directory)
                    method, params = await self.stage(r, action)
                    entered, release = asyncio.Event(), asyncio.Event()
                    original = r.request

                    async def request(name, *args, **kwargs):
                        if name == action:
                            entered.set()
                            await release.wait()
                        return await original(name, *args, **kwargs)

                    r.request = request
                    task = asyncio.create_task(r.tool(method, params))
                    try:
                        await asyncio.wait_for(entered.wait(), 2)
                        await self.assert_gate_without_mutex(r)
                        if change == "agent":
                            r.config["agentId"] = "different"
                        elif change == "context":
                            r.config["contextIds"]["reader"] = "different"
                        elif change in ("thread", "turn", "permit"):
                            setattr(r, change, "different")
                        elif change == "material":
                            r.material_ids.append("different")
                        elif change == "epoch":
                            r.rpc.process = object()
                        elif change == "phase":
                            r.automatic.pending["state"] = "unexpected_phase"
                        else:
                            r.inbox.uncertain = True
                    finally:
                        release.set()
                        await asyncio.gather(task, return_exceptions=True)
                    with self.assertRaises(RuntimeError):
                        task.result()
                    self.assertEqual(r.automatic.pending["state"], "held")
                    self.assertNotIn("hostReceipt", r.automatic.pending)

    async def test_thread_read_waits_do_not_own_mutex(self):
        for action in ("active_snapshot", "active_installed"):
            with (
                self.subTest(action=action),
                tempfile.TemporaryDirectory() as directory,
            ):
                r = self.runner(directory)
                method, params = await self.stage(r, action)
                entered, release = asyncio.Event(), asyncio.Event()
                original = r.rpc.call

                async def rpc(name, value, **kwargs):
                    if name == "thread/read":
                        entered.set()
                        await release.wait()
                    return await original(name, value, **kwargs)

                r.rpc.call = rpc
                task = asyncio.create_task(r.tool(method, params))
                try:
                    await asyncio.wait_for(entered.wait(), 2)
                    await self.assert_gate_without_mutex(r)
                    await asyncio.wait_for(r.cancel(), 0.5)
                finally:
                    release.set()
                    await asyncio.gather(task, return_exceptions=True)
                with self.assertRaises(RuntimeError):
                    task.result()
                self.assertTrue(r.automatic.held)

    async def test_provenance_scans_leave_loop_and_mutex_available(self):
        from lax_connector import automatic_context_refill as module

        for action, name in (
            ("active_snapshot", "capture"),
            ("active_installed", "verify"),
        ):
            with (
                self.subTest(action=action),
                tempfile.TemporaryDirectory() as directory,
            ):
                r = self.runner(directory)
                method, params = await self.stage(r, action)
                entered, release = asyncio.Event(), threading.Event()
                original = getattr(module, name)
                loop = asyncio.get_running_loop()

                def observe(*args):
                    loop.call_soon_threadsafe(entered.set)
                    if not release.wait(5):
                        raise RuntimeError("Test observation was not released")
                    return original(*args)

                with patch.object(module, name, observe):
                    task = asyncio.create_task(r.tool(method, params))
                    try:
                        await asyncio.wait_for(entered.wait(), 2)
                        await self.assert_gate_without_mutex(r)
                        await asyncio.wait_for(r.cancel(), 0.5)
                        self.assertFalse(task.done())
                    finally:
                        release.set()
                        await asyncio.gather(task, return_exceptions=True)
                with self.assertRaises(RuntimeError):
                    task.result()
                self.assertTrue(r.automatic.held)

    async def test_installed_arrival_before_prepare_submission_waits_for_original_outcome(
        self,
    ):
        for written in (True, False):
            with (
                self.subTest(written=written),
                tempfile.TemporaryDirectory() as directory,
            ):
                r = self.runner(directory)
                p = self.params()
                response = await r.tool(PREPARE, p)
                installed = self.install_native(r, response)
                task = asyncio.create_task(r.tool(INSTALL, installed))
                try:
                    await asyncio.sleep(0)
                    self.assertTrue(r.automatic.install_started)
                    self.assertFalse(task.done())
                    self.assertEqual(r.automatic.pending["state"], "response_prepared")
                    self.assertEqual(r.calls, ["thread/read", "active_snapshot"])
                    await self.assert_gate_without_mutex(r)
                    await r.automatic.submitted(PREPARE, p, written)
                    result = await asyncio.gather(task, return_exceptions=True)
                finally:
                    if not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                if written:
                    self.assertEqual(
                        result, [{"operationId": "op", "status": "recorded"}]
                    )
                    self.assertEqual(r.automatic.pending["state"], "host_ack_recorded")
                    self.assertTrue(r.automatic.blocked)
                    await r.automatic.submitted(INSTALL, installed, True)
                    self.assertFalse(r.automatic.blocked)
                else:
                    self.assertIsInstance(result[0], RuntimeError)
                    self.assertEqual(r.calls, ["thread/read", "active_snapshot"])
                    self.assertTrue(AutomaticContextRefill(r).held)

    async def test_cancellation_wakes_installed_waiting_for_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            r = self.runner(directory)
            response = await r.tool(PREPARE, self.params())
            task = asyncio.create_task(
                r.tool(INSTALL, self.install_native(r, response))
            )
            await asyncio.sleep(0)
            await asyncio.wait_for(r.cancel(), 0.5)
            with self.assertRaises(RuntimeError):
                await asyncio.wait_for(task, 0.5)
            self.assertNotIn("active_installed", r.calls)
            self.assertTrue(r.automatic.held)

    async def test_disabled_policy_does_not_enable_automatic_callbacks(self):
        with tempfile.TemporaryDirectory() as directory:
            r = self.runner(directory)
            del r.config["automaticContextRefill"]
            self.assertIsNone(r.automatic.policy())
            with self.assertRaises(RuntimeError):
                await r.tool(PREPARE, self.params())
            self.assertEqual(r.calls, [])


if __name__ == "__main__":
    unittest.main()
