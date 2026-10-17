"""Real loopback HTTP/effect journals; captured failure plus synthetic canonical rows."""

import copy
import json
import tempfile
import types
import unittest
from pathlib import Path
from uuid import UUID

from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer

from lax_connector import continuation_context as causal
from lax_connector import participation
from lax_connector.connector import Connector
from lax_connector.effects import digest
from test_completed_report_reconcile import Fixture


def uid(n):
    return str(UUID(int=n))


CAPTURE = json.loads((Path(__file__).parent / "fixtures/async-public-report-failure.json").read_text())


class ReplyTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lax-public-reply-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.c = Fixture(self.root)
        case = CAPTURE["case"]
        self.actor, self.authority, self.host = case["agent"], uid(100), uid(101)
        self.current, self.request_id, self.goal_id = case["id"], case["event"], case["data"]["goalReferenceId"]
        self.original_room, self.private_room = uid(201), uid(202)
        self.goal_room = "098c6c5c-c373-5428-81ff-6ecece7cbe55"
        self.original_id, self.original_delivery = uid(203), uid(204)
        self.goal_source, self.material_id = uid(205), case["source"]
        self.rows = {}
        def event(identity, room, author, seq, kind="request", audience="room", recipient=None, source=None, data=None):
            return {"id": identity, "authority": self.authority, "room": room,
                    "author": author, "recipient": recipient, "kind": kind,
                    "audience": audience, "source": source, "body": "Synthetic canonical fixture text",
                    "data": {"authorKind": "agent", **(data or {})}, "seq": seq}
        def delivery(identity, request, agent, state, generation=1):
            return {"delivery": {"id": identity, "authority": self.authority, "agent": agent,
                                 "host": self.host, "event": request["id"], "generation": generation,
                                 "claim_id": "fixture-claim", "revision": 2, "state": state,
                                 "cancellation_requested": False}, "request": request}
        self.event = event
        self.delivery = delivery
        self.origin = delivery(self.original_delivery, event(
            self.original_id, self.original_room, uid(206), 400, recipient=self.actor), self.actor, "completed")
        current_event = event(self.request_id, self.private_room, self.actor, 480,
                              audience="direct", recipient=self.actor, source=self.material_id, data=case["data"])
        self.c.active = delivery(self.current, current_event, self.actor, "claimed")
        self.rows["deliveries/" + self.current] = copy.deepcopy(self.c.active)
        self.rows["deliveries/" + self.original_delivery] = self.origin
        self.rows["inbox/events/" + self.goal_source] = {"event": event(
            self.goal_source, self.goal_room, self.actor, 410, kind="message", source=self.original_id,
            data={"type": "goalOrigin", "goalId": self.goal_id,
                  "scope": "explicit-planning-intent/v1", "originRequestId": self.original_id,
                  "originAuthorKind": "agent", "originRoomId": self.original_room})}
        self.rows["inbox/events/" + self.material_id] = {"event": event(
            self.material_id, self.goal_room, uid(207), 478, kind="message",
            data={"workflowAction": "work.review", "goalId": self.goal_id})}
        self.goal = {"id": self.goal_id, "authority": self.authority, "room": self.goal_room,
                     "owner": self.actor, "creator": self.actor, "source": self.goal_source,
                     "revision": 9, "state": "active"}
        self.rows["goals/" + self.goal_id] = {"goal": self.goal}
        self.item = {"principal": self.actor, "scope": "goal", "reference": self.goal_id,
                     "goal": self.goal_id, "delivery": None, "source_event": self.material_id,
                     "latest_seq": 478, "dispatched_seq": 478,
                     "dispatched_digest": case["data"]["triggerDigest"],
                     "request_event": self.request_id, "review_delivery": self.current}
        self.policy = {"principal": self.actor, "authority": self.authority, "room": self.private_room,
                       "enabled": True, "revision": 1}
        self.c.agent, self.c.authority, self.c.host, self.c.current = self.actor, self.authority, self.host, self.current
        self.c.config.update(agentId=self.actor, hostId=self.host)
        self.c.journal = self.c.state / "current-native-journal.json"
        self.c.journal.write_text(json.dumps({"nativeTurn": "unchanged-native-turn"}))
        self.c.causal_task_context = None
        self.posts, self.reads, self.commands, self.headers = [], [], {}, []
        self.can_post, self.lose_reply = True, False
        app = web.Application()
        app.router.add_route("*", "/hollywood/v3/{path:.*}", self.handle)
        self.server = TestServer(app)
        await self.server.start_server()
        self.addAsyncCleanup(self.server.close)
        self.c.session = ClientSession()
        self.addAsyncCleanup(self.c.session.close)
        self.c.config["hollywoodUrl"] = str(self.server.make_url("")).rstrip("/")
        self.c.http = types.MethodType(Connector.http, self.c)
        self.c._http = types.MethodType(Connector._http, self.c)
        self.ledger = causal.LocatorLedger(self.c.state / "causal-locators-v2")
        self.ledger.remember(self.origin)

    async def handle(self, request):
        self.assertEqual(request.headers["Authorization"], "Bearer " + self.c.config["token"])
        path = request.match_info["path"]
        if request.method == "GET":
            self.reads.append(path)
            if path.startswith("agents/" + self.actor + "/supervision"):
                return web.json_response({"policy": self.policy, "items": [self.item], "nextCursor": None})
            if path.startswith("commands/"):
                value = self.commands.get(path.removeprefix("commands/"))
                return web.json_response(value or {"error": "unavailable"}, status=200 if value else 404)
            return web.json_response(self.rows[path])
        self.assertEqual(request.method, "POST")
        body = await request.json()
        self.posts.append((path, copy.deepcopy(body)))
        self.headers.append(json.loads(request.headers["X-Hollywood-Native-Source"]))
        if not self.can_post:
            return web.json_response({"error": "current room posting grant revoked"}, status=403)
        operation = body["operationId"]
        if operation in self.commands:
            return web.json_response(self.commands[operation]["canonicalCommand"]["acceptedResult"])
        room = path.split("/")[1]
        event = self.event(uid(600 + len(self.posts)), room, self.actor, 600 + len(self.posts),
                           kind=body["kind"], audience=body["audience"],
                           recipient=body.get("recipientId"), source=body["sourceEventId"])
        event["body"] = body["body"]
        accepted = {"accepted": True, "event": event, "deliveries": []}
        wire = {"method": "POST", "path": path, "body": body}
        self.commands[operation] = {**accepted, "canonicalCommand": {
            "schema": "hollywood-command/v1", "authorityId": self.authority,
            "actorId": self.actor, "operationId": operation, "wireRequest": wire,
            "wireDigest": digest(wire), "eventId": event["id"],
            "acceptedResult": accepted, "evidenceComplete": True}}
        if self.lose_reply:
            return web.Response(status=503, text="synthetic accepted reply lost")
        return web.json_response(accepted)

    async def prepare(self):
        self.c.causal_task_context = await causal.prepare_context(
            lambda path: self.c.http("GET", path), self.c.state, self.c.active)
        self.c.active["delivery"].update(state="running", revision=3)
        return self.c.causal_task_context

    async def invoke(self, args, call="new-authored-summary", name="hollywood_publish"):
        params = {"threadId": self.c.thread, "callId": call, "tool": name, "arguments": args}
        with self.c.effects.tool_scope("item/tool/call", params):
            return await Connector._tool(self.c, "item/tool/call", params)

    def summary(self, room=None, **extra):
        return {"body": "New authored progress summary; no private transcript copied.",
                "roomId": room or self.original_room, "audience": "room", **extra}

    def peer(self, private_origin=False):
        peer, child, result = uid(300), uid(301), uid(302)
        child_request = self.event(uid(303), self.goal_room, self.actor, 450, audience="direct",
                                   recipient=peer, source=self.original_id, data={"expectsReply": True})
        child_receipt = self.delivery(child, child_request, peer, "completed")
        child_receipt["delivery"]["result_event"] = result
        self.rows["deliveries/" + child] = child_receipt
        self.rows["inbox/events/" + result] = {"event": self.event(
            result, self.goal_room, peer, 470, kind="result", audience="direct", recipient=self.actor,
            source=child_request["id"], data={"deliveryId": child, "generation": 1, "state": "completed"})}
        request = self.event(self.request_id, self.goal_room, peer, 480, audience="direct",
                             recipient=self.actor, source=result,
                             data={"type": "peerCompletion", "replyToRequest": child_request["id"], "replyToDelivery": child})
        request["body"] = json.dumps({"type": "peer_completion", "requestId": child_request["id"],
                                     "resultEventId": result, "executionState": "completed",
                                     "originRequestId": self.original_id})
        self.c.active = self.delivery(self.current, request, self.actor, "claimed")
        self.rows["deliveries/" + self.current] = copy.deepcopy(self.c.active)
        if private_origin:
            self.origin["request"].update(audience="direct", author=peer, room=self.goal_room)
            # A separate private-origin fixture state leaves the public fixture's
            # original locator immutable rather than rewriting its history.
            self.c.state = self.root / "private-origin-state"
            self.c.state.mkdir()
            self.c.journal = self.c.state / "current-native-journal.json"
            self.c.journal.write_text(json.dumps({"nativeTurn": "unchanged-native-turn"}))
            self.ledger = causal.LocatorLedger(self.c.state / "causal-locators-v2")
            self.ledger.remember(self.origin)

    async def test_captured_portfolio_failure_is_reproduced_without_a_verified_scope(self):
        self.assertEqual(self.c.active["request"]["data"]["portfolioReview"], CAPTURE["case"]["data"]["portfolioReview"])
        self.assertEqual(self.c.active["request"]["audience"], "direct")
        with self.assertRaisesRegex(PermissionError, CAPTURE["observedFailure"]):
            participation.message(self.c, "hollywood_publish", self.summary(), "operation")
        self.assertFalse(self.posts)

    async def test_portfolio_public_origin_can_publish_only_new_explicit_summary(self):
        context = await self.prepare()
        self.assertIsInstance(context, causal.VerifiedContext)
        self.assertLessEqual(len(json.dumps(context).encode()), causal.MAX_FRAGMENT_BYTES)
        self.assertEqual(context["replyScope"]["kind"], "goal")
        before = copy.deepcopy((self.c.active, self.c.agent_binding, self.c.thread, self.c.context_id))
        result = await self.invoke(self.summary())
        self.assertTrue(result["success"], result)
        path, body = self.posts[0]
        self.assertEqual(path, "rooms/" + self.original_room + "/messages")
        self.assertEqual(body["sourceEventId"], self.original_id)
        self.assertNotIn("expectsReply", body)
        self.assertEqual(body["kind"], "message")
        self.assertEqual(self.headers[0]["requestId"], self.request_id)
        self.assertEqual(self.headers[0]["deliveryId"], self.current)
        self.assertEqual(before, (self.c.active, self.c.agent_binding, self.c.thread, self.c.context_id))
        self.c.rpc.call.assert_not_called()

    async def test_explicit_goal_report_uses_verified_scoped_intent_not_private_material(self):
        await self.prepare()
        result = await self.invoke(self.summary(self.goal_room))
        self.assertTrue(result["success"], result)
        self.assertEqual(self.posts[0][1]["sourceEventId"], self.goal_source)
        self.assertNotEqual(self.posts[0][1]["sourceEventId"], self.material_id)

    async def test_peer_completion_keeps_original_public_request_and_current_execution_distinct(self):
        self.peer()
        await self.prepare()
        result = await self.invoke(self.summary())
        self.assertTrue(result["success"], result)
        self.assertEqual(self.c.causal_task_context["replyScope"]["kind"], "peer")
        self.assertEqual(self.posts[0][1]["sourceEventId"], self.original_id)
        self.assertEqual(self.headers[0]["requestId"], self.request_id)

    async def test_private_goal_origin_remains_private_and_default_direct_is_unchanged(self):
        self.rows["inbox/events/" + self.goal_source]["event"].update(audience="direct", recipient=self.actor)
        context = await self.prepare()
        self.assertEqual(context["replyScopeHeld"], "PRIVATE_GOAL_ORIGIN_HELD")
        self.assertFalse((await self.invoke(self.summary()))["success"])
        self.assertTrue((await self.invoke({"body": "Private default reply"}, call="direct-default"))["success"])
        body = self.posts[0][1]
        self.assertEqual((body["audience"], body["recipientId"], body["sourceEventId"]),
                         ("direct", self.actor, self.request_id))

    async def test_private_peer_origin_has_no_public_scope_and_keeps_direct_reply(self):
        self.peer(private_origin=True)
        context = await self.prepare()
        self.assertNotIn("replyScope", context)
        self.assertFalse((await self.invoke(self.summary()))["success"])
        result = await self.invoke({"body": "Private peer reply"}, call="private-peer")
        self.assertTrue(result["success"], result)
        self.assertEqual(self.posts[0][1]["recipientId"], uid(300))
        self.assertEqual(self.posts[0][1]["audience"], "direct")

    async def test_goal_origin_cannot_assert_an_unlocated_or_foreign_request(self):
        source = self.rows["inbox/events/" + self.goal_source]["event"]
        source["source"] = source["data"]["originRequestId"] = uid(995)
        context = await self.prepare()
        self.assertEqual(context["replyScopeHeld"], "ORIGIN_LOCATOR_MISSING_OR_AMBIGUOUS")
        self.assertFalse((await self.invoke(self.summary(sourceEventId=self.original_id)))["success"])
        self.assertFalse(self.posts)

    async def test_private_delivery_portfolio_review_has_no_goal_reporting_exception(self):
        self.c.active["request"]["data"].update(goalReferenceId=None, deliveryReferenceId=uid(994))
        self.rows["deliveries/" + self.current] = copy.deepcopy(self.c.active)
        context = await self.prepare()
        self.assertEqual(context["replyScopeHeld"], "PORTFOLIO_SCOPE_HELD")
        self.assertFalse((await self.invoke(self.summary()))["success"])
        self.assertFalse(self.posts)

    async def test_original_failed_tool_receipt_is_preserved_after_scope_is_available(self):
        failed = await self.invoke(self.summary(), call="original-refused")
        self.assertFalse(failed["success"])
        await self.prepare()
        again = await self.invoke(self.summary(), call="original-refused")
        self.assertEqual(again, failed)
        self.assertFalse(self.posts)
        authored = await self.invoke(self.summary(), call="new-explicit-intent")
        self.assertTrue(authored["success"], authored)
        self.assertEqual(len(self.posts), 1)

    async def test_type_flag_alone_foreign_review_or_unlinked_goal_never_authorizes_publication(self):
        self.item["request_event"] = uid(999)
        context = await self.prepare()
        self.assertEqual(context["replyScopeHeld"], "CANONICAL_PORTFOLIO_REVIEW_REQUIRED")
        self.assertFalse((await self.invoke(self.summary(sourceEventId=self.original_id)))["success"])
        self.assertFalse(self.posts)

    async def test_arbitrary_source_wrong_room_and_new_execution_request_are_refused(self):
        await self.prepare()
        for n, args in enumerate((self.summary(sourceEventId=uid(998)),
                                  self.summary(uid(997)),
                                  {"body": "No implicit room intent", "audience": "room"})):
            self.assertFalse((await self.invoke(args, call="refused-" + str(n)))["success"])
        self.assertFalse((await self.invoke(self.summary(recipientId=uid(996)),
                                           call="not-a-new-request", name="hollywood_request"))["success"])
        self.assertFalse(self.posts)

    async def test_plain_json_or_stale_current_claim_cannot_reuse_verified_reply_authority(self):
        context = await self.prepare()
        self.c.causal_task_context = json.loads(json.dumps(context))
        self.assertFalse((await self.invoke(self.summary(), call="forged-json"))["success"])
        self.c.causal_task_context = context
        self.c.active["delivery"]["claim_id"] = "different-current-claim"
        self.assertFalse((await self.invoke(self.summary(), call="stale-proof"))["success"])
        self.assertFalse(self.posts)

    async def test_canonical_bookkeeping_revision_preserves_the_exact_claim_locator(self):
        self.rows["deliveries/" + self.current]["delivery"]["revision"] += 1
        context = await self.prepare()
        self.assertIn("replyScope", context)
        self.assertTrue((await self.invoke(self.summary()))["success"])

    async def test_current_server_room_rights_are_required_despite_verified_origin(self):
        await self.prepare()
        self.can_post = False
        result = await self.invoke(self.summary())
        self.assertFalse(result["success"])
        self.assertFalse(self.commands)
        self.assertEqual(len(self.posts), 1)

    async def test_same_call_and_lost_reply_recover_original_receipt_without_new_post(self):
        await self.prepare()
        self.lose_reply = True
        first = await self.invoke(self.summary(), call="lost-original")
        again = await self.invoke(self.summary(), call="lost-original")
        self.assertTrue(first["success"], first)
        self.assertEqual(first, again)
        self.assertEqual(len(self.posts), 1)
        self.assertTrue(any(p.startswith("commands/") for p in self.reads))
        changed = await self.invoke(self.summary(body="Changed original payload"), call="lost-original")
        self.assertFalse(changed["success"])
        self.assertEqual(len(self.posts), 1)
