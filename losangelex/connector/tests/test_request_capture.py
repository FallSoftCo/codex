"""Dynamic capture on real fixture roots; canonical/source facts are synthetic."""

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lax_connector.collaboration_bridge import Held, digest
from lax_connector.delivery_edit import briefing_sequence
from test_collaboration_capture import CaptureFixture, uid


@unittest.skipUnless(os.geteuid() == 0, "root-protected fixture route required")
class DynamicCaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(
            prefix="lax-request-capture-", dir="/run"
        )
        self.addCleanup(self.tmp.cleanup)
        self.f = CaptureFixture(Path(self.tmp.name))
        self.f.policy["schema"] = "lax-automatic-native-capture/v2"
        self.f.policy[
            "agents"
        ] = {}  # Canonical access, no ongoing local agent whitelist.
        self.f.snapshot["request"]["data"] = {"workId": None, "attemptId": None}
        original = self.f.http
        self.metadata = self.target()

        def http(method, route, body=None):
            if route.endswith("/collaboration-bridge"):
                return {
                    "bridge": {
                        "state": "active",
                        "revision": 1,
                        "protocol": "canonical-edit-plans/v2",
                    },
                    "resourceRouting":"canonical-agent-resources/v1", "resourceDefaults":True, "resourceMetadata":True,
                    "deliveryEdits": True,
                    "deliveryEditSchema": "canonical-delivery-edits/v1",
                }
            if route.startswith("agents/" + self.f.agent + "/resources?"):
                workspace = {k:v for k,v in self.metadata.items() if k not in {"grant_state","grant_revision","can_read","can_write","execution_host"}}
                grant = {"revision":self.metadata["grant_revision"],"state":self.metadata["grant_state"],
                         **{k:self.metadata[k] for k in ("can_read","can_write","execution_host")}}
                return {"schema":"hollywood-agent-resources/v1","authorityId":self.f.authority,"agentId":self.f.agent,"executionHost":self.f.host,
                        "resources":[{"workspace":workspace,"grant":grant}],"nextCursor":None,"limit":8,"mayApply":False}
            if route.startswith("collaboration/delivery-targets/"):
                self.f.calls.append((method, route, body))
                return {
                    "schema": "hollywood-agent-physical-target-registry/v1",
                    "deliveryId": self.f.delivery,
                    "principalId": self.f.agent,
                    "mayApply": False,
                    "targets": [copy.deepcopy(self.metadata)],
                }
            return original(method, route, body)

        self.f.bridge.http = http
        self.f.capture.admin_http = http

    def target(self):
        root = self.f.physical
        environment = digest({"hostId": self.f.host, "environmentId": "local"})
        return {
            "id": self.f.resource,
            "host": self.f.host,
            "root_path": root["root"],
            "revision": 1,
            "state": "active",
            "grant_state": "active",
            "grant_revision": 2,
            "can_read": True,
            "can_write": True,
            "execution_host": self.f.host,
            "environment_sha256": environment,
            "root_identity_sha256": digest(
                {
                    "hostId": self.f.host,
                    "environmentSha256": environment,
                    "device": root["device"],
                    "inode": root["inode"],
                }
            ),
        }

    def test_ordinary_current_delivery_has_no_work_goal_plan_or_implicit_grant_write(
        self,
    ):
        record = self.f.ensure()
        self.assertEqual(record["scope"], "delivery")
        self.assertIsNone(record["work"])
        self.assertEqual(record["resources"][0]["workspaceId"], self.f.resource)
        self.assertFalse([call for call in self.f.calls if call[0] != "GET"])
        self.assertFalse(
            [call for call in self.f.calls if call[1].startswith(("work/", "goals/"))]
        )

    def test_repeat_capture_and_unrelated_agent_policy_data_do_not_rewrite_current_channel(
        self,
    ):
        first = self.f.ensure()
        original = next((self.f.state / "channels").glob("*.json")).read_bytes()
        self.f.policy["agents"][uid(99)] = {"unrelated": "not authorization"}
        self.assertEqual(self.f.ensure(), first)
        self.assertEqual(
            next((self.f.state / "channels").glob("*.json")).read_bytes(), original
        )

    def test_revoked_readonly_or_changed_physical_identity_holds(self):
        for key, value in [
            ("grant_state", "revoked"),
            ("can_write", False),
            ("root_identity_sha256", "0" * 64),
            ("host", uid(99)),
        ]:
            before = self.metadata[key]
            with self.subTest(key=key):
                self.metadata[key] = value
                with self.assertRaises(Held):
                    self.f.ensure()
            self.metadata[key] = before
        self.assertEqual(list((self.f.state / "channels").glob("*.json")), [])

    def test_current_resource_revision_change_never_silently_overwrites_a_channel(self):
        self.f.ensure()
        self.metadata["grant_revision"] += 1
        with self.assertRaisesRegex(Held, "authority changed"):
            self.f.ensure()

    def test_structured_source_stays_planned_and_keeps_original_work_grants(self):
        self.f.snapshot["request"]["data"] = {"workId": self.f.work}
        record = self.f.ensure()
        self.assertEqual(record["scope"], "plan")
        self.assertEqual(record["work"], {"id": self.f.work, "revision": 4})
        self.assertEqual(len([call for call in self.f.calls if call[0] == "PUT"]), 1)

    def test_cancelled_or_foreign_structured_assignment_cannot_fall_back_to_direct(
        self,
    ):
        self.f.snapshot["request"]["data"] = {"workId": self.f.work}
        self.f.work_row["owner"] = uid(99)
        with self.assertRaises(Held):
            self.f.ensure()
        self.assertEqual(list((self.f.state / "channels").glob("*.json")), [])


class BriefingWatermarkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        (self.home / "state").mkdir()
        self.base = {
            "authorityId": uid(1),
            "agentId": uid(2),
            "deliveryId": uid(3),
            "generation": 1,
            "claimId": "original",
        }
        self.record = {"sourceBase": self.base}
        self.enterContext(
            patch(
                "lax_connector.delivery_edit.expected_owner",
                return_value=(os.geteuid(), self.home, "unused"),
            )
        )

    def save(self, sequence, **changes):
        path = (
            self.home / "state" / ("briefing-" + uid(3) + "-" + str(sequence) + ".json")
        )
        path.write_text(
            json.dumps(
                {
                    "schema": "lax-work-briefing/v1",
                    **self.base,
                    "asOfSequence": sequence,
                    **changes,
                }
            )
        )
        path.chmod(0o600)
        return path

    def test_latest_exact_scope_observation_is_used_without_fetching_new_decisions(
        self,
    ):
        self.save(10)
        self.save(12)
        self.assertEqual(briefing_sequence(self.record), 12)

    def test_latest_wrong_claim_is_held_instead_of_falling_back(self):
        self.save(10)
        self.save(12, claimId="another-claim")
        with self.assertRaises(Held):
            briefing_sequence(self.record)

    def test_missing_or_symlink_watermark_never_fabricates_currentness(self):
        with self.assertRaises(Held):
            briefing_sequence(self.record)
        outside = self.home / "outside.json"
        outside.write_text("{}")
        target = self.home / "state" / ("briefing-" + uid(3) + "-12.json")
        target.symlink_to(outside)
        with self.assertRaises(OSError):
            briefing_sequence(self.record)
