"""Native-history control fixtures; actual original rollout evidence is separate."""
import json
import tempfile
import unittest
from pathlib import Path

from lax_connector.automatic_refill_history import capture
from lax_connector.automatic_refill_preturn import failed_before_model


class FailedBeforeModelTests(unittest.TestCase):
    def stage(self, directory, before=None, after=None):
        path = Path(directory) / "original.jsonl"
        owner = {"purpose": "writer", "turnId": "turn", "materialIds": ["work"]}
        started = {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "turn"}}
        prefix = before if before is not None else [started]
        path.write_text("".join(json.dumps(row) + "\n" for row in prefix))
        original = capture({"id": "thread", "path": str(path), "ephemeral": False}, "thread")
        rows = after if after is not None else [
            {"type": "response_item", "payload": {
                "type": "function_call_output", "id": "input", "name": "context_material_available",
                "output": json.dumps({"purpose": "writer", "materialIds": ["work"]}),
                "internal_chat_message_metadata_passthrough": {"turn_id": "turn"}}},
            {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "turn",
                "error": {"message": "Synthetic pre-turn failure"}}},
        ]
        with path.open("a") as stream:
            for row in rows:
                stream.write(json.dumps(row) + "\n")
        return path, original, {"phase": "preTurn"}, owner

    def test_exact_failed_turn_survives_later_legitimate_turn_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path, original, request, owner = self.stage(directory)
            before = failed_before_model(original, request, owner)
            with path.open("a") as stream:
                stream.write(json.dumps({"type": "event_msg", "payload": {
                    "type": "task_started", "turn_id": "later"}}) + "\n")
            self.assertEqual(before, failed_before_model(original, request, owner))
            self.assertTrue(before["failedBeforeModel"])

    def test_prior_model_activity_or_duplicate_start_cannot_be_declared_zero_model(self):
        started = {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "turn"}}
        model = {"type": "response_item", "payload": {"type": "message", "role": "assistant"}}
        for prefix in ([started, model], [started, started]):
            with self.subTest(prefix=prefix), tempfile.TemporaryDirectory() as directory:
                _, original, request, owner = self.stage(directory, before=prefix)
                with self.assertRaises(RuntimeError):
                    failed_before_model(original, request, owner)

    def test_output_effect_or_missing_failed_completion_keeps_hold(self):
        for tail in (
            [{"type": "response_item", "payload": {"type": "message", "role": "assistant"}}],
            [{"type": "response_item", "payload": {"type": "function_call", "name": "exec_command"}}],
            [{"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "turn"}}],
        ):
            with self.subTest(tail=tail), tempfile.TemporaryDirectory() as directory:
                _, original, request, owner = self.stage(directory, after=tail)
                with self.assertRaises(RuntimeError):
                    failed_before_model(original, request, owner)
