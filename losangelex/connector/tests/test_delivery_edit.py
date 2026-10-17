"""Exact direct-permit adapter fixtures, without native/backend/model execution."""

import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from lax_connector.collaboration_bridge import Bridge, Held, digest
from lax_connector.delivery_edit import SCHEMA, normalized_envelope


def uid(n):
    return str(UUID(int=n))


class DeliveryPatchFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(
            prefix="lax-direct-unit-", dir="/run" if os.geteuid() == 0 else None
        )
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "commands").mkdir()
        physical = self.root / "ordinary-files"
        physical.mkdir()
        self.path = physical / "hello.txt"
        self.path.write_bytes(b"before")
        info = physical.stat()
        self.resource = {
            "workspaceId": uid(4),
            "root": str(physical),
            "environmentId": "local",
            "hostId": uid(2),
            "device": info.st_dev,
            "inode": info.st_ino,
            "agentGrantRevision": 2,
            "registryRevision": 1,
        }
        self.source = {
            "schema": "hollywood-native-source/v2",
            "authorityId": uid(1),
            "agentId": uid(3),
            "hostId": uid(2),
            "deliveryId": uid(5),
            "requestId": uid(6),
            "generation": 1,
            "claimId": "claim",
            "nativeThread": "thread",
            "nativeTurn": "turn",
            "contextId": "context",
            "roleRevision": 1,
            "nativeGoalId": None,
            "callId": "patch-call",
            "tool": "apply_patch",
            "argumentsDigest": "b" * 64,
        }
        self.record = {
            "scope": "delivery",
            "work": None,
            "briefingSequence": 11,
            "executorId": uid(7),
            "descriptorDigest": "d" * 64,
            "serviceBindingDigest": "e" * 64,
            "bridgeRevision": 1,
            "resources": [self.resource],
            "sourceBase": self.source,
            "native": {"pid": os.getpid()},
        }
        self.frame = {
            "port": "patch-preflight",
            "arguments": "literal original native patch",
            "evidence": {
                "environmentId": "local",
                "files": [
                    {
                        "pathUri": self.path.as_uri(),
                        "beforeSha256": hashlib.sha256(b"before").hexdigest(),
                        "beforeSize": 6,
                        "afterSha256": hashlib.sha256(b"after").hexdigest(),
                        "afterSize": 5,
                    }
                ],
            },
        }
        self.calls = []
        self.state = "ready"
        self.bridge = object.__new__(Bridge)
        self.bridge.state = self.root
        self.bridge.config = {
            "hostId": uid(2),
            "automaticCapture": {"schema": "lax-automatic-native-capture/v2"},
        }
        self.bridge.http = self.http
        self.bridge.briefing_sequence = lambda record: 11
        # Protected fixture files under /run when root; portable nonroot journal tests.
        self.enterContext(
            patch(
                "lax_connector.collaboration_bridge.protected",
                side_effect=lambda p: json.loads(p.read_text()),
            )
        )
        self.enterContext(
            patch(
                "lax_connector.delivery_edit.protected",
                side_effect=lambda p: json.loads(p.read_text()),
            )
        )

    def http(self, method, route, body=None):
        self.calls.append((method, route, copy.deepcopy(body)))
        if route.startswith("collaboration/delivery-targets/"):
            root = self.resource
            env = digest({"hostId": root["hostId"], "environmentId": "local"})
            return {
                "schema": "hollywood-agent-physical-target-registry/v1",
                "deliveryId": uid(5),
                "principalId": uid(3),
                "mayApply": False,
                "targets": [
                    {
                        "id": root["workspaceId"],
                        "root_path": root["root"],
                        "host": root["hostId"],
                        "revision": 1,
                        "grant_revision": 2,
                        "state": "active",
                        "grant_state": "active",
                        "can_read": True,
                        "can_write": True,
                        "execution_host": uid(2),
                        "environment_sha256": env,
                        "root_identity_sha256": digest(
                            {
                                "hostId": root["hostId"],
                                "environmentSha256": env,
                                "device": root["device"],
                                "inode": root["inode"],
                            }
                        ),
                    }
                ],
            }
        if method == "POST":
            if os.environ.get("LAX_DELIVERY_EDIT_SCHEMA"):
                import jsonschema

                jsonschema.validate(
                    body,
                    json.loads(
                        Path(os.environ["LAX_DELIVERY_EDIT_SCHEMA"]).read_text()
                    ),
                )
            self.assertEqual(route, "collaboration/delivery-edits")
            command = body["command"]
            if command["action"] == "begin":
                self.state = "executing"
                return {
                    "replayed": False,
                    "receipt": {"schema": SCHEMA, "permit": {"state": self.state}},
                    "admission": {
                        "mayApply": True,
                        "oneShotOriginalResponseOnly": True,
                        "permitId": command["permitId"],
                        "permitRevision": 2,
                        "patchSha256": command["patchSha256"],
                        "expiresAt": "2099-01-01T00:00:00Z",
                    },
                }
            if command["action"] == "settle":
                self.state = "settled" if command["outcome"] == "applied" else "held"
            return {
                "replayed": False,
                "admission": None,
                "receipt": {"schema": SCHEMA, "permit": {"state": self.state}},
            }
        if route.startswith("collaboration/delivery-edits/"):
            return {
                "permit": {"state": self.state},
                "effectiveState": self.state,
                "mayApply": False,
            }
        if route.startswith("collaboration/commands/"):
            return {"acceptedResult": {"schema": SCHEMA, "mayApply": False}}
        raise AssertionError((method, route))

    def invoke(self, phase):
        self.frame["port"] = phase
        return self.bridge.patch(self.record, self.source, self.frame)

    def test_normal_non_git_patch_uses_delivery_scope_and_normalized_target_digest(
        self,
    ):
        self.assertFalse((self.path.parent / ".git").exists())
        self.invoke("patch-preflight")
        body = next(body for method, _, body in self.calls if method == "POST")
        self.assertEqual(body["scope"], "delivery")
        self.assertNotIn("workId", body["command"])
        self.assertNotIn("planId", body["command"])
        self.assertIsNone(body["command"]["sourceRevision"])
        self.assertEqual(
            body["target"]["actionDigest"],
            digest({key: value for key, value in body.items() if key != "target"}),
        )
        self.assertEqual(body["command"]["files"][0]["relativePath"], "hello.txt")
        begin = self.invoke("patch-begin")
        self.assertTrue(begin["admission"]["mayApply"])
        self.path.write_bytes(
            b"after"
        )  # Simulated filesystem action, not a native qualification.
        self.frame["evidence"]["outcome"] = "applied"
        self.assertEqual(self.invoke("patch-settle")["settlementState"], "settled")

    def test_replayed_begin_never_reissues_an_apply_grant(self):
        self.invoke("patch-preflight")
        self.invoke("patch-begin")
        with self.assertRaises(Held):
            self.invoke("patch-begin")
        self.assertEqual(
            len(
                [
                    1
                    for method, _, body in self.calls
                    if method == "POST" and body["command"]["action"] == "begin"
                ]
            ),
            1,
        )

    def test_lost_begin_reply_is_only_read_and_never_reposted(self):
        self.invoke("patch-preflight")
        original = self.bridge.http

        def lose(method, route, body=None):
            if method == "POST":
                original(method, route, body)
                raise TimeoutError("lost begin reply")
            return original(method, route, body)

        self.bridge.http = lose
        with self.assertRaises(TimeoutError):
            self.invoke("patch-begin")
        with self.assertRaisesRegex(Held, "one-shot"):
            self.invoke("patch-begin")
        self.assertEqual(
            len(
                [
                    1
                    for method, _, body in self.calls
                    if method == "POST" and body["command"]["action"] == "begin"
                ]
            ),
            1,
        )
        self.assertTrue(
            any(
                route.startswith("collaboration/commands/")
                for method, route, _ in self.calls
                if method == "GET"
            )
        )

    def test_current_source_and_complete_file_set_are_immutable(self):
        self.invoke("patch-preflight")
        self.source["nativeTurn"] = "another-turn"
        with self.assertRaisesRegex(Held, "source, files or namespace"):
            self.invoke("patch-begin")
        self.source["nativeTurn"] = "turn"
        self.frame["evidence"]["files"][0]["afterSize"] = 99
        with self.assertRaisesRegex(Held, "source, files or namespace"):
            self.invoke("patch-begin")

    def test_actual_baseline_change_holds_before_begin_post(self):
        self.invoke("patch-preflight")
        self.path.write_bytes(b"changed externally")
        with self.assertRaisesRegex(Held, "baseline"):
            self.invoke("patch-begin")
        self.assertEqual(len([1 for method, _, _ in self.calls if method == "POST"]), 1)

    def test_captured_work_cannot_select_direct_mode(self):
        self.record["work"] = {"id": uid(80)}
        with self.assertRaisesRegex(Held, "captured delivery scope"):
            self.invoke("patch-preflight")
        self.assertFalse(self.calls)

    def test_unknown_observed_settlement_retains_held_state(self):
        self.invoke("patch-preflight")
        self.invoke("patch-begin")
        self.path.write_bytes(b"partial")
        self.frame["evidence"]["outcome"] = "unknown"
        self.assertEqual(self.invoke("patch-settle")["settlementState"], "held")

    def test_replaced_root_and_symlink_targets_hold(self):
        self.resource["inode"] += 1
        with self.assertRaises(Held):
            self.invoke("patch-preflight")
        self.resource["inode"] -= 1
        self.path.unlink()
        self.path.symlink_to(self.root / "outside")
        with self.assertRaises(OSError):
            self.invoke("patch-preflight")

    def test_missing_delivery_capability_never_uses_planned_fallback(self):
        self.record["ports"] = ["patch-preflight"]
        self.bridge.captured = lambda *args: (
            self.record,
            self.source,
            {"patchPermits": True, "physicalTargets": True},
        )
        with self.assertRaisesRegex(Held, "delivery edit protocol unavailable"):
            self.bridge.handle((123, 456, 0), self.frame)
        self.assertFalse(self.calls)

    def test_normalization_requires_explicit_nullable_revision_and_rejects_extra_fields(
        self,
    ):
        self.invoke("patch-preflight")
        body = next(body for method, _, body in self.calls if method == "POST")
        body.pop("target")
        body["command"].pop("sourceRevision")
        with self.assertRaises(Held):
            normalized_envelope(body)
        body["command"]["sourceRevision"] = None
        body["command"]["workId"] = uid(80)
        with self.assertRaises(Held):
            normalized_envelope(body)
