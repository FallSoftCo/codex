"""Narrow package-preflight regression checks, not production native/model QA.

Temporary diagnostic fixtures are staged by the real upstream layout writer.
No fixture executable is installed into a maintained or qualification package.
"""

import json
import os
import platform
import pwd
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from lax_connector.native_package import (
    PackageError,
    inspect_package,
    preflight_as_owner,
)
from lax_connector.rpc import AppServer
from lax_connector import service_admin

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))
with patch.dict(os.environ, {"CODEX_REPO_ROOT": str(REPO)}):
    from codex_package.layout import build_package_dir, prepare_package_dir
    from codex_package.targets import PACKAGE_VARIANTS, PackageInputs, TARGET_SPECS


class PackageFixture:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(
            prefix="lax-package-unit-", dir=os.environ.get("LAX_PACKAGE_TEST_ROOT")
        )
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o755)
        executable = self.root / "diagnostic-fixture"
        executable.write_text(
            "#!/usr/bin/python3\nimport os\nprint('diagnostic-fixture UID=' + str(os.geteuid()))\n"
        )
        executable.chmod(0o755)
        self.package = self.root / "package"
        prepare_package_dir(self.package, force=False)
        machine = {"amd64": "x86_64", "arm64": "aarch64"}.get(
            platform.machine().lower(), platform.machine().lower()
        )
        self.target = machine + "-unknown-linux-gnu"
        build_package_dir(
            self.package,
            "0.163.0-test",
            PACKAGE_VARIANTS["codex"],
            TARGET_SPECS[self.target],
            PackageInputs(executable, executable, executable, executable, None, None),
        )
        self.binary = self.package / "bin/codex"


class PackageTests(PackageFixture, unittest.TestCase):
    def test_upstream_layout_complete_assets_and_bounded_startup(self):
        out = inspect_package(self.binary, expected_uid=os.geteuid())
        self.assertTrue(out["ready"])
        self.assertEqual(out["uid"], os.geteuid())
        self.assertEqual(out["metadata"]["target"], self.target)
        self.assertEqual(len(out["startupChecks"]), 4)
        self.assertFalse(out["toolExecutionProved"])
        self.assertEqual(out["modelsStarted"], 0)

    def test_headless_upstream_package_uses_its_declared_entrypoint(self):
        package = self.root / "headless-package"
        prepare_package_dir(package, force=False)
        build_package_dir(
            package,
            "0.163.0-test",
            PACKAGE_VARIANTS["codex-app-server"],
            TARGET_SPECS[self.target],
            PackageInputs(self.binary, self.binary, self.binary, self.binary, None, None),
        )
        out = inspect_package(package / "bin/codex-app-server", expected_uid=os.geteuid())
        self.assertEqual(out["metadata"]["variant"], "codex-app-server")
        self.assertEqual(out["metadata"]["entrypoint"], "bin/codex-app-server")
        self.assertEqual(len(out["startupChecks"]), 4)
        self.assertFalse(out["toolExecutionProved"])
        self.assertEqual(out["modelsStarted"], 0)

    def test_missing_code_host_rejected_before_any_diagnostic(self):
        (self.package / "bin/codex-code-mode-host").unlink()
        with patch("lax_connector.native_package.subprocess.run") as run:
            with self.assertRaisesRegex(PackageError, "codex-code-mode-host"):
                inspect_package(self.binary)
        run.assert_not_called()

    def test_inaccessible_or_failed_helper_does_not_become_ready(self):
        host = self.package / "bin/codex-code-mode-host"
        host.chmod(0o644)
        with self.assertRaisesRegex(PackageError, "service UID"):
            inspect_package(self.binary)
        host.write_text("#!/usr/bin/python3\nraise SystemExit(7)\n")
        host.chmod(0o755)
        with self.assertRaisesRegex(PackageError, "codeModeHost.*exited 7"):
            inspect_package(self.binary)

    def test_metadata_entrypoint_and_actual_uid_are_required(self):
        meta = self.package / "codex-package.json"
        value = json.loads(meta.read_text())
        value["entrypoint"] = "bin/another-command"
        meta.write_text(json.dumps(value))
        with self.assertRaisesRegex(PackageError, "unsupported canonical CLI layout"):
            inspect_package(self.binary)
        with self.assertRaisesRegex(PackageError, "execution UID differs"):
            inspect_package(self.binary, expected_uid=os.geteuid() + 1)

    @unittest.skipUnless(
        os.geteuid() == 0 and os.environ.get("LAX_TEST_SERVICE_UID"),
        "actual identity drop requires root and an explicit existing service fixture UID",
    )
    def test_administrator_drops_to_existing_native_service_identity(self):
        # Existing current worker identity; no account/service/context is created or resumed.
        account = pwd.getpwuid(int(os.environ["LAX_TEST_SERVICE_UID"]))
        # A readable isolated installed runtime; the source checkout stays private.
        runtime = self.root / "runtime"
        subprocess.run(
            ["/usr/bin/python3", "-m", "venv", "--without-pip", str(runtime)],
            check=True,
            capture_output=True,
            timeout=10,
        )
        sites = list((runtime / "lib").glob("python*/site-packages"))
        self.assertEqual(len(sites), 1)
        module = sites[0] / "lax_connector"
        module.mkdir()
        for directory in [
            runtime,
            *[p for p in runtime.rglob("*") if p.is_dir() and not p.is_symlink()],
        ]:
            directory.chmod(0o755)
        for name in ("__init__.py", "native_package.py"):
            shutil.copyfile(
                REPO / "losangelex/connector/lax_connector" / name, module / name
            )
            (module / name).chmod(0o644)
        # An invalid import override must be ignored by isolated-mode Python.
        with patch.dict(
            os.environ, {"PYTHONPATH": "/missing/untrusted-module-override"}
        ):
            out = preflight_as_owner(
                self.binary, runtime / "bin/python3", account.pw_uid, account.pw_dir
            )
        self.assertEqual(out["uid"], account.pw_uid)
        self.assertNotEqual(out["uid"], os.geteuid())
        self.assertTrue(out["ready"])
        self.assertFalse(out["toolExecutionProved"])


class StartupGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_enterprise_package_failure_precedes_native_process_spawn(self):
        with tempfile.TemporaryDirectory() as root:
            server = AppServer(
                "/missing/bin/codex",
                Path(root) / "home",
                Path(root) / "state",
                None,
                None,
                enterprise=True,
            )
            with patch("lax_connector.rpc.asyncio.create_subprocess_exec") as spawn:
                with self.assertRaises(PackageError):
                    await server.start()
            spawn.assert_not_called()
            self.assertIsNone(server.process)


class ReadinessTests(PackageFixture, unittest.TestCase):
    def test_registered_healthy_service_with_missing_helper_is_not_ready(self):
        from contextlib import ExitStack

        authority, host, agent = [str(UUID(int=n)) for n in (1, 2, 3)]
        info = {
            "Id": "fixture.service",
            "ActiveState": "active",
            "MainPID": "222",
            "InvocationID": UUID(int=4).hex,
            "ControlGroup": "/fixture",
            "KillMode": "control-group",
        }
        guardian = {
            "pid": 222,
            "uid": os.geteuid(),
            "controlGroup": "/fixture",
            "start": "10",
        }
        image = self.binary.stat()
        baseline = {
            "schema": "lax-service-enrollment/v1",
            "authorityId": authority,
            "hostId": host,
            "agentId": agent,
            "uid": os.geteuid(),
            "home": str(self.root),
            "unit": info["Id"],
            "unitDefinitionDigest": "definition",
            "binary": str(self.binary),
            "binaryDevice": image.st_dev,
            "binaryInode": image.st_ino,
            "machineIdentity": "machine",
            "killMode": "control-group",
        }
        binding = {
            **baseline,
            "schema": "lax-service-incarnation/v1",
            "bootId": "boot",
            "serviceInvocation": info["InvocationID"],
            "controlGroup": "/fixture",
            "guardianPid": 222,
            "guardianStart": "10",
        }
        registry = self.root / "registry"
        registry.mkdir()
        (registry / "enrollment.json").write_text("{}")
        (registry / (info["InvocationID"] + ".json")).write_text("{}")

        def protected(path):
            if path.name == "enrollment.json":
                return baseline
            if path.name == "global-admin-receipt.json":
                return {"agentId": agent}
            if path.name == "global-admin-intent.json":
                return {"spec": {"interpreter": sys.executable}}
            return binding

        with ExitStack() as stack:
            for name, value in {
                "expected_owner": (os.geteuid(), self.root, str(self.binary)),
                "installed_unit": info["Id"],
                "properties": info,
                "process": guardian,
                "unit_definition": "definition",
                "machine_identity": "machine",
                "directory": registry,
                "boot_id": "boot",
            }.items():
                stack.enter_context(
                    patch.object(service_admin.observer, name, return_value=value)
                )
            stack.enter_context(
                patch.object(service_admin.observer, "protected", side_effect=protected)
            )
            from contextlib import nullcontext

            stack.enter_context(
                patch(
                    "lax_connector.native_image_upgrade.registry_lock",
                    return_value=nullcontext(0),
                )
            )
            stack.enter_context(
                patch("lax_connector.native_image_upgrade.require_settled_transition")
            )
            check = stack.enter_context(
                patch.object(
                    service_admin,
                    "preflight_as_owner",
                    side_effect=PackageError(
                        "bin/codex-code-mode-host", "missing required asset"
                    ),
                )
            )
            result = service_admin.inspect(authority, host, agent)
        self.assertFalse(result["ready"])
        self.assertEqual(result["reason"], "native-package-preflight-failed")
        check.assert_called_once_with(
            str(self.binary), sys.executable, os.geteuid(), self.root
        )
