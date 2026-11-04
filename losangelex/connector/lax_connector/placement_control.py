"""Revisioned same-host placement metadata; pause is not physical drainage."""

from .tool_execution import participation

from uuid import UUID
from .collaboration_bridge import require
from .resource_routing import connector_capabilities

READ_TOOL = "hollywood_placement_read"
SET_TOOL = "hollywood_placement_set"
CAPABILITY = "canonical-placement-control/v1"


def capabilities(value):
    require(
        value.get("placementControl") == CAPABILITY
        and value.get("pausedResourceSetup") is True,
        "Canonical placement control/paused setup capability unavailable",
    )
    return value


def view(value, authority, agent, host=None):
    # Preserve the existing public Held error contract for tool consumers.
    from .placement_view import view as projection_view
    try:
        return projection_view(value, authority, agent, host)
    except ValueError as error:
        require(False, str(error))


async def read(c, args):
    agent = str(UUID(args["agentId"]))
    require(
        c.role_context.value["communicationAdministrator"]
        or agent == c.config["agentId"],
        "Placement owner or administrator required",
    )
    capabilities(await connector_capabilities(c))
    return view(
        await c.http("GET", "placements/" + agent),
        participation(c)["request"]["authority"],
        agent,
    )


async def set_state(c, args, operation):
    require(
        c.role_context.value["communicationAdministrator"],
        "Administrator required for placement CAS",
    )
    agent, host = str(UUID(args["agentId"])), str(UUID(args["hostId"]))
    require(
        type(args["revision"]) is int
        and args["revision"] >= 1
        and type(args["enabled"]) is bool,
        "Inspected placement revision and strict boolean required",
    )
    capabilities(await connector_capabilities(c))
    # Backend enforces the original same enrollment and current native source,
    # including a paused administrator's inability to resume itself.
    payload = {
        "operationId": operation + ":admin:placement-state",
        "revision": args["revision"],
        "hostId": host,
        "enabled": args["enabled"],
    }
    return view(
        await c.http("PUT", "placements/" + agent, payload),
        participation(c)["request"]["authority"],
        agent,
        host,
    )


def definitions(spec):
    text = {"type": "string"}
    return [
        spec(
            READ_TOOL,
            "Inspect an owned placement or, as administrator, a named agent's current enrollment and revision. Reading admits no execution and verifies no drain.",
            {"agentId": text},
            ["agentId"],
        ),
        spec(
            SET_TOOL,
            "Administrator: CAS pause/resume the same inspected host enrollment. Pause does not stop a process, withdraw an issued apply grant or clear unknowns/locks. Independent drain is required; resume admits no work by itself.",
            {
                "agentId": text,
                "hostId": text,
                "revision": {"type": "integer", "minimum": 1},
                "enabled": {"type": "boolean"},
            },
            ["agentId", "hostId", "revision", "enabled"],
        ),
    ]
