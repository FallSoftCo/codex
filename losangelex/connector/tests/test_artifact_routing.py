"""Distinct real roots and loopback report HTTP; canonical facts are synthetic."""

import copy
import hashlib
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer

from lax_connector import workflow
from lax_connector.collaboration_bridge import digest
from lax_connector.connector import Connector
from test_completed_report_reconcile import Fixture
from test_resource_routing import fixture_view


CAPTURE = json.loads((Path(__file__).parent / "fixtures/artifact-project-report-failure.json").read_text())
POLICY = {"artifactResourceEvidence": True, "artifactRootPolicy": "hollywood-artifact-root/v1", "resourceRouting": "canonical-agent-resources/v1", "resourceDefaults": True,
          "resourceMetadata": True}


class ArtifactJourneyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lax-artifact-journey-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.private, self.project = self.base / "private", self.base / "project"
        self.private.mkdir()
        self.project.mkdir()
        self.c = Fixture(self.private)
        self.c.active["request"]["data"]["workId"] = self.c.work
        self.c.role_context.value["communicationAdministrator"] = False
        self.c.journal = self.c.state / "native-journal.json"
        self.c.journal.write_text(json.dumps({"nativeTurn": "unchanged-current-turn"}))
        self.c.report_scope_briefings[self.c.prior]["reader"]["nativeTurn"] = "unchanged-current-turn"
        self.relative = CAPTURE["artifactPath"]
        self.content = b'print("synthetic accepted project result")\n'
        (self.project / self.relative).write_bytes(self.content)
        environment = digest({"hostId": self.c.host, "environmentId": "local"})
        info = self.project.stat()
        self.workspace = {"id": str(uuid4()), "authority": self.c.authority,
            "host": self.c.host, "root_path": str(self.project), "revision": 5,
            "state": "active", "environment_sha256": environment,
            "root_identity_sha256": digest({"hostId": self.c.host,
                "environmentSha256": environment, "device": info.st_dev, "inode": info.st_ino})}
        self.grant = {"authority": self.c.authority, "workspace": self.workspace["id"],
            "principal": self.c.agent, "execution_host": self.c.host, "revision": 9,
            "state": "active", "can_read": True, "can_write": False}
        self.view = fixture_view(self.c.authority, self.c.agent, self.c.host, self.workspace, self.grant)
        self.posts, self.reads, self.headers, self.commands = [], [], [], {}
        self.metadata_reads, self.on_recheck, self.pagination = 0, None, False
        self.outer_authority = self.c.authority
        self.counter, self.lose_reply = 0, False
        # Only the protected guardian capability projection is synthetic here.
        # Canonical metadata and reports use current Connector HTTP over real TCP.
        capability = patch("lax_connector.owner_briefing.publish", AsyncMock(return_value={
            "resourceCapabilities": POLICY}))
        self.capability = capability.start()
        self.addCleanup(capability.stop)
        app = web.Application()
        app.router.add_route("*", "/hollywood/v3/{path:.*}", self.handle)
        self.server = TestServer(app)
        await self.server.start_server()
        self.addAsyncCleanup(self.server.close)
        self.c.session = ClientSession()
        self.addAsyncCleanup(self.c.session.close)
        self.c.config["hollywoodUrl"] = str(self.server.make_url("")).rstrip("/")
        self.c.http = types.MethodType(Connector.http, self.c)
        self.c._http = types.MethodType(Connector._http, self.c)

    async def handle(self, request):
        self.assertEqual(request.headers["Authorization"], "Bearer " + self.c.config["token"])
        path = request.match_info["path"]
        if request.method == "GET":
            self.reads.append(path)
            if path.startswith("commands/"):
                return web.json_response(self.commands[path.removeprefix("commands/")])
            if path == "work/" + self.c.work:
                return web.json_response(self.c.work_response)
            if path == "deliveries/" + self.c.prior:
                return web.json_response(self.c.original)
            if path.startswith("agents/" + self.c.agent + "/resource"):
                if not request.query.get("after"):
                    self.metadata_reads += 1
                    if self.metadata_reads == 2 and self.on_recheck:
                        self.on_recheck()
                if "/resource-defaults/" in path:
                    return web.json_response({**self.view, "authorityId": self.outer_authority})
                first = self.pagination and not request.query.get("after")
                return web.json_response({"schema": "hollywood-agent-resources/v1",
                    "authorityId": self.outer_authority, "agentId": self.c.agent,
                    "executionHost": self.c.host, "default": self.view,
                    "resources": [] if first else [{"workspace": self.workspace, "grant": self.grant}],
                    "limit": 8, "nextCursor": self.workspace["id"] if first else None,
                    "mayApply": False})
            raise AssertionError(path)
        self.assertEqual(request.method, "POST")
        self.assertIn(path, ["work/" + self.c.work + "/report", "work/" + self.c.work + "/report-reconcile"])
        body = await request.json()
        self.posts.append((path, body))
        self.headers.append(json.loads(request.headers["X-Hollywood-Native-Source"]))
        event = {"id": str(uuid4()), "author": self.c.agent}
        accepted = {"accepted": True, "event": event, "state": body["state"], "deliveryId":
            self.c.prior if path.endswith("report-reconcile") else self.c.current}
        wire = {"method": "POST", "path": path, "body": body}
        self.commands[body["operationId"]] = {**accepted, "canonicalCommand": {
            "schema": "hollywood-command/v1", "authorityId": self.c.authority,
            "actorId": self.c.agent, "operationId": body["operationId"],
            "wireRequest": wire, "wireDigest": digest(wire), "eventId": event["id"],
            "acceptedResult": accepted, "evidenceComplete": True}}
        if self.lose_reply:
            return web.Response(status=503, text="synthetic lost accepted report reply")
        return web.json_response(accepted)

    async def invoke(self, reconcile=False, **extra):
        self.counter += 1
        self.metadata_reads = 0
        args = {"workId": self.c.work, "revision": 7, "state": "submitted",
                "note": "Verified original project artifact and criteria.", "artifactPaths": [self.relative]}
        if reconcile:
            args.update(priorDeliveryId=self.c.prior, effectDisposition="reviewed")
        args.update(extra)
        params = {"threadId": self.c.thread, "callId": "artifact-journey-" + str(self.counter),
                  "tool": "hollywood_work_report_reconcile" if reconcile else "hollywood_work_report",
                  "arguments": args}
        with self.c.effects.tool_scope("item/tool/call", params):
            result = await Connector._tool(self.c, "item/tool/call", params)
        self.c.rpc.call.assert_not_called()
        return result

    def unchanged(self):
        return copy.deepcopy((self.c.config, self.c.active, self.c.agent_binding, self.c.thread,
                              self.c.context_id, self.c.original, self.c.work_response))

    def assert_evidence(self, body):
        self.assertNotIn("artifactWorkspaceId", body)
        self.assertNotIn("artifactPaths", body)
        self.assertEqual(body["evidence"], [{"hostId": self.c.host,
            "workspaceId": self.c.config["workspaceId"], "relativePath": self.relative,
            "sha256": hashlib.sha256(self.content).hexdigest(), "size": len(self.content),
            "artifactRoot": {"schema": "hollywood-artifact-root/v1",
                "workspaceId": self.workspace["id"], "workspaceRevision": 5, "grantRevision": 9,
                "environmentSha256": self.workspace["environment_sha256"],
                "rootIdentitySha256": self.workspace["root_identity_sha256"]}}])
        self.assertNotEqual(self.c.config["workspaceId"], self.workspace["id"])
        header = self.headers[-1]
        for key, value in {"schema": "hollywood-native-source/v2", "agentId": self.c.agent,
            "deliveryId": self.c.current, "generation": 3, "claimId": "current-claim",
            "nativeThread": self.c.thread, "contextId": self.c.context_id,
            "nativeTurn": "unchanged-current-turn"}.items():
            self.assertEqual(header[key], value)
        self.assertFalse((self.private / self.relative).exists())

    async def test_captured_failure_then_selected_project_report_real_hash(self):
        self.assertEqual(CAPTURE["runtime"], "dev52/H34/native32708")
        with self.assertRaises(FileNotFoundError):
            workflow.artifacts(self.c.config, [self.relative])
        before = self.unchanged()
        self.assertTrue((await self.invoke())["success"])
        self.assert_evidence(self.posts[-1][1])
        self.assertEqual(self.metadata_reads, 2)
        self.assertEqual(before, self.unchanged())
        self.assertTrue(all(path.startswith("agents/" + self.c.agent + "/") for path in self.reads))
        self.assertGreaterEqual(self.capability.await_count, 2)

    async def test_explicit_paginated_readonly_project_reconciles_original_context(self):
        self.pagination = True
        self.view.update(effectiveState="cleared", selection=None, resource=None)
        before = self.unchanged()
        self.assertTrue((await self.invoke(True, artifactWorkspaceId=self.workspace["id"]))["success"])
        body = self.posts[-1][1]
        self.assert_evidence(body)
        self.assertEqual(body["priorDeliveryId"], self.c.prior)
        self.assertEqual(body["briefingSequence"], 122)
        self.assertEqual(body["scopeRead"], self.c.report_scope_briefings[self.c.prior]["scopeRead"])
        self.assertNotIn("claimId", body)
        self.assertEqual(before, self.unchanged())
        self.assertEqual(sum("/resources" in path for path in self.reads), 4)

    async def test_both_reporters_accept_both_choices_and_recover_original_lost_reply(self):
        for reconcile, explicit in [(False, True), (True, False)]:
            with self.subTest(reconcile=reconcile, explicit=explicit):
                self.lose_reply = True
                before = len(self.posts)
                args = {"artifactWorkspaceId": self.workspace["id"]} if explicit else {}
                self.assertTrue((await self.invoke(reconcile, **args))["success"])
                self.assertEqual(len(self.posts), before + 1)
                self.assert_evidence(self.posts[-1][1])
                self.assertTrue(any(path.startswith("commands/") for path in self.reads))

    async def test_changed_or_revoked_root_refuses_each_report_before_post(self):
        for reconcile in [False, True]:
            for target, field, value in [(self.grant, "state", "revoked"),
                (self.grant, "can_read", False), (self.grant, "revision", 10),
                (self.workspace, "revision", 6), (self.workspace, "state", "revoked"),
                (self.workspace, "root_identity_sha256", "f" * 64)]:
                with self.subTest(reconcile=reconcile, field=field, value=value):
                    prior = target[field]
                    self.on_recheck = lambda: target.update({field: value})
                    result = await self.invoke(reconcile, artifactWorkspaceId=self.workspace["id"])
                    self.assertFalse(result["success"])
                    self.assertEqual(self.metadata_reads, 2)
                    self.assertFalse(self.posts)
                    self.assertFalse(self.c.uncertain_tools)
                    target[field] = prior

    async def test_default_switch_and_physical_replacement_refuse_after_hash(self):
        self.on_recheck = lambda: self.view.update(effectiveState="held")
        self.assertFalse((await self.invoke())["success"])
        self.view["effectiveState"] = "selected"
        def replace():
            self.project.rename(self.base / "original-project")
            self.project.mkdir()
            (self.project / self.relative).write_bytes(b"replacement bytes")
        self.on_recheck = replace
        self.assertFalse((await self.invoke(True, artifactWorkspaceId=self.workspace["id"]))["success"])
        self.assertFalse(self.posts)
        self.assertFalse(self.c.uncertain_tools)

    async def test_server_missing_artifact_capability_refuses_without_read_or_post(self):
        with patch.dict(POLICY, {"artifactResourceEvidence": False}):
            self.assertFalse((await self.invoke())["success"])
        self.assertEqual(self.metadata_reads, 0)
        self.assertFalse(self.posts)

    async def test_no_private_fallback_or_foreign_root_or_scope(self):
        (self.private / self.relative).write_bytes(b"private decoy")
        self.view["effectiveState"] = "held"
        self.assertFalse((await self.invoke())["success"])
        self.assertFalse((await self.invoke(artifactWorkspaceId=str(uuid4())))["success"])
        self.view["effectiveState"] = "selected"
        self.outer_authority = str(uuid4())
        self.assertFalse((await self.invoke(True))["success"])
        self.outer_authority = self.c.authority
        self.grant["principal"] = str(uuid4())
        self.assertFalse((await self.invoke())["success"])
        self.grant["principal"] = self.c.agent
        self.workspace["host"] = str(uuid4())
        self.assertFalse((await self.invoke())["success"])
        self.assertFalse(self.posts)

    async def test_descriptor_paths_links_size_and_identity_are_fenced(self):
        (self.project / "link").symlink_to(self.private / "result.txt")
        for relative in ["../private/result.txt", "link", "a\\b", "./environment_report.py"]:
            with self.subTest(relative=relative):
                self.assertFalse((await self.invoke(artifactPaths=[relative]))["success"])
        self.c.config["artifactEvidenceMaxBytes"] = 1
        self.assertFalse((await self.invoke())["success"])
        del self.c.config["artifactEvidenceMaxBytes"]
        link = self.base / "project-link"
        link.symlink_to(self.project, target_is_directory=True)
        for path in [link, link / "subdir"]:
            self.workspace["root_path"] = str(path)
            self.assertFalse((await self.invoke())["success"])
        self.workspace["root_path"] = str(self.project)
        self.workspace["environment_sha256"] = "f" * 64
        self.assertFalse((await self.invoke())["success"])
        self.assertFalse(self.posts)
        self.assertFalse(self.c.uncertain_tools)

    async def test_empty_blocked_report_claims_no_resource_and_original_fences_remain(self):
        self.view["effectiveState"] = "held"
        self.assertTrue((await self.invoke(True, artifactPaths=[], state="blocked",
            effectDisposition="unknown"))["success"])
        self.assertEqual(self.posts[-1][1]["evidence"], [])
        self.assertFalse(any("/resource" in path for path in self.reads))
        self.posts.clear()
        self.c.original["agentContextBinding"]["workspace_id"] = str(uuid4())
        self.assertFalse((await self.invoke(True))["success"])
        self.c.active["request"]["data"]["workId"] = str(uuid4())
        self.assertFalse((await self.invoke())["success"])
        self.assertFalse(self.posts)


if __name__ == "__main__":
    unittest.main()
