"""Global's native provisioning tool installs full LAX peers, never TUI children."""

import asyncio
import hashlib
import json
import secrets
import sys
from pathlib import Path
from uuid import uuid4
from .journal import saved
from .service_memory import validate, DEFAULT_BYTES


async def provision(c, arguments, operation, spec):
    from .host import machine_identity

    spec = {
        **spec,
        "machineIdentity": machine_identity(),
        "pythonRoot": c.config["pythonRoot"],
        "serviceMemoryMaxBytes": validate(
            arguments.get(
                "serviceMemoryMaxBytes",
                c.config.get("workerServiceMemoryMaxBytes", DEFAULT_BYTES),
            )
        ),
    }
    # New peers inherit the explicit installation context policy coherently.
    # Omitted settings remain omitted; old intents are never rewritten.
    from .purpose_install import context_settings

    spec.update(context_settings(c.config))
    if c.config.get("nativeCollaborationChannel"):
        spec["nativeCollaborationChannel"] = c.config["nativeCollaborationChannel"]
    path = c.state / ("purpose-provision-" + spec["agentId"] + ".json")
    old = json.loads(path.read_text()) if path.exists() else None
    if arguments.get("toolProfileFile"):
        spec["toolProfileFile"] = arguments["toolProfileFile"]
    elif old is not None:
        # An observed original intent keeps its original declared toolkit,
        # including an intentional legacy omission. Never retrofit a replay.
        if old.get("toolProfileFile"):
            spec["toolProfileFile"] = old["toolProfileFile"]
    elif c.config.get("toolProfileFile"):
        # Copy the approved declaration through the installer, not the parent's
        # credentials, context, workspace, role or agent configuration.
        from .tool_profile import read as read_tool_profile
        if not c.config.get("toolProfileSha256"):
            raise ValueError("Current approved tool declaration digest is missing")
        read_tool_profile(c.config["toolProfileFile"], c.config["toolProfileSha256"])
        spec["toolProfileFile"] = c.config["toolProfileFile"]
    if old is not None:
        expected = {
            k: v
            for k, v in old.items()
            if k not in ("tokens", "contextIds", "workspaceId")
        }
        if expected != spec:
            raise ValueError(
                "Original purpose provisioning differs; inspect explicit upgrade"
            )
        spec = old
    else:
        spec.update(
            workspaceId=str(uuid4()),
            tokens={
                p: secrets.token_urlsafe(40) for p in ("reader", "writer", "responder")
            },
            contextIds={p: str(uuid4()) for p in ("reader", "writer", "responder")},
        )
        saved(path, spec)
    bindings = [
        {
            "purpose": p,
            "contextId": spec["contextIds"][p],
            "credentialDigest": hashlib.sha256(
                json.dumps(t, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        }
        for p, t in spec["tokens"].items()
    ]
    await c.http(
        "PUT",
        "agents/" + spec["agentId"] + "/context-system",
        {
            "operationId": operation + ":admin:purpose-context",
            "hostId": spec["hostId"],
            "workspaceId": spec["workspaceId"],
            "bindings": bindings,
        },
    )
    command = [
        "sudo",
        "-n",
        sys.executable,
        "-m",
        "lax_connector.purpose_install",
        "--spec",
        str(path),
        "--activate",
    ]
    proc = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    saved(
        c.state / ("purpose-provision-process-" + spec["agentId"] + ".json"),
        {
            "returnCode": proc.returncode,
            "stdout": stdout.decode(errors="replace")[:20000],
            "stderr": stderr.decode(errors="replace")[:20000],
            "replayed": False,
        },
    )
    if proc.returncode:
        # No process restart/setup replay here. Keep original intent and inspect its receipt.
        raise RuntimeError(
            "Purpose installation requires inspection; original intent retained"
        )
    result = json.loads(stdout)
    if (result["authorityId"], result["agentId"]) != (
        spec["authorityId"],
        spec["agentId"],
    ):
        raise RuntimeError("Installed peer receipt belongs to another identity")
    return result
