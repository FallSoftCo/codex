"""Current connector hooks with synthetic authority/RPC and actual local files.

These checks start no native runtime, model, worker, service or live authority.
"""

import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from lax_connector.connector import Connector
from lax_connector.passive_context import PassiveReceiver


class PassiveConnectorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir(mode=0o700)
        (self.home / "sessions").mkdir(mode=0o700)
        self.authority, self.actor, self.host, self.thread, self.delivery, self.room = [
            str(uuid4()) for _ in range(6)
        ]
        self.context = "b" * 64
        self.path = self.home / "sessions/fixture.jsonl"
        self.path.write_text(
            json.dumps(
                {
                    "type": "session_meta",
                    "payload": {
                        "id": self.thread,
                        "session_id": self.thread,
                        "cwd": str(self.root),
                    },
                }
            )
            + "\n"
        )
        self.path.chmod(0o600)
        self.reply = {
            "thread": {
                "id": self.thread,
                "sessionId": self.thread,
                "ephemeral": False,
                "path": str(self.path),
                "cwd": str(self.root),
            }
        }
        self.c = object.__new__(Connector)
        self.c.config = {
            "hostId": self.host,
            "agentId": self.actor,
            "codexHome": str(self.home),
        }
        self.c.state = self.root
        self.c.context_id = self.context
        self.c.thread = self.thread
        self.c.active = {
            "delivery": {
                "id": self.delivery,
                "authority": self.authority,
                "agent": self.actor,
                "host": self.host,
                "generation": 1,
                "claim_id": "fixture-claim",
                "state": "running",
                "native_thread": self.thread,
                "native_turn": str(uuid4()),
                "cancellation_requested": False,
            },
            "request": {
                "id": str(uuid4()),
                "authority": self.authority,
                "room": self.room,
                "author": str(uuid4()),
                "recipient": self.actor,
                "kind": "request",
                "audience": "room",
                "source": None,
                "body": "ordinary task",
                "seq": 10,
                "data": {"authorKind": "human"},
            },
        }
        self.c.passive_receiver = PassiveReceiver(
            self.root / "receiver",
            authority_id=self.authority,
            principal_id=self.actor,
            context_id=self.context,
            thread_id=self.thread,
        )
        self.c.passive_readback = None
        self.c.passive_new_thread = False
        self.c.passive_native_started = self.reply
        self.c.passive_epoch = self.delivery + ":fixture"
        self.c.rpc = SimpleNamespace(
            process=SimpleNamespace(returncode=None, pid=42),
            call=AsyncMock(side_effect=self.rpc),
        )
        self.c.http = AsyncMock(side_effect=self.http)
        self.row = None
        self.reply_lost = False

    async def rpc(self, method, params, **kwargs):
        if method == "thread/read":
            self.assertEqual(params, {"threadId": self.thread, "includeTurns": False})
            return copy.deepcopy(self.reply)
        if method == "thread/inject_items":
            self.assertEqual(params["threadId"], self.thread)
            self.assertEqual(len(params["items"]), 1)
            item = params["items"][0]
            self.assertEqual(item["type"], "agent_message")
            payload = {
                **item,
                "internal_chat_message_metadata_passthrough": {
                    "turn_id": self.c.active["delivery"]["native_turn"],
                    "create_time": 1,
                },
            }
            with self.path.open("a") as f:
                f.write(
                    json.dumps({"type": "response_item", "payload": payload}) + "\n"
                )
            if self.reply_lost:
                raise TimeoutError("synthetic accepted reply lost")
            return {}
        if method == "turn/interrupt":
            return {}
        raise AssertionError("unexpected native method: " + method)

    async def http(self, method, route, payload=None):
        self.assertEqual(method, "GET")
        if route == "deliveries/" + self.delivery:
            return {
                **copy.deepcopy(self.c.active),
                "agentContextBinding": {
                    "principal": self.actor,
                    "context_id": self.context,
                    "native_thread": self.thread,
                },
            }
        if route.startswith("inbox?"):
            events = []
            head = self.row["seq"] if self.row else 10
            if "after=10&" in route and self.row:
                events = [
                    {
                        "eventId": self.row["id"],
                        "roomId": self.room,
                        "kind": "message",
                        "sequence": head,
                        "authorityId": self.authority,
                        "principalId": self.actor,
                    }
                ]
            return {
                "authorityId": self.authority,
                "principalId": self.actor,
                "events": events,
                "head": head,
                "nextCursor": head,
            }
        if self.row and route == "inbox/events/" + self.row["id"]:
            return {"event": copy.deepcopy(self.row)}
        raise AssertionError(route)

    def publish_fixture(self):
        self.row = {
            "id": str(uuid4()),
            "authority": self.authority,
            "room": self.room,
            "author": str(uuid4()),
            "recipient": None,
            "kind": "message",
            "audience": "room",
            "source": None,
            "body": "A passive observation",
            "seq": 11,
            "data": {"authorKind": "agent"},
        }

    async def test_existing_rpc_metadata_exact_readback_and_forward_progress(self):
        await self.c.receive_passive_context()
        self.publish_fixture()
        await self.c.receive_passive_context()
        cp = self.c.passive_receiver.checkpoint()
        self.assertEqual((cp["cursor"], cp["pending"]), (10, self.row["id"]))
        await self.c.receive_passive_context()
        cp = self.c.passive_receiver.checkpoint()
        self.assertEqual((cp["cursor"], cp["pending"]), (11, None))
        self.assertEqual(
            [c.args[0] for c in self.c.rpc.call.await_args_list],
            ["thread/read", "thread/inject_items"],
        )
        proof = self.c.passive_readback.journal.phase(self.row["id"], "01-proof")
        self.assertEqual(proof["persistedRawItem"]["id"], self.row["id"])
        self.assertFalse(proof["modelConsumptionProved"])

    async def test_accepted_lost_reply_progresses_by_readback_without_resend(self):
        await self.c.receive_passive_context()
        self.publish_fixture()
        self.reply_lost = True
        await self.c.receive_passive_context()
        phase = self.c.passive_receiver.journal.phase(self.row["id"], "01-native")
        self.assertEqual((phase["state"], phase["resend"]), ("unknown", False))
        await self.c.receive_passive_context()
        self.assertIsNone(self.c.passive_receiver.checkpoint()["pending"])
        self.assertEqual(
            [c.args[0] for c in self.c.rpc.call.await_args_list],
            ["thread/read", "thread/inject_items"],
        )

    async def test_unloaded_transport_does_not_read_metadata_or_authority(self):
        self.c.rpc.process.returncode = 0
        await self.c.receive_passive_context()
        self.c.rpc.call.assert_not_awaited()
        self.c.http.assert_not_awaited()
        self.assertIsNone(self.c.passive_readback)

    async def test_metadata_gap_stays_local_without_injecting(self):
        self.reply["thread"]["path"] = str(self.root / "outside.jsonl")
        await self.c.receive_passive_context()
        self.assertIsNone(self.c.passive_readback)
        self.assertEqual(
            [c.args[0] for c in self.c.rpc.call.await_args_list], ["thread/read"]
        )
        self.c.http.assert_not_awaited()
        gap = json.loads((self.root / "passive-context-gap.json").read_text())
        self.assertEqual(
            gap,
            {"error": "Held", "executionAdmitted": False, "nativeReplayAllowed": False},
        )

    async def test_stop_monitor_remains_independent_of_waiting_passive_pump(self):
        self.c.finished = asyncio.get_running_loop().create_future()
        self.c.controls = SimpleNamespace(tick=AsyncMock())
        self.c.cancel_requested = False
        self.c.journal = self.root / "execution.json"
        self.c.journal.write_text("{}")
        self.c.active["delivery"]["cancellation_requested"] = True
        entered, release = asyncio.Event(), asyncio.Event()

        async def waiting():
            entered.set()
            await release.wait()

        self.c.receive_passive_context = waiting
        guidance = asyncio.create_task(self.c.monitor_guidance("fixture-turn"))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            await asyncio.wait_for(self.c.monitor_cancellation("fixture-turn"), 1)
            self.assertTrue(self.c.cancel_requested)
            self.assertFalse(guidance.done())
            self.c.rpc.call.assert_awaited_once_with(
                "turn/interrupt", {"threadId": self.thread, "turnId": "fixture-turn"}
            )
        finally:
            self.c.finished.set_result(None)
            release.set()
            guidance.cancel()
            await asyncio.gather(guidance, return_exceptions=True)
