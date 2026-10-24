"""Mechanical append/adopt recovery fence checks; no model inference."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from lax_connector.reader_inbox import ReaderInbox


class InboxFenceTests(unittest.IsolatedAsyncioTestCase):
    def runner(self, root, enabled=True):
        async def request(*args, **kwargs):
            return {"materialIds": ["input"], "deliveredRevisions": {"input": 1}}

        path = root / "native.jsonl"
        path.write_text("{}\n")

        async def call(*args):
            return {"thread": {"path": str(path)}}

        return SimpleNamespace(
            state=root,
            thread="thread",
            turn="turn",
            request=request,
            rpc=SimpleNamespace(call=call),
            material_ids=["input"],
            automatic=SimpleNamespace(
                policy=lambda: {"type": "canonical"} if enabled else None
            ),
            failed=False,
            trace=lambda *_: None,
        )

    async def test_adopted_batch_is_durable_and_not_unknown_on_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = self.runner(root)
            inbox = ReaderInbox(runner)
            batch = {
                "operation": "op",
                "snapshot": {"inputIds": ["input"]},
                "state": "accepted",
                "items": [],
            }
            inbox.uncertain = True
            await inbox.adopt(batch)
            self.assertFalse(inbox.uncertain)
            path = inbox.directory / (hashlib.sha256(b"op").hexdigest() + ".json")
            self.assertEqual(json.loads(path.read_text())["state"], "adopted")
            recovered = ReaderInbox(runner)
            await recovered.recover()
            self.assertFalse(runner.failed)
            self.assertFalse(recovered.uncertain)

    async def test_unknown_append_is_observed_not_replayed_and_holds_only_optin(self):
        for enabled in (False, True):
            with (
                self.subTest(enabled=enabled),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                runner = self.runner(root, enabled)
                inbox = ReaderInbox(runner)
                (inbox.directory / "old.json").write_text(
                    json.dumps(
                        {"operation": "original", "state": "accepted", "items": []}
                    )
                )
                await inbox.recover()
                self.assertTrue(inbox.uncertain)
                self.assertEqual(runner.failed, enabled)
                self.assertEqual(
                    json.loads((inbox.directory / "old.json").read_text())["state"],
                    "accepted",
                )
