"""Provisioning-journal contract checks; installer and network are intercepted."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from lax_connector import purpose_provision


class PeerContextPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def invoke(self, policy):
        with tempfile.TemporaryDirectory(prefix="lax-peer-context-policy-") as tmp:
            state = Path(tmp)
            config = {"pythonRoot": "/opt/fixture/runtime", **policy}
            connector = SimpleNamespace(state=state, config=config, http=AsyncMock())
            expected = {
                "authorityId": "authority",
                "agentId": "agent",
                "hostId": "host",
            }
            process = SimpleNamespace(
                returncode=0,
                communicate=AsyncMock(
                    return_value=(json.dumps(expected).encode(), b"")
                ),
            )
            with patch("lax_connector.host.machine_identity", return_value="machine"):
                with patch.object(
                    asyncio,
                    "create_subprocess_exec",
                    new=AsyncMock(return_value=process),
                ) as launch:
                    await purpose_provision.provision(
                        connector, {}, "original-operation", expected
                    )
                    saved = json.loads(
                        (state / "purpose-provision-agent.json").read_text()
                    )
                    self.assertEqual(launch.await_count, 1)
            return saved

    async def test_complete_explicit_context_policy_reaches_original_peer_spec(self):
        policy = {
            "contextRebuildEnabled": True,
            "automaticContextRefill": {"type": "canonical"},
            "nativeActionRetention": 1,
        }
        saved = await self.invoke(policy)
        self.assertEqual({k: saved[k] for k in policy}, policy)

    async def test_omitted_settings_and_explicit_disabled_policy_stay_distinct(self):
        for policy in (
            {},
            {
                "contextRebuildEnabled": False,
                "automaticContextRefill": None,
                "nativeActionRetention": 0,
            },
        ):
            saved = await self.invoke(policy)
            keys = {
                "contextRebuildEnabled",
                "automaticContextRefill",
                "nativeActionRetention",
            }
            self.assertEqual({k: saved[k] for k in keys if k in saved}, policy)

    async def test_incomplete_policy_has_no_journal_http_or_process_effects(self):
        with tempfile.TemporaryDirectory(prefix="lax-peer-invalid-policy-") as tmp:
            connector = SimpleNamespace(
                state=Path(tmp),
                config={"pythonRoot": "/opt/fixture", "nativeActionRetention": 1},
                http=AsyncMock(),
            )
            with patch("lax_connector.host.machine_identity", return_value="machine"):
                with patch.object(
                    asyncio, "create_subprocess_exec", new=AsyncMock()
                ) as launch:
                    with self.assertRaisesRegex(ValueError, "Retained-native Writer"):
                        await purpose_provision.provision(
                            connector, {}, "original-operation", {"agentId": "agent"}
                        )
                    connector.http.assert_not_called()
                    launch.assert_not_called()
            self.assertEqual(list(Path(tmp).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
