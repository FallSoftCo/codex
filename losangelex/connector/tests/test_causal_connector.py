"""Current connector dispatch and lost-reply hooks with synthetic canonical facts."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

from lax_connector.connector import Connector
from test_completed_report_reconcile import Fixture
from test_canonical_delegation import native_proof


class CausalConnectorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.c = Fixture(Path(self.tmp.name))
        self.posts = 0
        self.c.active["delivery"].update(revision=3, cancellation_requested=False)
        self.c.active["request"].update(
            kind="request",
            audience="room",
            source=None,
            author=str(uuid4()),
            recipient=self.c.agent,
            body="Original public source task",
            seq=10,
            data={"authorKind": "agent"},
        )
        self.child = str(uuid4())
        self.child_delivery = str(uuid4())
        peer = str(uuid4())
        self.args = {
            "body": "A bounded synthetic delegation",
            "recipientId": peer,
            "audience": "room",
        }
        self.accepted = {
            "accepted": True,
            "event": {
                "id": self.child,
                "authority": self.c.authority,
                "room": self.c.room,
                "kind": "request",
                "audience": "room",
                "source": self.c.active["request"]["id"],
                "author": self.c.agent,
                "recipient": peer,
                "body": self.args["body"],
                "seq": 11,
                "data": {"authorKind": "agent", "expectsReply": True},
            },
            "deliveries": [
                {
                    "id": self.child_delivery,
                    "event": self.child,
                    "authority": self.c.authority,
                    "agent": peer,
                }
            ],
        }
        self.child_receipt = {
            "delivery": self.accepted["deliveries"][0],
            "request": self.accepted["event"],
        }
        self.c.active["delivery"]["native_thread"] = self.c.thread
        self.c.active["agentContextBinding"] = copy.deepcopy(self.c.agent_binding)
        self.child_receipt["delivery"].update(generation=1, claim_id="fixture-child-claim", revision=1,
            state="pending", cancellation_requested=False, host=self.c.host)
        self.get_failed = False
        self.reply_lost = False
        self.c.http = self.http

    async def http(self, method, path, payload=None):
        if method == "POST":
            self.posts += 1
            if self.reply_lost:
                raise TimeoutError("synthetic accepted reply lost")
            return copy.deepcopy(self.accepted)
        if self.get_failed:
            raise PermissionError("synthetic locator read refused")
        if path == "deliveries/" + self.child_delivery + "/delegation":
            return native_proof(self.child_receipt, self.c.active)
        if path == "deliveries/" + self.child_delivery:
            return copy.deepcopy(self.child_receipt)
        if path == "deliveries/" + self.c.current:
            return copy.deepcopy(self.c.active)
        raise AssertionError(path)

    async def invoke(self, call_id):
        return await Connector._tool(
            self.c,
            "item/tool/call",
            {
                "threadId": self.c.thread,
                "callId": call_id,
                "tool": "hollywood_request",
                "arguments": self.args,
            },
        )

    async def test_accepted_request_records_exact_edge_without_repeating(self):
        before = copy.deepcopy(self.c.active)
        first = await self.invoke("normal")
        again = await self.invoke("normal")
        self.assertTrue(first["success"])
        self.assertEqual(first, again)
        self.assertEqual(self.posts, 1)
        self.assertEqual(
            len(list((self.c.state / "causal-locators-v2/native-edges").rglob("*.json"))), 1
        )
        self.assertEqual(self.c.active, before)
        self.c.rpc.call.assert_not_called()

    async def test_accepted_request_survives_locator_failure_without_resend(self):
        self.get_failed = True
        first = await self.invoke("index-held")
        again = await self.invoke("index-held")
        self.assertTrue(first["success"])
        self.assertEqual(first, again)
        self.assertEqual(self.posts, 1)
        self.assertIn("effectAlreadyAccepted", json.dumps(first))

    async def test_original_lost_reply_recovery_also_records_edge_without_second_post(
        self,
    ):
        self.reply_lost = True
        self.c.effects.recover_live = AsyncMock(
            return_value=copy.deepcopy(self.accepted)
        )
        first = await self.invoke("lost")
        again = await self.invoke("lost")
        self.assertTrue(first["success"])
        self.assertEqual(first, again)
        self.assertEqual(self.posts, 1)
        self.c.effects.recover_live.assert_awaited_once()
        self.assertEqual(
            len(list((self.c.state / "causal-locators-v2/native-edges").rglob("*.json"))), 1
        )
