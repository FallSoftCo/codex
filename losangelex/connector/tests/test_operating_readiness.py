"""Changed registration/memory/routing mechanics; real private files, synthetic host facts."""

import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from lax_connector import service_restart as restart, service_memory as memory
from lax_connector import service_observer as observer, service_admin
from lax_connector.journal import saved
from lax_connector.collaboration_bridge import digest, Held
from test_collaboration_capture import uid


@unittest.skipUnless(os.geteuid() == 0, "Root protected fixture route")
class RestartRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lax-readiness-", dir="/run")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.authority, self.host, self.agent = uid(1), uid(2), uid(3)
        self.registry = (
            self.root
            / "harness"
            / self.authority
            / "hosts"
            / self.host
            / "services"
            / self.agent
        )
        self.registry.mkdir(parents=True)
        self.home = self.root / "home"
        self.home.mkdir()
        (self.home / "state").mkdir()
        self.image = self.root / "codex"
        self.image.write_bytes(b"synthetic native file, never executed")
        self.image.chmod(0o600)
        self.guardian_image = self.root / "python"
        self.guardian_image.write_bytes(b"synthetic guardian, never executed")
        self.guardian_image.chmod(0o600)
        self.unit = self.root / "lax-fixture.service"
        self.unit.write_text("[Service]\nMemoryMax=2G\nKillMode=control-group\n")
        self.unit.chmod(0o644)
        self.configfile = self.home / "connector.json"
        saved(
            self.configfile,
            {
                "model": "unchanged",
                "effort": "unchanged",
                "sandbox": "danger-full-access",
            },
        )
        self.oldpid, self.newpid = 1001, 2002
        self.info = {
            "Id": "lax-fixture.service",
            "ActiveState": "active",
            "MainPID": str(self.oldpid),
            "InvocationID": uid(4).replace("-", ""),
            "ControlGroup": "/fixture",
            "User": "root",
            "KillMode": "control-group",
            "FragmentPath": str(self.unit),
            "MemoryMax": str(2 * 1024**3),
            "MemoryCurrent": "193011712",
            "MemoryPeak": str(2 * 1024**3),
        }
        self.processes = {
            self.oldpid: {
                "pid": self.oldpid,
                "start": "old-start",
                "uid": 0,
                "controlGroup": "/fixture",
            }
        }
        self.groups = {"/fixture": {self.oldpid}}
        self.enterContext(
            patch.object(
                observer, "expected_owner", return_value=(0, self.home, str(self.image))
            )
        )
        self.enterContext(
            patch.object(observer, "directory", return_value=self.registry)
        )
        self.enterContext(
            patch.object(observer, "installed_unit", return_value="lax-fixture.service")
        )
        self.enterContext(
            patch.object(
                observer,
                "properties",
                side_effect=lambda unit: copy.deepcopy(self.info),
            )
        )
        self.enterContext(
            patch.object(
                observer,
                "process",
                side_effect=lambda pid: (
                    {
                        "executable": str(self.guardian_image),
                        "executableDevice": self.guardian_image.stat().st_dev,
                        "executableInode": self.guardian_image.stat().st_ino,
                        **copy.deepcopy(self.processes[pid]),
                    }
                    if pid in self.processes
                    else None
                ),
            )
        )
        self.enterContext(
            patch.object(
                observer,
                "members",
                side_effect=lambda group: set(self.groups.get(group, set())),
            )
        )
        self.enterContext(
            patch.object(observer, "machine_identity", return_value="machine")
        )
        self.enterContext(patch.object(observer, "boot_id", return_value=uid(9)))
        observer._register(self.authority, self.host, self.agent, "lax-fixture.service")
        self.baseline = observer.protected(self.registry / "enrollment.json")
        self.enrollment = digest(self.baseline)
        self.definition = hashlib.sha256(self.unit.read_bytes()).hexdigest()
        self.config = {
            "authorityId": self.authority,
            "hostId": self.host,
            "machineIdentity": "machine",
            "state": str(self.root / "controller"),
            "hollywoodUrl": "http://fixture.invalid",
            "token": "synthetic",
        }
        Path(self.config["state"]).mkdir()
        self.expected_image = hashlib.sha256(self.image.read_bytes()).hexdigest()
        self.expected_config = hashlib.sha256(self.configfile.read_bytes()).hexdigest()
        restart.approve(
            self.authority,
            self.host,
            self.agent,
            self.enrollment,
            self.definition,
            self.expected_image,
            self.expected_config,
        )
        self.info.update(MainPID=str(self.newpid), InvocationID=uid(5).replace("-", ""))
        self.processes = {
            self.newpid: {
                "pid": self.newpid,
                "start": "new-start",
                "uid": 0,
                "controlGroup": "/fixture",
            }
        }
        self.groups = {"/fixture": {self.newpid}}

    @property
    def target(self):
        return self.registry / (self.info["InvocationID"] + ".json")

    def test_idle_restart_becomes_registered_without_manual_register_or_model(self):
        with (
            patch.object(
                memory,
                "approved_spec",
                return_value=({"interpreter": "/usr/bin/python3"}, {}, False),
            ),
            patch.object(
                service_admin,
                "preflight_as_owner",
                return_value={"ready": True, "modelsStarted": 0},
            ),
        ):
            self.assertEqual(
                service_admin.inspect(self.authority, self.host, self.agent)["reason"],
                "invocation-registration-required",
            )
            first = restart.reconcile_one(self.config, self.agent, [])
            self.assertTrue(first["changed"])
            self.assertFalse(first["newExecutionAdmitted"])
            self.assertTrue(
                service_admin.inspect(self.authority, self.host, self.agent)["ready"]
            )
        before = self.target.read_bytes()
        self.assertFalse(restart.reconcile_one(self.config, self.agent, [])["changed"])
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(
            observer.protected(self.registry / "enrollment.json"), self.baseline
        )
        self.assertTrue((self.registry / (uid(4).replace("-", "") + ".json")).exists())

    def test_controller_scans_approved_idle_services_and_never_posts_work(self):
        original_path = Path

        def mapped_path(value, *args):
            return (
                self.root / "harness"
                if str(value) == "/var/lib/harness"
                else original_path(value, *args)
            )

        with (
            patch.object(restart, "Path", side_effect=mapped_path),
            patch(
                "lax_connector.host.request",
                return_value={"executors": [], "nextAfter": None},
            ) as http,
        ):
            result = restart.reconcile_services(self.config)
        self.assertEqual(
            (result["registered"], result["held"], result["modelsStarted"]), (1, 0, 0)
        )
        self.assertEqual(http.call_args.args[2], "GET")

    def test_stopped_service_and_leftover_helper_never_register(self):
        self.info.update(ActiveState="inactive", MainPID="0")
        with self.assertRaises(restart.ServiceStopped):
            restart.reconcile_one(self.config, self.agent, [])
        self.info.update(ActiveState="active", MainPID=str(self.newpid))
        self.groups["/fixture"].add(777)
        with self.assertRaisesRegex(ValueError, "alone"):
            restart.reconcile_one(self.config, self.agent, [])
        self.assertFalse(self.target.exists())

    def test_live_old_guardian_and_unknown_old_executor_hold_independently(self):
        self.processes[self.oldpid] = {
            "pid": self.oldpid,
            "start": "old-start",
            "uid": 0,
            "controlGroup": "/old",
        }
        with self.assertRaisesRegex(ValueError, "guardian remains live"):
            restart.reconcile_one(self.config, self.agent, [])
        self.processes.pop(self.oldpid)
        row = {
            "agent": self.agent,
            "descriptor": {"serviceInvocation": uid(4).replace("-", "")},
            "state": "unknown",
        }
        original = copy.deepcopy(row)
        with patch.object(observer, "observe", return_value={"state": "unknown"}):
            with self.assertRaisesRegex(ValueError, "stop remains unknown"):
                restart.reconcile_one(self.config, self.agent, [row])
        self.assertEqual(row, original)
        self.assertFalse(self.target.exists())

    def test_already_admitted_unlaunched_reservation_is_only_metadata_registered(self):
        row = {
            "agent": self.agent,
            "launch_phase": "reserved",
            "state": "unknown",
            "descriptor": {
                "serviceInvocation": self.info["InvocationID"],
                "nativePid": None,
                "guardianPid": self.newpid,
                "guardianStart": "new-start",
                "serviceUnit": "lax-fixture.service",
                "bootId": uid(9),
                "machineIdentity": "machine",
                "controlGroup": "/fixture",
            },
        }
        original = copy.deepcopy(row)
        result = restart.reconcile_one(self.config, self.agent, [row])
        self.assertFalse(result["originalExecutorStateChanged"])
        self.assertFalse(result["newExecutionAdmitted"])
        self.assertEqual(row, original)

    def test_changed_native_config_or_definition_never_auto_approves(self):
        for path in [self.image, self.configfile, self.unit]:
            before = path.read_bytes()
            path.write_bytes(before + b" ")
            with self.subTest(path=path.name):
                with self.assertRaises(ValueError):
                    restart.reconcile_one(self.config, self.agent, [])
                self.assertFalse(self.target.exists())
            path.write_bytes(before)
            # Restore the approved identity only by a fresh explicit reviewed approval.
            old = observer.protected(self.registry / restart.POLICY)
            self.info.update(
                MainPID=str(self.oldpid), InvocationID=uid(4).replace("-", "")
            )
            self.processes[self.oldpid] = {
                "pid": self.oldpid,
                "start": "old-start",
                "uid": 0,
                "controlGroup": "/fixture",
            }
            restart.approve(
                self.authority,
                self.host,
                self.agent,
                self.enrollment,
                self.definition,
                self.expected_image,
                self.expected_config,
                digest(old),
            )
            self.info.update(
                MainPID=str(self.newpid), InvocationID=uid(5).replace("-", "")
            )
            self.processes.pop(self.oldpid)

    def test_unsettled_definition_or_native_transition_holds(self):
        path = self.registry / "upgrade-pending.json"
        saved(path, {"schema": "lax-service-upgrade/v1", "state": "intent"})
        with self.assertRaisesRegex(ValueError, "definition transition"):
            restart.reconcile_one(self.config, self.agent, [])
        path.unlink()
        saved(self.registry / "image-pending-intent.json", {"state": "intent"})
        with self.assertRaisesRegex(ValueError, "explicit reconciliation"):
            restart.reconcile_one(self.config, self.agent, [])
        self.assertFalse(self.target.exists())

    def test_approval_missing_changed_cas_and_incarnation_race_do_not_publish(self):
        policy = observer.protected(self.registry / restart.POLICY)
        with self.assertRaises(ValueError):
            restart.approve(
                self.authority,
                self.host,
                self.agent,
                self.enrollment,
                "0" * 64,
                self.expected_image,
                self.expected_config,
                digest(policy),
            )
        count = 0

        def properties(unit):
            nonlocal count
            count += 1
            value = copy.deepcopy(self.info)
            if count >= 3:
                value["InvocationID"] = uid(99).replace("-", "")
            return value

        with patch.object(observer, "properties", side_effect=properties):
            with self.assertRaisesRegex(ValueError, "before publication"):
                restart.reconcile_one(self.config, self.agent, [])
        self.assertFalse(self.target.exists())
        self.assertFalse(
            (self.registry / (uid(99).replace("-", "") + ".json")).exists()
        )
        (self.registry / restart.POLICY).unlink()
        with self.assertRaises(FileNotFoundError):
            restart.reconcile_one(self.config, self.agent, [])

    def test_memory_plan_changes_only_preview_and_retains_original_spec(self):
        spec = {"approved": "historical", "model": "same", "effort": "same"}
        receipt = {"unitDigest": self.definition}
        with patch.object(memory, "approved_spec", return_value=(spec, receipt, False)):
            before = self.unit.read_bytes()
            result = memory.prepare(
                self.authority,
                self.host,
                self.agent,
                8 * 1024**3,
                self.enrollment,
                self.definition,
                self.root / "memory-plan",
            )
            inspected = memory.inspection(
                self.authority, self.agent, {**self.info, "MemoryMax": str(8 * 1024**3)}
            )
        self.assertEqual(self.unit.read_bytes(), before)
        self.assertFalse(result["liveUnitChanged"])
        self.assertIn(
            "MemoryMax=8589934592",
            (self.root / "memory-plan/service.prepared").read_text(),
        )
        self.assertEqual(inspected["approvedProvisioningMemoryMaxBytes"], 2 * 1024**3)
        self.assertEqual(inspected["runtimeMemoryMax"], str(8 * 1024**3))
        self.assertFalse(inspected["memoryLeakFixed"])


class MemoryConfigurationTests(unittest.TestCase):
    def test_fresh_default_is_explicit_but_legacy_spec_and_unit_bytes_are_retained(
        self,
    ):
        from lax_connector.linux_worker import expected_unit

        with tempfile.TemporaryDirectory() as name:
            intent = Path(name) / "intent.json"
            spec = {"interpreter": "/usr/bin/python3"}
            fresh = memory.provisioning_spec(spec, intent)
            self.assertEqual(fresh["serviceMemoryMaxBytes"], 8 * 1024**3)
            self.assertTrue(fresh["automaticRestartRegistration"])
            saved(intent, {"spec": spec})
            self.assertEqual(memory.provisioning_spec(spec, intent), spec)
            self.assertIn(
                "MemoryMax=2G", expected_unit(spec, uid(1), "fixture", Path(name))
            )
            self.assertIn(
                "MemoryMax=8589934592",
                expected_unit(fresh, uid(1), "fixture", Path(name)),
            )
            saved(intent, {"spec": fresh})
            self.assertEqual(memory.provisioning_spec(spec, intent), fresh)
        for value in [True, "8G", 1, -1, 2**50]:
            with self.assertRaises(ValueError):
                memory.validate(value)

    def test_memory_does_not_change_worker_model_effort_or_execution_permissions(self):
        from lax_connector.linux_worker import expected_configuration, expected_unit

        spec = {
            "hollywoodUrl": "http://fixture.invalid",
            "credential": "synthetic",
            "hostId": uid(2),
            "binary": "/opt/native/bin/codex",
            "model": "existing",
            "effort": "high",
            "interpreter": "/usr/bin/python3",
        }
        old = expected_configuration(spec, uid(1), uid(3), Path("/fixture"))
        new = expected_configuration(
            {**spec, "serviceMemoryMaxBytes": 8 * 1024**3},
            uid(1),
            uid(3),
            Path("/fixture"),
        )
        self.assertEqual(
            {k: v for k, v in new.items() if k != "serviceMemoryMaxBytes"}, old
        )
        a = expected_unit(spec, uid(3), "fixture", Path("/fixture"))
        b = expected_unit(
            {**spec, "serviceMemoryMaxBytes": 8 * 1024**3},
            uid(3),
            "fixture",
            Path("/fixture"),
        )
        self.assertEqual(a.replace("MemoryMax=2G", "MemoryMax=8589934592"), b)


@unittest.skipUnless(os.geteuid() == 0, "Root protected fixture route")
class RoutingReselectionTests(unittest.TestCase):
    def test_reviewed_paused_seed_reselects_only_known_invalidation_with_same_pins(
        self,
    ):
        import test_resource_routing as fixtures
        from lax_connector import resource_routing as routing

        f = fixtures.PlannedRoutingTests(
            methodName="test_current_explicit_default_routes_relative_intent_without_changing_capture_or_cwd"
        )
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.view.update(
            effectiveState="held", holdReason="participation-invalidated", resource=None
        )
        calls = []
        state = {"view": copy.deepcopy(f.view)}

        def http(method, path, body=None):
            calls.append((method, path, body))
            if path.startswith("placements/"):
                return {
                    "schema": "hollywood-placement/v1",
                    "authorityId": f.f.authority,
                    "agentId": f.f.agent,
                    "hostId": f.f.host,
                    "placement": {
                        "authority": f.f.authority,
                        "agent": f.f.agent,
                        "host": f.f.host,
                        "enabled": False,
                        "generation": 1,
                        "revision": 2,
                    },
                    "state": "paused",
                    "newExecutionAdmitted": False,
                    "drainVerified": False,
                    "mayApply": False,
                }
            if "/resource-defaults/" in path:
                if method == "PUT":
                    state["view"] = copy.deepcopy(f.view)
                    state["view"]["selectionRevision"] += 1
                    state["view"]["selection"]["revision"] += 1
                    state["view"]["holdReason"] = "participation-unavailable"
                return copy.deepcopy(state["view"])
            return f.http(method, path, body)

        args = (
            f.f.state,
            http,
            f.f.authority,
            f.f.host,
            {f.f.agent: {"defaultWorkspaceId": f.f.resource}},
            {f.f.resource: f.f.physical},
        )
        result = routing.seed_defaults(*args)
        self.assertEqual([c for c in calls if c[0] == "PUT"][0][2]["revision"], 19)
        self.assertEqual(result[0]["holdReason"], "participation-unavailable")
        routing.seed_defaults(*args)
        self.assertEqual(len([c for c in calls if c[0] == "PUT"]), 1)
        state["view"]["selection"]["grant_revision"] += 1
        with self.assertRaises(Held):
            routing.seed_defaults(*args)
        self.assertEqual(len([c for c in calls if c[0] == "PUT"]), 1)


@unittest.skipUnless(os.geteuid() == 0, "Root protected fixture route")
class FreshApprovalAndStopTests(unittest.TestCase):
    def fixture(self):
        f = RestartRecoveryTests(
            methodName="test_idle_restart_becomes_registered_without_manual_register_or_model"
        )
        f.setUp()
        self.addCleanup(f.doCleanups)
        return f

    def test_fresh_reviewed_provisioning_seeds_restart_approval_without_new_permission(
        self,
    ):
        f = self.fixture()
        (f.registry / restart.POLICY).unlink()
        f.info.update(MainPID=str(f.oldpid), InvocationID=uid(4).replace("-", ""))
        f.processes = {
            f.oldpid: {
                "pid": f.oldpid,
                "start": "old-start",
                "uid": 0,
                "controlGroup": "/fixture",
            }
        }
        f.groups = {"/fixture": {f.oldpid}}
        cfg = json.loads(f.configfile.read_text())
        receipt = {
            "configurationDigest": hashlib.sha256(
                json.dumps(cfg, sort_keys=True).encode()
            ).hexdigest(),
            "nativePackage": {"assets": {"entrypoint": {"sha256": f.expected_image}}},
        }
        with patch.object(
            memory,
            "approved_spec",
            return_value=({"automaticRestartRegistration": True}, receipt, False),
        ):
            result = observer.register(
                f.authority, f.host, f.agent, "lax-fixture.service"
            )
        self.assertTrue(result["automaticRestartApproval"]["approved"])
        self.assertEqual(observer.protected(f.registry / "enrollment.json"), f.baseline)

    def test_fresh_config_drift_refuses_before_registry_publication(self):
        f = self.fixture()
        (f.registry / restart.POLICY).unlink()
        receipt = {
            "configurationDigest": "0" * 64,
            "nativePackage": {"assets": {"entrypoint": {"sha256": f.expected_image}}},
        }
        with patch.object(
            memory,
            "approved_spec",
            return_value=({"automaticRestartRegistration": True}, receipt, False),
        ):
            with self.assertRaisesRegex(ValueError, "configuration differs"):
                observer.register(f.authority, f.host, f.agent, "lax-fixture.service")
        self.assertFalse(f.target.exists())

    def test_old_executor_stop_fact_remains_available_when_new_policy_is_held(self):
        f = self.fixture()
        old = observer.protected(f.registry / (uid(4).replace("-", "") + ".json"))
        f.configfile.write_text("changed")
        row = {
            "agent": f.agent,
            "launch_phase": "attached",
            "descriptor": {
                "serviceInvocation": old["serviceInvocation"],
                "serviceUnit": old["unit"],
                "controlGroup": old["controlGroup"],
                "guardianPid": old["guardianPid"],
                "guardianStart": old["guardianStart"],
                "bootId": old["bootId"],
                "machineIdentity": old["machineIdentity"],
                "nativePid": None,
                "nativeStart": None,
            },
        }
        fact = observer.observe(f.config, row)
        self.assertEqual(fact["state"], "stopped")
        self.assertFalse(fact["evidence"]["externalEffectsUndone"])

    def test_stopped_inspection_does_not_register_or_run_native_probes(self):
        f = self.fixture()
        f.info.update(ActiveState="inactive", MainPID="0")
        with (
            patch.object(memory, "approved_spec", return_value=({}, {}, False)),
            patch.object(service_admin, "preflight_as_owner") as native,
        ):
            result = service_admin.inspect(f.authority, f.host, f.agent)
        native.assert_not_called()
        self.assertEqual(result["reason"], "service-stopped")
        self.assertFalse(f.target.exists())


class NativeMemoryAdminTests(unittest.IsolatedAsyncioTestCase):
    async def test_verified_role_admin_forwards_explicit_cap_without_model_or_permission_changes(
        self,
    ):
        from unittest.mock import AsyncMock
        from lax_connector.administration import _administer

        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            saved(
                root / ("agent-credential-" + uid(7) + ".json"),
                {"authorityId": uid(3), "token": "synthetic"},
            )
            c = SimpleNamespace(
                state=root,
                role_context=SimpleNamespace(
                    value={
                        "communicationAdministrator": True,
                        "hostAdministrationVerified": True,
                    }
                ),
                config={
                    "agentId": uid(1),
                    "hostId": uid(2),
                    "codexHome": str(root / "codex"),
                    "hollywoodUrl": "http://fixture.invalid",
                    "binary": "/opt/native/bin/codex",
                    "model": "same-model",
                    "effort": "same-effort",
                },
                active={"request": {"authority": uid(3)}},
                http=AsyncMock(return_value={"home_room": uid(8)}),
            )
            child = SimpleNamespace(
                returncode=0,
                communicate=AsyncMock(return_value=(b'{"accepted":true}', b"")),
            )
            with patch(
                "lax_connector.administration.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=child),
            ) as process:
                await _administer(
                    c,
                    "lax_provision_worker",
                    {"agentId": uid(7), "serviceMemoryMaxBytes": 6 * 1024**3},
                    "original",
                )
            spec = json.loads(
                (root / ("worker-provision-" + uid(7) + ".json")).read_text()
            )
            self.assertEqual(spec["serviceMemoryMaxBytes"], 6 * 1024**3)
            self.assertEqual(
                (spec["model"], spec["effort"]), ("same-model", "same-effort")
            )
            self.assertEqual(process.await_count, 1)


class UnknownRoutingHoldTests(unittest.TestCase):
    @unittest.skipUnless(os.geteuid() == 0, "Root protected fixture route")
    def test_unknown_hold_never_reselects(self):
        import test_resource_routing as fixtures
        from lax_connector import resource_routing as routing

        f = fixtures.PlannedRoutingTests(
            methodName="test_current_explicit_default_routes_relative_intent_without_changing_capture_or_cwd"
        )
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.view.update(effectiveState="held", holdReason="unknown-reason", resource=None)

        def read(method, path, body=None):
            self.assertEqual(method, "GET")
            if "/resource-defaults/" in path:
                return copy.deepcopy(f.view)
            return f.http(method, path, body)

        result = routing.seed_defaults(
            f.f.state,
            read,
            f.f.authority,
            f.f.host,
            {f.f.agent: {"defaultWorkspaceId": f.f.resource}},
            {f.f.resource: f.f.physical},
        )
        self.assertEqual(result[0]["holdReason"], "unknown-reason")


@unittest.skipUnless(os.geteuid() == 0, "Root protected fixture route")
class OriginalSeedRecoveryTests(unittest.TestCase):
    def test_initial_r13_operation_is_recovered_by_get_without_new_selection_put(self):
        import test_resource_routing as fixtures
        from lax_connector import resource_routing as routing

        f = fixtures.PlannedRoutingTests(
            methodName="test_current_explicit_default_routes_relative_intent_without_changing_capture_or_cwd"
        )
        f.setUp()
        self.addCleanup(f.doCleanups)
        route = "agents/" + f.f.agent + "/resource-defaults/" + f.f.host
        operation = "install-resource-default:" + digest(
            [f.f.agent, f.f.host, f.f.resource, 1, 7]
        )
        payload = {
            "operationId": operation,
            "revision": 0,
            "state": "selected",
            "workspaceId": f.f.resource,
            "workspaceRevision": 1,
            "grantRevision": 7,
        }
        identity = {
            "method": "PUT",
            "path": "/hollywood/v3/" + route,
            "wireDigest": hashlib.sha256(json.dumps(payload).encode()).hexdigest(),
        }
        saved(
            f.f.state / "administration" / (digest([route, operation]) + ".json"),
            {"state": "pending", "identity": identity, "payload": payload},
        )
        accepted = copy.deepcopy(f.view)
        accepted.update(
            effectiveState="held", holdReason="participation-unavailable", resource=None
        )
        missing = {
            **accepted,
            "selection": None,
            "selectionRevision": 0,
            "effectiveState": "missing",
        }
        reads = []

        def http(method, path, body=None):
            self.assertEqual(method, "GET")
            reads.append(path)
            if path == route:
                return missing
            if path == "administration/commands/" + operation:
                return {**identity, "acceptedResult": accepted}
            return f.http(method, path, body)

        result = routing.seed_defaults(
            f.f.state,
            http,
            f.f.authority,
            f.f.host,
            {f.f.agent: {"defaultWorkspaceId": f.f.resource}},
            {f.f.resource: f.f.physical},
        )
        self.assertEqual(result, [accepted])
        self.assertIn("administration/commands/" + operation, reads)


@unittest.skipUnless(os.geteuid() == 0, "Root protected fixture route")
class GuardianImagePinTests(unittest.TestCase):
    def test_changed_guardian_executable_is_held_without_new_incarnation(self):
        f = RestartRecoveryTests(
            methodName="test_idle_restart_becomes_registered_without_manual_register_or_model"
        )
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.guardian_image.write_bytes(b"changed guardian image")
        with self.assertRaisesRegex(ValueError, "guardian executable changed"):
            restart.reconcile_one(f.config, f.agent, [])
        self.assertFalse(f.target.exists())


@unittest.skipUnless(os.geteuid() == 0, "Root protected fixture route")
class HostIdentityRefusalTests(unittest.TestCase):
    def test_machine_uid_and_cgroup_drift_hold_original_incarnation(self):
        f = RestartRecoveryTests(
            methodName="test_idle_restart_becomes_registered_without_manual_register_or_model"
        )
        f.setUp()
        self.addCleanup(f.doCleanups)
        with self.assertRaises(PermissionError):
            restart.reconcile_one(
                {**f.config, "machineIdentity": "foreign"}, f.agent, []
            )
        for key, value in [("uid", 1), ("controlGroup", "/foreign")]:
            old = f.processes[f.newpid][key]
            f.processes[f.newpid][key] = value
            with self.assertRaises(PermissionError):
                restart.reconcile_one(f.config, f.agent, [])
            f.processes[f.newpid][key] = old
        self.assertFalse(f.target.exists())


class ReadinessCliTests(unittest.TestCase):
    def test_explicit_pin_and_memory_preview_cli_dispatch_do_not_register_or_start(
        self,
    ):
        import contextlib
        import io

        base = [
            "lax-service",
            "--authority",
            uid(1),
            "--host",
            uid(2),
            "--agent",
            uid(3),
            "--expected-enrollment",
            "a" * 64,
            "--expected-definition",
            "b" * 64,
        ]
        with (
            patch(
                "sys.argv",
                base
                + [
                    "--approve-restarts",
                    "--expected-image-sha256",
                    "c" * 64,
                    "--expected-configuration-sha256",
                    "d" * 64,
                ],
            ),
            patch.object(
                restart, "approve", return_value={"approved": True}
            ) as approval,
            patch.object(observer, "register") as registration,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            service_admin.main()
        approval.assert_called_once_with(
            uid(1), uid(2), uid(3), "a" * 64, "b" * 64, "c" * 64, "d" * 64, None
        )
        registration.assert_not_called()
        with (
            patch(
                "sys.argv",
                base
                + [
                    "--prepare-memory-max-bytes",
                    str(8 * 1024**3),
                    "--output",
                    "/run/review-only",
                ],
            ),
            patch.object(
                memory, "prepare", return_value={"liveUnitChanged": False}
            ) as preview,
            patch.object(observer, "register") as registration,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            service_admin.main()
        self.assertEqual(preview.call_args.args[3], 8 * 1024**3)
        registration.assert_not_called()
