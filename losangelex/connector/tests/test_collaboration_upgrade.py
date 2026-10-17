"""Bounded offline upgrade fixtures. No real services, canonical writes or model calls."""

import copy
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from lax_connector import collaboration_upgrade as upgrade
from lax_connector.collaboration_bridge import Bridge, Held
from lax_connector.collaboration_install import prepare
from lax_connector.journal import saved
import test_collaboration_capture as capture_fixture
from test_collaboration_capture import uid


@unittest.skipUnless(os.geteuid() == 0, "root-owned fixture route required")
class BridgeUpgradeTests(unittest.TestCase):
    setUp = capture_fixture.InstallerTests.setUp

    def fixture(self):
        with patch(
            "lax_connector.collaboration_install.expected_owner",
            return_value=(0, self.root, "/usr/bin/python3"),
        ):
            prepare(self.spec, self.root / "prepared")
        self.prepared = self.root / "prepared"
        self.manifest = json.loads((self.prepared / "setup.json").read_text())
        self.state = Path(self.manifest["stateDirectory"])
        for name in ("", "channels", "commands", "administration"):
            (self.state / name).mkdir(mode=0o700, exist_ok=True)
        self.config_path = Path(self.manifest["configPath"])
        self.unit_path = Path(self.manifest["unitPath"])
        self.descriptor_path = Path(self.manifest["runtimeDirectory"]) / "channel.json"
        self.descriptor_path.parent.mkdir(mode=0o755)
        candidate = json.loads((self.prepared / "bridge.prepared.json").read_text())
        self.old = copy.deepcopy(candidate)
        self.old["adapterSha256"] = "a" * 64
        self.old["automaticCapture"]["schema"] = "lax-automatic-native-capture/v1"
        self.old["automaticCapture"]["agents"] = json.loads(
            (self.prepared / "agent-access-seeds.json").read_text()
        )
        for root in self.old["automaticCapture"]["resources"]:
            root["registryRevision"] = 3
        saved(self.config_path, self.old)
        saved(
            self.descriptor_path,
            json.loads((self.prepared / "channel.prepared.json").read_text()),
        )
        self.unit_path.write_bytes(b"original-unit\n")
        self.unit_path.chmod(0o644)
        saved(self.state / "setup-receipt.json", {"original": "unchanged"})
        self.original_receipt = (self.state / "setup-receipt.json").read_bytes()
        home = self.root / "consumer"
        (home / "state").mkdir(parents=True)
        (home / "state/connector.lock").touch(mode=0o600)
        registry = self.root / "registry"
        registry.mkdir(mode=0o700)
        controller = json.loads(self.controller.read_text())
        controller["nativeCollaborationCaptureConfig"] = str(self.config_path)
        saved(self.controller, controller)
        Path(controller["state"]).mkdir(mode=0o700)
        (Path(controller["state"]) / "controller.lock").touch(mode=0o600)
        controller_unit_path = self.root / "units/controller.service"
        controller_unit_path.write_text(
            "ExecStart=/usr/bin/python3 -m lax_connector.host --serve "
            + str(self.controller)
            + "\n"
        )
        self.enterContext(patch("lax_connector.resource_routing.seed_defaults", return_value=[]))
        self.calls = []
        self.info = {
            "ActiveState": "inactive",
            "MainPID": "0",
            "ControlGroup": "",
            "User": "root",
            "FragmentPath": str(controller_unit_path),
        }
        self.kwargs = {
            "expected_revision": 4,
            "expected_config_sha256": upgrade.file_sha(self.config_path),
            "expected_unit_sha256": upgrade.file_sha(self.unit_path),
            "expected_descriptor_sha256": upgrade.file_sha(self.descriptor_path),
            "agents": [self.agent],
            "controller_unit": "controller.service",
            "expected_controller_unit_sha256": upgrade.file_sha(self.unit_path),
        }
        self.enterContext(patch.object(upgrade, "_clients", return_value={self.agent}))
        self.enterContext(
            patch.object(
                upgrade.observer,
                "expected_owner",
                return_value=(0, home, "/usr/bin/python3"),
            )
        )
        self.enterContext(
            patch.object(upgrade.observer, "directory", return_value=registry)
        )
        self.enterContext(
            patch.object(upgrade.observer, "properties", return_value=self.info)
        )
        self.enterContext(
            patch.object(
                upgrade.observer,
                "unit_definition",
                return_value=self.kwargs["expected_unit_sha256"],
            )
        )
        self.drain = self.enterContext(
            patch.object(
                upgrade, "_drain", return_value={self.agent: {"settled": True}}
            )
        )

        def request(url, token, method, route, body=None):
            self.calls.append((token, method, route, copy.deepcopy(body)))
            if method == "GET" and route.endswith("/collaboration-bridge"):
                return {
                    "resourceRouting": "canonical-agent-resources/v1", "resourceDefaults": True, "resourceMetadata": True,
                    "placementControl": "canonical-placement-control/v1", "pausedResourceSetup": True,
                    "bridge": {
                        "state": "active",
                        "protocol": "canonical-edit-plans/v2",
                        "revision": 4,
                        "adapter_sha256": "a" * 64,
                        "controller": self.agent,
                    }
                }
            if method == "PUT":
                return {"accepted": True, "revision": 5}
            raise AssertionError((method, route))

        self.enterContext(patch.object(upgrade, "request", side_effect=request))

    def test_drained_original_cas_archives_history_and_requires_separate_activation(
        self,
    ):
        self.fixture()
        result = upgrade.upgrade(self.prepared, **self.kwargs)
        self.assertTrue(result["activationRequired"])
        self.assertEqual(result["servicesStarted"], 0)
        self.assertFalse(result["unknownEffectsCleared"])
        self.assertEqual(
            (self.state / "setup-receipt.json").read_bytes(), self.original_receipt
        )
        self.assertEqual(
            Path(result["beforeArchive"]).joinpath("bridge.service").read_bytes(),
            b"original-unit\n",
        )
        self.assertEqual(
            json.loads(self.config_path.read_text())["automaticCapture"]["schema"],
            "lax-automatic-native-capture/v2",
        )
        self.assertEqual(len([x for x in self.calls if x[1] == "PUT"]), 2)
        upgrade.require_settled_upgrades(self.state)
        with self.assertRaises(Held):
            upgrade.upgrade(self.prepared, **self.kwargs)
        self.assertEqual(len([x for x in self.calls if x[1] == "PUT"]), 2)

    def test_original_artifact_or_revision_cas_change_is_held(self):
        self.fixture()
        self.config_path.write_bytes(self.config_path.read_bytes() + b" ")
        with self.assertRaisesRegex(Held, "artifact CAS"):
            upgrade.upgrade(self.prepared, **self.kwargs)
        self.assertEqual(self.calls, [])

    def test_running_original_controller_blocks_before_any_canonical_put(self):
        self.fixture()
        self.info["ActiveState"] = "active"
        self.info["MainPID"] = "12345"
        with self.assertRaisesRegex(Held, "Original controller must remain stopped"):
            upgrade.upgrade(self.prepared, **self.kwargs)
        self.assertFalse([row for row in self.calls if row[1] == "PUT"])

    def test_all_affected_consumers_need_explicit_scope(self):
        self.fixture()
        self.kwargs["agents"] = [uid(999)]
        with self.assertRaisesRegex(Held, "explicit upgrade/drain scope"):
            upgrade.upgrade(self.prepared, **self.kwargs)
        self.assertEqual(self.calls, [])

    def test_after_canonical_cas_interruption_retains_intent_and_startup_hold(self):
        self.fixture()
        self.drain.side_effect = [
            {self.agent: {"settled": True}},
            {self.agent: {"settled": True}},
            {"changed": True},
        ]
        with self.assertRaisesRegex(Held, "after canonical CAS"):
            upgrade.upgrade(self.prepared, **self.kwargs)
        self.assertEqual(len([x for x in self.calls if x[1] == "PUT"]), 1)
        self.assertEqual(json.loads(self.config_path.read_text()), self.old)
        self.assertEqual(len(list((self.state / "upgrades").glob("*-intent.json"))), 1)
        with self.assertRaisesRegex(Held, "unsettled"):
            Bridge(self.config_path)
        with self.assertRaisesRegex(Held, "unsettled"):
            upgrade.upgrade(self.prepared, **self.kwargs)
        self.assertEqual(len([x for x in self.calls if x[1] == "PUT"]), 1)

    def test_unknown_root_command_never_expires_or_clears_during_drain(self):
        self.fixture()
        saved(
            self.state / "commands/unknown.json",
            {"state": "unknown", "wire": {"command": {"action": "begin"}}},
        )

        # Call the original function, with no consumers, so only host and protected command state are observed.
        def relay(method, route):
            return {"executors": [], "nextAfter": None}

        with self.assertRaisesRegex(Held, "pending/unknown"):
            DRAIN(self.old, self.state, set(), relay)
        self.assertEqual(
            json.loads((self.state / "commands/unknown.json").read_text())["state"],
            "unknown",
        )

    def test_effective_held_direct_permit_is_not_raw_settled(self):
        self.fixture()
        permit = uid(77)
        saved(
            self.state / "commands/done.json",
            {
                "state": "completed",
                "wire": {
                    "scope": "delivery",
                    "command": {"action": "begin", "permitId": permit},
                },
            },
        )

        def relay(method, route):
            if route.endswith("/executors"):
                return {"executors": [], "nextAfter": None}
            return {
                "permit": {"state": "settled"},
                "effectiveState": "held",
                "mayApply": False,
            }

        with self.assertRaisesRegex(Held, "held/unsettled"):
            DRAIN(self.old, self.state, set(), relay)


DRAIN = upgrade._drain
