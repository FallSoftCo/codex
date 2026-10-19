"""Substrate regression checks; RPC is stubbed, no model/native-fault claim."""
import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from lax_connector.reader_inbox import ReaderInbox

INPUT = "4018c4c1-9be6-4879-bb6b-2c2ba4812920"
SNAPSHOT = {"schema": "lax-reader-input/v1", "nativeThread": "test-thread",
    "inputIds": [INPUT], "chunks": [{"reference": INPUT, "revision": 1,
        "offset": 0, "content": '{"event":{"body":"Canonical input"}}',
        "nextOffset": None}]}


class QueueOnlyRpc:
    """Model the inspected API's acknowledgement before history retention."""
    def __init__(self, history, *, lose_reply=False):
        self.history = history
        self.lose_reply = lose_reply
        self.injects = []

    async def call(self, method, payload):
        if method == "thread/read":
            return {"thread": {"path": str(self.history)}}
        assert method == "thread/inject_items"
        self.injects.append(copy.deepcopy(payload))
        if self.lose_reply:
            self.lose_reply = False
            raise TimeoutError("Accepted into volatile queue, reply lost")
        return {}


def runner(path, rpc, actions):
    async def request(action, value=None, **kwargs):
        actions.append(action)
        assert action == "inbox", "Rebuilding input must not replay semantic work"
        assert value == {"materialIds": [INPUT]}
        return copy.deepcopy(SNAPSHOT)
    return SimpleNamespace(state=path, thread="test-thread", turn=None,
        active=False, accepting=False, rpc=rpc, request=request,
        trace=lambda *args: None)


async def acknowledged_but_unretained():
    with tempfile.TemporaryDirectory() as name:
        path = Path(name);history = path/"native.jsonl";history.write_text("")
        actions=[];rpc=QueueOnlyRpc(history)
        first=ReaderInbox(runner(path,rpc,actions))
        await first.append([{"id":INPUT,"revision":1}])
        # Fresh process/reader inference with the same still-pending canonical input.
        second=ReaderInbox(runner(path,rpc,actions));await second.recover()
        await second.append([{"id":INPUT,"revision":1}])
        assert len(rpc.injects)==2, "Old queue acknowledgement suppressed missing canonical content"
        assert actions==["inbox","inbox"]


async def uncertain_append_receipt_preserved():
    with tempfile.TemporaryDirectory() as name:
        path=Path(name);history=path/"native.jsonl";history.write_text("")
        actions=[];rpc=QueueOnlyRpc(history,lose_reply=True)
        first=ReaderInbox(runner(path,rpc,actions))
        try:await first.append([{"id":INPUT,"revision":1}])
        except TimeoutError:pass
        else:raise AssertionError("Fault did not run")
        original=next((path/"input-delivery").glob("*.json"))
        original_bytes=original.read_bytes()
        assert json.loads(original_bytes)["state"]=="intent"
        second=ReaderInbox(runner(path,rpc,actions));await second.recover()
        await second.append([{"id":INPUT,"revision":1}])
        assert original.read_bytes()==original_bytes, "Unknown receipt was rewritten as success"
        assert len(rpc.injects)==2
        operations=[json.loads(p.read_text()).get("operation")
                    for p in (path/"input-delivery").glob("*.json")
                    if json.loads(p.read_text()).get("operation")]
        assert len(set(operations))==2, "Reconstruction replayed the original transport operation"
        assert actions==["inbox","inbox"]


def test_acknowledged_but_unretained():
    asyncio.run(acknowledged_but_unretained())


def test_uncertain_append_receipt_preserved():
    asyncio.run(uncertain_append_receipt_preserved())


class ReaderInputRecoveryTests(unittest.TestCase):
    test_acknowledged_but_unretained = staticmethod(test_acknowledged_but_unretained)
    test_uncertain_append_receipt_preserved = staticmethod(test_uncertain_append_receipt_preserved)


if __name__ == "__main__":
    unittest.main()
