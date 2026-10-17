"""Changed Work capture/callback invariants; synthetic authority, real fixture files."""

import copy
import json
import os
import unittest
import urllib.error
from unittest.mock import patch

from lax_connector.collaboration_bridge import Bridge, Held, digest
from lax_connector.journal import saved
from lax_connector.work_delivery import POLICY, capability
import test_delivery_edit as delivery_fixtures
from test_delivery_edit import uid
import test_request_capture as capture_fixtures


@unittest.skipUnless(os.geteuid() == 0, "protected fixture route requires root")
class WorkCaptureTests(unittest.TestCase):
    target = capture_fixtures.DynamicCaptureTests.target
    assigned_work = capture_fixtures.DynamicCaptureTests.assigned_work

    def setUp(self):
        capture_fixtures.DynamicCaptureTests.setUp(self)
        self.assigned_work()

    def test_business_work_pins_original_identity_without_planned_calls(self):
        first = self.f.ensure()
        self.assertEqual(first["scope"], "delivery")
        self.assertEqual(first["work"], {
            "id": self.f.work, "revision": 4, "goalId": self.f.goal,
            "attemptId": self.f.delivery, "attemptNumber": 1, "roomId": uid(91),
        })
        self.assertIsNone(first["sourceBase"]["nativeGoalId"])
        self.assertEqual(first["sourceBase"]["contextId"], "private-context")
        self.assertEqual(first, self.f.ensure())
        self.assertFalse([c for c in self.f.calls
                          if c[0] != "GET" or "physical-targets" in c[1]])

    def test_explicit_callback_keeps_channel_and_seeds_only_original_work_grant(self):
        first = self.f.ensure()
        result = self.f.capture.ensure(
            (os.getpid(), os.geteuid(), 0),
            {"threadId": "thread", "turnId": "turn", "port": "coordination"},
        )
        self.assertEqual(result, first)
        writes = [c for c in self.f.calls if c[0] == "PUT"]
        self.assertEqual(len(writes), 1)
        self.assertTrue(writes[0][1].endswith("/grants/" + self.f.work))
        self.assertEqual(writes[0][2]["workRevision"], 4)

    def test_changed_assignment_or_attempt_is_held_without_ordinary_fallback(self):
        data = self.f.snapshot["request"]["data"]
        for key, value in (("workRevision", 5), ("goalId", uid(99)),
                           ("attemptId", uid(99)), ("attemptNumber", None)):
            original = data[key]
            data[key] = value
            with self.subTest(key=key), self.assertRaises(Held):
                self.f.ensure()
            data[key] = original
        self.assertFalse(list((self.f.state / "channels").glob("*.json")))

    def test_work_capability_is_explicit_and_ordinary_compatibility_is_retained(self):
        capability(None, {})
        for policy in ({}, {"workDeliveryEdits": True},
                       {"workDeliveryEdits": True, "workDeliveryEditPolicy": "other"}):
            with self.assertRaises(Held):
                capability({"id": self.f.work}, policy)
        capability({"id": self.f.work},
                   {"workDeliveryEdits": True, "workDeliveryEditPolicy": POLICY})

    def test_cancelled_source_or_revoked_write_never_gets_plan_fallback(self):
        self.f.snapshot["delivery"]["cancellation_requested"] = True
        with self.assertRaises(Held):
            self.f.ensure()
        self.f.snapshot["delivery"]["cancellation_requested"] = False
        self.metadata["can_write"] = False
        with self.assertRaises(Held):
            self.f.ensure()
        self.assertFalse([c for c in self.f.calls if c[0] != "GET"])


class WorkPatchTests(unittest.TestCase):
    invoke = delivery_fixtures.DeliveryPatchFixture.invoke

    def setUp(self):
        delivery_fixtures.DeliveryPatchFixture.setUp(self)
        self.record["ports"] = ["patch-preflight", "patch-begin", "patch-settle", "edit-plans", "coordination"]
        self.record["work"] = {
            "id": uid(20), "revision": 4, "goalId": uid(21),
            "attemptId": self.source["deliveryId"], "attemptNumber": 2, "roomId": uid(22),
        }
        self.authority = {
            "schema": POLICY, "workId": uid(20), "workRevision": 4,
            "goalId": uid(21), "goalRevision": 6, "decisionSequence": 11,
            "cooperationRevision": 2, "placementRevision": 3, "roomGrantRevision": 1,
            "attemptId": self.source["deliveryId"], "attemptNumber": 2,
            "ownerId": self.source["agentId"], "requestId": self.source["requestId"],
            "roomId": uid(22), "attemptDigest": "a"*64, "executionDigest": "b"*64,
        }
        self.plan = None
        self.bridge.captured = lambda peer, frame: (
            self.record, self.source,
            {"patchPermits": True, "physicalTargets": True, "deliveryEdits": True,
             "deliveryEditSchema": "canonical-delivery-edits/v1",
             "workDeliveryEdits": True, "workDeliveryEditPolicy": POLICY},
        )

    def http(self, method, route, body=None):
        if route.startswith("collaboration/physical-targets/"):
            result = delivery_fixtures.DeliveryPatchFixture.http(
                self, method, "collaboration/delivery-targets/" + uid(5), body)
            result["workRevision"] = 4
            return result
        if route.startswith("collaboration/edit-plans/"):
            self.calls.append((method, route, copy.deepcopy(body)))
            return copy.deepcopy(self.plan)
        if method == "POST" and route == "collaboration/edit-plans":
            self.calls.append((method, route, copy.deepcopy(body)))
            return {"receipt": {}, "replayed": False, "admission": None}
        result = delivery_fixtures.DeliveryPatchFixture.http(self, method, route, body)
        if "permit" in result:
            result["permit"]["proof"] = {"workAuthority": copy.deepcopy(self.authority)}
        if "receipt" in result and "permit" in result["receipt"]:
            result["receipt"]["permit"]["proof"] = {
                "workAuthority": copy.deepcopy(self.authority)}
        return result

    def original(self):
        return self.root / "commands" / (
            "permit-" + digest([self.source["nativeThread"], self.source["callId"]]) + ".json")

    def test_assigned_work_uses_unchanged_dto_and_pins_additive_server_proof(self):
        self.invoke("patch-preflight")
        body = next(b for m, _, b in self.calls if m == "POST")
        self.assertEqual(body["scope"], "delivery")
        self.assertNotIn("workId", body["command"])
        self.assertNotIn("planId", body["command"])
        self.assertIsNone(body["source"]["nativeGoalId"])
        self.assertEqual(json.loads(self.original().read_text())["workAuthority"],
                         self.authority)
        self.assertTrue(self.invoke("patch-begin")["admission"]["mayApply"])
        self.path.write_bytes(b"after")  # Observed fixture mutation; no native/model run.
        self.frame["evidence"]["outcome"] = "applied"
        self.assertEqual(self.invoke("patch-settle")["settlementState"], "settled")

    def test_wrong_or_missing_work_proof_retains_command_without_apply(self):
        for key, value in (("workId", uid(99)), ("attemptId", uid(99)),
                           ("requestId", uid(99)), ("executionDigest", "bad")):
            original = self.authority[key]
            self.authority[key] = value
            with self.subTest(key=key), self.assertRaises(Held):
                self.invoke("patch-preflight")
            self.authority[key] = original
            # One retained response is immutable; use a distinct original call.
            self.source["callId"] += "-next"
        self.authority = None
        with self.assertRaises(Held):
            self.invoke("patch-preflight")
        self.assertFalse(self.original().exists())

    def test_work_authority_drift_at_begin_discards_even_returned_admission(self):
        self.invoke("patch-preflight")
        self.authority["goalRevision"] += 1
        with self.assertRaisesRegex(Held, "authority changed"):
            self.invoke("patch-begin")
        self.assertEqual(json.loads(self.original().read_text())["permitRevision"], 1)
        with self.assertRaises(Held):
            self.invoke("patch-begin")
        self.assertEqual(len([c for c in self.calls if c[0] == "POST"]), 2)

    def test_replayed_begin_is_not_an_apply_grant(self):
        self.invoke("patch-preflight")
        self.invoke("patch-begin")
        with self.assertRaises(Held):
            self.invoke("patch-begin")
        self.assertEqual(len([c for c in self.calls if c[0] == "POST"]), 2)

    def test_unknown_post_is_recovered_only_by_original_get_never_posted_again(self):
        original = self.bridge.http
        failed = []

        def http(method, route, body=None):
            if method == "POST":
                failed.append(copy.deepcopy(body))
                raise TimeoutError("synthetic lost original reply")
            return original(method, route, body)

        self.bridge.http = http
        with self.assertRaises(TimeoutError):
            self.invoke("patch-preflight")
        with self.assertRaises(Held):
            self.invoke("patch-preflight")
        self.assertEqual(len(failed), 1)
        self.assertFalse(self.original().exists())
        self.assertTrue(any("collaboration/commands/" in c[1] for c in self.calls))

    def test_claim_ready_plan_and_unsettled_conflicts_are_not_retried_as_planned(self):
        original = self.bridge.http

        def http(method, route, body=None):
            if method == "POST":
                self.calls.append((method, route, copy.deepcopy(body)))
                raise urllib.error.HTTPError(route, 409, "scope_busy", None, None)
            return original(method, route, body)

        self.bridge.http = http
        with self.assertRaises(urllib.error.HTTPError):
            self.invoke("patch-preflight")
        with self.assertRaises(Held):
            self.invoke("patch-preflight")
        self.assertEqual([c[1] for c in self.calls if c[0] == "POST"],
                         ["collaboration/delivery-edits"])

    def test_ordinary_absent_proof_is_compatible_but_cannot_gain_work(self):
        self.record["work"] = None
        self.authority = None
        self.invoke("patch-preflight")
        self.invoke("patch-begin")

    def install_plan(self):
        item = self.frame["evidence"]["files"][0]
        manifest = {"sourceRevision": "c"*40, "files": [{
            "relativePath": "hello.txt",
            **{k: item[k] for k in ("beforeSha256", "beforeSize", "afterSha256", "afterSize")},
        }]}
        self.plan = {
            "plan": {"id": uid(30), "host": self.resource["hostId"],
                     "workspace_id": self.resource["workspaceId"], "integrator_work": uid(20),
                     "revision": 1, "state": "ready"},
            "manifest": manifest, "manifestSha256": "d"*64, "consentSetDigest": "e"*64,
        }
        saved(self.bridge.plan_pointer(self.record, self.resource), {"planId": uid(30)})

    def test_explicit_plan_pointer_uses_original_planned_callback(self):
        self.install_plan()
        with patch("lax_connector.collaboration_bridge.revision", return_value="c"*40):
            self.invoke("patch-preflight")
        body = next(b for m, _, b in self.calls if m == "POST")
        self.assertEqual(body["command"]["workId"], uid(20))
        self.assertEqual(body["command"]["planId"], uid(30))
        self.assertNotIn("scope", body)
        self.assertEqual(json.loads(self.original().read_text())["schema"],
                         "lax-original-patch-permit/v1")

    def test_nonready_plan_metadata_alone_does_not_force_a_file_plan(self):
        self.install_plan()
        for state in ("collecting", "withdrawn", "settled"):
            with self.subTest(state=state):
                self.plan["plan"]["state"] = state
                self.source["callId"] += "-next"
                self.invoke("patch-preflight")
        self.assertEqual([route for method, route, _ in self.calls if method == "POST"],
                         ["collaboration/delivery-edits"]*3)

    def test_ready_plan_on_another_file_does_not_capture_this_patch(self):
        self.install_plan()
        self.plan["manifest"]["files"][0]["relativePath"] = "different.txt"
        self.invoke("patch-preflight")
        self.assertEqual([route for method, route, _ in self.calls if method == "POST"],
                         ["collaboration/delivery-edits"])

    def test_explicit_native_plan_callback_stores_the_pointer_used_by_patch(self):
        self.install_plan()
        pointer = self.bridge.plan_pointer(self.record, self.resource)
        pointer.unlink()
        self.source["tool"] = "collaborative_edit_plan"
        self.source["callId"] = "explicit-plan"
        self.bridge.config["automaticCapture"] = {}
        record, source, policy = self.bridge.captured(None, None)
        policy.update(editPlans=True, bridge={"protocol": "canonical-edit-plans/v2"})
        self.bridge.captured = lambda *args: (record, source, policy)
        frame = {
            "port": "edit-plans",
            "arguments": {"command": {
                "action": "propose", "workId": uid(20), "workRevision": 4,
                "planId": uid(30), "manifest": self.plan["manifest"],
            }},
            "evidence": {"environmentId": "local",
                         "cwd": self.path.parent.as_uri()},
        }
        with patch("lax_connector.collaboration_bridge.revision", return_value="c"*40):
            self.bridge.handle((os.getpid(), os.geteuid(), 0), frame)
        self.assertEqual(json.loads(pointer.read_text()), {"planId": uid(30)})
        self.source["tool"] = "apply_patch"
        self.source["callId"] = "actual-patch"
        with patch("lax_connector.collaboration_bridge.revision", return_value="c"*40):
            self.invoke("patch-preflight")
        self.assertEqual([route for method, route, _ in self.calls if method == "POST"],
                         ["collaboration/edit-plans"]*2)

    def test_wrong_plan_manifest_holds_without_direct_fallback(self):
        self.install_plan()
        self.plan["manifest"]["files"][0]["afterSize"] = 999
        with patch("lax_connector.collaboration_bridge.revision", return_value="c"*40):
            with self.assertRaises(Held):
                self.invoke("patch-preflight")
        self.assertFalse([c for c in self.calls if c[0] == "POST"])

    def test_direct_original_cannot_switch_protocol_when_a_plan_pointer_appears(self):
        self.invoke("patch-preflight")
        self.install_plan()
        self.invoke("patch-begin")
        self.assertEqual([route for method, route, _ in self.calls if method == "POST"],
                         ["collaboration/delivery-edits"]*2)

    def test_native_handle_rechecks_work_capability_before_mutation(self):
        record, source, policy = self.bridge.captured(None, None)
        policy["workDeliveryEdits"] = False
        self.bridge.captured = lambda *args: (record, source, policy)
        with self.assertRaisesRegex(Held, "capability"):
            self.bridge.handle((os.getpid(), os.geteuid(), 0), self.frame)
        self.assertFalse(self.calls)
