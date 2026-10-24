"""Legacy accepted inbox recovery; actual model/HTTP proof is recorded separately."""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from lax_connector.reader_inbox import ReaderInbox
from test_reader_input_recovery import INPUT, SNAPSHOT, QueueOnlyRpc, runner


class LegacyReaderReceiptRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def fixture(
        self,
        directory,
        *,
        nested=False,
        wrong_receipt=False,
        denied=False,
        prior_hold=False,
        missing_request=False,
    ):
        root = Path(directory)
        history = root / "native.jsonl"
        history.write_text("")
        actions = []
        rpc = QueueOnlyRpc(history)
        r = runner(root, rpc, actions)
        original = await ReaderInbox(r).append([{"id": INPUT, "revision": 1}])
        batch = (
            root
            / "input-delivery"
            / (hashlib.sha256(original["operation"].encode()).hexdigest() + ".json")
        )
        original_bytes = batch.read_bytes()
        item = original["items"][0]
        row = (
            {"type": "event_msg", "payload": {"description": item}}
            if nested
            else {"type": "response_item", "payload": item}
        )
        history.write_text(json.dumps(row) + "\n")
        adoption = "reader-adopt:original-turn:" + original["operation"]
        if not missing_request:
            request = {
                "operationId": adoption,
                "action": "inbox_adopt",
                "nativeThread": "test-thread",
                "nativeTurn": "original-turn",
                "value": {"snapshotOperationId": original["operation"]},
            }
            (
                root
                / (
                    "operation-"
                    + hashlib.sha256(adoption.encode()).hexdigest()
                    + ".json"
                )
            ).write_text(json.dumps({"request": request, "state": "intent"}))
        calls = []

        async def http(purpose, method, path):
            calls.append((purpose, method, path))
            self.assertEqual((purpose, method), ("reader", "GET"))
            if denied:
                raise PermissionError("Original receipt unavailable")
            if path.endswith("/" + adoption):
                return {
                    "nativeTurn": "another-turn" if wrong_receipt else "original-turn",
                    "snapshotOperationId": original["operation"],
                    "materialIds": [INPUT],
                    "deliveredRevisions": {INPUT: 1},
                    "interpretationInferred": False,
                }
            self.assertTrue(path.endswith("/" + original["operation"]))
            return copy.deepcopy(SNAPSHOT)

        r.config = {"agentId": "test-agent"}
        r.agent = SimpleNamespace(http=http)
        r.automatic = SimpleNamespace(policy=lambda: {"type": "canonical"})
        r.failed = prior_hold
        recovery = ReaderInbox(r)
        await recovery.recover()
        self.assertEqual(batch.read_bytes(), original_bytes)
        self.assertEqual(len(rpc.injects), 1, "Recovery re-appended original input")
        self.assertEqual(actions, ["inbox"], "Recovery replayed a canonical mutation")
        return r, recovery, calls

    async def test_original_receipts_resolve_legacy_acceptance_without_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            r, inbox, calls = await self.fixture(directory)
            self.assertFalse(r.failed)
            self.assertFalse(inbox.uncertain)
            self.assertEqual(len(calls), 2)
            self.assertEqual(
                inbox.delivered, {}, "Historical delivery became a current cursor"
            )

    async def test_wrong_or_unavailable_original_receipt_remains_held(self):
        for failure in ("wrong_receipt", "denied", "missing_request"):
            with (
                self.subTest(failure=failure),
                tempfile.TemporaryDirectory() as directory,
            ):
                r, inbox, _ = await self.fixture(directory, **{failure: True})
                self.assertTrue(r.failed)
                self.assertTrue(inbox.uncertain)
                self.assertIn(
                    "Original reader inbox reconciliation unresolved", r.failure_reason
                )

    async def test_nested_description_is_not_a_retained_native_output(self):
        with tempfile.TemporaryDirectory() as directory:
            r, inbox, calls = await self.fixture(directory, nested=True)
            self.assertTrue(r.failed)
            self.assertTrue(inbox.uncertain)
            self.assertEqual(calls, [])

    async def test_known_adoption_cannot_clear_an_unrelated_native_hold(self):
        with tempfile.TemporaryDirectory() as directory:
            r, inbox, calls = await self.fixture(directory, prior_hold=True)
            self.assertTrue(r.failed)
            self.assertFalse(inbox.uncertain)
            self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
