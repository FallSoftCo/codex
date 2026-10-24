"""Original receipt recovery fixtures only; actual native/model proof is separate."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
import test_automatic_context_refill as fixture
from lax_connector.automatic_context_refill import AutomaticContextRefill, PREPARE
from lax_connector.automatic_refill_recovery import RECONCILE, startup
from lax_connector.automatic_refill_data import CUT


class OriginalReceiptRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def stage(self, directory, *, missing_callback=False):
        helper = fixture.AutomaticRefillTests()
        helper.addCleanup = self.addCleanup
        r = helper.runner(directory)
        p = helper.params()
        response = await r.tool(PREPARE, p)
        await r.automatic.submitted(PREPARE, p, True)
        raw = helper.install_native(r, response)
        installed = {k: v for k, v in raw.items() if k != "_rpcRequestId"}
        if not missing_callback:
            r.automatic.save("host_ack_intent", installed=installed)
        else:
            r.automatic.save("response_written")
        owner = r.automatic.pending["owner"]
        receipt = {
            **{
                k: installed[k]
                for k in CUT
                | {
                    "previousWindowId",
                    "windowId",
                    "nativeHistoryBytes",
                    "nativeHistorySha256",
                }
            },
            "schema": "lax-active-context-installed/v1",
            "operationId": "op",
            "requestOperationId": "op",
            "installedOperationId": "active-installed:"
            + __import__("hashlib").sha256(b"op").hexdigest(),
            "status": "recorded",
            "historyVersion": 1,
            "binding": {
                "agentId": owner["agentId"],
                "contextId": owner["contextId"],
                "purpose": owner["purpose"],
                "nativeThread": owner["threadId"],
                "nativeTurn": owner["turnId"],
                "permitId": owner["permitId"],
                "materialIds": owner["materialIds"],
            },
        }
        calls = []

        async def http(purpose, method, path):
            self.assertEqual((purpose, method), ("reader", "GET"))
            calls.append(path)
            return receipt

        r.agent.http = http
        original = r.automatic.path.read_bytes()
        r.automatic.timer.cancel()
        r.automatic = AutomaticContextRefill(r)
        return r, raw, receipt, calls, original

    async def test_recorded_lost_ack_uses_original_get_without_rewriting_or_post(self):
        with tempfile.TemporaryDirectory() as directory:
            r, raw, receipt, calls, original = await self.stage(directory)
            before = list(r.calls)
            await startup(r.automatic)
            self.assertFalse(r.automatic.held)
            self.assertFalse(r.failed)
            self.assertEqual(len(calls), 1)
            self.assertEqual(
                await r.tool(RECONCILE, raw),
                {"operationId": "op", "status": "recorded"},
            )
            await r.automatic.submitted(RECONCILE, raw, True)
            self.assertEqual(r.calls, before)
            self.assertEqual(len(calls), 2)
            self.assertEqual(
                next(r.automatic.root.glob("*.json")).read_bytes(), original
            )
            self.assertFalse(r.automatic.blocked)

    async def test_lost_installed_callback_is_found_only_in_typed_original_native_history(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            r, raw, _, calls, original = await self.stage(
                directory, missing_callback=True
            )
            await startup(r.automatic)
            self.assertFalse(r.automatic.held)
            self.assertEqual(len(calls), 1)
            self.assertEqual(
                next(r.automatic.root.glob("*.json")).read_bytes(), original
            )

    async def test_wrong_or_unavailable_host_receipt_stays_held_without_replay(self):
        for denied in (False, True):
            with (
                self.subTest(denied=denied),
                tempfile.TemporaryDirectory() as directory,
            ):
                r, raw, receipt, calls, original = await self.stage(directory)
                if denied:

                    async def unknown(*args):
                        raise RuntimeError("Original receipt unavailable")

                    r.agent.http = unknown
                else:
                    receipt["nativeHistorySha256"] = "0" * 64
                before = list(r.calls)
                await startup(r.automatic)
                self.assertTrue(r.automatic.held)
                self.assertTrue(r.failed)
                self.assertIn("unconfirmed", r.failure_reason)
                self.assertEqual(r.calls, before)
                self.assertEqual(
                    next(r.automatic.root.glob("*.json")).read_bytes(), original
                )

    async def test_known_receipt_never_clears_unrelated_hold_or_accepts_wrong_purpose(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            r, raw, _, calls, _ = await self.stage(directory)
            r.failed = True
            await startup(r.automatic)
            self.assertFalse(r.automatic.held)
            self.assertTrue(r.failed)
            before = len(calls)
            with self.assertRaises(RuntimeError):
                await r.tool(RECONCILE, {**raw, "purpose": "writer"})
            self.assertEqual(len(calls), before)
            self.assertTrue(r.failed)

    async def test_connection_changed_while_reading_cannot_rebind(self):
        with tempfile.TemporaryDirectory() as directory:
            r, raw, receipt, calls, _ = await self.stage(directory)

            async def changed(*args):
                r.rpc.process = object()
                return receipt

            r.agent.http = changed
            await startup(r.automatic)
            self.assertTrue(r.automatic.held)
            self.assertTrue(r.failed)
