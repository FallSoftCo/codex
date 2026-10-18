"""Protocol checks complement the actual-model lost-notification journey."""
import asyncio
from types import SimpleNamespace
import unittest

from lax_connector.context_observation import wait_terminal
from lax_connector.context_runtime import ContextRunner


class ObservationTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_notification_observes_original_without_cancelling_waiter(self):
        calls = []
        traces = []
        statuses = iter(("inProgress", "completed"))
        finished = asyncio.get_running_loop().create_future()

        async def call(method, params, **kwargs):
            self.assertFalse(finished.cancelled())
            calls.append((method, params))
            return {"data": [{"id": "original-turn", "status": next(statuses)}]}

        runner = SimpleNamespace(
            config={"turnObservationSeconds": .001},
            thread="original-thread", turn="original-turn",
            finished=finished, rpc=SimpleNamespace(call=call),
            trace=lambda event, value: traces.append((event, value)),
        )
        result = await wait_terminal(runner)
        self.assertEqual(result, {"id": "original-turn", "status": "completed"})
        self.assertEqual(finished.result(), result)
        self.assertEqual([m for m, _ in calls], ["thread/turns/list"] * 2)
        self.assertEqual([p["threadId"] for _, p in calls], ["original-thread"] * 2)

    async def test_completion_arriving_during_observation_preserves_original_future(self):
        finished = asyncio.get_running_loop().create_future()
        terminal = {"id": "original-turn", "status": "completed"}

        async def call(method, params, **kwargs):
            finished.set_result(terminal)
            return {"data": [{"id": "original-turn", "status": "inProgress"}]}

        runner = SimpleNamespace(
            config={"turnObservationSeconds": .001},
            thread="original-thread", turn="original-turn", finished=finished,
            rpc=SimpleNamespace(call=call), trace=lambda *_: None,
        )
        self.assertEqual(await wait_terminal(runner), terminal)
        self.assertFalse(finished.cancelled())

    async def test_missing_original_is_held_without_starting_replacement(self):
        calls = []
        async def call(method, params, **kwargs):
            calls.append(method)
            return {"data": [{"id": "different-turn", "status": "completed"}]}
        runner = SimpleNamespace(
            config={"turnObservationSeconds": .001},
            thread="original-thread", turn="original-turn",
            finished=asyncio.get_running_loop().create_future(),
            rpc=SimpleNamespace(call=call), trace=lambda *_: None,
        )
        with self.assertRaisesRegex(RuntimeError, "Original native turn unavailable"):
            await wait_terminal(runner)
        self.assertEqual(calls, ["thread/turns/list"])
        self.assertFalse(runner.finished.cancelled())

    async def test_late_and_wrong_turn_callbacks_never_reach_effect_transport(self):
        runner = ContextRunner.__new__(ContextRunner)
        runner.admitted = asyncio.Event()
        runner.admitted.set()
        runner.effect_lock = asyncio.Lock()
        runner.active = True
        runner.accepting = True
        runner.closing = False
        runner.thread = "original-thread"
        runner.turn = "original-turn"
        params = {"threadId": runner.thread, "turnId": "different-turn"}
        with self.assertRaises(PermissionError):
            await runner.tool("item/tool/call", params)
        runner.accepting = False
        params["turnId"] = runner.turn
        with self.assertRaises(PermissionError):
            await runner.tool("item/tool/call", params)


if __name__ == "__main__":
    unittest.main()
