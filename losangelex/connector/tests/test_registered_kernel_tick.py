"""Host tick selection; real protected fixture files, synthetic manager/kernel facts.

The separate integration_managed_kernel_incarnation journey verifies real pins.
No service, process, manager operation or model is started by these fixtures.
"""
import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_operating_readiness as fixtures
from lax_connector import kernel_incarnation as kernel
from lax_connector import purpose_observer as purpose
from lax_connector import service_observer as observer
from lax_connector import service_restart as restart
from lax_connector.journal import saved


@unittest.skipUnless(os.geteuid() == 0, "Root protected fixture route")
class RegisteredManagedTickTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RestartRecoveryTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        # Seed through the unchanged manager registration path before the outage.
        with patch.object(kernel, "invocation", side_effect=kernel.Unavailable("fixture")):
            restart.reconcile_one(self.fixture.config, self.fixture.agent, [])
        self.binding = observer.protected(self.fixture.target)
        self.before = {p.name: p.read_bytes() for p in self.fixture.registry.glob("*.json")}
        self.enterContext(patch.object(kernel, "invocation", return_value=self.binding["serviceInvocation"]))

    def tick(self):
        return restart.reconcile_one(self.fixture.config, self.fixture.agent, [])

    def assert_originals(self):
        self.assertEqual({p.name: p.read_bytes() for p in self.fixture.registry.glob("*.json")}, self.before)

    def test_registered_live_tick_avoids_manager_during_outage(self):
        with (patch.object(kernel, "managed_guardian", return_value={"pid": self.fixture.newpid}) as guard,
              patch.object(observer, "properties", side_effect=TimeoutError("manager outage")) as manager):
            self.assertEqual(self.tick(), {"state": "registered", "changed": False,
                "agentId": self.fixture.agent, "observationSource": "kernel-incarnation",
                "managerStateInspected": False})
            guard.assert_called_once_with(self.binding)
            manager.assert_not_called()
        self.assert_originals()

    def test_unavailable_kernel_keeps_manager_failure_unknown(self):
        with (patch.object(kernel, "managed_guardian", side_effect=kernel.Unavailable("no complete binding")),
              patch.object(observer, "properties", side_effect=TimeoutError("manager outage")) as manager):
            with self.assertRaises(TimeoutError):
                self.tick()
            manager.assert_called()
        self.assert_originals()

    def test_changed_kernel_pin_holds_without_manager_fallback(self):
        with (patch.object(kernel, "managed_guardian", side_effect=PermissionError("changed pin")),
              patch.object(observer, "properties", side_effect=AssertionError("must not query")) as manager):
            with self.assertRaises(PermissionError):
                self.tick()
            manager.assert_not_called()
        self.assert_originals()

    def test_new_invocation_keeps_manager_inspection(self):
        observer.properties.reset_mock()
        with (patch.object(kernel, "invocation", return_value="f" * 32),
              patch.object(kernel, "managed_guardian") as guard):
            self.assertFalse(self.tick()["changed"])
            observer.properties.assert_called()
            guard.assert_not_called()
        self.assert_originals()

    def test_unsettled_transition_is_checked_before_kernel_shortcut(self):
        saved(self.fixture.registry / "upgrade-pending.json",
              {"schema": "lax-service-upgrade/v1", "state": "intent"})
        with patch.object(kernel, "managed_guardian") as guard:
            with self.assertRaisesRegex(ValueError, "definition transition"):
                self.tick()
            guard.assert_not_called()

    def test_foreign_policy_or_registered_owner_cannot_select_another_service(self):
        for path, value in ((self.fixture.registry / restart.POLICY,
                             observer.protected(self.fixture.registry / restart.POLICY)),
                            (self.fixture.target, self.binding)):
            before = path.read_bytes()
            changed = copy.deepcopy(value)
            changed["agentId"] = fixtures.uid(99)
            saved(path, changed)
            with patch.object(kernel, "managed_guardian") as guard:
                with self.assertRaises((ValueError, PermissionError)):
                    self.tick()
                guard.assert_not_called()
            path.write_bytes(before)
        self.assert_originals()


@unittest.skipUnless(os.geteuid() == 0, "Root protected fixture route")
class RegisteredPurposeTickTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="lax-purpose-tick-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "incarnations").mkdir()
        self.unit, self.invocation = "lax-fixture-writer.service", "a" * 32
        self.value = {"authorityId": fixtures.uid(1), "agentId": fixtures.uid(3),
                      "units": {"writer": self.unit}}
        self.binding = {"unit": self.unit, "serviceInvocation": self.invocation}
        self.target = self.root / "incarnations" / (self.invocation + ".json")
        saved(self.target, self.binding)
        self.enterContext(patch.object(purpose, "validate"))
        self.enterContext(patch.object(purpose, "directory", return_value=self.root))
        original_path = Path
        self.enterContext(patch.object(purpose, "Path", side_effect=lambda p, *args:
            self.root / "absent-runtime-profile" if str(p) == "/run/systemd/units"
            else original_path(p, *args)))
        self.enterContext(patch.object(kernel, "invocation", return_value=self.invocation))

    def test_registered_purpose_avoids_manager_during_outage(self):
        before = self.target.read_bytes()
        with (patch.object(kernel, "guardian", return_value={"pid": 123}) as guard,
              patch.object(observer, "properties", side_effect=TimeoutError("manager outage")) as manager):
            self.assertEqual(purpose.register(self.value, "writer"), {
                "state": "registered", "purpose": "writer", "changed": False,
                "unit": self.unit, "serviceInvocation": self.invocation, "servicesStarted": 0,
                "observationSource": "kernel-incarnation", "managerStateInspected": False})
            guard.assert_called_once_with(self.value, self.binding)
            manager.assert_not_called()
        self.assertEqual(self.target.read_bytes(), before)

    def test_changed_purpose_pin_does_not_fall_back_or_rewrite(self):
        before = self.target.read_bytes()
        with (patch.object(kernel, "guardian", side_effect=PermissionError("changed pin")),
              patch.object(observer, "properties") as manager):
            with self.assertRaises(PermissionError):
                purpose.register(self.value, "writer")
            manager.assert_not_called()
        self.assertEqual(self.target.read_bytes(), before)

    def test_new_purpose_invocation_still_requires_manager(self):
        with (patch.object(kernel, "invocation", return_value="b" * 32),
              patch.object(observer, "properties", side_effect=TimeoutError("manager outage")) as manager):
            with self.assertRaises(TimeoutError):
                purpose.register(self.value, "writer")
            manager.assert_called_once_with(self.unit)


if __name__ == "__main__":
    unittest.main()
