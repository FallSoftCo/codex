"""Actual oversized progress regression; deterministic tool-contract fixture."""
import asyncio
import json
import unittest
from types import SimpleNamespace
from lax_connector.context_contract import tools
from lax_connector.context_runtime import ContextRunner

class ContextFeedbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_oversized_progress_lengths_report_bounds_without_dispatch(self):
        for count in (4999,4051):
            with self.subTest(count=count):
                r=ContextRunner.__new__(ContextRunner)
                r.admitted=asyncio.Event();r.admitted.set()
                r.effect_lock=asyncio.Lock()
                r.automatic=SimpleNamespace(blocked=False)
                r.active=r.accepting=True;r.closing=False
                r.thread,r.turn="thread","turn"
                r.allowed=r.context_names={"record_progress"}
                r.native_tools=None;r.declarations=tools("writer",False)
                r.trace=lambda *args:None
                async def request(*args,**kwargs):
                    self.fail("Known invalid input must not dispatch a canonical operation")
                r.request=request
                result=await r.tool("item/tool/call",{"threadId":"thread","turnId":"turn",
                    "tool":"record_progress","callId":"invalid-progress",
                    "arguments":{"workId":"work","body":"x"*count}})
                body=json.loads(result["contentItems"][0]["text"])
                self.assertFalse(result["success"]);self.assertFalse(body["dispatched"])
                self.assertEqual(body["code"],"CONTEXT_FIELD_BOUNDS")
                self.assertIn(str(count),body["message"]);self.assertIn("4000",body["message"])
