"""Protocol regression from a real cancelled native command's progress message."""
import unittest

from lax_connector.terminal_output import terminal_body


class NativeTerminalOutput(unittest.TestCase):
    def test_cancelled_execution_does_not_publish_the_model_progress_plan(self):
        # Same phase/status shape captured by the native Stop integration.
        message = {"type": "agentMessage", "phase": "commentary",
                   "text": "I will run the foreground observation now."}
        for state in ("cancelled", "failed"):
            with self.subTest(state=state):
                reply = terminal_body(state, [message])
                self.assertNotIn(message["text"], reply)
                self.assertNotIn("observation", reply)

    def test_completed_reply_preserves_final_phase_over_later_progress(self):
        final = {"type": "agentMessage", "phase": "final_answer", "text": "Accepted artifact verified."}
        progress = {"type": "agentMessage", "phase": "commentary", "text": "Checking another detail."}
        legacy_ui = {"type": "agentMessage", "delivery": "async", "text": "Old UI question."}
        self.assertEqual(terminal_body("completed", [final, progress, legacy_ui]), final["text"])
        unphased = {"type": "agentMessage", "text": "Provider without phases."}
        self.assertEqual(terminal_body("completed", [unphased, progress]), unphased["text"])

    def test_unsettled_native_state_cannot_be_presented_as_a_terminal_reply(self):
        with self.assertRaises(ValueError):
            terminal_body("unknown", [{"type": "agentMessage", "text": "Earlier text."}])


if __name__ == "__main__":
    unittest.main()
