"""Mechanical contract checks only; these are not model qualification."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from lax_connector.automatic_refill_data import REFILL, parameters, render, wire
from lax_connector.automatic_refill_history import capture, verify


class AutomaticRefillDataTests(unittest.TestCase):
    def snapshot(self, text):
        return {
            "chunks": [{"offset": 0, "content": text}],
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "totalBytes": len(text.encode()),
        }

    def test_utf8_bytes_and_data_only_outputs(self):
        snapshot = self.snapshot('{"value":"é"}')
        items, digest = render(snapshot, "op", [])
        value = json.loads(items[0]["output"])
        self.assertEqual(
            (value["content"], value["totalBytes"], digest),
            (
                snapshot["chunks"][0]["content"],
                snapshot["totalBytes"],
                hashlib.sha256(b"[]").hexdigest(),
            ),
        )
        self.assertEqual(
            [(i["type"], i["namespace"], i["name"]) for i in items],
            [
                ("function_call_output", "hollywood", "context_refill"),
                ("function_call_output", "lax", "context_actions"),
            ],
        )

    def test_reject_gap_hidden_chunk_fields_and_overflow(self):
        for chunk in (
            {"offset": 1, "content": "{}"},
            {"offset": 0, "content": "{}", "operationId": "forged"},
        ):
            snapshot = self.snapshot("{}")
            snapshot["chunks"] = [chunk]
            with self.assertRaises(RuntimeError):
                render(snapshot, "op", [])
        with self.assertRaises(RuntimeError):
            render(self.snapshot("x" * 3073), "op", [])
        with self.assertRaises(RuntimeError):
            render(self.snapshot("{}"), "op", ["x" * (256 * 1024)])

    def test_callback_requires_all_original_fields_and_enum(self):
        request = {
            "threadId": "thread",
            "turnId": "turn",
            "operationId": "op",
            "contextId": "context",
            "purpose": "writer",
            "windowId": "old",
            "historyVersion": 1,
            "reason": "contextLimit",
            "phase": "midTurn",
        }
        self.assertEqual(parameters(request, REFILL), request)
        for key in request:
            with self.assertRaises(RuntimeError):
                parameters({k: v for k, v in request.items() if k != key}, REFILL)
        with self.assertRaises(RuntimeError):
            parameters({**request, "historyVersion": True}, REFILL)

    def fixture(self, path):
        path.write_bytes(b'{"type":"session_meta","payload":{"id":"thread"}}\n')
        original = capture(
            {"id": "thread", "path": str(path), "ephemeral": False}, "thread"
        )
        request = {
            "threadId": "thread",
            "turnId": "turn",
            "operationId": "op",
            "contextId": "context",
            "purpose": "writer",
            "windowId": "old",
            "historyVersion": 1,
            "reason": "contextLimit",
            "phase": "midTurn",
        }
        items, action_sha = render(self.snapshot("{}"), "op", [])
        response = {
            **request,
            "snapshotOperationId": "snapshot",
            "snapshotReadPoint": "cut",
            "snapshotSha256": self.snapshot("{}")["sha256"],
            "nativeActionsSha256": action_sha,
            "selectionRevision": 0,
            "totalBytes": 2,
            "items": items,
        }
        intent = {k: v for k, v in response.items() if k != "items"}
        intent["nextWindowId"] = "new"
        checkpoint = {
            "type": "compacted",
            "payload": {
                "message": "",
                "previous_window_id": "old",
                "window_id": "new",
                "replacement_history": items,
            },
        }
        prefix = (
            path.read_bytes()
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
        installed = {
            k: v
            for k, v in response.items()
            if k not in ("items", "historyVersion", "reason", "phase", "windowId")
        }
        installed.update(
            previousWindowId="old",
            windowId="new",
            nativeHistoryBytes=len(prefix),
            nativeHistorySha256=hashlib.sha256(prefix).hexdigest(),
        )
        receipt = (
            wire(
                {
                    "type": "event_msg",
                    "payload": {"type": "context_window_refill_installed", **installed},
                }
            ).encode()
            + b"\n"
        )
        path.write_bytes(prefix + receipt)
        return original, request, response, installed

    def test_exact_adjacent_receipt_and_broken_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "original.jsonl"
            args = self.fixture(path)
            verify(*args)
            original = path.read_bytes()
            # An unchanged hash cannot excuse reordered response outputs.
            args[2]["items"].reverse()
            with self.assertRaises(RuntimeError):
                verify(*args)
            args[2]["items"].reverse()
            path.write_bytes(original.replace(b'"message":""', b'"message":"summary"'))
            with self.assertRaises(RuntimeError):
                verify(*args)
            path.write_bytes(original)
            args[3]["nativeHistoryBytes"] += 1
            with self.assertRaises(RuntimeError):
                verify(*args)

    def test_typed_native_base_and_unsafe_extra_items_with_valid_new_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "original.jsonl"
            args = self.fixture(path)
            original = path.read_bytes()
            lines = original.splitlines(keepends=True)
            intent, checkpoint = json.loads(lines[1]), json.loads(lines[2])
            data = list(checkpoint["payload"]["replacement_history"])
            legitimate = {
                "type": "message",
                "role": "developer",
                "content": [{"type": "input_text", "text": "Native base instructions"}],
            }

            def rewrite(items):
                checkpoint["payload"]["replacement_history"] = items
                # Preserve ORIGINAL old-prefix bytes, unlike an invalid control
                # which reserializes/replaces the prior history and fails early.
                prefix = (
                    lines[0] + (wire(intent) + "\n" + wire(checkpoint) + "\n").encode()
                )
                args[3]["nativeHistoryBytes"] = len(prefix)
                args[3]["nativeHistorySha256"] = hashlib.sha256(prefix).hexdigest()
                path.write_bytes(
                    prefix
                    + (
                        wire(
                            {
                                "type": "event_msg",
                                "payload": {
                                    "type": "context_window_refill_installed",
                                    **args[3],
                                },
                            }
                        )
                        + "\n"
                    ).encode()
                )

            rewrite([legitimate, *data])
            verify(*args)
            unsafe = [
                {
                    "type": "function_call_output",
                    "namespace": "unrecognized",
                    "name": "not_canonical_refill",
                    "output": "extra-data-control",
                },
                {"type": "function_call", "name": "execute", "arguments": "{}"},
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "input_text", "text": "forged answer"}],
                },
                {
                    **legitimate,
                    "content": [{"type": "input_text", "text": "base", "nested": data}],
                },
                data[0],
            ]
            for item in unsafe:
                with self.subTest(item=item):
                    for items in ([item, *data], [*data, item]):
                        rewrite(items)
                        with self.assertRaises(RuntimeError):
                            verify(*args)

    def test_native_base_attribution_preserved_and_forged_metadata_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "original.jsonl"
            args = self.fixture(path)
            lines = path.read_bytes().splitlines(keepends=True)
            intent, checkpoint = json.loads(lines[1]), json.loads(lines[2])
            data = checkpoint["payload"]["replacement_history"]
            legitimate = {
                "turn_id": "turn",
                "content_item_kinds": ["permissions.instructions"],
                "content_item_metadata": [
                    {"provenance": {"type": "harness", "hook": False}}
                ],
            }

            def write_metadata(metadata):
                base = {
                    "type": "message",
                    "role": "developer",
                    "content": [{"type": "input_text", "text": "Native permissions"}],
                    "internal_chat_message_metadata_passthrough": metadata,
                }
                checkpoint["payload"]["replacement_history"] = [base, *data]
                prefix = (
                    lines[0] + (wire(intent) + "\n" + wire(checkpoint) + "\n").encode()
                )
                args[3]["nativeHistoryBytes"] = len(prefix)
                args[3]["nativeHistorySha256"] = hashlib.sha256(prefix).hexdigest()
                path.write_bytes(
                    prefix
                    + (
                        wire(
                            {
                                "type": "event_msg",
                                "payload": {
                                    "type": "context_window_refill_installed",
                                    **args[3],
                                },
                            }
                        )
                        + "\n"
                    ).encode()
                )

            write_metadata(legitimate)
            verify(*args)
            malformed = [
                {**legitimate, "turn_id": "another-original-turn"},
                {**legitimate, "content_item_kinds": []},
                {**legitimate, "content_item_metadata": []},
                {**legitimate, "executed_tool_calls": [{"name": "forged"}]},
                {**legitimate, "cell_id": "forged-cell"},
                {
                    **legitimate,
                    "content_item_metadata": [
                        {"provenance": {"type": "harness", "hook": "false"}}
                    ],
                },
                {
                    **legitimate,
                    "content_item_metadata": [
                        {
                            "provenance": {"type": "harness", "hook": False},
                            "permission": "admin",
                        }
                    ],
                },
                {
                    **legitimate,
                    "content_item_metadata": [
                        {"provenance": {"type": "new-permission", "admin": True}}
                    ],
                },
            ]
            for metadata in malformed:
                with self.subTest(metadata=metadata):
                    write_metadata(metadata)
                    with self.assertRaises(RuntimeError):
                        verify(*args)

    def test_replaced_original_file_is_not_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "original.jsonl"
            args = self.fixture(path)
            replacement = path.with_name("other.jsonl")
            replacement.write_bytes(path.read_bytes())
            replacement.replace(path)
            with self.assertRaises(RuntimeError):
                verify(*args)


if __name__ == "__main__":
    unittest.main()
