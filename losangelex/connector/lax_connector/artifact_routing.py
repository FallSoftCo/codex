"""Hash reports through current canonical roots without changing execution context."""

import errno
import os
from uuid import UUID

from .collaboration_bridge import Held, canonical_relative, digest, require
from .collaboration_resources import open_root
from .errors import ToolValidationError
from .resource_routing import connector_capabilities, read
from .tool_execution import participation


def validated(c, resource, selection=None):
    authority = participation(c)["request"]["authority"]
    agent, host = c.config["agentId"], c.config["hostId"]
    workspace, grant = resource["workspace"], resource["grant"]
    identity = str(UUID(workspace["id"]))
    require(
        workspace.get("authority", authority) == authority
        and grant.get("authority", authority) == authority
        and workspace["host"] == host
        and grant["execution_host"] == host
        and grant["workspace"] == identity
        and grant["principal"] == agent
        and workspace["state"] == "active"
        and grant["state"] == "active"
        and grant["can_read"] is True
        and all(type(v) is int and v > 0 for v in (workspace["revision"], grant["revision"])),
        "Artifact root/grant scope, revision or readable access differs",
    )
    environment = digest({"hostId": host, "environmentId": "local"})
    require(workspace["environment_sha256"] == environment,
            "Artifact root is not in the current local host environment")
    proof = {
        "schema": "hollywood-artifact-root/v1",
        "workspaceId": identity,
        "workspaceRevision": workspace["revision"],
        "grantRevision": grant["revision"],
        "environmentSha256": environment,
        "rootIdentitySha256": workspace["root_identity_sha256"],
    }
    if selection is not None:
        pointer = selection["selection"]
        require(
            pointer["authority"] == authority
            and pointer["principal"] == agent
            and pointer["execution_host"] == host
            and pointer["state"] == "selected"
            and pointer["revision"] == selection["selectionRevision"]
            and all(type(v) is int and v > 0 for v in (
                pointer["revision"], pointer["workspace_revision"], pointer["grant_revision"]))
            and pointer["workspace"] == identity
            and (pointer["workspace_revision"], pointer["grant_revision"])
            == (workspace["revision"], grant["revision"]),
            "Selected artifact default pins differ",
        )
    return {"proof": proof, "root": workspace["root_path"],
            "selectionRevision": selection["selectionRevision"] if selection else None}


async def resolve(c, explicit):
    args = {"agentId": c.config["agentId"], "executionHost": c.config["hostId"]}
    if explicit is None:
        view = await read(c, "hollywood_resource_default", args)
        require(view["effectiveState"] == "selected" and view["resource"] is not None,
                "Artifact paths require a current selected resource default or explicit artifactWorkspaceId")
        return validated(c, view["resource"], view)
    matches, seen = [], set()
    for _ in range(4):
        page = await read(c, "hollywood_agent_resources", {**args, "limit": 8})
        matches.extend(row for row in page["resources"] if row["workspace"]["id"] == explicit)
        after = page.get("nextCursor")
        if after is None:
            require(len(matches) == 1, "Explicit artifact root is not a unique own authorized resource")
            return validated(c, matches[0])
        require(after not in seen, "Artifact resource cursor repeated")
        seen.add(after)
        args["after"] = after
    require(False, "Artifact resource page budget exhausted")


def physical(c, pinned, fd):
    info = os.fstat(fd)
    require(digest({
        "hostId": c.config["hostId"],
        "environmentSha256": pinned["proof"]["environmentSha256"],
        "device": info.st_dev, "inode": info.st_ino,
    }) == pinned["proof"]["rootIdentitySha256"], "Artifact physical root identity differs")
    return info.st_dev, info.st_ino


async def collect(c, args, reader):
    """Retain execution identity; attach a separate physical-root proof per file.

    The final canonical read reauthorizes the same root/grant after hashing. The
    server must still fence races transactionally when accepting the report.
    Empty evidence makes no filesystem claim and needs no selected resource.
    """
    try:
        return await _collect(c, args, reader)
    except Held as error:
        raise PermissionError(str(error)) from error
    except (KeyError, TypeError) as error:
        raise ValueError("Canonical artifact root metadata or arguments are incomplete") from error
    except AttributeError as error:
        raise ToolValidationError("ARTIFACT_PREPARATION_FAILED",
            "Report artifact preparation failed before submission.",
            "Inspect the installed native artifact reader. No report POST was dispatched by artifact preparation.") from error


async def _collect(c, args, reader):
    paths = args["artifactPaths"]
    require(isinstance(paths, list) and len(paths) <= 16, "At most 16 artifact paths required")
    for value in paths:
        canonical_relative(value)
    explicit = args.get("artifactWorkspaceId")
    if "artifactWorkspaceId" in args:
        require(isinstance(explicit, str), "Explicit artifactWorkspaceId must be a UUID string")
        explicit = str(UUID(explicit))
    if not paths:
        return []
    policy = await connector_capabilities(c)
    require(policy.get("artifactResourceEvidence") is True
            and policy.get("artifactRootPolicy") == "hollywood-artifact-root/v1",
            "Server artifact resource evidence capability unavailable; no report submitted")
    pinned = await resolve(c, explicit)
    try:
        fd = open_root(pinned["root"])
        try:
            identity = physical(c, pinned, fd)
            evidence = reader(c.config, paths, root_fd=fd)
            current = await resolve(c, explicit)
            require(current == pinned, "Artifact root/default or grant changed while hashing")
            current_fd = open_root(current["root"])
            try:
                require(physical(c, current, current_fd) == identity,
                        "Artifact root incarnation changed while hashing")
            finally:
                os.close(current_fd)
            return [{**item, "artifactRoot": dict(pinned["proof"])} for item in evidence]
        finally:
            os.close(fd)
    except OSError as error:
        raise ToolValidationError(
            "ARTIFACT_READ_UNAVAILABLE",
            "Artifact cannot be read by this agent (" + errno.errorcode.get(error.errno, "OS_ERROR") + ")",
            "Inspect the registered root's directory-search and file-read permissions for this Unix account. "
            "Retain the original Work/delivery and existing files; do not copy or reimplement them.",
        ) from error
