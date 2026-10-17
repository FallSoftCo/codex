"""Synthetic canonical fixtures plus actual root-owned files; no native/model proof."""

import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from lax_connector.collaboration_capture import AutomaticCapture, administrative_put
from lax_connector.collaboration_bridge import Bridge, Held, digest
from lax_connector.collaboration_install import prepare, apply
from lax_connector.host import machine_identity


def uid(number):
    return str(UUID(int=number))


class CaptureFixture:
    def __init__(self, root):
        self.root = root
        self.state = root / "state"
        for path in [
            self.state,
            self.state / "channels",
            self.state / "channels/archive",
            self.state / "commands",
            self.state / "administration",
        ]:
            path.mkdir(mode=0o700, exist_ok=True)
        physical = root / "checkout"
        physical.mkdir()
        info = physical.stat()
        (
            self.authority,
            self.host,
            self.agent,
            self.delivery,
            self.executor,
            self.work,
            self.goal,
            self.request,
            self.resource,
        ) = [uid(i) for i in range(1, 10)]
        self.physical = {
            "root": str(physical),
            "device": info.st_dev,
            "inode": info.st_ino,
            "hostId": self.host,
            "environmentId": "local",
            "workspaceId": self.resource,
            "registryRevision": 1,
        }
        self.config = {"hostId": self.host, "authorityId": self.authority}
        self.policy = {
            "schema": "lax-automatic-native-capture/v1",
            "agents": {
                self.agent: {
                    "workspaceIds": [self.resource],
                    "defaultWorkspaceId": self.resource,
                }
            },
            "resources": [self.physical],
        }
        self.row = {
            "id": self.executor,
            "agent": self.agent,
            "host": self.host,
            "delivery": self.delivery,
            "generation": 1,
            "claim_id": "claim",
            "launch_phase": "attached",
            "state": "live",
            "descriptor_digest": "d" * 64,
            "descriptor": {"nativePid": os.getpid(), "nativeStart": "fixture-start"},
        }
        self.snapshot = {
            "delivery": {
                "id": self.delivery,
                "agent": self.agent,
                "host": self.host,
                "generation": 1,
                "claim_id": "claim",
                "event": self.request,
                "state": "running",
                "cancellation_requested": False,
                "native_thread": "thread",
                "native_turn": "turn",
            },
            "request": {
                "id": self.request,
                "authority": self.authority,
                "data": {"workId": self.work},
            },
            "agentContextBinding": {
                "delivery": self.delivery,
                "generation": 1,
                "principal": self.agent,
                "native_thread": "thread",
                "context_id": "private-context",
                "workspace_id": uid(90),
                "role_revision": 7,
            },
        }
        self.work_row = {
            "id": self.work,
            "owner": self.agent,
            "delivery": self.delivery,
            "request_event": self.request,
            "state": "assigned",
            "revision": 4,
            "goal": self.goal,
        }
        self.targets = []
        self.calls = []
        self.lost = False
        self.original = None
        self.native = {
            "pid": os.getpid(),
            "start": "fixture-start",
            "uid": os.geteuid(),
        }
        self.fact = {"state": "live", "evidence": {"serviceBindingDigest": "b" * 64}}
        self.bridge = SimpleNamespace(
            config=self.config, state=self.state, http=self.http
        )
        self.capture = object.__new__(AutomaticCapture)
        self.capture.bridge = self.bridge
        self.capture.config = self.config
        self.capture.state = self.state
        self.capture.policy = self.policy
        self.capture.admin_http = self.http
        self.capture.peer = lambda peer: (
            copy.deepcopy(self.row),
            copy.deepcopy(self.native),
            copy.deepcopy(self.fact),
        )

    def http(self, method, route, body=None):
        self.calls.append((method, route, copy.deepcopy(body)))
        if route == "deliveries/" + self.delivery:
            return copy.deepcopy(self.snapshot)
        if route == "agents/" + self.agent + "/role":
            return {"revision": 7}
        if route == "work/" + self.work:
            return {"work": copy.deepcopy(self.work_row)}
        if route == "goals/" + self.goal:
            return {"goal": {"state": "active"}}
        if route.endswith("/collaboration-bridge"):
            return {
                "bridge": {
                    "revision": 1,
                    "state": "active",
                    "protocol": "canonical-edit-plans/v2",
                }
            }
        if route == "collaboration/physical-targets/" + self.work:
            return {"workRevision": 4, "targets": copy.deepcopy(self.targets)}
        if method == "PUT":
            env = digest({"hostId": self.host, "environmentId": "local"})
            self.targets = [
                {
                    "id": self.resource,
                    "state": "active",
                    "grant_state": "active",
                    "revision": 1,
                    "grant_revision": 1,
                    "work_revision": 4,
                    "root_path": self.physical["root"],
                    "host": self.host,
                    "environment_sha256": env,
                    "root_identity_sha256": digest(
                        {
                            "hostId": self.host,
                            "environmentSha256": env,
                            "device": self.physical["device"],
                            "inode": self.physical["inode"],
                        }
                    ),
                }
            ]
            result = {"grant": {"revision": 1}}
            self.original = {
                "method": "PUT",
                "path": "/hollywood/v3/" + route,
                "wireDigest": hashlib.sha256(json.dumps(body).encode()).hexdigest(),
                "acceptedResult": result,
            }
            if self.lost:
                raise TimeoutError("synthetic lost accepted reply")
            return result
        if route.startswith("administration/commands/"):
            return copy.deepcopy(self.original)
        raise AssertionError((method, route))

    def ensure(self, turn="turn"):
        return self.capture.ensure(
            (os.getpid(), os.geteuid(), 0), {"threadId": "thread", "turnId": turn}
        )


class AutomaticCaptureTests(unittest.TestCase):
    def setUp(self):
        if os.geteuid() != 0:
            self.skipTest(
                "root-owned fixture semantics require administrator test route"
            )
        self.tmp = tempfile.TemporaryDirectory(prefix="lax-capture-unit-", dir="/run")
        self.addCleanup(self.tmp.cleanup)
        self.f = CaptureFixture(Path(self.tmp.name))

    def test_capture_grant_and_per_turn_history_preserve_private_context(self):
        first = self.f.ensure()
        again = self.f.ensure()
        self.assertEqual(first, again)
        self.assertEqual(first["sourceBase"]["contextId"], "private-context")
        self.assertNotEqual(
            first["resources"][0]["workspaceId"],
            self.f.snapshot["agentContextBinding"]["workspace_id"],
        )
        self.assertEqual(len([c for c in self.f.calls if c[0] == "PUT"]), 1)
        self.f.snapshot["delivery"]["native_turn"] = "next-turn"
        second = self.f.ensure("next-turn")
        self.assertEqual(
            second["sourceBase"]["nativeThread"], first["sourceBase"]["nativeThread"]
        )
        self.assertEqual(len(list((self.f.state / "channels").glob("*.json"))), 2)

    def test_foreign_frame_and_cancelled_work_never_grant(self):
        with self.assertRaises(Held):
            self.f.ensure("forged")
        self.f.snapshot["delivery"]["cancellation_requested"] = True
        with self.assertRaises(Held):
            self.f.ensure()
        self.f.snapshot["delivery"]["cancellation_requested"] = False
        self.f.work_row["owner"] = uid(99)
        with self.assertRaises(Held):
            self.f.ensure()
        self.assertFalse([c for c in self.f.calls if c[0] == "PUT"])

    def test_revoked_or_replaced_root_does_not_get_reactivated(self):
        self.f.targets = [
            {
                "id": self.f.resource,
                "state": "active",
                "grant_state": "revoked",
                "revision": 1,
                "grant_revision": 2,
                "work_revision": 4,
            }
        ]
        with self.assertRaises(Held):
            self.f.ensure()
        self.f.targets = []
        self.f.physical["inode"] += 1
        with self.assertRaises(Held):
            self.f.ensure()
        self.assertFalse([c for c in self.f.calls if c[0] == "PUT"])

    def test_unknown_administrative_grant_inspects_original_without_repeating(self):
        self.f.lost = True
        self.f.ensure()
        self.f.ensure()
        self.assertEqual(len([c for c in self.f.calls if c[0] == "PUT"]), 1)
        self.assertEqual(
            len(
                [c for c in self.f.calls if c[1].startswith("administration/commands/")]
            ),
            1,
        )

    def test_changed_original_administrative_wire_is_held(self):
        calls = []

        def http(method, route, body=None):
            calls.append(method)
            if method == "PUT":
                raise TimeoutError()
            return {
                "method": "PUT",
                "path": "wrong",
                "wireDigest": "wrong",
                "acceptedResult": {},
            }

        payload = {"operationId": "fixture-once", "revision": 0}
        for _ in range(2):
            with self.assertRaises(Held):
                administrative_put(self.f.state, http, "fixed-route", payload)
        self.assertEqual(calls, ["PUT", "GET", "GET"])

    def test_no_structured_work_holds_without_hidden_admission(self):
        self.f.snapshot["request"]["data"] = {}
        with self.assertRaisesRegex(Held, "structured work"):
            self.f.ensure()
        self.assertFalse([c for c in self.f.calls if c[0] == "PUT"])
        self.assertEqual(list((self.f.state / "channels").glob("*.json")), [])

    def intent_fixture(self):
        record = self.f.ensure()
        bridge = object.__new__(Bridge)
        bridge.state = self.f.state
        bridge.captured = lambda *args: (
            record,
            {"tool": "collaborative_edit_plan"},
            {
                "editPlans": True,
                "physicalTargets": True,
                "bridge": {"protocol": "canonical-edit-plans/v2"},
            },
        )
        observed = []
        bridge.relay = lambda *args: (
            observed.append(args) or {"receipt": {"accepted": True}}
        )
        frame = {
            "port": "edit-plans",
            "arguments": {
                "command": {
                    "action": "propose",
                    "workId": self.f.work,
                    "planId": uid(100),
                    "manifest": {"files": []},
                }
            },
            "evidence": {"environmentId": "local", "cwd": self.f.root.as_uri()},
        }
        return bridge, record, frame, observed

    def test_installed_intent_root_is_separate_from_unchanged_private_cwd(self):
        bridge, record, frame, observed = self.intent_fixture()
        cwd = frame["evidence"]["cwd"]
        result = bridge.handle((os.getpid(), os.geteuid(), 0), frame)
        self.assertTrue(result["success"])
        self.assertEqual(observed[0][4]["root"], self.f.physical["root"])
        self.assertEqual(frame["evidence"]["cwd"], cwd)
        self.assertEqual(record["sourceBase"]["contextId"], "private-context")

    def test_model_cannot_choose_a_resource_or_invent_a_default(self):
        bridge, record, frame, observed = self.intent_fixture()
        frame["evidence"]["workspaceId"] = self.f.resource
        with self.assertRaises(Held):
            bridge.handle((os.getpid(), os.geteuid(), 0), frame)
        frame["evidence"].pop("workspaceId")
        record["resources"][0]["defaultForIntent"] = False
        with self.assertRaises(Held):
            bridge.handle((os.getpid(), os.geteuid(), 0), frame)
        self.assertEqual(observed, [])

    def test_current_enrolled_native_peer_reaches_independent_observation(self):
        import sys

        image = Path(sys.executable).resolve().stat()
        actual = {
            **self.f.native,
            "executableDevice": image.st_dev,
            "executableInode": image.st_ino,
        }
        self.f.bridge.http = lambda *args: {
            "executors": [self.f.row],
            "nextAfter": None,
        }
        with (
            patch(
                "lax_connector.collaboration_capture.installed_native_owner",
                return_value=(self.f.agent, sys.executable),
            ),
            patch("lax_connector.collaboration_capture.process", return_value=actual),
            patch(
                "lax_connector.collaboration_capture.expected_owner",
                return_value=(os.geteuid(), None, sys.executable),
            ),
            patch(
                "lax_connector.collaboration_capture.observe", return_value=self.f.fact
            ) as independent,
        ):
            row, native, fact = AutomaticCapture.peer(
                self.f.capture, (os.getpid(), os.geteuid(), 0)
            )
        self.assertEqual(row["id"], self.f.executor)
        self.assertEqual(native["pid"], os.getpid())
        independent.assert_called_once()

    def test_unrelated_image_is_refused_without_querying_server(self):
        from unittest.mock import Mock

        self.f.bridge.http = Mock(
            side_effect=AssertionError("No unrelated server query")
        )
        with (
            patch(
                "lax_connector.collaboration_capture.installed_native_owner",
                return_value=(self.f.agent, "/usr/bin/python3"),
            ),
            patch(
                "lax_connector.collaboration_capture.process",
                return_value=self.f.native,
            ),
            patch(
                "lax_connector.collaboration_capture.expected_owner",
                return_value=(os.geteuid(), None, "/usr/bin/python3"),
            ),
        ):
            with self.assertRaises(Held):
                AutomaticCapture.peer(self.f.capture, (os.getpid(), os.geteuid(), 0))
        self.f.bridge.http.assert_not_called()

    def test_pre_frame_peer_authentication_rejects_another_process_owner(self):
        self.f.bridge.http = lambda *args: {
            "executors": [self.f.row],
            "nextAfter": None,
        }
        with (
            patch(
                "lax_connector.collaboration_capture.installed_native_owner",
                return_value=(self.f.agent, "/usr/bin/python3"),
            ),
            patch(
                "lax_connector.collaboration_capture.process",
                return_value=self.f.native,
            ),
            patch(
                "lax_connector.collaboration_capture.expected_owner",
                return_value=(os.geteuid() + 1, None, None),
            ),
            patch(
                "lax_connector.collaboration_capture.observe", return_value=self.f.fact
            ),
        ):
            with self.assertRaises(Held):
                AutomaticCapture.peer(self.f.capture, (os.getpid(), os.geteuid(), 0))


class InstallerTests(unittest.TestCase):
    def setUp(self):
        if os.geteuid() != 0:
            self.skipTest(
                "root-owned fixture semantics require administrator test route"
            )
        self.tmp = tempfile.TemporaryDirectory(prefix="lax-setup-unit-", dir="/run")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o711)
        self.checkout = self.root / "checkout"
        self.checkout.mkdir()
        self.host, self.authority, self.agent = uid(1), uid(2), uid(3)
        common = {
            "authorityId": self.authority,
            "hostId": self.host,
            "hollywoodUrl": "http://fixture.invalid",
            "machineIdentity": machine_identity(),
        }
        self.controller = self.root / "controller.json"
        self.controller.write_text(
            json.dumps(
                {
                    **common,
                    "state": str(self.root / "controller-state"),
                    "token": "synthetic-controller",
                }
            )
        )
        self.controller.chmod(0o600)
        self.admin = self.root / "administrator.json"
        self.admin.write_text(
            json.dumps({**common, "token": "synthetic-administrator"})
        )
        self.admin.chmod(0o600)
        (self.root / "units").mkdir()
        self.spec = {
            "schema": "lax-collaboration-install/v1",
            "controllerConfig": str(self.controller),
            "administratorConfig": str(self.admin),
            "runtimeDirectory": str(self.root / "public"),
            "socketDirectory": str(self.root / "socket"),
            "stateDirectory": str(self.root / "private"),
            "unitDirectory": str(self.root / "units"),
            "interpreter": "/usr/bin/python3",
            "resources": [{"name": "shared", "root": str(self.checkout)}],
            "agents": {
                self.agent: {"resources": ["shared"], "defaultResource": "shared"}
            },
        }

    def test_preparation_is_repeatable_and_exposes_no_admin_credential_to_native(self):
        with patch(
            "lax_connector.collaboration_install.expected_owner",
            return_value=(1000, None, None),
        ):
            first = prepare(self.spec, self.root / "prepared")
            second = prepare(self.spec, self.root / "prepared")
        self.assertEqual(first, second)
        descriptor = json.loads(
            (self.root / "prepared/channel.prepared.json").read_text()
        )
        self.assertEqual(set(descriptor), {"schema", "socket", "ports"})
        self.assertNotIn("native-child-admission", descriptor["ports"])
        self.assertFalse((self.root / "public").exists())
        self.assertEqual(first["modelsStarted"], 0)

    def test_private_ancestor_cannot_publish_an_unusable_native_descriptor(self):
        self.root.chmod(0o700)
        with patch(
            "lax_connector.collaboration_install.expected_owner",
            return_value=(1000, None, None),
        ):
            with self.assertRaisesRegex(Held, "private ancestor"):
                prepare(self.spec, self.root / "prepared")
        self.assertFalse((self.root / "public").exists())

    def test_apply_uses_separate_admin_and_controller_routes_without_starting_services(
        self,
    ):
        with patch(
            "lax_connector.collaboration_install.expected_owner",
            return_value=(1000, None, None),
        ):
            prepare(self.spec, self.root / "prepared")
        calls = []

        def http(url, token, method, route, payload=None):
            calls.append((token, method, route))
            if route.endswith("/admission"):
                return {"policy": {"controller": uid(10)}}
            if method == "GET" and route.endswith("/collaboration-bridge"):
                if token != "synthetic-administrator":
                    raise PermissionError("403: bridge is not enrolled yet")
                return {"bridge": None}
            if route.endswith("/collaboration-bridge"):
                return {"bridge": {"revision": 1}}
            if route.startswith("physical-workspaces/") and "/agent-grants/" in route:
                return {"grant": {"revision": 1}}
            if "/physical-workspaces/" in route:
                return {"workspace": {"revision": 1}}
            raise AssertionError(route)

        with (
            patch("lax_connector.collaboration_install.request", side_effect=http),
            patch("subprocess.run") as start,
        ):
            receipt = apply(self.root / "prepared")
            start.assert_not_called()
        self.assertEqual(receipt["servicesStarted"], 0)
        loaded = Bridge(Path(receipt["configPath"]))
        automatic = AutomaticCapture(loaded)
        self.assertEqual(automatic.config["token"], "synthetic-controller")
        self.assertEqual(
            json.loads(self.controller.read_text())["token"], "synthetic-controller"
        )
        self.assertTrue(
            all(
                token == "synthetic-administrator"
                for token, method, route in calls
                if method == "PUT"
            )
        )
        self.assertTrue(
            all(
                token
                == (
                    "synthetic-administrator"
                    if route.endswith("/collaboration-bridge")
                    else "synthetic-controller"
                )
                for token, method, route in calls
                if method == "GET"
            )
        )
        channel = Path(receipt["channelPath"])
        self.assertEqual(channel.stat().st_mode & 0o777, 0o644)
