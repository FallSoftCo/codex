"""Confirmed terminal callback closure must not block the next context rebuild."""
import asyncio,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from lax_connector.context_runtime import ContextRunner

class TerminalBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def runner(self, root, *, end_error=False):
        runner=ContextRunner.__new__(ContextRunner)
        runner.turn="disposable-original-turn"
        runner.thread="disposable-original-thread"
        runner.purpose="reader"
        runner.state=Path(root)
        runner.accepting=False
        runner.closing=True
        runner.failed=False
        runner.automatic=SimpleNamespace(pending=None)
        runner.effect_lock=asyncio.Lock()
        runner.native_tools=None
        runner.permit="disposable-permit"
        runner.trace=lambda *args:None
        async def request(action,value,operation):
            self.assertEqual(action,"end")
            self.assertEqual(operation,"context-end:disposable-original-turn")
            if end_error:raise RuntimeError("Unconfirmed original domain end")
            return {"nativeTurn":runner.turn,"state":"completed"}
        runner.request=request
        return runner

    async def test_confirmed_terminal_closure_allows_following_rebuild(self):
        with tempfile.TemporaryDirectory() as root:
            runner=self.runner(root)
            await runner.settle_turn("original-fingerprint",{"id":runner.turn,"status":"completed"})
            self.assertFalse(runner.closing)
            self.assertFalse(runner.accepting)
            self.assertEqual(json.loads((Path(root)/"wake.json").read_text())["state"],"finished")

    async def test_unconfirmed_end_keeps_callback_closure_and_no_finished_wake(self):
        with tempfile.TemporaryDirectory() as root:
            runner=self.runner(root,end_error=True)
            with self.assertRaisesRegex(RuntimeError,"Unconfirmed original"):
                await runner.settle_turn("original-fingerprint",{"id":runner.turn,"status":"completed"})
            self.assertTrue(runner.closing)
            self.assertFalse((Path(root)/"wake.json").exists())
