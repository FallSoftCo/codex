
import unittest
from uuid import uuid4

from lax_connector.errors import ToolValidationError
from lax_connector.workflow import invoke


class Connector:
    def __init__(self):
        self.config = {"agentId": str(uuid4())}
        self.active = {"request": {"id": str(uuid4()), "room": str(uuid4())}}
        self.agent_binding = {"contextId": "unchanged"}
        self.goal_binding = None
        self.calls = []

    async def http(self, method, path, payload):
        self.calls.append((method, path, payload))
        return {"goalId": payload["id"]}


class ScopedGoalContext(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.c = Connector()
        self.args = {"title": "Goal", "objective": "Deliver", "acceptance": "Verify", "reviewBudget": 1}

    async def test_current_room_keeps_original_wire_and_context(self):
        binding = self.c.agent_binding
        await invoke(self.c, "hollywood_goal_create", self.args, "original-operation")
        method, path, payload = self.c.calls[0]
        self.assertEqual((method, path), ("POST", "rooms/" + self.c.active["request"]["room"] + "/goals"))
        self.assertNotIn("publishScopedIntent", payload)
        self.assertEqual(payload["sourceEventId"], self.c.active["request"]["id"])
        self.assertIs(self.c.agent_binding, binding)

    async def test_other_room_requires_explicit_scope_before_any_send(self):
        with self.assertRaises(ToolValidationError) as error:
            await invoke(self.c, "hollywood_goal_create", {**self.args, "roomId": str(uuid4())}, "scope")
        self.assertEqual(error.exception.code, "scoped_intent_required")
        self.assertEqual(self.c.calls, [])

    async def test_explicit_other_room_keeps_original_source_and_context(self):
        room, binding = str(uuid4()), self.c.agent_binding
        await invoke(self.c, "hollywood_goal_create",
                     {**self.args, "roomId": room, "publishScopedIntent": True}, "scoped-operation")
        method, path, payload = self.c.calls[0]
        self.assertEqual((method, path), ("POST", "rooms/" + room + "/goals"))
        self.assertIs(payload["publishScopedIntent"], True)
        self.assertEqual(payload["sourceEventId"], self.c.active["request"]["id"])
        self.assertEqual(payload["operationId"], "scoped-operation")
        self.assertIs(self.c.agent_binding, binding)

    async def test_invalid_flag_is_not_truthy_authorization(self):
        with self.assertRaises(ToolValidationError):
            await invoke(self.c, "hollywood_goal_create",
                         {**self.args, "publishScopedIntent": "true"}, "invalid")
        self.assertEqual(self.c.calls, [])


if __name__ == "__main__":
    unittest.main()
