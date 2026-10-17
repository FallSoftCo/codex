"""Connector boundary tests with synthetic authenticated receipt/HTTP fixtures.

No service, provider, database or historical executor is started. The separately
admitted two-participation native/server proof remains required for activation.
"""
import copy
import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from lax_connector import workflow
from lax_connector.connector import Connector, TOOLS, CAPABILITIES
from lax_connector.effects import Effects, digest
from lax_connector.errors import HttpFailure, ToolValidationError
from lax_connector.native_policy import normalized, verify


class Fixture:
    def __init__(self, root):
        self.agent, self.host, self.authority, self.work, self.prior, self.current = [str(uuid4()) for _ in range(6)]
        self.thread, self.context_id, self.room = str(uuid4()), "a" * 64, str(uuid4())
        self.config = {"agentId": self.agent, "hostId": self.host, "workspace": str(root),
                       "workspaceId": str(uuid4()), "token": "synthetic-fixture-not-a-credential",
                       "hollywoodUrl": "http://unused.invalid"}
        self.active = {"delivery": {"id": self.current, "agent": self.agent, "host": self.host,
                                   "authority": self.authority, "generation": 3,
                                   "claim_id": "current-claim", "event": str(uuid4()), "state": "running"},
                       "request": {"authority": self.authority, "room": self.room, "data": {}}}
        self.active["request"]["id"] = self.active["delivery"]["event"]
        self.role_context = SimpleNamespace(value={"roleRevision": 2})
        self.agent_binding = {"delivery": self.current, "generation": 3, "principal": self.agent,
                              "native_thread": self.thread, "context_id": self.context_id,
                              "workspace_id": self.config["workspaceId"], "role_revision": 2}
        original_request = str(uuid4())
        self.work_response = {"work": {"id": self.work, "owner": self.agent, "authority": self.authority,
                                     "revision": 7, "delivery": self.prior, "state": "assigned",
                                     "request_event": original_request, "room": self.room,
                                     "report_event": None, "evidence": []}}
        self.original = {"delivery": {"id": self.prior, "agent": self.agent, "host": self.host,
                                      "authority": self.authority, "generation": 1,
                                      "claim_id": "terminal-original-claim-never-sent-as-active",
                                      "event": original_request, "native_thread": self.thread,
                                      "state": "completed", "result_event": str(uuid4())},
                         "request": {"id": original_request, "authority": self.authority,
                                     "room": self.room, "recipient": self.agent, "kind": "request",
                                     "data": {"workId": self.work}},
                         "agentContextBinding": {**self.agent_binding, "delivery": self.prior,
                                                 "generation": 1, "role_revision": 1}}
        self.args = {"workId": self.work, "revision": 7, "priorDeliveryId": self.prior,
                     "state": "submitted", "effectDisposition": "reviewed",
                     "note": "Inspected original receipts and artifact; criteria verified. No effect replay.",
                     "artifactPaths": ["result.txt"]}
        (root / "result.txt").write_text("original-result\n")
        self.calls = []
        self.receipt = {"accepted": True, "state": "submitted", "deliveryId": self.prior,
                        "participationDeliveryId": self.current, "workRevision": 8}
        self.work_briefing = {"asOfSequence": 123}
        self.work_briefings = {self.prior: {"asOfSequence": 122,
            "authorityId": self.authority, "agentId": self.agent, "deliveryId": self.prior,
            "roomId": self.room, "generation": 1,
            "claimId": self.original["delivery"]["claim_id"], "requiresDeeperRead": False}}

        read_id = str(uuid4())
        self.report_scope_briefings = {self.prior: {
            "schema":"completed-report-briefing/v1", "readId":read_id,"revision":1,
            "scope":{"authorityId":self.authority,"agentId":self.agent,"workId":self.work,"workRevision":7,
                     "deliveryId":self.prior,"roomId":self.room,"requestId":original_request,
                     "generation":1,"claimId":self.original["delivery"]["claim_id"]},
            "reader":{"authorityId":self.authority,"agentId":self.agent,"hostId":self.host,
                      "deliveryId":self.current,"generation":3,"claimId":"current-claim",
                      "requestId":self.active["request"]["id"],"nativeThread":self.thread,
                      "contextId":self.context_id,"roleRevision":2},
            "snapshotSha256":"a"*64,"scopeSha256":"b"*64,"decisionsSha256":"c"*64,
            "complete":True,"decisionCount":0,"coveredCount":0,"nextCursor":None,
            "originalRoomDecisionSequence":122,"newExecutionAdmitted":False,"currentParticipationUnchanged":True,
            "expiresAt":(datetime.now(timezone.utc)+timedelta(minutes=15)).isoformat()}}
        value=self.report_scope_briefings[self.prior]
        value["scopeRead"]={"schema":"completed-report-scope-proof/v1",**{key:value[key] for key in
            ("readId","revision","snapshotSha256","scopeSha256","decisionsSha256","complete")}}
        self.report_scope_reads = {}
        self.scope_pages = []
        self.goal_binding = None
        self.rpc = SimpleNamespace(call=AsyncMock(side_effect=AssertionError("No native goal/turn operation allowed")))
        self.state = root / "state"
        self.state.mkdir()
        self.uncertain_tools = False
        self.publications = []
        self.effects = Effects(self)
        self.post_error = None

    async def http(self, method, path, payload=None):
        self.calls.append((method, path, copy.deepcopy(payload)))
        if method == "GET" and path == "work/" + self.work:
            return copy.deepcopy(self.work_response)
        if method == "GET" and path == "deliveries/" + self.prior:
            return copy.deepcopy(self.original)
        if method == "POST" and path == "work/" + self.work + "/report-briefing":
            return copy.deepcopy(self.scope_pages.pop(0))
        if method == "POST" and path == "work/" + self.work + "/report-reconcile":
            if self.post_error:
                raise self.post_error
            return copy.deepcopy(self.receipt)
        raise AssertionError((method, path))

    def posts(self):
        return [call for call in self.calls if call[0] == "POST"]


class ReconcileTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.c = Fixture(self.root)

    def tearDown(self):
        self.temp.cleanup()

    async def invoke(self, args=None):
        return await workflow.invoke(self.c, "hollywood_work_report_reconcile", args or self.c.args, "lax-tool:fixture")

    async def test_hash_original_and_keep_both_deliveries_distinct(self):
        before = copy.deepcopy((self.c.active, self.c.agent_binding, self.c.original, self.c.work_response))
        result = await self.invoke()
        payload = self.c.posts()[0][2]
        self.assertEqual(result["deliveryId"], self.c.prior)
        self.assertEqual(payload["priorDeliveryId"], self.c.prior)
        self.assertEqual(payload["effectDisposition"], "reviewed")
        self.assertTrue({"currentDeliveryId", "currentClaimId", "currentGeneration"}.isdisjoint(payload))
        self.assertNotIn("claimId", payload)
        self.assertNotIn("artifactPaths", payload)
        self.assertEqual(payload["evidence"], [{"hostId": self.c.host,
            "workspaceId": self.c.config["workspaceId"], "relativePath": "result.txt",
            "sha256": hashlib.sha256(b"original-result\n").hexdigest(), "size": 16}])
        self.assertEqual(before, (self.c.active, self.c.agent_binding, self.c.original, self.c.work_response))
        self.c.rpc.call.assert_not_called()

    async def test_original_scope_required_despite_newer_current_room_sequence(self):
        self.c.work_briefing = {"asOfSequence": 999999}
        original = copy.deepcopy(self.c.report_scope_briefings[self.c.prior])
        foreign=copy.deepcopy(original)
        foreign["scope"]["roomId"]=str(uuid4())
        partial={**original,"complete":False,"scopeRead":None}
        expired={**original,"expiresAt":"2000-01-01T00:00:00+00:00"}
        for value in [None,foreign,partial,expired]:
            self.c.report_scope_briefings={self.c.prior:value}
            with self.assertRaises(PermissionError):
                await self.invoke()
            self.assertFalse(self.c.posts())
        self.c.report_scope_briefings={self.c.prior:original}
        await self.invoke()
        self.assertEqual(self.c.posts()[0][2]["briefingSequence"],122)
        self.assertEqual(self.c.posts()[0][2]["scopeRead"],original["scopeRead"])

    async def test_explicit_scope_pages_preserve_current_participation_and_require_all_pages(self):
        from lax_connector.report_scope import read
        active=copy.deepcopy(self.c.active)
        last=copy.deepcopy(self.c.report_scope_briefings[self.c.prior])
        last.update(decisionCount=2,coveredCount=2)
        first={**last,"complete":False,"scopeRead":None,"coveredCount":1,"nextCursor":1}
        self.c.scope_pages=[first,last]
        self.c.report_scope_briefings={}
        page=await read(self.c,{"deliveryId":self.c.prior,"pageSize":1},"fixture:scope-page0")
        with self.assertRaises(PermissionError):
            await self.invoke()
        result=await read(self.c,{"deliveryId":self.c.prior,"readId":page["readId"],"cursor":1,"pageSize":1},"fixture:scope-page1")
        await self.invoke()
        self.assertEqual(self.c.posts()[-1][2]["scopeRead"],result["scopeRead"])
        self.assertEqual(self.c.active,active)
        self.c.rpc.call.assert_not_called()

    async def test_scope_pages_refuse_reader_and_snapshot_drift(self):
        from lax_connector.report_scope import read
        original=copy.deepcopy(self.c.report_scope_briefings[self.c.prior])
        for key,value in [("schema","unexpected"),("newExecutionAdmitted",True),
                          ("reader",{**original["reader"],"deliveryId":self.c.prior})]:
            self.c.scope_pages=[{**original,key:value}]
            with self.assertRaises(PermissionError):
                await read(self.c,{"deliveryId":self.c.prior},"fixture:scope-malformed")

    async def test_oversized_scope_output_cannot_populate_report_proof(self):
        from lax_connector.report_scope import read
        value=copy.deepcopy(self.c.report_scope_briefings[self.c.prior])
        value["decisions"]=[{"body":"x"*9000}]
        self.c.scope_pages=[value]
        self.c.report_scope_briefings={}
        with self.assertRaisesRegex(PermissionError,"native output bound"):
            await read(self.c,{"deliveryId":self.c.prior},"fixture:oversized-page")
        self.assertEqual(self.c.report_scope_briefings,{})
        self.assertEqual(self.c.report_scope_reads,{})
        with self.assertRaises(PermissionError):
            await self.invoke()

    async def test_blocked_may_preserve_uncertainty_without_artifact(self):
        args = {**self.c.args, "state": "blocked", "artifactPaths": [], "effectDisposition": "unknown",
                "note": "Original provider outcome remains unknown; no retry or success attested."}
        await self.invoke(args)
        self.assertEqual(self.c.posts()[0][2]["state"], "blocked")
        self.assertEqual(self.c.posts()[0][2]["effectDisposition"], "unknown")
        self.assertEqual(self.c.posts()[0][2]["evidence"], [])

    async def test_original_snapshot_fences_before_any_post(self):
        mutations = [
            ("work", "owner", str(uuid4())), ("work", "authority", str(uuid4())),
            ("work", "revision", 8), ("work", "delivery", str(uuid4())),
            ("work", "state", "cancel_requested"), ("work", "state", "submitted"),
            ("work", "report_event", str(uuid4())), ("work", "evidence", [{"size": 0}]),
            ("work", "request_event", str(uuid4())),
            ("delivery", "state", "running"), ("delivery", "state", "failed"),
            ("delivery", "state", "unknown"), ("delivery", "state", "cancelled"),
            ("delivery", "agent", str(uuid4())), ("delivery", "host", str(uuid4())),
            ("delivery", "authority", str(uuid4())), ("delivery", "native_thread", str(uuid4())),
            ("delivery", "result_event", None), ("delivery", "cancellation_requested", True),
            ("request", "recipient", str(uuid4())), ("request", "room", str(uuid4())),
            ("agentContextBinding", "context_id", "b" * 64),
            ("agentContextBinding", "native_thread", str(uuid4())),
            ("agentContextBinding", "workspace_id", str(uuid4())),
            ("agentContextBinding", "principal", str(uuid4())),
            ("agentContextBinding", "generation", 2),
        ]
        work, original = copy.deepcopy((self.c.work_response, self.c.original))
        for section, field, value in mutations:
            with self.subTest(section=section, field=field, value=value):
                self.c.work_response, self.c.original = copy.deepcopy((work, original))
                target = self.c.work_response["work"] if section == "work" else self.c.original[section]
                target[field] = value
                with self.assertRaises(PermissionError):
                    await self.invoke()
                self.assertFalse(self.c.posts())

    async def test_current_participation_binding_and_cancellation_fences(self):
        active, binding = copy.deepcopy((self.c.active, self.c.agent_binding))
        for section, field, value in [
            ("binding", "delivery", self.c.prior), ("binding", "generation", 2),
            ("binding", "workspace_id", str(uuid4())), ("binding", "context_id", "b" * 64),
            ("binding", "native_thread", str(uuid4())), ("binding", "role_revision", 1),
            ("delivery", "cancellation_requested", True), ("delivery", "host", str(uuid4())),
            ("delivery", "state", "completed"), ("delivery", "event", str(uuid4())),
        ]:
            with self.subTest(section=section, field=field):
                self.c.active, self.c.agent_binding = copy.deepcopy((active, binding))
                (self.c.agent_binding if section == "binding" else self.c.active["delivery"])[field] = value
                with self.assertRaises(PermissionError):
                    await self.invoke()
                self.assertFalse(self.c.calls)
        self.c.agent_binding = None
        with self.assertRaises(PermissionError):
            await self.invoke()

    async def test_paths_symlinks_missing_fifo_and_bounded_files_fail_without_post(self):
        (self.root / "link").symlink_to(self.root / "result.txt")
        (self.root / "dirlink").symlink_to(self.root, target_is_directory=True)
        os.mkfifo(self.root / "fifo")
        for path in ["../result.txt", "/etc/passwd", "", "missing", "link", "dirlink/result.txt", "fifo"]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                await self.invoke({**self.c.args, "artifactPaths": [path]})
            self.assertFalse(self.c.posts())
        self.c.config["artifactEvidenceMaxBytes"] = 1
        with self.assertRaises(ValueError):
            await self.invoke()
        self.assertFalse(self.c.posts())

    async def test_workspace_root_symlink_denied(self):
        link = self.root / "workspace-link"
        link.symlink_to(self.root, target_is_directory=True)
        self.c.config["workspace"] = str(link)
        with self.assertRaises(ValueError):
            await self.invoke()
        self.assertFalse(self.c.posts())

    async def test_root_descriptor_pins_directory_across_path_replacement(self):
        original = workflow.artifacts
        workspace = self.root / "workspace"
        workspace.mkdir()
        (workspace / "result.txt").write_text("original-result\n")
        self.c.config["workspace"] = str(workspace)
        def replace_path(config, paths, *, root_fd):
            workspace.rename(self.root / "retained-workspace")
            workspace.mkdir()
            (workspace / "result.txt").write_text("replacement\n")
            return original(config, paths, root_fd=root_fd)
        with patch.object(workflow, "artifacts", replace_path):
            await self.invoke()
        self.assertEqual(self.c.posts()[0][2]["evidence"][0]["sha256"], hashlib.sha256(b"original-result\n").hexdigest())

    async def test_file_changed_during_hash_rejected(self):
        real = hashlib.sha256
        class MutatingHash:
            def __init__(self): self.hash = real()
            def update(inner, block):
                inner.hash.update(block)
                (self.root / "result.txt").write_text("changed\n")
            def hexdigest(inner): return inner.hash.hexdigest()
        with patch.object(workflow.hashlib, "sha256", MutatingHash):
            with self.assertRaisesRegex(ValueError, "changed"):
                await self.invoke()
        self.assertFalse(self.c.posts())

    async def test_note_state_revision_and_artifact_arguments_validated(self):
        for patch_args in [{"note": " "}, {"note": "x" * 4001}, {"state": "accepted"},
                           {"revision": True}, {"revision": 0}, {"artifactPaths": "result.txt"},
                           {"artifactPaths": [None]}, {"artifactPaths": ["result.txt"] * 17}]:
            with self.subTest(patch=patch_args), self.assertRaises(ValueError):
                await self.invoke({**self.c.args, **patch_args})
            self.assertFalse(self.c.calls)

    async def test_effect_disposition_is_required_never_inferred_from_note_or_completion(self):
        missing = {k: v for k, v in self.c.args.items() if k != "effectDisposition"}
        for args in [missing, {**self.c.args, "effectDisposition": "unknown"},
                     {**self.c.args, "effectDisposition": True},
                     {**self.c.args, "effectDisposition": "stopped"}]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                await self.invoke(args)
            self.assertFalse(self.c.calls)

    async def test_normal_report_stays_captured_and_native_goal_strict(self):
        with self.assertRaises(PermissionError):
            await workflow.invoke(self.c, "hollywood_work_report", self.c.args, "fixture")
        self.c.active["request"]["data"]["workId"] = self.c.work
        self.c.goal_binding = {"nativeGoalId": "unfinished-original"}
        with patch.object(workflow, "progress", AsyncMock(return_value={"status": "active"})):
            with self.assertRaises(ToolValidationError):
                await workflow.invoke(self.c, "hollywood_work_report", self.c.args, "fixture")
        self.assertFalse(self.c.posts())

    async def test_native_dispatch_idempotent_same_call_and_changed_arguments_held(self):
        params = {"threadId": self.c.thread, "callId": "fixture-call", "tool": "hollywood_work_report_reconcile", "arguments": self.c.args}
        first = await Connector._tool(self.c, "item/tool/call", params)
        count = len(self.c.calls)
        second = await Connector._tool(self.c, "item/tool/call", params)
        self.assertTrue(first["success"])
        self.assertEqual(first, second)
        self.assertEqual(len(self.c.calls), count)
        changed = await Connector._tool(self.c, "item/tool/call", {**params, "arguments": {**self.c.args, "note": "changed"}})
        self.assertFalse(changed["success"])
        self.assertEqual(len(self.c.posts()), 1)

    async def test_unknown_effects_hold_new_reconciliation_mutation(self):
        self.c.uncertain_tools = True
        result = await Connector._tool(self.c, "item/tool/call", {"threadId": self.c.thread,
            "callId": "held", "tool": "hollywood_work_report_reconcile", "arguments": self.c.args})
        self.assertFalse(result["success"])
        self.assertFalse(self.c.calls)

    async def test_old_backend_missing_route_does_not_fallback_to_normal_report(self):
        self.c.post_error = HttpFailure(404, "route unavailable")
        result = await Connector._tool(self.c, "item/tool/call", {"threadId": self.c.thread,
            "callId": "unsupported", "tool": "hollywood_work_report_reconcile", "arguments": self.c.args})
        self.assertFalse(result["success"])
        self.assertTrue(self.c.uncertain_tools)
        self.assertEqual(len(self.c.posts()), 1)
        self.assertTrue(self.c.posts()[0][1].endswith("/report-reconcile"))

    async def test_server_rejections_propagate_without_connector_retry(self):
        for status in (403, 409):
            self.c.post_error = HttpFailure(status, "revoked, stale decision or report/cancel race")
            with self.assertRaises(HttpFailure):
                await self.invoke()
        self.assertEqual(len(self.c.posts()), 2)
        self.assertTrue(all(p[1].endswith("/report-reconcile") for p in self.c.posts()))

    async def test_current_native_source_v2_header_never_impersonates_original_claim(self):
        captured = {}
        class Response:
            status = 200
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return False
            async def json(self): return {"accepted": True}
        def request(method, url, **kwargs):
            captured.update(kwargs)
            return Response()
        self.c.session = SimpleNamespace(request=request)
        scope = {k: None for k in ("nativeGoalId", "argumentsDigest", "callId", "tool", "nativeTurn")}
        scope.update(authorityId=self.c.authority, agentId=self.c.agent, hostId=self.c.host,
                     deliveryId=self.c.current, claimId="current-claim", generation=3,
                     requestId=self.c.active["request"]["id"], nativeThread=self.c.thread,
                     roleRevision=2, contextId=self.c.context_id)
        self.c.effects.current.set({"scope": scope})
        await Connector._http(self.c, "POST", "work/" + self.c.work + "/report-reconcile", {})
        header = json.loads(captured["headers"]["X-Hollywood-Native-Source"])
        self.assertEqual(header["schema"], "hollywood-native-source/v2")
        self.assertEqual(header["deliveryId"], self.c.current)
        self.assertEqual(header["claimId"], "current-claim")
        self.assertNotEqual(header["deliveryId"], self.c.prior)

    async def test_lost_reply_recovers_exact_atomic_command_without_repost(self):
        scope = {"tool": "hollywood_work_report_reconcile", "authorityId": self.c.authority,
                 "agentId": self.c.agent, "hostId": self.c.host, "deliveryId": self.c.current,
                 "claimId": "current-claim", "generation": 3, "requestId": self.c.active["request"]["id"],
                 "nativeThread": self.c.thread, "callId": "lost-reply", "bindingAtStart": None}
        key = hashlib.sha256((self.c.thread + scope["callId"]).encode()).hexdigest()
        op = "lax-tool:" + key
        wire = {"method": "POST", "path": "work/" + self.c.work + "/report-reconcile",
                "body": {"operationId": op, "priorDeliveryId": self.c.prior}}
        step = {"ordinal": 0, "state": "unconfirmed", "method": "POST", "path": wire["path"],
                "operationId": op, "receiptSupported": True, "wireRequest": wire, "wireDigest": digest(wire)}
        event = str(uuid4())
        evidence = {"schema": "hollywood-command/v1", "evidenceComplete": True,
                    "authorityId": self.c.authority, "actorId": self.c.agent,
                    "operationId": op, "wireRequest": wire, "wireDigest": digest(wire),
                    "eventId": event, "acceptedResult": self.c.receipt}
        self.c.http = AsyncMock(return_value={"canonicalCommand": evidence,
            "event": {"id": event, "author": self.c.agent}})
        group = {"scope": scope, "steps": [step]}
        result = await self.c.effects.resolve(group)
        self.assertEqual(result, self.c.receipt)
        self.c.http.assert_awaited_once_with("GET", "commands/" + op)
        self.assertEqual(step["state"], "confirmed")
        evidence["wireDigest"] = "0" * 64
        with self.assertRaisesRegex(RuntimeError, "conflicts"):
            await self.c.effects.resolve(group)
        evidence["wireDigest"] = digest(wire)
        evidence["evidenceComplete"] = False
        self.assertIsNone(await self.c.effects.resolve(group))

    def test_tool_schema_dispatch_capability_and_native_policy_ceiling(self):
        tool = next(t for t in TOOLS if t["name"] == "hollywood_work_report_reconcile")
        self.assertFalse(tool["inputSchema"]["additionalProperties"])
        self.assertIn("priorDeliveryId", tool["inputSchema"]["required"])
        self.assertIn("effectDisposition", tool["inputSchema"]["required"])
        self.assertNotIn("evidence", tool["inputSchema"]["properties"])
        self.assertIn(tool["name"], workflow.MUTATION_TOOLS)
        self.assertNotIn(tool["name"], workflow.READ_TOOLS)
        self.assertIn("completed-work-report-reconciliation/v1", CAPABILITIES)
        ceiling = {"allowedTools": [{"name": tool["name"]}]}
        self.assertIn(("functions", tool["name"]), normalized(ceiling))
        verify(ceiling, {"toolPolicy": ceiling})


if __name__ == "__main__":
    unittest.main()
