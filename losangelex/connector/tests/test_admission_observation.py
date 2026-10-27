"""Pre-capture inspection recovery; model semantics are not simulated."""

import asyncio
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from lax_connector.admission_observation import AdmissionObservationWait
from lax_connector.context_runtime import ContextRunner
from lax_connector.execution_lifecycle import ExecutionLifecycle, ServiceInspectionUnavailable
from lax_connector.service_observer import properties

A = "e488f19b-0f60-46ca-bd48-4fe544f06757"
G = "2d4a0daa-0514-475e-be1e-71decacbd5bc"
H = "ec32d149-b563-589f-87c9-d5f468df1e79"
D = "201e3ce4-3f90-4417-a12e-e718517f1a47"
E = "acaf295a-869f-456b-bd50-caa1a7f42c48"
UNIT = "lax-agent-fixture-writer.service"


class AdmissionObservationTests(unittest.IsolatedAsyncioTestCase):
    def setup_runner(self, root, requests, transport):
        accepted = {
            "delivery": {"id": D, "authority": A, "event": E, "agent": G,
                         "host": H, "generation": 1, "claim_id": "original-claim"},
            "request": {"id": E, "authority": A},
        }
        runner = ContextRunner.__new__(ContextRunner)
        runner.purpose, runner.state = "writer", root
        runner.config = {"agentId": G, "hostId": H, "binary": "/usr/bin/true",
                         "installedPurposeRuntime": True}
        runner.thread = "original-native-thread"
        runner.admitted = asyncio.Event()
        runner.failed = False
        runner.admission_observation = AdmissionObservationWait(root)
        runner.rpc = SimpleNamespace(process=SimpleNamespace(pid=222))
        runner.agent = SimpleNamespace(http=transport)
        runner.trace = lambda event, value: requests.append((event, value))

        async def request(action, value=None, **kwargs):
            requests.append((action, value, kwargs))
            if action in ("admit", "ready"):
                return accepted
            if action == "reserve":
                return {"permit": {"id": "same-work-queued", "state": "queued"}}
            self.fail("Unexpected model/context action: " + action)

        runner.request = request
        return runner

    def process(self, pid):
        own = pid == os.getpid()
        return {"pid": pid, "start": "100" if own else "200", "uid": os.geteuid(),
                "controlGroup": "/lax.slice/" + UNIT,
                "executable": "/usr/bin/python3" if own else "/usr/bin/true"}

    def info(self):
        return {"MainPID": str(os.getpid()), "ActiveState": "active",
                "ControlGroup": "/lax.slice/" + UNIT,
                "InvocationID": "b99960f8505b546dabb75791282a33e7"}

    async def test_transient_inspection_recovers_same_work_before_any_inference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wake = root / "wake.json"
            wake.write_text('{"state":"finished","fingerprint":"original"}')
            original_wake = wake.read_bytes()
            requests, captures = [], []

            async def transport(purpose, method, path, payload=None):
                captures.append((method, path, payload))
                return {"executor": {
                    **{k: payload[k] for k in ("id", "hostId", "generation", "claimId")},
                    "host": payload["hostId"], "claim_id": payload["claimId"],
                    "delivery": D, "agent": G,
                    "descriptor": {k: v for k, v in payload.items()
                                   if k not in ("operationId", "id", "claimId", "generation", "hostId")},
                    "launch_phase": "attached",
                }}

            runner = self.setup_runner(root, requests, transport)
            failure = subprocess.CalledProcessError(
                1, ["systemctl", "show", UNIT], stderr="metadata bus unavailable")
            with patch("lax_connector.execution_lifecycle.process", side_effect=self.process), \
                 patch("lax_connector.execution_lifecycle.properties",
                       side_effect=[failure, self.info()]), \
                 patch.object(ExecutionLifecycle, "require_live", new=AsyncMock(return_value=True)):
                await runner.run("continued-original", [{"id": "original-material"}])
                self.assertFalse(runner.failed)
                self.assertFalse(runner.active)
                self.assertIsNone(runner.executor)
                self.assertEqual(captures, [])
                self.assertFalse((root / "capacity-wait.json").exists())
                self.assertEqual(wake.read_bytes(), original_wake)
                self.assertFalse(runner.admission_observation.eligible())
                with patch("lax_connector.admission_observation.time.monotonic",
                           return_value=runner.admission_observation.retry_at + 1):
                    self.assertTrue(runner.admission_observation.eligible())
                    await runner.run("continued-original", [{"id": "original-material"}])
            self.assertFalse(runner.failed)
            self.assertFalse(runner.active)
            self.assertEqual(len(captures), 1)
            self.assertEqual([x[0] for x in requests if x[0] in ("admit", "ready", "reserve")],
                             ["admit", "ready", "admit", "ready", "reserve"])
            self.assertEqual([x[2]["operation"] for x in requests if x[0] == "admit"],
                             ["context-admit:original-material"] * 2)
            self.assertEqual(wake.read_bytes(), original_wake)
            self.assertEqual(json.loads((root / "admission-observation.json").read_text())["state"],
                             "recovered")
            self.assertEqual(captures[0][1], "connector/deliveries/" + D + "/executor")

    async def test_policy_mismatch_is_not_reclassified_as_probe_unavailability(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            runner = self.setup_runner(Path(tmp), calls, AsyncMock())
            with patch("lax_connector.execution_lifecycle.process", side_effect=self.process), \
                 patch("lax_connector.execution_lifecycle.properties",
                       return_value={**self.info(), "ActiveState": "inactive"}):
                with self.assertRaisesRegex(RuntimeError, "ownership"):
                    await runner.run("original", [{"id": "original-material"}])
            self.assertTrue(runner.failed)
            self.assertFalse(runner.active)
            self.assertIsNone(runner.admission_observation.current)
            runner.agent.http.assert_not_awaited()

    async def test_unknown_capture_outcome_keeps_permanent_failure_fence(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = self.setup_runner(Path(tmp), [], AsyncMock(
                side_effect=RuntimeError("original capture outcome unknown")))
            with patch("lax_connector.execution_lifecycle.process", side_effect=self.process), \
                 patch("lax_connector.execution_lifecycle.properties", return_value=self.info()):
                with self.assertRaisesRegex(RuntimeError, "outcome unknown"):
                    await runner.run("original", [{"id": "original-material"}])
            self.assertTrue(runner.failed)
            self.assertFalse(runner.active)
            self.assertIsNone(runner.admission_observation.current)
            self.assertEqual(runner.agent.http.await_count, 2)  # POST, then original GET.

    async def test_current_cancellation_remains_fenced_after_inspection_wait(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = self.setup_runner(Path(tmp), [], AsyncMock())
            error = ServiceInspectionUnavailable(UNIT, subprocess.CalledProcessError(1, "probe"))
            runner.admission_observation.defer(error)

            async def cancelled(*args, **kwargs):
                raise PermissionError("Original work cancelled")
            runner.request = cancelled
            with self.assertRaisesRegex(PermissionError, "cancelled"):
                await runner.run("original", [{"id": "original-material"}])
            self.assertTrue(runner.failed)
            self.assertFalse(runner.active)
            runner.agent.http.assert_not_awaited()

    def test_inspection_backoff_is_bounded_and_preserves_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp:
            wait = AdmissionObservationWait(Path(tmp))
            error = ServiceInspectionUnavailable(
                UNIT, subprocess.CalledProcessError(1, "probe", stderr="retained failure"))
            delays = []
            with patch("lax_connector.admission_observation.time.monotonic", return_value=10), \
                 patch("lax_connector.admission_observation.time.time", return_value=100):
                for _ in range(20):
                    wait.defer(error)
                    delays.append(wait.retry_at - 10)
                    self.assertFalse(wait.eligible())
            self.assertTrue(all(0 < delay <= 60 for delay in delays))
            self.assertEqual(delays[-1], delays[-2])
            self.assertEqual(wait.current["attempt"], 20)
            self.assertEqual(wait.current["observation"]["diagnostic"], "retained failure")

    def test_real_probe_timeout_never_returns_invented_service_properties(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "systemctl"
            executable.write_text("#!/bin/sh\nexec /bin/sleep 10\n")
            executable.chmod(0o700)
            with patch.dict(os.environ, {"PATH": tmp}):
                with self.assertRaises(subprocess.TimeoutExpired):
                    properties(UNIT, timeout=0.05)


if __name__ == "__main__":
    unittest.main()
