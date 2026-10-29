"""Adapter control/JSONL tests with explicitly simulated native RPC replies.

These prove admission and persistence branches, not native collection or model
behavior. The real native old-format/RPC journey is a separate qualification.
"""
import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from lax_connector.automatic_context_refill import AutomaticContextRefill
from lax_connector.native_context_acquisition import NativeContextAcquisition


class NativeAcquisitionTests(unittest.IsolatedAsyncioTestCase):
    def runner(self, root, *, lost_reply=False, wrong_append=False):
        r = SimpleNamespace(
            state=Path(root), purpose="writer", thread="native-thread",
            active=False, accepting=False, closing=False, failed=False,
            config={"agentId": "agent", "contextIds": {"writer": "context"}},
            effect_lock=asyncio.Lock(), trace=lambda *args: None,
            agent=SimpleNamespace(stop=asyncio.Event(),
                                  acquire_context_operation="capture-1"))
        r.history = Path(root) / "original.jsonl"
        r.history.write_text('{"type":"session_meta","payload":{}}\n')
        r.calls = []
        r.native_receipt = None
        cut = {"threadId": r.thread, "contextId": "context", "purpose": "writer",
               "windowId": "original-window", "historyVersion": 4,
               "idle": True, "activeTurnId": None, "heldOperationId": None,
               "lastStartedTurnId": "original-turn", "producerSha256": None}

        async def rpc(method, params, **kwargs):
            r.calls.append(method)
            if method == "thread/read":
                return {"thread": {"id": r.thread, "path": str(r.history), "ephemeral": False}}
            if method == "thread/contextWindow/read":
                return {"state": copy.deepcopy(cut)}
            if method == "thread/contextWindow/readAcquisition":
                self.assertEqual(params["operationId"], "capture-1")
                if r.native_receipt is None:
                    raise RuntimeError("Original native acquisition unavailable")
                return {"state": copy.deepcopy(cut), "receipt": copy.deepcopy(r.native_receipt)}
            self.assertEqual(method, "thread/contextWindow/acquireIdle")
            self.assertEqual(params, {"threadId": r.thread, "state": cut, "operationId": "capture-1"})
            self.assertTrue(r.automatic.acquisition.blocked)
            journal = next(r.automatic.acquisition.root.glob("*.json"))
            self.assertEqual(json.loads(journal.read_text())["state"], "dispatch_intent")
            reference = {"turn_id": "original-turn"}
            world = {"tools": ["read", "write"]}
            source = {"schema": "lax-native-context-producer/v1",
                      "thread_id": r.thread, "context_id": "context",
                      "reference": reference, "acquired_step": reference,
                      "template": {"snapshot": world},
                      "acquisition": {"operation_id": "capture-1", "state": copy.deepcopy(cut)}}
            rows = [
                {"type": "response_item", "payload": {"type": "message"}},
                {"type": "turn_context", "payload": reference},
                {"type": "world_state", "payload": {
                    "full": True, "state": world,
                    "native_context_producer": {"source": source, "sha256": __import__("hashlib").sha256(
                        json.dumps(source, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}}}]
            r.native_receipt = {"operationId": "capture-1", "sourceState": copy.deepcopy(cut),
                                "producerSha256": rows[-1]["payload"]["native_context_producer"]["sha256"]}
            if wrong_append:
                rows.insert(0, {"type": "event_msg", "payload": {"type": "task_started"}})
            with r.history.open("a") as stream:
                for row in rows:
                    stream.write(json.dumps(row) + "\n")
            cut["producerSha256"] = r.native_receipt["producerSha256"]
            if lost_reply:
                raise TimeoutError("Explicitly simulated lost reply after append")
            return {"state": copy.deepcopy(cut)}

        r.rpc = SimpleNamespace(call=rpc, binary=str(Path(root) / "missing-binary"),
                                home=Path(root))
        r.automatic = AutomaticContextRefill(r)
        r.cut = cut
        return r

    async def test_explicit_capture_keeps_identity_and_second_call_is_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            r = self.runner(directory)
            result = await r.automatic.acquisition.run("capture-1")
            self.assertEqual(result["state"], "confirmed")
            self.assertEqual(result["after"]["windowId"], "original-window")
            self.assertIsNone(result["before"]["producerSha256"])
            self.assertEqual(result["after"]["historyVersion"], result["before"]["historyVersion"])
            self.assertEqual(result["after"]["producerSha256"],
                             result["nativeObservation"]["producerSha256"])
            self.assertFalse(r.automatic.blocked)
            calls = list(r.calls)
            self.assertEqual(await r.automatic.acquisition.run("capture-1"), result)
            self.assertEqual(r.calls, calls)

    async def test_lost_reply_cold_observation_releases_only_original_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            r = self.runner(directory, lost_reply=True)
            with self.assertRaises(TimeoutError):
                await r.automatic.acquisition.run("capture-1")
            r.automatic = AutomaticContextRefill(r)
            self.assertTrue(r.automatic.blocked)
            r.cut["historyVersion"] = 1  # Reconstructed process-local counter.
            result = await r.automatic.acquisition.run("capture-1")
            self.assertEqual(result["state"], "confirmed")
            self.assertEqual(result["nativeObservation"]["sourceState"]["historyVersion"], 4)
            self.assertEqual(result["after"]["historyVersion"], 1)
            self.assertEqual(r.calls.count("thread/contextWindow/acquireIdle"), 1)
            self.assertFalse(r.automatic.blocked)

    async def test_missing_original_native_receipt_keeps_hold_without_recollection(self):
        with tempfile.TemporaryDirectory() as directory:
            r = self.runner(directory, lost_reply=True)
            with self.assertRaises(TimeoutError):
                await r.automatic.acquisition.run("capture-1")
            path = next(r.automatic.acquisition.root.glob("*.json"))
            original = path.read_bytes()
            r.native_receipt = None
            r.automatic = AutomaticContextRefill(r)
            with self.assertRaisesRegex(RuntimeError, "acquisition unavailable"):
                await r.automatic.acquisition.run("capture-1")
            self.assertEqual(path.read_bytes(), original)
            r.agent.acquire_context_operation = "capture-2"
            with self.assertRaisesRegex(RuntimeError, "another active or unresolved"):
                await r.automatic.acquisition.run("capture-2")
            self.assertEqual(r.calls.count("thread/contextWindow/acquireIdle"), 1)
            self.assertTrue(r.automatic.blocked)

    async def test_other_hold_and_wrong_role_do_not_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            r = self.runner(directory)
            r.failed = True
            with self.assertRaises(RuntimeError):
                await r.automatic.acquisition.run("capture-1")
            self.assertEqual(r.calls, [])
            r.failed = False
            r.purpose = "reader"
            with self.assertRaises(RuntimeError):
                await r.automatic.acquisition.run("capture-1")
            self.assertEqual(r.calls, [])

    async def test_append_with_extra_task_stays_held(self):
        with tempfile.TemporaryDirectory() as directory:
            r = self.runner(directory, wrong_append=True)
            with self.assertRaisesRegex(RuntimeError, "task, effect or replacement"):
                await r.automatic.acquisition.run("capture-1")
            self.assertTrue(r.automatic.blocked)
            self.assertEqual(r.calls.count("thread/contextWindow/acquireIdle"), 1)


    async def test_queued_legacy_rebuild_reuses_accepted_snapshot_after_explicit_capture(self):
        from unittest.mock import patch
        from lax_connector.automatic_refill_history import capture
        from lax_connector.errors import HttpFailure
        from lax_connector.idle_context_rejection import inspect_rejected
        from lax_connector.idle_context_rebuild import SCHEMA
        from lax_connector.native_context_acquisition import PRODUCER_REFUSAL
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            r = self.runner(directory)
            r.config["nativeActionRetention"] = 1
            r.retained_context_contract = True
            r.agent.rebuild_only = True
            cut = (await r.rpc.call("thread/contextWindow/read", {}))["state"]
            request_id = "original-queued-rebuild"
            key = hashlib.sha256(("context:" + request_id).encode()).hexdigest()
            op_id = "context-refill-native:" + key
            snapshot_id = "context-refill-snapshot:" + key
            content = json.dumps({"agentId": "agent", "contextId": "context",
                                  "purpose": "writer", "nativeThread": r.thread})
            snapshot = {"chunks": [{"offset": 0, "content": content}],
                        "sha256": hashlib.sha256(content.encode()).hexdigest(),
                        "totalBytes": len(content.encode())}
            original = capture({"id": r.thread, "path": str(r.history),
                                "ephemeral": False}, r.thread)
            operation = {"schema": SCHEMA, "nativeContextMode": "idle_request",
                         "operationId": op_id, "requestOperationId": request_id,
                         "snapshotOperationId": snapshot_id,
                         "installedOperationId": "context-refill-installed:" + key,
                         "nativeThread": r.thread, "agentId": "agent",
                         "contextId": "context", "purpose": "writer",
                         "state": "held", "holdReason": PRODUCER_REFUSAL,
                         "snapshot": snapshot, "originalHistory": original,
                         "nativeState": cut, "request": {
                             **{k: cut[k] for k in ("threadId", "contextId", "purpose",
                                                   "windowId", "historyVersion")},
                             "operationId": op_id, "turnId": "original-turn",
                             "reason": "explicitRequest", "phase": "postTurn"}}
            path = r.automatic.idle.path(op_id)
            path.parent.mkdir()
            path.write_text(json.dumps(operation))
            original_journal = path.read_bytes()
            local = r.state / ("operation-" + hashlib.sha256(snapshot_id.encode()).hexdigest() + ".json")
            local.write_text(json.dumps({"state": "accepted", "receipt": snapshot,
                "request": {"operationId": snapshot_id, "action": "rebuild_snapshot",
                            "nativeThread": r.thread, "nativeTurn": "original-turn",
                            "value": {"materialIds": ["original-work"]}}}))
            metadata_calls = []

            async def http(purpose, method, route):
                metadata_calls.append((method, route))
                self.assertEqual(method, "GET")
                if route.endswith(snapshot_id):
                    return copy.deepcopy(snapshot)
                self.assertTrue(route.endswith(operation["installedOperationId"]))
                raise HttpFailure(404, "known absent", code="CONTEXT_OPERATION_NOT_FOUND")

            async def request(action, *args, **kwargs):
                metadata_calls.append(("context", action))
                self.assertEqual(action, "pending")  # No second snapshot request.
                return {"contextRebuild": {"requestedOperationId": request_id}}

            raw_rpc = r.rpc.call

            async def rpc(method, params, **kwargs):
                if method == "thread/turns/list":
                    return {"data": [{"id": "original-turn", "status": "completed"}],
                            "nextCursor": None}
                if method == "thread/contextWindow/preflight":
                    return {"preflight": {"state": params["state"], "operationId": op_id}}
                return await raw_rpc(method, params, **kwargs)

            r.rpc.call, r.agent.http, r.request = rpc, http, request
            await r.automatic.idle.startup()
            self.assertFalse(r.automatic.idle.held)
            self.assertTrue(r.automatic.idle.retryable[op_id])
            prior = await inspect_rejected(r.automatic.idle, path)
            self.assertEqual(prior["snapshot"], snapshot)
            self.assertEqual(path.read_bytes(), original_journal)
            await r.automatic.acquisition.run("capture-1")

            async def frame(runner, accepted, native_request, actions):
                self.assertEqual(accepted, snapshot)
                self.assertEqual(native_request["historyVersion"], cut["historyVersion"])
                return {"operationId": op_id}, {}

            with patch("lax_connector.context_action_memory.index", return_value=[]), \
                 patch("lax_connector.idle_context_rebuild.frame", new=frame):
                prepared = await r.automatic.idle._prepare(request_id, [], reviewed=False)
            self.assertEqual(prepared["state"], "snapshot_prepared")
            self.assertEqual(prepared["snapshot"], snapshot)
            self.assertEqual(prepared["preflight"]["state"]["historyVersion"], 4)
            self.assertEqual(prepared["preflight"]["state"]["producerSha256"],
                             r.native_receipt["producerSha256"])
            self.assertFalse(any(action == "rebuild_snapshot" for _, action in metadata_calls))
            self.assertEqual(r.calls.count("thread/contextWindow/acquireIdle"), 1)
            self.assertNotIn("thread/contextWindow/replaceIdle", r.calls)
            self.assertTrue(any((path.parent / "rejected-preparation").glob("*.json")))



if __name__ == "__main__":
    unittest.main()
