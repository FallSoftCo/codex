"""Native Hollywood administration tools; credentials never enter model output."""

from .tool_execution import participation

import asyncio
import hashlib
import json
import secrets
import sys
from pathlib import Path
from uuid import UUID, uuid5


class AdminEffectUnknown(RuntimeError):
    pass


async def administer(connector, name, arguments, operation):
    from .journal import saved

    if not connector.role_context.value["communicationAdministrator"]:
        raise PermissionError("Communication administrator required")
    if name == "hollywood_create_agent" and arguments["primary"] == "global":
        raise ValueError("Creating an agent role cannot grant Global authority")
    path = connector.state / (
        "administration-" + hashlib.sha256(operation.encode()).hexdigest() + ".json"
    )
    saved(
        path,
        {
            "state": "intent",
            "operationId": operation,
            "tool": name,
            "arguments": arguments,
        },
    )
    try:
        result = await _administer(connector, name, arguments, operation)
        saved(
            path,
            {
                "state": "completed",
                "operationId": operation,
                "tool": name,
                "result": result,
            },
        )
        return result
    except Exception as error:
        from .errors import HttpFailure

        # These workflows route all remote mutations through Effects. Worker
        # provisioning records its placement before starting the host process,
        # so a later host failure cannot satisfy safe_rejection().
        tracked = name in (
            "hollywood_create_agent", "hollywood_create_room", "hollywood_set_role",
            "hollywood_grant_room", "hollywood_grant_resource",
            "hollywood_select_resource_default", "hollywood_placement_set",
            "lax_provision_worker",
        )
        known_rejection = (
            tracked and connector.effects.safe_rejection()
            and (
                isinstance(error, (ValueError, PermissionError))
                or isinstance(error, HttpFailure) and error.status in (400, 403, 409)
            )
        )
        if known_rejection or (
            name == "hollywood_mutation_reconcile"
            and isinstance(error, HttpFailure) and error.status in (400, 403, 409)
        ):
            saved(
                path,
                {
                    "state": "rejected",
                    "operationId": operation,
                    "tool": name,
                    "arguments": arguments,
                    "status": error.status if isinstance(error, HttpFailure) else None,
                    "error": type(error).__name__,
                    "effect": "none; no mutation accepted",
                },
            )
            raise
        # A workflow may have completed one step before another rejects or loses
        # its reply. Never label the entire workflow rejected or blindly repeat it.
        saved(
            path,
            {
                "state": "unconfirmed",
                "operationId": operation,
                "tool": name,
                "arguments": arguments,
                "error": type(error).__name__,
            },
        )
        raise AdminEffectUnknown(
            "Administrative workflow requires inspection of original identities"
        ) from error


async def _administer(connector, name, arguments, operation):
    from .journal import saved

    if not connector.role_context.value["communicationAdministrator"]:
        raise PermissionError("Communication administrator required")
    if name in ("hollywood_mutation_observe", "hollywood_mutation_reconcile"):
        from .mutation_tools import administer
        return await administer(connector, name, arguments, operation)
    identity = str(uuid5(UUID(connector.config["agentId"]), operation))
    if name == "hollywood_create_agent":
        credential = connector.state / ("agent-credential-" + identity + ".json")
        if not credential.exists():
            saved(
                credential,
                {
                    "agentId": identity,
                    "authorityId": participation(connector)["request"]["authority"],
                    "token": secrets.token_urlsafe(40),
                },
            )
        protected = json.loads(credential.read_text())
        result = await connector.http(
            "POST",
            "principals",
            {"operationId": operation + ":admin:principal", **({
                "id": identity,
                "name": arguments["name"],
                "kind": "agent",
                "enrollmentCredential": protected["token"],
            })},
        )
        role = await connector.http("GET", "agents/" + identity + "/role")
        role = await connector.http(
            "PUT",
            "agents/" + identity + "/role",
            {"operationId": operation + ":admin:role", **({
                "primary": arguments["primary"],
                "purpose": arguments["purpose"],
                "homeRoomId": role["home_room"],
                "revision": role["revision"],
            })},
        )
        return {
            **result,
            "role": role,
            "credentialRef": identity,
            "executionProvisioned": False,
            "note": "Protected credential retained by LAX; metadata does not start execution.",
        }
    if name == "hollywood_create_room":
        return await connector.http(
            "POST",
            "rooms",
            {"operationId": operation + ":admin:room", **({
                "id": identity,
                "name": arguments["name"],
                "purpose": arguments["purpose"],
                "ownerId": arguments["ownerId"],
            })},
        )
    if name == "hollywood_set_role":
        return await connector.http(
            "PUT",
            "agents/" + arguments["agentId"] + "/role",
            {"operationId": operation + ":admin:role", **({
                "primary": arguments["primary"],
                "purpose": arguments["purpose"],
                "homeRoomId": arguments["homeRoomId"],
                **(
                    {"nativeGoalScope": arguments["nativeGoalScope"]}
                    if "nativeGoalScope" in arguments
                    else {}
                ),
                "revision": arguments["revision"],
            })},
        )
    if name == "hollywood_grant_room":
        return await connector.http(
            "PUT",
            "rooms/" + arguments["roomId"] + "/membership",
            {"operationId": operation + ":admin:membership", **({
                key: arguments[key]
                for key in [
                    "principalId",
                    "can_read",
                    "can_post",
                    "can_request",
                    "revision",
                ]
            })},
        )
    if name == "hollywood_placement_set":
        from .placement_control import set_state
        return await set_state(connector, arguments, operation)
    if name == "hollywood_select_resource_default":
        from .resource_routing import select
        return await select(connector, arguments, operation)
    if name == "hollywood_grant_resource":
        workspace, agent, host = [str(UUID(arguments[key])) for key in ("workspaceId", "agentId", "executionHost")]
        return await connector.http(
            "PUT", "physical-workspaces/" + workspace + "/agent-grants/" + agent,
            {"operationId": operation + ":admin:resource-grant", "executionHost": host,
             **{key: arguments[key] for key in ("revision", "workspaceRevision", "state", "canRead", "canWrite")}},
        )
    if name == "lax_provision_worker":
        if not connector.role_context.value["hostAdministrationVerified"]:
            raise PermissionError("Host administration not verified")
        agent = str(UUID(arguments["agentId"]))
        credential = json.loads(
            (connector.state / ("agent-credential-" + agent + ".json")).read_text()
        )
        authority = participation(connector)["request"]["authority"]
        if credential["authorityId"] != authority:
            raise PermissionError("Credential belongs to another enterprise")
        # An agent may be provisioned before joining any room. Membership is
        # checked by Hollywood when work is addressed; it is not runtime identity.
        await connector.http("GET", "agents/" + agent + "/role")
        host = connector.config["hostId"]
        await connector.http(
            "POST",
            "placements",
            {"operationId": operation + ":admin:placement", **({
                "hostId": host,
                "name": "Enrolled LAX host",
                "identityFingerprint": hashlib.sha256(
                    Path("/etc/machine-id").read_bytes()
                ).hexdigest(),
                "capabilities": {"localProvisioning": True},
                "agentId": agent,
            })},
        )
        spec = {
            "authorityId": authority,
            "agentId": agent,
            "credential": credential["token"],
            "hollywoodUrl": connector.config["hollywoodUrl"],
            "hostId": host,
            "machineIdentity": hashlib.sha256(Path("/etc/machine-id").read_bytes()).hexdigest(),
            "approvedModelAuthFile": str(
                Path(connector.config["codexHome"]) / "auth.json"
            ),
            "binary": connector.config["binary"],
            "interpreter": sys.executable,
            "model": connector.config["model"],
            "effort": connector.config["effort"],
        }
        from .service_memory import validate, DEFAULT_BYTES
        spec["serviceMemoryMaxBytes"] = validate(arguments.get("serviceMemoryMaxBytes", connector.config.get("workerServiceMemoryMaxBytes", DEFAULT_BYTES)))
        if connector.config.get("nativeCollaborationChannel"):
            spec["nativeCollaborationChannel"] = connector.config["nativeCollaborationChannel"]
        path = connector.state / ("worker-provision-" + agent + ".json")
        if path.exists() and "serviceMemoryMaxBytes" not in arguments:
            original = json.loads(path.read_text())
            if "serviceMemoryMaxBytes" in original:
                spec["serviceMemoryMaxBytes"] = original["serviceMemoryMaxBytes"]
            else:
                spec.pop("serviceMemoryMaxBytes", None)
        if path.exists() and json.loads(path.read_text()) != spec:
            raise ValueError(
                "Original worker provisioning differs; reconcile explicit upgrade"
            )
        saved(path, spec)
        command = [
            "sudo",
            "-n",
            sys.executable,
            "-m",
            "lax_connector.linux_worker",
            "--spec",
            str(path),
        ]
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await process.communicate()
        try:
            if process.returncode:
                raise RuntimeError("Worker provisioning returned no accepted result")
            return json.loads(stdout)
        except Exception:
            # Inspect original acceptance without repeating setup or enabling a unit.
            inspect = await asyncio.create_subprocess_exec(
                *command, "--inspect", stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            accepted, _ = await inspect.communicate()
            if inspect.returncode:
                raise RuntimeError(
                    "Worker provisioning remains partial or unknown; no setup was repeated"
                ) from None
            result = json.loads(accepted)
            if result["authorityId"] != authority or result["agentId"] != agent:
                raise RuntimeError("Original provisioning receipt belongs to another identity")
            return result
    raise ValueError("Unknown administrative tool")
