"""Captured relations plus synthetic authenticated metadata; no model/live effects."""

import copy
import hashlib
import itertools
import json
import tempfile
import unittest
from pathlib import Path
from uuid import UUID

from lax_connector import continuation_context as causal
from lax_connector.delegation_provenance import parent_for


CAPTURE = json.loads((Path(__file__).parent / "fixtures/canonical-delegation-failure-r20.json").read_text())
IDS = itertools.count(9000000)


def new_id():
    return str(UUID(int=next(IDS)))


def native_proof(child, parent):
    dd, de = child["delivery"], child["request"]
    pd, binding = parent["delivery"], parent["agentContextBinding"]
    call = (CAPTURE["diagnostics"][0]["nativeCallId"] if de["id"] == "f62f316c-ad6d-46c2-924f-6db0a314c41e"
            else "fixture-" + de["id"])
    return {"schema": "hollywood-native-delegation/v1", "childRequestId": de["id"],
        "childDeliveryId": dd["id"], "conversationSourceEventId": de["source"],
        "parent": {"authorityId": pd["authority"], "agentId": pd["agent"], "hostId": pd["host"],
            "deliveryId": pd["id"], "generation": pd["generation"], "claimId": pd["claim_id"],
            "requestId": pd["event"], "contextId": binding["context_id"],
            "roleRevision": binding["role_revision"]},
        "nativeCallId": call,
        "operationId": "lax-tool:" + hashlib.sha256((binding["native_thread"] + call).encode()).hexdigest(),
        "proof": {"nativeEffectId": int(hashlib.sha256(de["id"].encode()).hexdigest()[:14], 16) + 1,
                  "recordedBy": "verified_original_transaction"}}


class DelegationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = causal.LocatorLedger(Path(self.tmp.name) / "locators")
        self.rows = copy.deepcopy(CAPTURE["canonicalReads"])
        self.child = self.rows["deliveries/ce2e6b22-2e84-44a2-a333-49276914777b"]
        self.parent = self.rows["deliveries/8b19d35e-7971-4ae6-9059-068ef2c77432"]
        self.actor = self.parent["delivery"]["agent"]
        self.authority = self.parent["delivery"]["authority"]
        self.path = "deliveries/" + self.child["delivery"]["id"] + "/delegation"
        self.rows[self.path] = native_proof(self.child, self.parent)
        self.reads = []
        self.accepted = {"accepted": True, "event": self.child["request"],
            "deliveries": [{k: self.child["delivery"][k] for k in ("id", "authority", "agent", "event")}]}

    async def get(self, path):
        self.reads.append(path)
        return copy.deepcopy(self.rows[path])

    async def test_captured_result_source_indexes_actual_execution_parent(self):
        self.assertNotEqual(self.child["request"]["source"], self.parent["request"]["id"])
        self.assertEqual(causal.origin_reference(self.parent), CAPTURE["diagnostics"][0]["capturedParentRef"])
        with self.assertRaisesRegex(causal.ContextHeld, "ORIGIN_LOCATOR_MISSING"):
            self.ledger.unique(self.child["request"]["source"])
        before = copy.deepcopy(self.accepted)
        result = await causal.index_accepted_delegation(self.get, self.ledger, self.parent, self.accepted)
        self.assertEqual(result["causalLocator"], {"state": "recorded"})
        self.assertEqual({k: result[k] for k in before}, before)
        edge = json.loads(next((self.ledger.directory / "native-edges").rglob("*.json")).read_text())
        self.assertEqual(edge["parent"], causal.origin_reference(self.parent))
        self.assertEqual(edge["conversationSourceEventId"], self.child["request"]["source"])
        self.assertFalse((self.ledger.directory / "edges").exists())

    async def test_missing_native_proof_holds_accepted_effect_without_fallback(self):
        del self.rows[self.path]
        self.ledger.remember(self.parent)
        result = await causal.index_accepted_delegation(self.get, self.ledger, self.parent, self.accepted)
        self.assertEqual(result["event"], self.accepted["event"])
        self.assertEqual(result["causalLocator"], {"state": "held", "code": "CANONICAL_READ_UNAVAILABLE",
            "effectAlreadyAccepted": True, "resend": False})
        self.assertFalse((self.ledger.directory / "native-edges").exists())

    async def test_native_provenance_scope_and_historical_binding_fail_closed(self):
        proof = self.rows[self.path]
        cases = [(proof, "schema", "other"), (proof, "childRequestId", new_id()),
            (proof, "childDeliveryId", new_id()), (proof, "conversationSourceEventId", self.parent["request"]["id"]),
            (proof["parent"], "agentId", new_id()), (proof["parent"], "authorityId", new_id()),
            (proof["parent"], "hostId", new_id()), (proof["parent"], "generation", 2),
            (proof["parent"], "claimId", "other"), (proof["parent"], "contextId", "f" * 64),
            (proof["parent"], "roleRevision", 2), (proof, "nativeCallId", ""),
            (proof, "operationId", ""), (proof["proof"], "nativeEffectId", 0),
            (proof["proof"], "recordedBy", "model_hint"),
            (self.child["request"], "author", new_id()),
            (self.parent["agentContextBinding"], "native_thread", new_id()),
            (self.parent["delivery"], "cancellation_requested", True),
            (self.parent["delivery"], "state", "unknown")]
        for target, key, value in cases:
            with self.subTest(key=key, value=value):
                old = target[key]
                target[key] = value
                with self.assertRaises(causal.ContextHeld):
                    await parent_for(self.get, self.child, self.actor, self.authority)
                target[key] = old

    async def test_completed_parent_needs_historical_binding_not_live_executor(self):
        self.assertEqual(self.parent["delivery"]["state"], "completed")
        proved = await parent_for(self.get, self.child, self.actor, self.authority)
        self.assertEqual(proved["reference"], CAPTURE["diagnostics"][0]["capturedParentRef"])
        self.assertEqual(self.reads, [self.path, "deliveries/" + self.parent["delivery"]["id"], self.path])

    def parent_record(self, sequence=10, *, request_id=None, room=None, body="Public original task"):
        identity, request_id = new_id(), request_id or new_id()
        row = {"delivery": {**self.parent["delivery"], "id": identity, "event": request_id,
                           "state": "completed", "result_event": None},
            "request": {**self.parent["request"], "id": request_id, "seq": sequence,
                "source": None, "room": room or new_id(), "author": new_id(),
                "kind": "request", "audience": "room", "recipient": self.actor,
                "body": body, "data": {"authorKind": "agent"}},
            "agentContextBinding": {**self.parent["agentContextBinding"], "delivery": identity}}
        self.rows["deliveries/" + identity] = row
        return row

    def supply_child(self, current, parent, child=None):
        """Supply explicitly synthetic missing records around a captured pointer."""
        nd, ne = current["delivery"], current["request"]
        pointer = causal.pointer(ne)
        child_id = ne["data"]["replyToDelivery"]
        child = child or {"delivery": {**nd, "id": child_id, "event": pointer["requestId"],
            "agent": ne["author"], "state": "completed", "result_event": pointer["resultEventId"]},
            "request": {**ne, "id": pointer["requestId"], "author": self.actor,
                "recipient": ne["author"], "source": pointer["originRequestId"],
                "seq": ne["seq"] - 3, "body": "Synthetic child request",
                "data": {"authorKind": "agent", "expectsReply": True}}}
        result = {**ne, "id": pointer["resultEventId"], "kind": "result",
            "source": pointer["requestId"], "seq": ne["seq"] - 1,
            "body": "Synthetic supplemental result; outcome remains unassessed",
            "data": {"authorKind": "agent", "deliveryId": child_id,
                "state": "completed", "generation": child["delivery"]["generation"]}}
        self.rows["deliveries/" + nd["id"]] = current
        self.rows["deliveries/" + child_id] = child
        self.rows["inbox/events/" + result["id"]] = {"event": result}
        self.rows["deliveries/" + child_id + "/delegation"] = native_proof(child, parent)
        return child

    def next_completion(self, parent, sequence, *, source=None):
        current = self.parent_record(sequence)
        request, peer, child_request, child_delivery, result = [new_id() for _ in range(5)]
        current["delivery"].update(event=request, state="claimed")
        current["request"].update(id=request, room=self.child["request"]["room"], author=peer,
            source=result, body=json.dumps({"type": "peer_completion", "requestId": child_request,
                "resultEventId": result, "executionState": "completed",
                "originRequestId": source or parent["request"]["id"]}),
            data={"authorKind": "agent", "type": "peerCompletion",
                  "replyToRequest": child_request, "replyToDelivery": child_delivery})
        self.supply_child(current, parent)
        return current

    async def test_captured_failed_callback_constructs_context_from_execution_parent(self):
        pointer = causal.pointer(self.parent["request"])
        root = self.parent_record(request_id=pointer["originRequestId"])
        self.supply_child(self.parent, root)
        current = self.rows["deliveries/" + CAPTURE["failedDelivery"]]
        self.supply_child(current, self.parent, self.child)
        built = await causal.build_context(self.get, current, self.ledger.resolve, inspection=True)
        self.assertEqual(built["fragment"]["task"]["requestId"], root["request"]["id"])
        self.assertEqual(built["fragment"]["ancestry"]["depth"], 2)
        self.assertFalse(built["scopes"])
        self.assertEqual(self.rows["deliveries/" + CAPTURE["failedDelivery"]]["delivery"]["state"], "failed")

    async def test_sixteen_sequential_completions_keep_anchor_and_bounded_pages(self):
        root = current = self.parent_record()
        for i in range(16):
            current["delivery"]["state"] = "completed"
            current = self.next_completion(current, 30 + i * 10,
                source=current["request"]["source"] if i else None)
            pages = []
            def sink(page):
                pages.append(copy.deepcopy(page))
                self.ledger.retain_audit(page)
            built = await causal.build_context(self.get, current, self.ledger.resolve, retain_page=sink)
            self.assertEqual(built["fragment"]["task"]["requestId"], root["request"]["id"])
            self.assertEqual(built["fragment"]["ancestry"]["depth"], i + 1)
            self.assertLessEqual(len(json.dumps(built["fragment"]).encode()), causal.MAX_FRAGMENT_BYTES)
            self.assertTrue(all(len(page["hops"]) <= causal.AUDIT_PAGE_HOPS
                and len(causal.encoded(page)) <= causal.MAX_AUDIT_BYTES for page in pages))
            for previous, page in zip(pages, pages[1:]):
                self.assertEqual(page["previousSha256"], causal.digest(previous))
            self.assertEqual(built["audit"]["ancestryPages"]["headSha256"], causal.digest(pages[-1]))
            self.assertEqual(built["scopes"], [{"roomId": root["request"]["room"], "sourceEventId": root["request"]["id"]}])

    async def test_local_locator_cannot_override_parent_and_private_origin_stays_private(self):
        root = self.parent_record()
        current = self.next_completion(root, 30, source=new_id())
        def untrusted(*args):
            raise AssertionError("Local ancestry is not authority")
        built = await causal.build_context(self.get, current, untrusted)
        self.assertEqual(built["fragment"]["task"]["requestId"], root["request"]["id"])
        root["request"].update(audience="direct", author=self.actor, body="PRIVATE_ORIGINAL_MARKER")
        with self.assertRaisesRegex(causal.ContextHeld, "PRIVATE_SCOPE_HELD"):
            await causal.build_context(self.get, current, self.ledger.resolve)

    async def test_cancelled_callback_and_changed_provenance_hold_without_context(self):
        root = self.parent_record()
        current = self.next_completion(root, 30)
        current["delivery"]["cancellation_requested"] = True
        with self.assertRaisesRegex(causal.ContextHeld, "CANCELLED_OR_UNKNOWN_LINEAGE"):
            await causal.build_context(self.get, current, self.ledger.resolve)
        current["delivery"]["cancellation_requested"] = False
        path = "deliveries/" + current["request"]["data"]["replyToDelivery"] + "/delegation"
        reads = 0
        async def changed(route):
            nonlocal reads
            result = await self.get(route)
            if route == path:
                reads += 1
                if reads == 2:
                    result["proof"]["nativeEffectId"] += 1
            return result
        with self.assertRaisesRegex(causal.ContextHeld, "NATIVE_DELEGATION_CHANGED_DURING_READ"):
            await causal.build_context(changed, current, self.ledger.resolve)

    async def test_private_portfolio_parent_uses_verified_public_goal_anchor(self):
        root = self.parent_record()
        self.ledger.remember(root)
        private = self.parent_record(20, body="PRIVATE_PORTFOLIO_MARKER")
        goal, goal_source, material, private_room = [new_id() for _ in range(4)]
        public_room = self.child["request"]["room"]
        private["request"].update(author=self.actor, recipient=self.actor, audience="direct",
            room=private_room, source=material, data={"authorKind": "agent", "portfolioReview": True,
                "goalReferenceId": goal, "deliveryReferenceId": None, "triggerDigest": "c" * 64,
                "materialSequence": 18})
        self.rows["agents/" + self.actor + "/supervision?limit=32"] = {
            "policy": {"principal": self.actor, "authority": self.authority, "enabled": True, "room": private_room},
            "items": [{"scope": "goal", "reference": goal, "goal": goal, "principal": self.actor,
                "request_event": private["request"]["id"], "review_delivery": private["delivery"]["id"],
                "dispatched_digest": "c" * 64}], "nextCursor": None}
        self.rows["goals/" + goal] = {"goal": {"id": goal, "authority": self.authority,
            "room": public_room, "owner": self.actor, "creator": self.actor, "source": goal_source}}
        self.rows["inbox/events/" + goal_source] = {"event": {**root["request"], "id": goal_source,
            "kind": "message", "author": self.actor, "seq": 15, "source": root["request"]["id"],
            "room": public_room, "data": {"authorKind": "agent", "type": "goalOrigin",
                "scope": "explicit-planning-intent/v1", "goalId": goal,
                "originRequestId": root["request"]["id"], "originRoomId": root["request"]["room"],
                "originAuthorKind": "agent"}}}
        self.rows["inbox/events/" + material] = {"event": {**root["request"], "id": material,
            "kind": "message", "room": public_room, "seq": 18}}
        current = self.next_completion(private, 35, source=material)
        built = await causal.build_context(self.get, current, self.ledger.resolve)
        self.assertEqual(built["fragment"]["task"]["requestId"], root["request"]["id"])
        self.assertEqual(built["audit"]["goal"]["id"], goal)
        self.assertEqual(built["fragment"]["task"]["goalId"], goal)
        self.assertEqual(len(built["scopes"]), 2)
        self.assertNotIn("PRIVATE_PORTFOLIO_MARKER", json.dumps(built))
        self.rows["agents/" + self.actor + "/supervision?limit=32"]["items"][0]["review_delivery"] = new_id()
        with self.assertRaisesRegex(causal.ContextHeld, "CANONICAL_PORTFOLIO_REVIEW_REQUIRED"):
            await causal.build_context(self.get, current, self.ledger.resolve)


if __name__ == "__main__":
    unittest.main()
