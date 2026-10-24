"""Deterministic native-observation/transport fixtures; no model evidence."""
import hashlib
import json
import tempfile
import unittest
from types import MethodType

import test_automatic_context_refill as fixture
from lax_connector.automatic_context_refill import AutomaticContextRefill
from lax_connector.automatic_refill_history import capture
from lax_connector.automatic_refill_recovery import startup
from lax_connector.automatic_refill_terminal import history_before_snapshot
from lax_connector.context_runtime import ContextRunner


class TerminalBeforeSnapshotTests(unittest.IsolatedAsyncioTestCase):
    def stage(self, directory):
        helper = fixture.AutomaticRefillTests()
        helper.addCleanup = self.addCleanup
        r = helper.runner(directory)
        r.purpose = "writer"
        r.config["contextIds"] = {"writer": "context"}
        r.active = r.accepting = False
        r.inbox = None
        owner = {"agentId": "agent", "contextId": "context", "purpose": "writer",
                 "threadId": "thread", "turnId": "turn", "permitId": "permit",
                 "materialIds": ["work"]}
        params = helper.params()
        params.pop("_rpcRequestId")
        params["purpose"] = "writer"
        original = {"state": "held", "owner": owner, "request": params,
                    "originalHistory": capture(
                        {"id": "thread", "path": str(r.native), "ephemeral": False}, "thread"),
                    "holdReason": "HttpFailure"}
        path = r.automatic.root / (hashlib.sha256(b"op").hexdigest() + ".json")
        path.write_text(json.dumps(original))
        expected = {key: owner[key] for key in ("contextId", "permitId", "materialIds")}
        expected.update({key: params[key] for key in (
            "operationId", "windowId", "historyVersion", "reason", "phase")})
        rejection_path = r.state / ("operation-" + hashlib.sha256(b"op").hexdigest() + ".json")
        rejection_path.write_text(json.dumps({"state": "rejected", "status": 409,
            "request": {"operationId": "op", "action": "active_snapshot",
                        "nativeThread": "thread", "nativeTurn": "turn", "value": expected}}))
        r.automatic = AutomaticContextRefill(r)
        r.request = MethodType(ContextRunner.request, r)
        calls, receipts = [], {}
        r.observed_status = "completed"

        async def rpc(method, value, **kwargs):
            self.assertEqual(method, "thread/turns/list")
            return {"data": [{"id": "turn", "status": r.observed_status}], "nextCursor": None}

        async def http(purpose, method, path, payload=None):
            self.assertEqual(purpose, "writer")
            calls.append((method, payload))
            if method == "POST":
                self.assertEqual(payload["action"], "active_terminal")
                result = {"schema": "lax-active-context-terminal-uninstalled/v1",
                          "status": "terminal_uninstalled", "agentId": "agent",
                          "purpose": "writer", "nativeThread": "thread",
                          "nativeTurn": "turn", "newExecutionAdmitted": False,
                          **payload["value"]}
                receipts[payload["operationId"]] = result
                return result
            return receipts[path.rsplit("/", 1)[1]]

        r.rpc.call = rpc
        r.agent.http = http
        return r, path, rejection_path, original, calls

    async def test_original_rejected_cut_reconciles_without_reset_replay_or_journal_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            r, path, rejected, original, calls = self.stage(directory)
            before = (path.read_bytes(), rejected.read_bytes(), r.native.read_bytes())
            await startup(r.automatic)
            self.assertFalse(r.failed)
            self.assertFalse(r.automatic.held)
            await startup(r.automatic)
            self.assertEqual(sum(method == "POST" for method, _ in calls), 1)
            self.assertEqual((path.read_bytes(), rejected.read_bytes(), r.native.read_bytes()), before)

    async def test_unknown_or_active_native_turn_cannot_release_the_hold(self):
        for status in ("inProgress", "unknown"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                r, path, _, _, calls = self.stage(directory)
                r.observed_status = status
                await startup(r.automatic)
                self.assertTrue(r.automatic.held)
                self.assertTrue(r.failed)
                self.assertEqual(calls, [])

    async def test_ambiguous_original_request_is_never_repeated_or_declared_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            r, path, rejected, _, calls = self.stage(directory)
            value = json.loads(rejected.read_text())
            value["state"] = "intent"
            rejected.write_text(json.dumps(value))
            before = path.read_bytes()
            await startup(r.automatic)
            self.assertTrue(r.automatic.held)
            self.assertEqual(calls, [])
            self.assertEqual(path.read_bytes(), before)

    async def test_only_typed_native_cut_or_partial_history_blocks_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            r, _, _, original, _ = self.stage(directory)
            base = r.native.read_bytes()
            r.native.write_bytes(base + b'{"type":"response_item","payload":{"text":"context_window_refill_intent"}}\n')
            history_before_snapshot(original["originalHistory"], "op")
            r.native.write_bytes(base + b'{"type":"event_msg","payload":{"type":"context_window_refill_intent","operationId":"later-valid-cut"}}\n{"type":"compacted","payload":{}}\n')
            history_before_snapshot(original["originalHistory"], "op")
            for tail in (
                b'{"type":"event_msg","payload":{"type":"context_window_refill_intent","operationId":"op"}}\n',
                b'{"type":"event_msg"',
            ):
                with self.subTest(tail=tail):
                    r.native.write_bytes(base + tail)
                    with self.assertRaises(RuntimeError):
                        history_before_snapshot(original["originalHistory"], "op")
