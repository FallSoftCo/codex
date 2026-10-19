"""Native tools for canonical Work resource intent, never agent identity changes."""
from uuid import UUID
from .tool_execution import participation

READ_TOOL = "hollywood_work_resource"
SELECT_TOOL = "hollywood_select_work_resource"
CAPABILITY = "canonical-work-resource-routing/v1"


async def read(c, arguments):
    from .resource_routing import bounded
    work = str(UUID(arguments["workId"]))
    value = bounded(await c.http("GET", "work/" + work + "/resource"))
    if (value.get("schema") != CAPABILITY or value.get("workId") != work
            or value.get("authorityId") != participation(c)["request"]["authority"]):
        raise PermissionError("Canonical Work resource scope differs")
    return value


async def select(c, arguments, operation):
    if not c.role_context.value["communicationAdministrator"]:
        raise PermissionError("Communication administrator required")
    work = str(UUID(arguments["workId"]))
    payload = {k: arguments[k] for k in (
        "revision", "workRevision", "state", "workspaceId", "workspaceRevision", "grantRevision")}
    if payload["workspaceId"] is not None:
        payload["workspaceId"] = str(UUID(payload["workspaceId"]))
    payload["operationId"] = operation + ":admin:work-resource"
    return await c.http("PUT", "work/" + work + "/resource", payload)


def definitions(spec):
    string = {"type": "string"}
    nullable = {"type": ["string", "null"]}
    fields = {"workId": string, "revision": {"type": "integer", "minimum": 0},
              "workRevision": {"type": "integer", "minimum": 1},
              "state": {"type": "string", "enum": ["selected", "cleared"]},
              "workspaceId": nullable,
              "workspaceRevision": {"type": ["integer", "null"], "minimum": 1},
              "grantRevision": {"type": ["integer", "null"], "minimum": 1}}
    return [
        spec(READ_TOOL, "Read the original Work's explicit physical resource selection and current effective state. This is distinct from the agent's private context and default; no mutation is admitted.",
             {"workId": string}, ["workId"]),
        spec(SELECT_TOOL, "Administrator: select an already authorized local physical resource for one exact unfinished Work using inspected Work/routing/root/agent-grant revisions. Requires the enrolled native bridge capability. The agent identity, private workspace and default remain unchanged. Cleared or stale routing holds Work-relative intent; it never silently selects another root. Settle original claims/consents/mutations before rerouting away.",
             fields, list(fields)),
    ]
