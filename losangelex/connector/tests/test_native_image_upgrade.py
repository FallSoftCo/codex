"""Focused offline image-transition fixtures. No native process, server or model."""

import contextlib
import fcntl
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from lax_connector import native_image_upgrade as image
from lax_connector import service_admin, service_observer as observer


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    path.chmod(0o600)


@unittest.skipUnless(
    os.geteuid() == 0, "protected disposable filesystem fixtures require root"
)
class ImageTransitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lax-image-unit-", dir="/run")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.authority, self.host, self.agent = [str(UUID(int=n)) for n in (1, 2, 3)]
        self.registry = self.root / "host/services" / self.agent
        self.registry.mkdir(parents=True)
        self.home = self.root / "home"
        self.state = self.home / "state"
        self.state.mkdir(parents=True)
        (self.state / "connector.lock").touch(mode=0o600)
        self.package = self.root / "native"
        relatives = {
            "entrypoint": "bin/codex",
            "codeModeHost": "bin/codex-code-mode-host",
            "bubblewrap": "codex-resources/bwrap",
            "ripgrep": "codex-path/rg",
        }
        self.assets = {}
        for label, relative in relatives.items():
            path = self.package / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(("Unexecuted diagnostic fixture: " + label).encode())
            path.chmod(0o755)
            info = path.stat()
            self.assets[label] = {
                "path": str(path),
                "device": info.st_dev,
                "inode": info.st_ino,
                "size": info.st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        self.binary = self.package / "bin/codex"
        write(self.package / "codex-package.json", {"fixture": True})
        self.sha = self.assets["entrypoint"]["sha256"]
        self.probe = {
            "ready": True,
            "assets": self.assets,
            "packageRoot": str(self.package),
            "metadataSha256": hashlib.sha256(
                (self.package / "codex-package.json").read_bytes()
            ).hexdigest(),
            "modelsStarted": 0,
            "toolExecutionProved": False,
        }
        self.definition = "a" * 64
        self.old = {
            "schema": "lax-service-enrollment/v1",
            "authorityId": self.authority,
            "hostId": self.host,
            "agentId": self.agent,
            "uid": 0,
            "home": str(self.home),
            "unit": "lax-fixture.service",
            "binary": str(self.binary),
            "binaryDevice": 12,
            "binaryInode": 34,
            "machineIdentity": "fixture-machine",
            "killMode": "control-group",
            "unitDefinitionDigest": "b" * 64,
        }
        self.old_digest = observer.digest(self.old)
        write(self.registry / "enrollment.json", self.old)
        self.prior = {
            **self.old,
            "schema": "lax-service-incarnation/v1",
            "guardianPid": 901,
            "guardianStart": "old",
            "controlGroup": "/old-fixture",
        }
        write(self.registry / "old.json", self.prior)
        self.config = {
            "agentId": self.agent,
            "hostId": self.host,
            "state": str(self.state),
            "binary": str(self.binary),
            "hollywoodUrl": "http://fixture.invalid",
            "token": "fixture-only",
        }
        write(self.home / "connector.json", self.config)
        self.controller = {
            "authorityId": self.authority,
            "hostId": self.host,
            "machineIdentity": "fixture-machine",
            "hollywoodUrl": self.config["hollywoodUrl"],
            "token": "fixture-controller-only",
        }
        write(self.root / "host/controller.json", self.controller)
        self.info = {
            "Id": "lax-fixture.service",
            "ActiveState": "inactive",
            "MainPID": "0",
            "ControlGroup": "/new-fixture",
            "User": "fixture",
            "KillMode": "control-group",
        }
        self.pending = {"enabled": False, "busy": None, "pending": None}
        self.executors = {"executors": [], "nextAfter": None}
        self.calls = []
        stack = self.enterContext(contextlib.ExitStack())
        for name, value in {
            "directory": self.registry,
            "expected_owner": (0, self.home, str(self.binary)),
            "installed_unit": self.info["Id"],
            "properties": self.info,
            "unit_definition": self.definition,
            "process": None,
            "members": set(),
        }.items():
            stack.enter_context(patch.object(observer, name, return_value=value))
        self.properties = observer.properties
        self.members = observer.members
        self.process = observer.process
        stack.enter_context(
            patch.object(image, "machine_identity", return_value="fixture-machine")
        )
        stack.enter_context(
            patch.object(observer, "machine_identity", return_value="fixture-machine")
        )
        stack.enter_context(
            patch.object(image.pwd, "getpwnam", return_value=SimpleNamespace(pw_uid=0))
        )
        self.preflight = stack.enter_context(
            patch.object(image, "preflight_as_owner", return_value=self.probe)
        )
        self.request = stack.enter_context(
            patch.object(image, "request", side_effect=self.get)
        )
        stack.enter_context(
            patch.object(
                observer,
                "protected",
                side_effect=lambda p: (
                    json.loads(p.read_text())
                    if p.is_file()
                    else {"agentId": self.agent}
                    if p.name == "global-admin-receipt.json"
                    else {"spec": {"interpreter": "/unexecuted/fixture/python"}}
                ),
            )
        )

    def get(self, url, token, method, route):
        self.calls.append((method, route))
        return self.pending if route.startswith("connector/pending") else self.executors

    def approve(self):
        return image.approve_image_upgrade(
            self.authority,
            self.host,
            self.agent,
            self.old_digest,
            self.definition,
            self.sha,
        )

    def assert_unchanged(self):
        self.assertEqual(
            json.loads((self.registry / "enrollment.json").read_text()), self.old
        )
        self.assertEqual(
            json.loads((self.registry / "old.json").read_text()), self.prior
        )

    def test_success_preserves_history_and_journals_without_activation_or_replay(self):
        original_state = {p.name: p.read_bytes() for p in self.state.iterdir()}
        result = self.approve()
        self.assertEqual(result["state"], "accepted")
        self.assertFalse(result["executionReady"])
        self.assertEqual(result["servicesStarted"], 0)
        self.assertTrue(all(method == "GET" for method, _ in self.calls))
        self.assertEqual(
            original_state, {p.name: p.read_bytes() for p in self.state.iterdir()}
        )
        self.assertEqual(
            json.loads((self.registry / "old.json").read_text()), self.prior
        )
        self.assertEqual(
            json.loads(next(self.registry.glob("image-*-before.json")).read_text()),
            self.old,
        )
        with image.registry_lock(self.registry) as fd:
            image.require_settled_transition(fd)
        with self.assertRaisesRegex(ValueError, "Original enrollment changed"):
            self.approve()

    def test_running_guardian_or_remaining_descendants_block(self):
        self.info.update(ActiveState="active", MainPID="100")
        with self.assertRaisesRegex(ValueError, "stopped empty"):
            self.approve()
        self.info.update(ActiveState="inactive", MainPID="0")
        self.members.side_effect = lambda group: (
            {777} if group == "/old-fixture" else set()
        )
        with self.assertRaisesRegex(ValueError, "remaining descendants"):
            self.approve()
        self.assert_unchanged()

    def test_old_guardian_still_present_blocks(self):
        self.process.return_value = {"pid": 901, "start": "old"}
        with self.assertRaisesRegex(ValueError, "prior registered guardian"):
            self.approve()
        self.assert_unchanged()

    def test_admission_must_be_disabled_and_canonically_drained(self):
        for key, value in [
            ("enabled", True),
            ("busy", {"state": "unknown"}),
            ("pending", {"id": "fixture"}),
        ]:
            with self.subTest(key=key):
                self.pending[key] = value
                with self.assertRaisesRegex(ValueError, "placement must stay disabled"):
                    self.approve()
                self.pending = {"enabled": False, "busy": None, "pending": None}
        self.executors["executors"] = [{"agent": self.agent}]
        with self.assertRaisesRegex(ValueError, "independent stopped evidence"):
            self.approve()
        self.assert_unchanged()

    def test_canonical_cursor_uncertainty_is_held(self):
        self.executors["nextAfter"] = str(UUID(int=99))
        with self.assertRaisesRegex(ValueError, "cursor repeated"):
            self.approve()
        self.assert_unchanged()

    def attempt(self, delivery, state):
        event = str(UUID(int=delivery + 100))
        delivery = str(UUID(int=delivery))
        value = {
            "state": state,
            "delivery": {
                "id": delivery,
                "generation": 1,
                "claim_id": "original",
                "event": event,
                "authority": self.authority,
                "agent": self.agent,
                "host": self.host,
            },
            "request": {"id": event, "authority": self.authority},
        }
        write(self.state / "executions" / delivery / "1/execution.json", value)
        return value

    def test_unselected_unsettled_attempt_cannot_be_hidden(self):
        self.attempt(10, "completed")
        self.attempt(11, "unknown")
        with self.assertRaisesRegex(ValueError, "remains unsettled"):
            self.approve()
        self.assert_unchanged()

    def test_dangling_open_index_and_projection_gaps_are_not_recovered(self):
        opened = self.state / "executions/open"
        opened.mkdir(parents=True)
        os.symlink("../missing/1/execution.json", opened / (str(UUID(int=12)) + ".1"))
        with self.assertRaisesRegex(ValueError, "Dangling or changed"):
            self.approve()
        self.assertTrue(next(opened.iterdir()).is_symlink())
        self.assert_unchanged()

    def test_consistent_settled_selection_is_read_only(self):
        value = self.attempt(13, "completed")
        write(self.state / "execution.json", value)
        write(self.state / "execution-current.json", image.execution_key(value))
        before = {
            str(p.relative_to(self.state)): p.read_bytes()
            for p in self.state.rglob("*")
            if p.is_file()
        }
        self.approve()
        after = {
            str(p.relative_to(self.state)): p.read_bytes()
            for p in self.state.rglob("*")
            if p.is_file()
        }
        self.assertEqual(before, after)

    def test_hash_mismatch_and_symlink_are_rejected(self):
        approved = self.sha
        self.sha = "0" * 64
        with self.assertRaisesRegex(ValueError, "approved SHA256"):
            self.approve()
        self.sha = approved
        target = self.binary.with_name("other")
        self.binary.rename(target)
        self.binary.symlink_to(target)
        with self.assertRaises(OSError):
            self.approve()
        self.assert_unchanged()

    def test_same_bytes_replaced_inode_during_probe_is_rejected(self):
        def replace(*args):
            data = self.binary.read_bytes()
            other = self.binary.with_name("replacement")
            other.write_bytes(data)
            other.chmod(0o755)
            other.replace(self.binary)
            return self.probe

        self.preflight.side_effect = replace
        with self.assertRaisesRegex(ValueError, "asset differs"):
            self.approve()
        self.assert_unchanged()

    def test_writable_helper_is_rejected(self):
        Path(self.assets["codeModeHost"]["path"]).chmod(0o777)
        with self.assertRaises(PermissionError):
            self.approve()
        self.assert_unchanged()

    def test_both_registry_and_connector_lock_contention_hold(self):
        with image.registry_lock(self.registry):
            with self.assertRaises(BlockingIOError):
                self.approve()
        with (self.state / "connector.lock").open("r+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                self.approve()
        self.assert_unchanged()

    def test_race_after_durable_intent_holds_registration_and_preserves_old_enrollment(
        self,
    ):
        original = image._write

        def race(fd, name, value, **kwargs):
            original(fd, name, value, **kwargs)
            if name == image.INDEX and value["state"] == "intent":
                self.binary.write_bytes(b"changed-after-intent")

        with patch.object(image, "_write", side_effect=race):
            with self.assertRaisesRegex(ValueError, "asset changed"):
                self.approve()
        self.assert_unchanged()
        self.assertEqual(
            json.loads((self.registry / image.INDEX).read_text())["state"], "intent"
        )
        with patch.object(observer, "_register") as register:
            with self.assertRaisesRegex(ValueError, "explicit reconciliation"):
                observer.register(
                    self.authority, self.host, self.agent, self.info["Id"]
                )
            register.assert_not_called()

    def test_interruption_after_enrollment_cas_is_never_rolled_back_or_replayed(self):
        original = image._write

        def crash(fd, name, value, **kwargs):
            original(fd, name, value, **kwargs)
            if name == "enrollment.json":
                raise RuntimeError("injected-crash-after-CAS")

        with patch.object(image, "_write", side_effect=crash):
            with self.assertRaisesRegex(RuntimeError, "injected-crash"):
                self.approve()
        enrolled = (self.registry / "enrollment.json").read_bytes()
        self.assertNotEqual(json.loads(enrolled), self.old)
        with self.assertRaisesRegex(ValueError, "explicit reconciliation"):
            self.approve()
        self.assertEqual(enrolled, (self.registry / "enrollment.json").read_bytes())
        self.assertEqual(
            json.loads(next(self.registry.glob("image-*-before.json")).read_text()),
            self.old,
        )
        self.assertFalse(list(self.registry.glob("image-*-accepted.json")))

    def test_definition_only_upgrade_still_rejects_native_image_change(self):
        self.info.update(ActiveState="active", MainPID="100")
        guardian = {
            "pid": 100,
            "start": "new",
            "uid": 0,
            "controlGroup": "/new-fixture",
        }
        self.process.side_effect = lambda pid: guardian if pid == 100 else None
        self.members.return_value = {100}
        with self.assertRaisesRegex(
            ValueError, "cannot change identity, native image or host"
        ):
            observer.approve_drained_upgrade(
                self.authority, self.host, self.agent, self.old_digest, self.definition
            )
        self.assert_unchanged()

    def test_later_definition_only_transition_preserves_accepted_image_guard(self):
        self.approve()
        enrolled = json.loads((self.registry / "enrollment.json").read_text())
        self.info.update(ActiveState="active", MainPID="100")
        guardian = {
            "pid": 100,
            "start": "new",
            "uid": 0,
            "controlGroup": "/new-fixture",
        }
        self.process.side_effect = lambda pid: guardian if pid == 100 else None
        self.members.return_value = {100}
        observer.unit_definition.return_value = "d" * 64
        observer.approve_drained_upgrade(
            self.authority, self.host, self.agent, observer.digest(enrolled), "d" * 64
        )
        with image.registry_lock(self.registry) as fd:
            image.require_settled_transition(fd)
        with patch.object(
            observer, "_register", return_value={"registered": True}
        ) as register:
            self.assertEqual(
                observer.register(
                    self.authority, self.host, self.agent, self.info["Id"]
                ),
                {"registered": True},
            )
            register.assert_called_once()

    def test_a_second_explicit_image_transition_preserves_both_histories(self):
        first = self.approve()
        self.old_digest = observer.digest(
            json.loads((self.registry / "enrollment.json").read_text())
        )
        replacement = self.binary.with_name("next-image")
        replacement.write_bytes(b"another-unexecuted-fixture-image")
        replacement.chmod(0o755)
        replacement.replace(self.binary)
        info = self.binary.stat()
        self.sha = hashlib.sha256(self.binary.read_bytes()).hexdigest()
        self.assets["entrypoint"].update(
            device=info.st_dev, inode=info.st_ino, size=info.st_size, sha256=self.sha
        )
        second = self.approve()
        self.assertNotEqual(first["operationId"], second["operationId"])
        self.assertEqual(len(list(self.registry.glob("image-*-accepted.json"))), 2)
        with image.registry_lock(self.registry) as fd:
            image.require_settled_transition(fd)
        self.old_digest = second["newEnrollmentDigest"]
        with self.assertRaisesRegex(ValueError, "already enrolled"):
            self.approve()

    def test_orphan_intent_before_pointer_write_holds_registration_without_replay(self):
        original = image._write

        def crash(fd, name, value, **kwargs):
            if name == image.INDEX:
                raise RuntimeError("injected-before-pointer")
            original(fd, name, value, **kwargs)

        with patch.object(image, "_write", side_effect=crash):
            with self.assertRaisesRegex(RuntimeError, "injected-before-pointer"):
                self.approve()
        self.assertFalse((self.registry / image.INDEX).exists())
        self.assertEqual(len(list(self.registry.glob("image-*-intent.json"))), 1)
        self.assert_unchanged()
        with patch.object(observer, "_register") as register:
            with self.assertRaisesRegex(ValueError, "explicit reconciliation"):
                observer.register(
                    self.authority, self.host, self.agent, self.info["Id"]
                )
            register.assert_not_called()
        with self.assertRaisesRegex(ValueError, "explicit reconciliation"):
            self.approve()

    def test_cli_image_transition_does_not_inspect_or_activate(self):
        args = [
            "lax-service",
            "--authority",
            self.authority,
            "--host",
            self.host,
            "--agent",
            self.agent,
            "--approve-image-upgrade",
            "--expected-enrollment",
            self.old_digest,
            "--expected-definition",
            self.definition,
            "--expected-image-sha256",
            self.sha,
        ]
        with (
            patch("sys.argv", args),
            patch.object(
                image, "approve_image_upgrade", return_value={"executionReady": False}
            ) as approve,
            patch.object(service_admin, "inspect") as inspect,
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            service_admin.main()
        approve.assert_called_once_with(
            self.authority,
            self.host,
            self.agent,
            self.old_digest,
            self.definition,
            self.sha,
        )
        inspect.assert_not_called()
        self.assertFalse(
            json.loads(output.getvalue())["imageUpgrade"]["executionReady"]
        )
