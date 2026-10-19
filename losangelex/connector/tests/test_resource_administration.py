"""Native resource administration/effect receipts, with canonical HTTP fixtures."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

from lax_connector.administration import administer
from lax_connector.effects import Effects
from lax_connector.journal import saved


def bind_owner(c):
    import copy
    c.captured_execution = lambda: {
        **copy.deepcopy(c.active), "nativeThread": getattr(c, "thread", "fixture-thread"),
        "nativeTurn": "fixture-native-turn",
    }
    return c


def uid(n):
    return str(UUID(int=n))


class ResourceAdministrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.c = SimpleNamespace(
            state=Path(self.tmp.name),
            role_context=SimpleNamespace(value={"communicationAdministrator": True}),
            config={"agentId": uid(1), "hostId": uid(2)},
            active={
                "request": {"authority": uid(3), "id": uid(4)},
                "delivery": {"id": uid(5), "claim_id": "claim", "generation": 1},
            },
            thread="thread",
        )
        bind_owner(self.c)
        self.args = {
            "workspaceId": uid(6),
            "agentId": uid(7),
            "executionHost": uid(2),
            "revision": 0,
            "workspaceRevision": 1,
            "state": "active",
            "canRead": True,
            "canWrite": True,
        }

    async def test_native_grant_uses_exact_existing_resource_and_atomic_admin_receipt_stage(
        self,
    ):
        self.c.http = AsyncMock(
            return_value={
                "schema": "hollywood-physical-agent-grant/v1",
                "grant": {"revision": 1},
                "mayApply": False,
            }
        )
        result = await administer(
            self.c, "hollywood_grant_resource", self.args, "lax-tool:fixture"
        )
        method, route, body = self.c.http.call_args.args
        self.assertEqual(
            (method, route),
            ("PUT", "physical-workspaces/" + uid(6) + "/agent-grants/" + uid(7)),
        )
        self.assertEqual(
            body,
            {
                "operationId": "lax-tool:fixture:admin:resource-grant",
                **{
                    k: self.args[k]
                    for k in self.args
                    if k not in {"workspaceId", "agentId"}
                },
            },
        )
        self.assertFalse(result["mayApply"])
        self.assertNotIn("rootPath", body)

    async def test_nonadministrator_never_sends_a_resource_mutation(self):
        self.c.role_context.value["communicationAdministrator"] = False
        self.c.http = AsyncMock()
        with self.assertRaises(PermissionError):
            await administer(
                self.c, "hollywood_grant_resource", self.args, "lax-tool:fixture"
            )
        self.c.http.assert_not_called()

    async def test_unconfirmed_grant_reads_exact_original_receipt_without_put_replay(
        self,
    ):
        effects = Effects(self.c)
        key = hashlib.sha256(b"threadcall").hexdigest()
        scope = {
            "authorityId": uid(3),
            "agentId": uid(1),
            "hostId": uid(2),
            "requestId": uid(4),
            "deliveryId": uid(5),
            "claimId": "claim",
            "generation": 1,
            "nativeThread": "thread",
            "tool": "hollywood_grant_resource",
            "callId": "call",
        }
        operation = "lax-tool:" + key + ":admin:resource-grant"
        step = {
            "administrativeReceiptSupported": True,
            "operationId": operation,
            "method": "PUT",
            "path": "physical-workspaces/" + uid(6) + "/agent-grants/" + uid(7),
            "wireDigest": "a" * 64,
            "state": "unconfirmed",
        }
        path = self.c.state / "effects.json"
        saved(path, {"scope": scope, "steps": [step]})
        result = {
            "schema": "hollywood-physical-agent-grant/v1",
            "grant": {"revision": 1},
            "mayApply": False,
        }
        self.c.http = AsyncMock(
            return_value={
                "schema": "hollywood-administrative-command/v1",
                "authorityId": uid(3),
                "actorId": uid(1),
                "operationId": operation,
                "method": "PUT",
                "path": step["path"],
                "wireDigest": step["wireDigest"],
                "acceptedResult": result,
            }
        )
        token = effects.current.set({"key": key, "scope": scope})
        try:
            self.assertEqual(await effects.recover_http((path, 0)), result)
        finally:
            effects.current.reset(token)
        self.c.http.assert_awaited_once_with(
            "GET", "administration/commands/" + operation
        )
        self.assertEqual(json.loads(path.read_text())["steps"][0]["state"], "confirmed")
