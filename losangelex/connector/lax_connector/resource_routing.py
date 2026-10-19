"""Exact additive canonical-agent-resources/v1 consumers. Routing grants no effect."""

from .tool_execution import participation

import json
from urllib.parse import urlencode
from uuid import UUID

from .collaboration_bridge import require, digest

CAPABILITY = "canonical-agent-resources/v1"
READ_TOOLS = {
    "hollywood_resource_roots",
    "hollywood_agent_resources",
    "hollywood_resource_default",
}
SELECT_TOOL = "hollywood_select_resource_default"


def capabilities(value):
    require(
        value.get("resourceRouting") == CAPABILITY
        and value.get("resourceDefaults") is True
        and value.get("resourceMetadata") is True,
        "Canonical resource routing/default/metadata capability unavailable",
    )
    return value


def bounded(value):
    require(
        len(json.dumps(value, ensure_ascii=True).encode("ascii")) <= 32768,
        "Resource metadata exceeds published bound; request a smaller page",
    )
    require(
        value.get("mayApply") is False, "Resource metadata is never mutation admission"
    )
    return value


def query(args, *, host_key=None):
    limit = args.get("limit", 4)
    require(type(limit) is int and 1 <= limit <= 8, "Resource page limit must be 1..8")
    values = {"limit": limit}
    if host_key and args.get(host_key) is not None:
        values[host_key] = str(UUID(args[host_key]))
    if args.get("after") is not None:
        values["after"] = str(UUID(args["after"]))
    return urlencode(values)


def default_view(value, authority, agent, host):
    bounded(value)
    require(
        value.get("schema") == "hollywood-agent-resource-default/v1"
        and (value.get("authorityId"), value.get("agentId"), value.get("executionHost"))
        == (authority, agent, host)
        and type(value.get("selectionRevision")) is int
        and value["selectionRevision"] >= 0
        and value.get("effectiveState") in {"missing", "cleared", "selected", "held"},
        "Resource default scope or revision differs",
    )
    return value


async def connector_capabilities(c):
    if c.role_context.value["communicationAdministrator"]:
        return capabilities(
            await c.http("GET", "hosts/" + c.config["hostId"] + "/collaboration-bridge")
        )
    # Owner agents cannot read the controller/admin-only capability endpoint.
    # Reuse the authenticated managed-guardian briefing channel; no new backend route.
    from .owner_briefing import publish

    receipt = await publish(c, c.work_briefing)
    return capabilities((receipt or {}).get("resourceCapabilities") or {})


async def read(c, name, args):
    admin = c.role_context.value["communicationAdministrator"]
    authority = participation(c)["request"]["authority"]
    if name == "hollywood_resource_roots":
        require(admin, "Administrator required for registered root discovery")
        route = "physical-workspaces?" + query(args, host_key="hostId")
        expected = "hollywood-resource-roots/v1"
    else:
        agent, host = str(UUID(args["agentId"])), str(UUID(args["executionHost"]))
        require(
            admin or agent == c.config["agentId"],
            "Only own-agent resource metadata is readable",
        )
        if name == "hollywood_resource_default":
            route = "agents/" + agent + "/resource-defaults/" + host
            expected = "hollywood-agent-resource-default/v1"
        else:
            require(name == "hollywood_agent_resources", "Unknown resource read")
            route = (
                "agents/"
                + agent
                + "/resources?"
                + query(args, host_key="executionHost")
            )
            expected = "hollywood-agent-resources/v1"
    await connector_capabilities(c)
    value = bounded(await c.http("GET", route))
    require(
        value.get("schema") == expected and value.get("authorityId") == authority,
        "Resource metadata schema/scope differs",
    )
    if name != "hollywood_resource_roots":
        require(
            (value.get("agentId"), value.get("executionHost")) == (agent, host),
            "Resource owner/host differs",
        )
    if name == "hollywood_resource_default":
        return default_view(value, authority, agent, host)
    key = "workspaces" if name == "hollywood_resource_roots" else "resources"
    limit = args.get("limit", 4)
    require(
        isinstance(value.get(key), list)
        and len(value[key]) <= limit
        and value.get("limit") == limit,
        "Resource page exceeds requested row bound",
    )
    if value.get("nextCursor") is not None:
        UUID(value["nextCursor"])
    if name == "hollywood_agent_resources":
        default_view(value["default"], authority, agent, host)
    return value


def selection_payload(args, operation):
    require(
        type(args["revision"]) is int and args["revision"] >= 0,
        "Exact default CAS revision required",
    )
    payload = {
        "operationId": operation,
        **{
            k: args[k]
            for k in (
                "revision",
                "state",
                "workspaceId",
                "workspaceRevision",
                "grantRevision",
            )
        },
    }
    require(1 <= len(operation) <= 128, "Bounded original operation identity required")
    values = [payload[k] for k in ("workspaceId", "workspaceRevision", "grantRevision")]
    if payload["state"] == "cleared":
        require(
            all(v is None for v in values),
            "Cleared default requires explicit null resource/revisions",
        )
    else:
        require(
            payload["state"] == "selected"
            and values[0] is not None
            and all(type(v) is int and v >= 1 for v in values[1:]),
            "Selected default requires exact root and agent-grant revisions",
        )
        payload["workspaceId"] = str(UUID(values[0]))
    return payload


async def select(c, args, operation):
    require(
        c.role_context.value["communicationAdministrator"],
        "Administrator required for default selection",
    )
    agent, host = str(UUID(args["agentId"])), str(UUID(args["executionHost"]))
    payload = selection_payload(args, operation + ":admin:resource-default")
    await connector_capabilities(c)
    value = await c.http(
        "PUT", "agents/" + agent + "/resource-defaults/" + host, payload
    )
    return default_view(value, participation(c)["request"]["authority"], agent, host)


def definitions(spec):
    text = {"type": "string"}
    nullable = {"type": ["string", "null"]}
    page = {"after": nullable, "limit": {"type": "integer", "minimum": 1, "maximum": 8}}
    owner = {"agentId": text, "executionHost": text}
    return [
        spec(
            "hollywood_resource_roots",
            "Administrator: read one bounded page of registered roots and current revisions; follow nextCursor. Metadata starts no execution.",
            {"hostId": nullable, **page},
            [],
        ),
        spec(
            "hollywood_agent_resources",
            "Read one bounded page of own permitted resources, grants and current default; administrators may name another agent. Follow nextCursor; each page reauthorizes.",
            {**owner, **page},
            list(owner),
        ),
        spec(
            "hollywood_resource_default",
            "Read the named agent/host's explicit current default and its effective state. Administrators or the owner only. A selection is routing metadata, never permission to apply.",
            owner,
            list(owner),
        ),
        spec(
            SELECT_TOOL,
            "Administrator: select or clear explicit resource routing using inspected pointer/root/agent-grant CAS revisions. Clear requires all three resource fields null. Grants, locks and execution state remain separate.",
            {
                **owner,
                "revision": {"type": "integer", "minimum": 0},
                "state": {"type": "string", "enum": ["selected", "cleared"]},
                "workspaceId": nullable,
                "workspaceRevision": {"type": ["integer", "null"], "minimum": 1},
                "grantRevision": {"type": ["integer", "null"], "minimum": 1},
            },
            [
                *owner,
                "revision",
                "state",
                "workspaceId",
                "workspaceRevision",
                "grantRevision",
            ],
        ),
    ]


def agent_rows(http, policy, authority, agent, host):
    capabilities(policy)
    rows, after, seen = [], None, set()
    for _ in range(4):
        route = (
            "agents/"
            + agent
            + "/resources?"
            + query(
                {"executionHost": host, "after": after, "limit": 8},
                host_key="executionHost",
            )
        )
        value = bounded(http("GET", route))
        require(
            value.get("schema") == "hollywood-agent-resources/v1"
            and (
                value.get("authorityId"),
                value.get("agentId"),
                value.get("executionHost"),
            )
            == (authority, agent, host)
            and value.get("limit") == 8
            and len(value["resources"]) <= 8,
            "Exact bounded captured resource metadata required",
        )
        rows.extend(value["resources"])
        after = value["nextCursor"]
        if after is None:
            return rows
        after = str(UUID(after))
        require(after not in seen, "Resource cursor repeated")
        seen.add(after)
    require(False, "Captured resource page budget exhausted")


def intent_root(bridge, record, policy, environment):
    capabilities(policy)
    base = record["sourceBase"]
    value = bounded(
        bridge.http(
            "GET", "collaboration/delivery-resource-default/" + base["deliveryId"]
        )
    )
    require(
        value.get("schema") == "hollywood-delivery-resource-default/v1"
        and (value.get("deliveryId"), value.get("agentId"), value.get("executionHost"))
        == (base["deliveryId"], base["agentId"], base["hostId"]),
        "Captured delivery routing scope differs",
    )
    view = default_view(
        value["default"], base["authorityId"], base["agentId"], base["hostId"]
    )
    require(
        view["effectiveState"] == "selected" and view["resource"] is not None,
        "Relative intent requires a current explicit selected default",
    )
    pointer, resource = view["selection"], view["resource"]
    workspace, grant = resource["workspace"], resource["grant"]
    roots = [
        root
        for root in record["resources"]
        if root["workspaceId"] == str(workspace["id"])
        and root["environmentId"] == environment
    ]
    require(
        len(roots) == 1, "Selected default is not an approved captured local resource"
    )
    root = roots[0]
    require(
        pointer["state"] == "selected"
        and pointer["revision"] == view["selectionRevision"]
        and str(pointer["workspace"]) == root["workspaceId"]
        and (pointer["workspace_revision"], pointer["grant_revision"])
        == (root["registryRevision"], root["agentGrantRevision"])
        and workspace["revision"] == root["registryRevision"]
        and grant["revision"] == root["agentGrantRevision"]
        and workspace["state"] == "active"
        and grant["state"] == "active"
        and grant["can_read"] is True
        and grant["can_write"] is True
        and str(workspace["host"]) == base["hostId"]
        and str(grant["execution_host"]) == base["hostId"]
        and str(grant["workspace"]) == root["workspaceId"]
        and str(grant["principal"]) == base["agentId"]
        and workspace["root_path"] == root["root"],
        "Selected default revisions/host/access changed",
    )
    return root


def seed_defaults(state, http, authority, host, seeds, roots):
    from .collaboration_capture import administrative_put

    policy = capabilities(http("GET", "hosts/" + host + "/collaboration-bridge"))
    receipts = []
    for agent, seed in seeds.items():
        workspace_id = seed["defaultWorkspaceId"]
        matches = [
            row
            for row in agent_rows(http, policy, authority, agent, host)
            if str(row["workspace"]["id"]) == workspace_id
        ]
        require(
            len(matches) == 1,
            "Reviewed default needs one current canonical resource grant",
        )
        workspace, grant = matches[0]["workspace"], matches[0]["grant"]
        require(
            workspace["revision"] == roots[workspace_id]["registryRevision"]
            and workspace["state"] == "active"
            and grant["state"] == "active"
            and grant["can_read"] is True
            and grant["can_write"] is True
            and str(workspace["host"]) == host
            and str(grant["execution_host"]) == host
            and str(grant["workspace"]) == workspace_id
            and str(grant["principal"]) == agent,
            "Reviewed default resource access changed",
        )
        route = "agents/" + agent + "/resource-defaults/" + host
        view = default_view(http("GET", route), authority, agent, host)
        if view["selectionRevision"]:
            pointer = view["selection"]
            require(
                pointer["state"] == "selected"
                and str(pointer["workspace"]) == workspace_id
                and pointer["workspace_revision"] == workspace["revision"]
                and pointer["grant_revision"] == grant["revision"],
                "Existing default differs; explicit administrator CAS selection required",
            )
            if not (
                view["effectiveState"] == "held"
                and view["holdReason"] == "participation-invalidated"
            ):
                receipts.append(view)
                continue
            from .placement_control import (
                capabilities as placement_capabilities,
                view as placement_view,
            )

            placement_capabilities(policy)
            placed = placement_view(
                http("GET", "placements/" + agent), authority, agent, host
            )
            require(
                placed["state"] == "paused",
                "Reviewed default reselection requires paused placement",
            )
        payload = selection_payload(
            {
                "revision": view["selectionRevision"],
                "state": "selected",
                "workspaceId": workspace_id,
                "workspaceRevision": workspace["revision"],
                "grantRevision": grant["revision"],
            },
            "install-resource-default:"
            + digest(
                [agent, host, workspace_id, workspace["revision"], grant["revision"]]
                + ([view["selectionRevision"]] if view["selectionRevision"] else [])
            ),
        )
        result = administrative_put(state, http, route, payload)
        receipts.append(default_view(result, authority, agent, host))
    return receipts
