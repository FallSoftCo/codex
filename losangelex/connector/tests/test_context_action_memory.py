"""Effect replay protection during deterministic context reconstruction."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from lax_connector.context_action_memory import index, collect, read


class ActionMemoryTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state = Path(self.directory.name)
        self.runner = SimpleNamespace(
            state=self.state, purpose="writer", thread="original-thread"
        )
        (self.state / "execution-original-turn.json").write_text(
            json.dumps(
                {
                    "executionScopes": [
                        {
                            "agentId": "original-agent",
                            "nativeThread": "original-thread",
                            "nativeTurn": "original-turn",
                            "sourceRequestId": "original-source",
                            "materialId": "original-work",
                            "deliveryId": "original-delivery",
                        }
                    ]
                }
            )
        )
        self.runner.config = {
            "agentId": "original-agent",
            "contextIds": {"writer": "original-context"},
        }
        self.content = {"obligations": [{"source": "original-source"}]}

    def record(self, items):
        with (self.state / "events.jsonl").open("w") as stream:
            for item in items:
                stream.write(
                    json.dumps(
                        {
                            "event": "item/completed",
                            "threadId": "original-thread",
                            "turnId": "original-turn",
                            "item": item,
                        }
                    )
                    + "\n"
                )

    def test_read_flood_does_not_hide_original_execution(self):
        self.record(
            [
                {
                    "type": "dynamicToolCall",
                    "id": str(n),
                    "namespace": None,
                    "tool": "context_material_read",
                    "status": "completed",
                }
                for n in range(1000)
            ]
            + [
                {
                    "type": "commandExecution",
                    "id": "original-command",
                    "status": "completed",
                    "command": "original command; never replay",
                }
            ]
        )
        actions = collect(self.runner, self.content)
        self.assertEqual(
            [(x["itemId"], x["type"], x["status"]) for x in actions],
            [("original-command", "commandExecution", "completed")],
        )

    def test_unsettled_read_is_still_a_hold(self):
        self.record(
            [
                {
                    "type": "dynamicToolCall",
                    "id": "read",
                    "namespace": None,
                    "tool": "context_material_read",
                    "status": "inProgress",
                }
            ]
        )
        with self.assertRaisesRegex(RuntimeError, "not terminal"):
            index(self.runner, self.content)

    def test_unknown_mutation_and_external_name_collision_are_retained(self):
        self.record(
            [
                {
                    "type": "dynamicToolCall",
                    "id": "mutation",
                    "namespace": None,
                    "tool": "retain_context_input",
                    "status": "completed",
                },
                {
                    "type": "dynamicToolCall",
                    "id": "external",
                    "namespace": "external",
                    "tool": "context_material_read",
                    "status": "completed",
                },
                {
                    "type": "mcpToolCall",
                    "id": "mcp",
                    "tool": "context_material_read",
                    "status": "completed",
                },
                {
                    "type": "dynamicToolCall",
                    "id": "unknown",
                    "namespace": None,
                    "tool": "future_tool",
                    "status": "completed",
                },
            ]
        )
        self.assertEqual(
            {x["itemId"] for x in collect(self.runner, self.content)},
            {"mutation", "external", "mcp", "unknown"},
        )

    def test_unknown_callback_receipt_cannot_be_discarded(self):
        tools = self.state / "native-tools"
        tools.mkdir()
        (tools / "tool-original.json").write_text(
            json.dumps(
                {
                    "nativeThread": "original-thread",
                    "requestId": "original-source",
                    "state": "unknown",
                }
            )
        )
        self.record([])
        with self.assertRaisesRegex(RuntimeError, "callback outcome"):
            index(self.runner, self.content)

    def test_large_history_is_pageable_without_omission(self):
        self.record(
            [
                {"type": "commandExecution", "id": str(n), "status": "completed"}
                for n in range(300)
            ]
        )
        descriptor = index(self.runner, self.content)
        self.assertEqual(descriptor["actionCount"], 300)
        self.assertLess(len(json.dumps(descriptor)), 6144)

        async def http(purpose, method, path):
            self.assertEqual(
                (purpose, method, path),
                ("writer", "GET", "connector/deliveries/original-delivery/context"),
            )
            return {
                "schema": "lax-agent-context/v1",
                "agentId": "original-agent",
                "requestId": "original-source",
                "briefingReference": {"deliveryId": "original-delivery"},
            }

        self.runner.agent = SimpleNamespace(http=http)

        async def pages():
            offset = 0
            entries = []
            while offset is not None:
                page = await read(
                    self.runner,
                    {"indexSha256": descriptor["indexSha256"], "pageOffset": offset},
                )
                self.assertLessEqual(len(json.dumps(page, separators=(",", ":"))), 6144)
                entries += page["entries"]
                offset = page["nextPageOffset"]
            return entries

        self.assertEqual(asyncio.run(pages()), collect(self.runner, self.content))

    def test_index_cannot_be_read_under_another_context(self):
        self.record(
            [
                {
                    "type": "commandExecution",
                    "id": "original-command",
                    "status": "completed",
                }
            ]
        )
        descriptor = index(self.runner, self.content)
        self.runner.config["contextIds"]["writer"] = "another-context"
        with self.assertRaisesRegex(PermissionError, "another context"):
            asyncio.run(read(self.runner, {"indexSha256": descriptor["indexSha256"]}))

    def test_action_authorization_uses_event_read_not_material_delivery(self):
        item = {
            "type": "commandExecution",
            "id": "original-command",
            "status": "completed",
        }
        self.record([item])
        calls = []

        async def http(purpose, method, path):
            calls.append((purpose, method, path))
            return {
                "schema": "lax-agent-context/v1",
                "agentId": "original-agent",
                "requestId": "original-source",
                "briefingReference": {"deliveryId": "original-delivery"},
            }

        async def request(*args, **kwargs):
            self.fail("Permission check must not replace the model material-read proof")

        async def rpc(method, params):
            self.assertEqual(method, "thread/items/read")
            return {"data": [{"turnId": "original-turn", "item": item}]}

        self.runner.agent = SimpleNamespace(http=http)
        self.runner.request = request
        self.runner.rpc = SimpleNamespace(call=rpc)
        result = asyncio.run(
            read(
                self.runner,
                {"nativeTurn": "original-turn", "itemId": "original-command"},
            )
        )
        self.assertEqual(json.loads(result["content"]), item)
        self.assertEqual(
            calls, [("writer", "GET", "connector/deliveries/original-delivery/context")]
        )


    def test_chunk_next_read_reassembles_evidence_with_source_permission_each_time(self):
        item={"type":"commandExecution","id":"original-command","status":"completed","output":"Z"*9000}
        calls=[]
        async def http(purpose,method,path):
            calls.append(path)
            return {"schema":"lax-agent-context/v1","agentId":"original-agent",
                    "requestId":"original-source","briefingReference":{"deliveryId":"original-delivery"}}
        async def rpc(method,params):
            self.assertEqual(method,"thread/items/read")
            return {"data":[{"turnId":"original-turn","item":item}]}
        self.runner.agent=SimpleNamespace(http=http);self.runner.rpc=SimpleNamespace(call=rpc)
        async def journey():
            args={"nativeTurn":"original-turn","itemId":"original-command"};chunks=[]
            while args is not None:
                chunk=await read(self.runner,args);chunks.append(chunk["content"]);args=chunk["nextRead"]
            return chunks
        chunks=asyncio.run(journey())
        self.assertGreater(len(chunks),1)
        self.assertEqual(json.loads("".join(chunks)),item)
        self.assertEqual(len(calls),len(chunks))

    def test_missing_digest_is_specific_local_rejection_before_native_read(self):
        from lax_connector.errors import ToolValidationError
        with self.assertRaises(ToolValidationError) as caught:
            asyncio.run(read(self.runner,{"nativeTurn":"original-turn","itemId":"original-command","offset":3072}))
        self.assertEqual(caught.exception.code,"ACTION_READ_DIGEST_REQUIRED")
        self.assertIn("nextRead",caught.exception.next_action)


    def test_index_retains_bounded_native_labels_without_reinterpreting_effects(self):
        self.record([{"type":"dynamicToolCall","id":"progress","tool":"record_progress",
                      "namespace":None,"status":"failed"},
                     {"type":"commandExecution","id":"read","status":"completed",
                      "command":"read-source "*100}])
        result={entry["itemId"]:entry for entry in collect(self.runner,self.content)}
        self.assertEqual(result["progress"]["tool"],"record_progress")
        self.assertEqual(result["progress"]["status"],"failed")
        self.assertEqual(result["read"]["commandPreview"],("read-source "*100)[:240])
        self.assertNotIn("authority",result["progress"])


if __name__ == "__main__":
    unittest.main()
