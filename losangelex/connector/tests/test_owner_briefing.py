"""Real protected fixture files; synthetic canonical and managed-service observations."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from lax_connector import owner_briefing as owner
from lax_connector.collaboration_bridge import Held, digest
from lax_connector.journal import saved
from test_collaboration_capture import CaptureFixture, uid


@unittest.skipUnless(os.geteuid() == 0, "root-owned fixture route required")
class OwnerBriefingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lax-owner-briefing-", dir="/run")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.f = CaptureFixture(self.root)
        (self.f.state / "briefings").mkdir(mode=0o700)
        self.f.snapshot["request"]["room"] = uid(30)
        self.peer = (os.getpid(), os.geteuid(), 0)
        self.owner = {
            "agentId": self.f.agent,
            "actual": {"pid": os.getpid(), "start": "actual-fixture"},
            "bindingDigest": "b" * 64,
        }
        self.brief = {
            "schema": "lax-work-briefing/v1",
            "authorityId": self.f.authority,
            "agentId": self.f.agent,
            "deliveryId": self.f.delivery,
            "generation": 1,
            "claimId": "claim",
            "roomId": uid(30),
            "asOfSequence": 42,
        }
        self.frame = {
            "schema": "lax-owner-briefing/v1",
            "briefing": self.brief,
            "responseSha256": "a" * 64,
            "contextId": "private-context",
            "nativeThread": "thread",
            "roleRevision": 7,
        }
        self.record = {
            "sourceBase": {
                **{
                    k: self.brief[k]
                    for k in (
                        "authorityId",
                        "agentId",
                        "deliveryId",
                        "generation",
                        "claimId",
                    )
                },
                "hostId": self.f.host,
                "contextId": "private-context",
                "nativeThread": "thread",
                "roleRevision": 7,
            },
            "serviceBindingDigest": "b" * 64,
        }
        self.enterContext(patch.object(owner, "guardian_peer", return_value=self.owner))

    def carry(self):
        return owner.carry(self.f.capture, self.peer, self.frame, self.owner)

    def test_observed_owner_metadata_is_root_protected_and_never_grants_an_effect(self):
        result = self.carry()
        self.assertFalse(result["result"]["mayApply"])
        self.assertEqual(owner.sequence(self.f.bridge, self.record), 42)
        path = next((self.f.state / "briefings").glob("*.json"))
        self.assertEqual(path.stat().st_uid, 0)
        self.assertFalse(path.stat().st_mode & 0o077)
        self.assertFalse([c for c in self.f.calls if c[0] != "GET"])
        self.assertEqual(self.carry(), result)
        self.frame["responseSha256"] = "c" * 64
        with self.assertRaisesRegex(Held, "Original protected"):
            self.carry()

    def test_current_claim_context_role_and_cancellation_are_checked(self):
        mutations = [
            (self.brief, "claimId", "other"),
            (self.frame, "contextId", "other"),
            (self.frame, "roleRevision", 8),
            (self.f.snapshot["delivery"], "cancellation_requested", True),
        ]
        for target, key, value in mutations:
            original = target[key]
            with self.subTest(key=key):
                target[key] = value
                with self.assertRaises(Held):
                    self.carry()
                self.assertEqual(list((self.f.state / "briefings").glob("*.json")), [])
            target[key] = original

    def test_protected_sequence_rejects_wrong_incarnation_and_no_owner_cache_fallback(
        self,
    ):
        cache = self.root / "state" / ("briefing-" + self.f.delivery + "-999.json")
        saved(cache, {**self.brief, "asOfSequence": 999})
        with self.assertRaisesRegex(Held, "unavailable"):
            owner.sequence(self.f.bridge, self.record)
        self.carry()
        self.record["serviceBindingDigest"] = "c" * 64
        with self.assertRaisesRegex(Held, "incarnation"):
            owner.sequence(self.f.bridge, self.record)

    def test_sequence_filename_cannot_claim_a_newer_observation(self):
        self.carry()
        path = next((self.f.state / "briefings").glob("*.json"))
        path.rename(path.with_name(path.name.replace("-42.json", "-999.json")))
        with self.assertRaises(Held):
            owner.sequence(self.f.bridge, self.record)


@unittest.skipUnless(os.geteuid() == 0, "root-owned fixture route required")
class GuardianIdentityTests(unittest.TestCase):
    def test_actual_managed_guardian_is_distinct_from_same_uid_child(self):
        with tempfile.TemporaryDirectory(prefix="lax-guardian-", dir="/run") as name:
            root = Path(name)
            binary = Path(sys.executable).resolve()
            image = binary.stat()
            authority, host, agent = uid(1), uid(2), uid(3)
            invocation = UUID(uid(4)).hex
            actual = {
                "pid": os.getpid(),
                "uid": 0,
                "controlGroup": "/fixture",
                "start": "actual-start",
            }
            info = {
                "ActiveState": "active",
                "MainPID": str(os.getpid()),
                "ControlGroup": "/fixture",
                "Id": "fixture.service",
                "InvocationID": invocation,
            }
            baseline = {
                "schema": "lax-service-enrollment/v1",
                "authorityId": authority,
                "hostId": host,
                "agentId": agent,
                "uid": 0,
                "home": str(root),
                "unit": info["Id"],
                "unitDefinitionDigest": "d" * 64,
                "binary": str(binary),
                "binaryDevice": image.st_dev,
                "binaryInode": image.st_ino,
                "machineIdentity": "machine",
                "killMode": "control-group",
            }
            binding = {
                **baseline,
                "schema": "lax-service-incarnation/v1",
                "bootId": "boot",
                "serviceInvocation": invocation,
                "controlGroup": "/fixture",
                "guardianPid": os.getpid(),
                "guardianStart": "actual-start",
            }
            saved(root / "enrollment.json", baseline)
            saved(root / (invocation + ".json"), binding)
            capture = SimpleNamespace(config={"authorityId": authority, "hostId": host})
            with (
                patch.object(
                    owner, "installed_native_owner", return_value=(agent, str(binary))
                ),
                patch.object(
                    owner.observer,
                    "expected_owner",
                    return_value=(0, root, str(binary)),
                ),
                patch.object(owner.observer, "properties", return_value=info),
                patch.object(
                    owner.observer, "installed_unit", return_value="fixture.service"
                ),
                patch.object(owner.observer, "process", return_value=actual),
                patch.object(owner.observer, "directory", return_value=root),
                patch.object(owner.observer, "unit_definition", return_value="d" * 64),
                patch.object(
                    owner.observer, "machine_identity", return_value="machine"
                ),
                patch.object(owner.observer, "boot_id", return_value="boot"),
            ):
                result = owner.guardian_peer(capture, (os.getpid(), 0, 0))
                self.assertEqual(result["bindingDigest"], digest(binding))
                with self.assertRaisesRegex(Held, "actual managed"):
                    owner.guardian_peer(capture, (os.getpid() + 1, 0, 0))
                binding["guardianStart"] = "replacement"
                saved(root / (invocation + ".json"), binding)
                with self.assertRaisesRegex(Held, "incarnation"):
                    owner.guardian_peer(capture, (os.getpid(), 0, 0))
