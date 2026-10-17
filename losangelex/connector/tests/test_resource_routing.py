"""Changed additive resource consumers only; no old edit suite or live service."""

import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from lax_connector import resource_routing as routing
from lax_connector.administration import administer
from lax_connector.collaboration_bridge import Bridge, Held, digest
from lax_connector.effects import Effects
from lax_connector.journal import saved
from test_collaboration_capture import CaptureFixture, uid

POLICY = {
    "resourceRouting": routing.CAPABILITY,
    "resourceDefaults": True,
    "resourceMetadata": True,
    "placementControl": "canonical-placement-control/v1",
    "pausedResourceSetup": True,
    "editPlans": True,
    "physicalTargets": True,
    "deliveryEdits": True,
    "deliveryEditSchema": "canonical-delivery-edits/v1",
    "workDeliveryEdits": True,
    "workDeliveryEditPolicy": "canonical-work-delivery-edits/v1",
    "bridge": {"revision": 1, "state": "active", "protocol": "canonical-edit-plans/v2"},
}


def fixture_view(authority, agent, host, workspace, grant, revision=19):
    return {
        "schema": "hollywood-agent-resource-default/v1",
        "authorityId": authority,
        "agentId": agent,
        "executionHost": host,
        "selection": {
            "authority": authority,
            "principal": agent,
            "execution_host": host,
            "revision": revision,
            "state": "selected",
            "workspace": workspace["id"],
            "workspace_revision": workspace["revision"],
            "grant_revision": grant["revision"],
        },
        "selectionRevision": revision,
        "effectiveState": "selected",
        "holdReason": None,
        "resource": {"workspace": workspace, "grant": grant},
        "mayApply": False,
    }


class NativeMetadataTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.c = SimpleNamespace(
            state=Path(self.tmp.name),
            role_context=SimpleNamespace(value={"communicationAdministrator": True}),
            config={"agentId": uid(1), "hostId": uid(2)},
            active={
                "request": {"authority": uid(3), "id": uid(4)},
                "delivery": {"id": uid(5), "generation": 1, "claim_id": "claim"},
            },
            thread="thread",
            work_briefing={"observed": True},
        )
        self.view = {
            "schema": "hollywood-agent-resource-default/v1",
            "authorityId": uid(3),
            "agentId": uid(1),
            "executionHost": uid(2),
            "selection": None,
            "selectionRevision": 0,
            "effectiveState": "missing",
            "holdReason": None,
            "resource": None,
            "mayApply": False,
        }

    async def test_admin_root_page_retains_exact_cursor_and_current_cas_metadata(self):
        page = {
            "schema": "hollywood-resource-roots/v1",
            "authorityId": uid(3),
            "workspaces": [{"id": uid(6), "revision": 7, "state": "revoked"}],
            "nextCursor": uid(6),
            "limit": 1,
            "mayApply": False,
        }
        self.c.http = AsyncMock(side_effect=[POLICY, page])
        result = await routing.read(
            self.c,
            "hollywood_resource_roots",
            {"hostId": uid(2), "after": uid(5), "limit": 1},
        )
        self.assertEqual(result, page)
        self.assertEqual(
            self.c.http.call_args.args,
            (
                "GET",
                "physical-workspaces?limit=1&hostId=" + uid(2) + "&after=" + uid(5),
            ),
        )
        self.assertEqual(self.c.http.await_count, 2)

    async def test_owner_page_uses_protected_capability_projection_and_no_admin_capability_read(
        self,
    ):
        self.c.role_context.value["communicationAdministrator"] = False
        page = {
            "schema": "hollywood-agent-resources/v1",
            "authorityId": uid(3),
            "agentId": uid(1),
            "executionHost": uid(2),
            "resources": [],
            "default": self.view,
            "nextCursor": None,
            "limit": 4,
            "mayApply": False,
        }
        self.c.http = AsyncMock(return_value=page)
        with patch(
            "lax_connector.owner_briefing.publish",
            new=AsyncMock(return_value={"resourceCapabilities": POLICY}),
        ) as carried:
            self.assertEqual(
                await routing.read(
                    self.c,
                    "hollywood_agent_resources",
                    {"agentId": uid(1), "executionHost": uid(2)},
                ),
                page,
            )
        carried.assert_awaited_once_with(self.c, self.c.work_briefing)
        self.assertEqual(
            self.c.http.call_args.args,
            ("GET", "agents/" + uid(1) + "/resources?limit=4&executionHost=" + uid(2)),
        )

    async def test_other_agent_and_root_reads_are_denied_before_any_http(self):
        self.c.role_context.value["communicationAdministrator"] = False
        self.c.http = AsyncMock()
        for name, args in [
            ("hollywood_resource_roots", {}),
            (
                "hollywood_agent_resources",
                {"agentId": uid(99), "executionHost": uid(2)},
            ),
        ]:
            with self.assertRaises(Held):
                await routing.read(self.c, name, args)
        self.c.http.assert_not_called()

    async def test_missing_capability_and_oversize_metadata_hold_without_truncating_or_next_page(
        self,
    ):
        self.c.http = AsyncMock(return_value={})
        with self.assertRaises(Held):
            await routing.read(self.c, "hollywood_resource_roots", {})
        self.assertEqual(self.c.http.await_count, 1)
        page = {
            "schema": "hollywood-resource-roots/v1",
            "authorityId": uid(3),
            "workspaces": [{"root_path": "x" * 33000}],
            "nextCursor": uid(9),
            "limit": 1,
            "mayApply": False,
        }
        self.c.http = AsyncMock(side_effect=[POLICY, page])
        with self.assertRaisesRegex(Held, "bound"):
            await routing.read(self.c, "hollywood_resource_roots", {"limit": 1})
        self.assertEqual(self.c.http.await_count, 2)

    async def test_select_and_clear_exact_nullable_dto_use_native_atomic_admin_stage(
        self,
    ):
        args = {
            "agentId": uid(1),
            "executionHost": uid(2),
            "revision": 0,
            "state": "selected",
            "workspaceId": uid(6),
            "workspaceRevision": 7,
            "grantRevision": 11,
        }
        for state in ["selected", "cleared"]:
            current = {**args, "state": state}
            if state == "cleared":
                current.update(
                    workspaceId=None, workspaceRevision=None, grantRevision=None
                )
            self.c.http = AsyncMock(side_effect=[POLICY, self.view])
            await administer(
                self.c, routing.SELECT_TOOL, current, "lax-tool:default-" + state
            )
            method, path, payload = self.c.http.call_args.args
            self.assertEqual(
                (method, path),
                ("PUT", "agents/" + uid(1) + "/resource-defaults/" + uid(2)),
            )
            self.assertEqual(
                payload,
                {
                    "operationId": "lax-tool:default-"
                    + state
                    + ":admin:resource-default",
                    **{
                        k: v
                        for k, v in current.items()
                        if k not in {"agentId", "executionHost"}
                    },
                },
            )
            if os.environ.get("LAX_RESOURCE_DEFAULT_SCHEMA"):
                import jsonschema

                jsonschema.validate(
                    payload,
                    json.loads(
                        Path(os.environ["LAX_RESOURCE_DEFAULT_SCHEMA"]).read_text()
                    ),
                )
        with self.assertRaises(Held):
            routing.selection_payload({**args, "state": "cleared"}, "operation")

    async def test_unconfirmed_default_uses_original_administrative_get_not_put(self):
        effects = Effects(self.c)
        key = hashlib.sha256(b"threadcall").hexdigest()
        operation = "lax-tool:" + key + ":admin:resource-default"
        scope = {
            "authorityId": uid(3),
            "agentId": uid(1),
            "hostId": uid(2),
            "requestId": uid(4),
            "deliveryId": uid(5),
            "claimId": "claim",
            "generation": 1,
            "nativeThread": "thread",
            "tool": routing.SELECT_TOOL,
            "callId": "call",
        }
        step = {
            "administrativeReceiptSupported": True,
            "operationId": operation,
            "method": "PUT",
            "path": "agents/" + uid(1) + "/resource-defaults/" + uid(2),
            "wireDigest": "a" * 64,
            "state": "unconfirmed",
        }
        journal = self.c.state / "effects-fixture.json"
        saved(journal, {"scope": scope, "steps": [step]})
        self.c.http = AsyncMock(
            return_value={
                "schema": "hollywood-administrative-command/v1",
                "authorityId": uid(3),
                "actorId": uid(1),
                "operationId": operation,
                "method": "PUT",
                "path": step["path"],
                "wireDigest": "a" * 64,
                "acceptedResult": self.view,
            }
        )
        token = effects.current.set({"key": key, "scope": scope})
        try:
            self.assertEqual(await effects.recover_http((journal, 0)), self.view)
        finally:
            effects.current.reset(token)
        self.assertEqual(
            self.c.http.call_args.args, ("GET", "administration/commands/" + operation)
        )


@unittest.skipUnless(os.geteuid() == 0, "Root protected fixture route")
class PlannedRoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lax-resource-route-", dir="/run")
        self.addCleanup(self.tmp.cleanup)
        self.f = CaptureFixture(Path(self.tmp.name))
        self.f.policy["schema"] = "lax-automatic-native-capture/v2"
        self.f.policy.pop("agents")
        self.f.snapshot["request"].update(kind="request", recipient=self.f.agent, room=uid(91))
        self.f.snapshot["request"]["data"] = {
            "workId": self.f.work, "workRevision": 4, "goalId": self.f.goal,
            "attemptId": self.f.delivery, "attemptNumber": 1,
            "workCompletionPolicy": "report-required/v1",
        }
        self.f.work_row["room"] = uid(91)
        root = self.f.physical
        env = digest({"hostId": self.f.host, "environmentId": "local"})
        self.workspace = {
            "id": self.f.resource,
            "host": self.f.host,
            "root_path": root["root"],
            "revision": 1,
            "state": "active",
            "environment_sha256": env,
            "root_identity_sha256": digest(
                {
                    "hostId": self.f.host,
                    "environmentSha256": env,
                    "device": root["device"],
                    "inode": root["inode"],
                }
            ),
        }
        self.grant = {
            "workspace": self.f.resource,
            "principal": self.f.agent,
            "revision": 7,
            "state": "active",
            "execution_host": self.f.host,
            "can_read": True,
            "can_write": True,
        }
        self.view = fixture_view(
            self.f.authority, self.f.agent, self.f.host, self.workspace, self.grant
        )
        self.original = self.f.http

        def http(method, route, body=None):
            if route.endswith("/collaboration-bridge"):
                return copy.deepcopy(POLICY)
            if route.startswith("agents/" + self.f.agent + "/resources?"):
                return {
                    "schema": "hollywood-agent-resources/v1",
                    "authorityId": self.f.authority,
                    "agentId": self.f.agent,
                    "executionHost": self.f.host,
                    "resources": [
                        {
                            "workspace": copy.deepcopy(self.workspace),
                            "grant": copy.deepcopy(self.grant),
                        }
                    ],
                    "default": copy.deepcopy(self.view),
                    "nextCursor": None,
                    "limit": 8,
                    "mayApply": False,
                }
            if route.startswith("collaboration/delivery-resource-default/"):
                return {
                    "schema": "hollywood-delivery-resource-default/v1",
                    "deliveryId": self.f.delivery,
                    "agentId": self.f.agent,
                    "executionHost": self.f.host,
                    "default": copy.deepcopy(self.view),
                    "mayApply": False,
                }
            if route.startswith("collaboration/delivery-targets/"):
                return {
                    "schema": "hollywood-agent-physical-target-registry/v1",
                    "deliveryId": self.f.delivery, "principalId": self.f.agent,
                    "mayApply": False,
                    "targets": [{**copy.deepcopy(self.workspace),
                                 "grant_revision": self.grant["revision"],
                                 "grant_state": self.grant["state"],
                                 **{k: self.grant[k] for k in
                                    ("can_read", "can_write", "execution_host")}}],
                }
            return self.original(method, route, body)

        self.http = http
        self.f.bridge.http = http
        self.f.capture.admin_http = http

    def test_business_capture_and_explicit_plan_keep_distinct_agent_work_grants(
        self,
    ):
        record = self.f.capture.ensure(
            (os.getpid(), os.geteuid(), 0),
            {"threadId": "thread", "turnId": "turn", "port": "coordination"},
        )
        root = record["resources"][0]
        self.assertEqual(root["agentGrantRevision"], 7)
        bridge = object.__new__(Bridge)
        bridge.config = self.f.config
        bridge.http = self.http
        target = bridge.attestation(
            record,
            {
                "source": record["sourceBase"],
                "command": {"workId": self.f.work, "workRevision": 4},
            },
            root,
            ["demo.txt"],
        )
        self.assertEqual(target["grantRevision"], 1)
        self.assertEqual(record["scope"], "delivery")
        self.assertEqual(record["work"]["id"], self.f.work)
        self.assertEqual(record["work"]["revision"], 4)

    def test_current_explicit_default_routes_relative_intent_without_changing_capture_or_cwd(
        self,
    ):
        record = self.f.ensure()
        before = copy.deepcopy(record)
        self.assertEqual(
            routing.intent_root(self.f.bridge, record, POLICY, "local"),
            record["resources"][0],
        )
        self.assertEqual(record, before)
        self.view["effectiveState"] = "cleared"
        self.view["resource"] = None
        with self.assertRaises(Held):
            routing.intent_root(self.f.bridge, record, POLICY, "local")
        self.assertEqual(
            self.f.ensure(), before
        )  # Routing change alone does not fence absolute native patch capture.

    def test_missing_held_capability_and_agent_revision_drift_never_choose_sole_resource(
        self,
    ):
        record = self.f.ensure()
        for state in ["missing", "held", "cleared"]:
            self.view["effectiveState"] = state
            with self.assertRaises(Held):
                routing.intent_root(self.f.bridge, record, POLICY, "local")
        self.view["effectiveState"] = "selected"
        self.view["selection"]["grant_revision"] = 8
        with self.assertRaises(Held):
            routing.intent_root(self.f.bridge, record, POLICY, "local")
        with self.assertRaises(Held):
            routing.intent_root(self.f.bridge, record, {}, "local")

    def test_capture_metadata_cursor_budget_does_not_fall_back_or_loop(self):
        def page(method, route):
            return {
                "schema": "hollywood-agent-resources/v1",
                "authorityId": self.f.authority,
                "agentId": self.f.agent,
                "executionHost": self.f.host,
                "resources": [],
                "limit": 8,
                "nextCursor": uid(99),
                "mayApply": False,
            }

        with self.assertRaisesRegex(Held, "cursor repeated"):
            routing.agent_rows(
                page, POLICY, self.f.authority, self.f.agent, self.f.host
            )

    def test_installer_seed_publishes_real_default_once_and_never_overwrites_clear(
        self,
    ):
        state = {
            "view": {
                **copy.deepcopy(self.view),
                "selection": None,
                "selectionRevision": 0,
                "effectiveState": "missing",
                "resource": None,
            }
        }
        calls = []

        def http(method, route, body=None):
            calls.append((method, route, copy.deepcopy(body)))
            if method == "PUT":
                state["view"] = copy.deepcopy(self.view)
                return copy.deepcopy(self.view)
            if "/resource-defaults/" in route:
                return copy.deepcopy(state["view"])
            return self.http(method, route, body)

        seeds = {self.f.agent: {"defaultWorkspaceId": self.f.resource}}
        routing.seed_defaults(
            self.f.state,
            http,
            self.f.authority,
            self.f.host,
            seeds,
            {self.f.resource: self.f.physical},
        )
        routing.seed_defaults(
            self.f.state,
            http,
            self.f.authority,
            self.f.host,
            seeds,
            {self.f.resource: self.f.physical},
        )
        puts = [c for c in calls if c[0] == "PUT"]
        self.assertEqual(len(puts), 1)
        self.assertEqual(puts[0][2]["grantRevision"], 7)
        state["view"]["selection"]["state"] = "cleared"
        with self.assertRaises(Held):
            routing.seed_defaults(
                self.f.state,
                http,
                self.f.authority,
                self.f.host,
                seeds,
                {self.f.resource: self.f.physical},
            )
        self.assertEqual(len([c for c in calls if c[0] == "PUT"]), 1)


class PlacementConsumerTests(unittest.IsolatedAsyncioTestCase):
    setUp = NativeMetadataTests.setUp

    # Only new placement methods are selected by the finite runner; inherited
    # resource tests are not rerun.
    async def test_same_host_placement_cas_uses_exact_dto_and_no_post_registration(
        self,
    ):
        from lax_connector import placement_control as placement

        row = {
            "schema": "hollywood-placement/v1",
            "authorityId": uid(3),
            "agentId": uid(7),
            "hostId": uid(2),
            "placement": {
                "authority": uid(3),
                "agent": uid(7),
                "host": uid(2),
                "enabled": False,
                "generation": 4,
                "revision": 10,
            },
            "state": "paused",
            "mayApply": False,
            "newExecutionAdmitted": False,
            "drainVerified": False,
        }
        args = {"agentId": uid(7), "hostId": uid(2), "revision": 9, "enabled": False}
        self.c.http = AsyncMock(side_effect=[POLICY, row])
        result = await administer(self.c, placement.SET_TOOL, args, "lax-tool:pause")
        self.assertEqual(result, row)
        method, path, payload = self.c.http.call_args.args
        self.assertEqual((method, path), ("PUT", "placements/" + uid(7)))
        self.assertEqual(
            payload,
            {
                "operationId": "lax-tool:pause:admin:placement-state",
                "revision": 9,
                "hostId": uid(2),
                "enabled": False,
            },
        )
        if os.environ.get("LAX_PLACEMENT_SCHEMA"):
            import jsonschema

            jsonschema.validate(
                payload,
                json.loads(Path(os.environ["LAX_PLACEMENT_SCHEMA"]).read_text()),
            )
        for enabled in [0, "false"]:
            with self.assertRaises(Held):
                await placement.set_state(
                    self.c, {**args, "enabled": enabled}, "lax-tool:invalid"
                )
        self.assertEqual(self.c.http.await_count, 2)

    async def test_owner_placement_inspect_cannot_mutate_even_with_capability(self):
        from lax_connector import placement_control as placement

        self.c.role_context.value["communicationAdministrator"] = False
        self.c.http = AsyncMock()
        with self.assertRaises(Held):
            await placement.set_state(
                self.c,
                {"agentId": uid(1), "hostId": uid(2), "revision": 1, "enabled": True},
                "lax-tool:self",
            )
        with self.assertRaises(Held):
            await placement.read(self.c, {"agentId": uid(99)})
        self.c.http.assert_not_called()


@unittest.skipUnless(os.geteuid() == 0, "Root protected fixture route")
class ChangedSetupTests(unittest.TestCase):
    def test_fresh_setup_records_paused_default_without_starting_or_resuming(self):
        import test_collaboration_capture as original_fixture
        from lax_connector.collaboration_install import prepare, apply

        original_fixture.InstallerTests.setUp(self)
        with patch(
            "lax_connector.collaboration_install.expected_owner",
            return_value=(1000, None, None),
        ):
            prepare(self.spec, self.root / "prepared")
        candidate = json.loads(
            (self.root / "prepared/bridge.prepared.json").read_text()
        )
        root = candidate["automaticCapture"]["resources"][0]
        workspace = {
            "id": root["workspaceId"],
            "revision": 1,
            "state": "active",
            "host": self.host,
            "root_path": root["root"],
        }
        grant = {
            "workspace": root["workspaceId"],
            "principal": self.agent,
            "revision": 1,
            "state": "active",
            "can_read": True,
            "can_write": True,
            "execution_host": self.host,
        }
        selected = fixture_view(
            self.authority, self.agent, self.host, workspace, grant, revision=1
        )
        selected.update(
            effectiveState="held", holdReason="participation-unavailable", resource=None
        )
        missing = {
            **selected,
            "selection": None,
            "selectionRevision": 0,
            "effectiveState": "missing",
        }
        calls = []

        def request(url, token, method, path, body=None):
            calls.append((method, path, body))
            if path.endswith("/admission"):
                return {"policy": {"controller": uid(10)}}
            if method == "GET" and path.endswith("/collaboration-bridge"):
                return {**POLICY, "bridge": None}
            if method == "PUT" and path.endswith("/collaboration-bridge"):
                return {"bridge": {"revision": 1}}
            if "/agent-grants/" in path:
                return {"grant": grant}
            if "/physical-workspaces/" in path:
                return {"workspace": {"revision": 1}}
            if "/resources?" in path:
                return {
                    "schema": "hollywood-agent-resources/v1",
                    "authorityId": self.authority,
                    "agentId": self.agent,
                    "executionHost": self.host,
                    "resources": [{"workspace": workspace, "grant": grant}],
                    "default": missing,
                    "nextCursor": None,
                    "limit": 8,
                    "mayApply": False,
                }
            if "/resource-defaults/" in path:
                return selected if method == "PUT" else missing
            raise AssertionError(path)

        with (
            patch("lax_connector.collaboration_install.request", side_effect=request),
            patch("subprocess.run") as system,
        ):
            result = apply(self.root / "prepared")
            system.assert_not_called()
        self.assertEqual(result["resourceDefaults"], [selected])
        self.assertEqual(result["servicesStarted"], 0)
        self.assertEqual(len([c for c in calls if c[0] == "PUT"]), 4)
        self.assertFalse([c for c in calls if c[1].startswith("placements")])

    def test_upgrade_refuses_missing_paused_setup_capability_before_intent_or_canonical_write(
        self,
    ):
        import test_collaboration_upgrade as original_fixture
        from lax_connector import collaboration_upgrade as upgrade

        original_fixture.BridgeUpgradeTests.setUp(self)
        original_fixture.BridgeUpgradeTests.fixture(self)

        def request(url, token, method, path, body=None):
            self.assertEqual(method, "GET")
            return {
                **POLICY,
                "pausedResourceSetup": False,
                "bridge": {
                    "state": "active",
                    "protocol": "canonical-edit-plans/v2",
                    "revision": 4,
                    "adapter_sha256": "a" * 64,
                    "controller": self.agent,
                },
            }

        with patch.object(upgrade, "request", side_effect=request):
            with self.assertRaisesRegex(Held, "paused setup"):
                upgrade.upgrade(self.prepared, **self.kwargs)
        self.assertEqual(list((self.state / "upgrades").glob("*-intent.json")), [])
        self.assertEqual(json.loads(self.config_path.read_text()), self.old)


class NativeSourceProjectionTests(unittest.IsolatedAsyncioTestCase):
    setUp = NativeMetadataTests.setUp

    async def test_new_mutations_keep_current_source_v2_header(self):
        from lax_connector.connector import Connector

        class Reply:
            status = 200

            async def json(self):
                return {"accepted": True}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

        observed = []

        def request(method, path, **kwargs):
            observed.append((method, path, kwargs))
            return Reply()

        c = object.__new__(Connector)
        c.config = {
            "token": "synthetic-not-a-secret",
            "hollywoodUrl": "http://fixture.invalid",
        }
        c.agent_binding = {"bound": True}
        c.session = SimpleNamespace(request=request)
        c.effects = Effects(c)
        base = {
            "authorityId": uid(3),
            "agentId": uid(1),
            "hostId": uid(2),
            "deliveryId": uid(5),
            "claimId": "original",
            "generation": 1,
            "requestId": uid(4),
            "nativeThread": "persistent-thread",
            "nativeTurn": "turn",
            "callId": "call",
            "argumentsDigest": "a" * 64,
            "roleRevision": 7,
            "contextId": "private-context",
            "nativeGoalId": None,
        }
        for name in [routing.SELECT_TOOL, "hollywood_placement_set"]:
            token = c.effects.current.set({"scope": {**base, "tool": name}})
            try:
                await c._http("PUT", "fixed-route", {"operationId": "original"})
            finally:
                c.effects.current.reset(token)
            header = json.loads(observed[-1][2]["headers"]["X-Hollywood-Native-Source"])
            self.assertEqual(
                header, {"schema": "hollywood-native-source/v2", **base, "tool": name}
            )


@unittest.skipUnless(os.geteuid() == 0, "Root protected fixture route")
class IntentAndGuardianProjectionTests(unittest.TestCase):
    def test_v2_relative_intent_never_selects_cwd_when_default_is_missing(self):
        fixture = PlannedRoutingTests(
            methodName="test_current_explicit_default_routes_relative_intent_without_changing_capture_or_cwd"
        )
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        f = fixture.f
        record = f.ensure()
        bridge = object.__new__(Bridge)
        bridge.config = {
            **f.config,
            "automaticCapture": {"schema": "lax-automatic-native-capture/v2"},
        }
        bridge.state = f.state
        bridge.http = fixture.http
        bridge.captured = lambda *args: (
            record,
            {"tool": "collaborative_edit_plan"},
            POLICY,
        )
        observed = []
        bridge.relay = lambda *args: (
            observed.append(args) or {"receipt": {"accepted": True}}
        )
        frame = {
            "port": "edit-plans",
            "arguments": {
                "command": {
                    "action": "propose",
                    "workId": f.work,
                    "planId": uid(90),
                    "manifest": {"files": []},
                }
            },
            "evidence": {
                "environmentId": "local",
                "cwd": Path(f.physical["root"]).as_uri(),
            },
        }
        fixture.view["effectiveState"] = "missing"
        fixture.view["resource"] = None
        with self.assertRaisesRegex(Held, "explicit selected default"):
            bridge.handle((os.getpid(), 0, 0), frame)
        self.assertEqual(observed, [])
        fixture.view["effectiveState"] = "selected"
        fixture.view["resource"] = {
            "workspace": fixture.workspace,
            "grant": fixture.grant,
        }
        self.assertTrue(bridge.handle((os.getpid(), 0, 0), frame)["success"])
        self.assertEqual(observed[0][4]["workspaceId"], f.resource)

    def test_guardian_briefing_receipt_projects_only_backend_capability_flags(self):
        import test_owner_briefing as fixture_module

        fixture = fixture_module.OwnerBriefingTests(
            methodName="test_observed_owner_metadata_is_root_protected_and_never_grants_an_effect"
        )
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.f.bridge.http = lambda *args: {
            **POLICY,
            "unexpectedPrivateField": "must not be projected",
        }
        result = fixture.carry()["result"]
        self.assertEqual(
            result["resourceCapabilities"],
            {
                key: POLICY[key]
                for key in [
                    "resourceRouting",
                    "resourceDefaults",
                    "resourceMetadata",
                    "placementControl",
                    "pausedResourceSetup",
                ]
            },
        )
        self.assertFalse(result["mayApply"])
