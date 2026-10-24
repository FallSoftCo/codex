"""Pin invariants with a disclosed synthetic read-only native RPC/source boundary."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from lax_connector.context_action_pages import wire
from lax_connector.errors import HttpFailure
from lax_connector.native_action_pins import capture, resolve, MAX_ITEM_BYTES


class NativeActionPinTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state = Path(self.directory.name)
        self.calls = []
        self.denied = False
        self.owner = {k: str(uuid4()) for k in (
            "authorityId", "agentId", "contextId", "hostId", "materialId",
            "sourceRequestId", "deliveryId")}
        self.owner.update(id="execution-original", purpose="writer",
                          nativeThread="original-thread", nativeTurn="original-turn")
        (self.state / "execution-original-turn.json").write_text(
            json.dumps({"executionScopes": [self.owner]}))
        self.item = {"type": "commandExecution", "id": "exec-" + str(uuid4()),
                     "status": "completed", "command": "original; never replay",
                     "aggregatedOutput": "Exact original result: é \\ \"\n", "exitCode": 0}

        async def http(purpose, method, path):
            self.calls.append(("http", method, path))
            self.assertEqual((purpose, method), ("writer", "GET"))
            if self.denied:
                raise HttpFailure(403, "Current source revoked")
            return {"schema": "lax-agent-context/v1", "agentId": self.owner["agentId"],
                    "requestId": self.owner["sourceRequestId"],
                    "briefingReference": {"deliveryId": self.owner["deliveryId"]}}

        async def rpc(method, value):
            self.calls.append(("rpc", method, value))
            self.assertEqual(method, "thread/items/read")
            return {"data": [{"turnId": self.owner["nativeTurn"], "item": copy.deepcopy(self.item)}]}

        self.runner = SimpleNamespace(state=self.state, purpose="writer",
            thread=self.owner["nativeThread"], agent=SimpleNamespace(http=http),
            rpc=SimpleNamespace(call=rpc),
            config={k: self.owner[k] for k in ("authorityId", "agentId", "hostId")})
        self.runner.config["contextIds"] = {"writer": self.owner["contextId"]}

    async def pin(self):
        encoded = wire(self.item)
        return await capture(self.runner, "original-turn", self.item["id"],
                             hashlib.sha256(encoded.encode()).hexdigest())

    async def test_exact_original_survives_new_native_item_and_reopen(self):
        original = wire(self.item)
        descriptor = await self.pin()
        self.item["aggregatedOutput"] = "later reconciliation must stay separate"
        reopened = SimpleNamespace(**vars(self.runner))
        resolved = await resolve(reopened, descriptor)
        self.assertEqual(resolved["payload"], original)
        self.assertEqual(sum(c[:2] == ("rpc", "thread/items/read") for c in self.calls), 1)
        second = await self.pin()
        self.assertNotEqual(second["reference"], descriptor["reference"])
        self.assertEqual((await resolve(reopened, descriptor))["payload"], original)

    async def test_digest_mismatch_and_nonterminal_do_not_publish(self):
        with self.assertRaisesRegex(RuntimeError, "changed"):
            await capture(self.runner, "original-turn", self.item["id"], "0" * 64)
        self.assertFalse((self.state / "native-action-pins").exists())
        self.item["status"] = "inProgress"
        with self.assertRaisesRegex(RuntimeError, "terminal"):
            await self.pin()
        self.assertFalse((self.state / "native-action-pins").exists())

    async def test_exact_item_limit_and_limit_plus_one(self):
        self.item["aggregatedOutput"] = ""
        self.item["aggregatedOutput"] = "x" * (MAX_ITEM_BYTES - len(wire(self.item).encode()))
        descriptor = await self.pin()
        self.assertEqual(descriptor["payloadBytes"], MAX_ITEM_BYTES)
        before = sorted((self.state / "native-action-pins").iterdir())
        self.item["aggregatedOutput"] += "x"
        with self.assertRaisesRegex(ValueError, "budget"):
            await self.pin()
        self.assertEqual(sorted((self.state / "native-action-pins").iterdir()), before)

    async def test_revoked_and_missing_are_explicit_without_rpc_fallback(self):
        descriptor = await self.pin()
        self.denied = True
        self.assertEqual((await resolve(self.runner, descriptor))["reason"],
                         "original_source_not_authorized")
        self.denied = False
        (self.state / "native-action-pins" / (descriptor["pinSha256"] + ".json")).unlink()
        self.assertEqual((await resolve(self.runner, descriptor))["reason"], "original_host_pin_missing")
        self.assertEqual(sum(c[0] == "rpc" for c in self.calls), 1)

    async def test_scope_and_tamper_controls_reject(self):
        descriptor = await self.pin()
        other = {**descriptor, "hostId": str(uuid4())}
        with self.assertRaises(PermissionError):
            await resolve(self.runner, other)
        path = self.state / "native-action-pins" / (descriptor["pinSha256"] + ".json")
        path.write_text("{}")
        with self.assertRaisesRegex(RuntimeError, "integrity"):
            await resolve(self.runner, descriptor)
        with self.assertRaisesRegex(RuntimeError, "immutable"):
            await self.pin()
        self.assertEqual(path.read_text(), "{}")

    async def test_symlink_pin_never_reads_target(self):
        descriptor = await self.pin()
        path = self.state / "native-action-pins" / (descriptor["pinSha256"] + ".json")
        path.unlink()
        target = self.state / "do-not-read"
        target.write_text("private")
        path.symlink_to(target)
        with self.assertRaises(OSError):
            await resolve(self.runner, descriptor)
        self.assertEqual(target.read_text(), "private")


if __name__ == "__main__":
    unittest.main()
