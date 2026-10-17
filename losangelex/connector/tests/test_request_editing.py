"""Request editing boundary fixtures; no model or backend execution."""

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID

from lax_connector.collaboration_bridge import Held
from lax_connector.collaboration_capture import AutomaticCapture, installed_native_owner

AUTHORITY, HOST, AGENT = [str(UUID(int=n)) for n in (1, 2, 3)]
BASE = Path("/var/lib/harness") / AUTHORITY


class InstalledNativeOwnerTests(unittest.TestCase):
    def test_new_installed_worker_is_derived_without_static_agent_policy(self):
        home = BASE / "workers" / AGENT / "home"
        with (
            patch(
                "lax_connector.collaboration_capture.pwd.getpwuid",
                return_value=SimpleNamespace(pw_dir=str(home)),
            ),
            patch(
                "lax_connector.collaboration_capture.protected",
                return_value={
                    "uid": 999,
                    "home": "/other",
                    "agentId": str(UUID(int=9)),
                },
            ),
            patch(
                "lax_connector.collaboration_capture.expected_owner",
                return_value=(123, home, "/installed/bin/codex"),
            ),
        ):
            self.assertEqual(
                installed_native_owner(AUTHORITY, 123), (AGENT, "/installed/bin/codex")
            )

    def test_global_owner_requires_the_recorded_nss_home(self):
        home = BASE / "global"
        receipt = {"uid": 123, "home": str(home), "agentId": AGENT}
        with (
            patch(
                "lax_connector.collaboration_capture.pwd.getpwuid",
                return_value=SimpleNamespace(pw_dir=str(home)),
            ),
            patch(
                "lax_connector.collaboration_capture.protected", return_value=receipt
            ),
            patch(
                "lax_connector.collaboration_capture.expected_owner",
                return_value=(123, home, "/installed/bin/codex"),
            ),
        ):
            self.assertEqual(installed_native_owner(AUTHORITY, 123)[0], AGENT)
        receipt["home"] = "/another-home"
        with (
            patch(
                "lax_connector.collaboration_capture.pwd.getpwuid",
                return_value=SimpleNamespace(pw_dir=str(home)),
            ),
            patch(
                "lax_connector.collaboration_capture.protected", return_value=receipt
            ),
        ):
            with self.assertRaises(Held):
                installed_native_owner(AUTHORITY, 123)

    def test_unrelated_nss_home_is_refused_without_owner_lookup(self):
        with (
            patch(
                "lax_connector.collaboration_capture.pwd.getpwuid",
                return_value=SimpleNamespace(pw_dir="/home/unrelated"),
            ),
            patch(
                "lax_connector.collaboration_capture.protected",
                return_value={"uid": 999, "home": "/other"},
            ),
            patch("lax_connector.collaboration_capture.expected_owner") as lookup,
        ):
            with self.assertRaises(Held):
                installed_native_owner(AUTHORITY, 123)
            lookup.assert_not_called()

    def test_protected_owner_uid_or_home_mismatch_is_held(self):
        home = BASE / "workers" / AGENT / "home"
        with (
            patch(
                "lax_connector.collaboration_capture.pwd.getpwuid",
                return_value=SimpleNamespace(pw_dir=str(home)),
            ),
            patch(
                "lax_connector.collaboration_capture.protected",
                return_value={"uid": 999, "home": "/other"},
            ),
            patch(
                "lax_connector.collaboration_capture.expected_owner",
                return_value=(124, home, "/installed/bin/codex"),
            ),
        ):
            with self.assertRaisesRegex(Held, "protected installation owner"):
                installed_native_owner(AUTHORITY, 123)

    def test_peer_ignores_static_whitelist_but_retains_actual_image_and_executor(self):
        image = Path(sys.executable).resolve().stat()
        actual = {
            "pid": os.getpid(),
            "uid": os.geteuid(),
            "start": "fixture-start",
            "executableDevice": image.st_dev,
            "executableInode": image.st_ino,
        }
        row = {
            "agent": AGENT,
            "host": HOST,
            "launch_phase": "attached",
            "state": "live",
            "descriptor": {"nativePid": os.getpid(), "nativeStart": "fixture-start"},
        }
        capture = object.__new__(AutomaticCapture)
        capture.config = {"authorityId": AUTHORITY, "hostId": HOST}
        capture.policy = {
            "agents": {}
        }  # Deliberately absent from any static agent map.
        capture.bridge = SimpleNamespace(
            http=Mock(return_value={"executors": [row], "nextAfter": None})
        )
        with (
            patch("lax_connector.collaboration_capture.process", return_value=actual),
            patch(
                "lax_connector.collaboration_capture.installed_native_owner",
                return_value=(AGENT, sys.executable),
            ),
            patch(
                "lax_connector.collaboration_capture.expected_owner",
                return_value=(os.geteuid(), None, sys.executable),
            ),
            patch(
                "lax_connector.collaboration_capture.observe",
                return_value={"state": "live"},
            ) as independent,
        ):
            result = capture.peer((os.getpid(), os.geteuid(), 0))
        self.assertEqual(result[0], row)
        independent.assert_called_once()
