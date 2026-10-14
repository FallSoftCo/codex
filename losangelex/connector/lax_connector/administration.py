"""Native Hollywood administration tools; credentials never enter model output."""

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
    from .connector import saved

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
    from .connector import saved

    if not connector.role_context.value["communicationAdministrator"]:
        raise PermissionError("Communication administrator required")
    identity = str(uuid5(UUID(connector.config["agentId"]), operation))
    if name == "hollywood_create_agent":
        credential = connector.state / ("agent-credential-" + identity + ".json")
        if not credential.exists():
            saved(
                credential,
                {
                    "agentId": identity,
                    "authorityId": connector.active["request"]["authority"],
                    "token": secrets.token_urlsafe(40),
                },
            )
        protected = json.loads(credential.read_text())
        result = await connector.http(
            "POST",
            "principals",
            {
                "id": identity,
                "name": arguments["name"],
                "kind": "agent",
                "enrollmentCredential": protected["token"],
            },
        )
        role = await connector.http("GET", "agents/" + identity + "/role")
        role = await connector.http(
            "PUT",
            "agents/" + identity + "/role",
            {
                "primary": arguments["primary"],
                "purpose": arguments["purpose"],
                "homeRoomId": role["home_room"],
                "revision": role["revision"],
            },
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
            {
                "id": identity,
                "name": arguments["name"],
                "purpose": arguments["purpose"],
                "ownerId": arguments["ownerId"],
            },
        )
    if name == "hollywood_set_role":
        return await connector.http(
            "PUT",
            "agents/" + arguments["agentId"] + "/role",
            {
                "primary": arguments["primary"],
                "purpose": arguments["purpose"],
                "homeRoomId": arguments["homeRoomId"],
                "revision": arguments["revision"],
            },
        )
    if name == "hollywood_grant_room":
        return await connector.http(
            "PUT",
            "rooms/" + arguments["roomId"] + "/membership",
            {
                key: arguments[key]
                for key in [
                    "principalId",
                    "can_read",
                    "can_post",
                    "can_request",
                    "revision",
                ]
            },
        )
    if name == "lax_provision_worker":
        if not connector.role_context.value["hostAdministrationVerified"]:
            raise PermissionError("Host administration not verified")
        agent = str(UUID(arguments["agentId"]))
        credential = json.loads(
            (connector.state / ("agent-credential-" + agent + ".json")).read_text()
        )
        authority = connector.active["request"]["authority"]
        if credential["authorityId"] != authority:
            raise PermissionError("Credential belongs to another enterprise")
        role = await connector.http("GET", "agents/" + agent + "/role")
        if role["home_room"] is None:
            raise ValueError("An accountable home room is required before provisioning")
        host = connector.config["hostId"]
        await connector.http(
            "POST",
            "placements",
            {
                "hostId": host,
                "name": "Enrolled LAX host",
                "identityFingerprint": hashlib.sha256(
                    Path("/etc/machine-id").read_bytes()
                ).hexdigest(),
                "capabilities": {"localProvisioning": True},
                "agentId": agent,
            },
        )
        spec = {
            "authorityId": authority,
            "agentId": agent,
            "credential": credential["token"],
            "hollywoodUrl": connector.config["hollywoodUrl"],
            "hostId": host,
            "approvedModelAuthFile": str(
                Path(connector.config["codexHome"]) / "auth.json"
            ),
            "binary": connector.config["binary"],
            "interpreter": sys.executable,
            "model": connector.config["model"],
            "effort": connector.config["effort"],
        }
        path = connector.state / ("worker-provision-" + agent + ".json")
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
        if process.returncode:
            raise RuntimeError(
                "Worker provisioning outcome requires inspection; private credentials retained"
            )
        return json.loads(stdout)
    raise ValueError("Unknown administrative tool")
