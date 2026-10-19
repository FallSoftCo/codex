"""Connector contract boundaries; HTTP replies are synthetic, not model evidence."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from lax_connector.attention import Attention


class HumanControlContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state = Path(self.directory.name)
        self.journal = self.state / "execution.json"
        self.journal.write_text(json.dumps({"nativeTurn": "original-turn"}))
        self.thread = "original-thread"
        self.active = {"delivery": {"id": str(uuid4()), "claim_id": "original-claim", "generation": 1}}
        self.finished = asyncio.get_running_loop().create_future()
        self.addCleanup(self.finished.cancel)
        self.calls = []
        self.attention = Attention(self)
        self.questions = [{"id": "audience", "header": "Audience",
                           "question": "Which audience?", "options": []}]
        self.answer = {"answers": {"audience": {"answers": ["Technical"]}}}

    def captured_execution(self):
        # Synthetic native callback ownership; this test starts no process/model.
        import copy
        return {**copy.deepcopy(self.active), "nativeThread": self.thread,
                "nativeTurn": json.loads(self.journal.read_text())["nativeTurn"]}

    async def http(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if method == "POST" and path == "attention":
            self.receipt = {
                "attention": {"id": payload["id"], "state": "pending"},
                "scope": {"deliveryId": self.active["delivery"]["id"],
                          "nativeThread": self.thread, "nativeTurn": "original-turn"},
                "responseMode": "native-callback" if payload["request"]["isBlocking"]
                                else "same-agent-context-input",
            }
            return self.receipt
        if method == "GET":
            return {**self.receipt,
                    "attention": {**self.receipt["attention"], "state": "response_submitted",
                                  "response": self.answer}}
        return {"state": payload["state"]}

    async def test_question_returns_durable_pending_without_waiting_or_callback(self):
        result = await self.attention.ask({"questions": self.questions}, slot="question-call")
        self.assertTrue(result["accepted"])
        self.assertEqual(result["state"], "pending")
        self.assertEqual(result["responseMode"], "same-agent-context-input")
        self.assertEqual([(method, path) for method, path, _ in self.calls], [("POST", "attention")])
        self.assertEqual(self.attention.pending, {})
        self.assertEqual(self.attention.rpc_slots, {})

    async def test_original_callback_returns_answer_and_preserves_submission_receipt(self):
        params = {"questions": self.questions, "_rpcRequestId": 13}
        answer = await self.attention.wait("hollywood/question", params, slot="original-call")
        self.assertEqual(answer, self.answer)
        await self.attention.submitted("hollywood/question", params, True)
        record = json.loads(next(self.state.glob("attention-*.json")).read_text())
        self.assertEqual(record["payload"]["nativeTurn"], "original-turn")
        self.assertEqual(record["state"], "native_submitted")
        self.assertEqual(self.calls[-1][2]["scope"], self.receipt["scope"])
