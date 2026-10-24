"""Verify authorized local resource roots as the installed Unix service identity.

This is a read-only installation check. Individual target access, native mount
views and edit admission are still checked by the native operation itself.
"""

import argparse
import json
import os
import subprocess

from .collaboration_bridge import digest, require
from .collaboration_resources import open_root
from .resource_routing import agent_rows


def observe(uid, resources):
    """Observe bounded roots without changing files, permissions or ownership."""
    require(os.geteuid() == uid and uid != 0, "Actual installed service UID required")
    require(
        isinstance(resources, list) and 1 <= len(resources) <= 32,
        "Bounded installed local resources required",
    )
    result = []
    for resource in resources:
        path = resource["root"]
        try:
            fd = open_root(path)
            try:
                info = os.fstat(fd)
                require(
                    (info.st_dev, info.st_ino)
                    == (resource["device"], resource["inode"]),
                    "Resource root incarnation changed",
                )
                mask = os.R_OK | os.X_OK
                if resource["canWrite"]:
                    mask |= os.W_OK
                require(
                    os.access(path, mask, effective_ids=True),
                    "Root access does not satisfy the canonical grant",
                )
                # Check the path still names the opened incarnation. Per-target
                # checks remain mandatory after this installation observation.
                after = os.stat(path, follow_symlinks=False)
                require(
                    (after.st_dev, after.st_ino) == (info.st_dev, info.st_ino),
                    "Resource root changed during observation",
                )
            finally:
                os.close(fd)
        except (OSError, RuntimeError) as error:
            raise PermissionError(
                f"Installed UID {uid} cannot use authorized resource {path}: {error}"
            ) from error
        result.append(resource)
    return result


def verify(value, config, http, policy):
    """Check every active readable grant, including non-private shared roots."""
    rows = agent_rows(
        http, policy, value["authorityId"], value["agentId"], value["hostId"]
    )
    resources, seen = [], set()
    environment = digest({"hostId": value["hostId"], "environmentId": "local"})
    for row in rows:
        workspace, grant = row["workspace"], row["grant"]
        identity = str(workspace["id"])
        require(identity not in seen, "Duplicate installed resource identity")
        seen.add(identity)
        require(
            str(workspace["authority"]) == value["authorityId"]
            and str(workspace["host"]) == value["hostId"]
            and str(grant["workspace"]) == identity
            and str(grant["principal"]) == value["agentId"]
            and str(grant["execution_host"]) == value["hostId"],
            "Installed resource canonical scope differs",
        )
        if (
            workspace["state"] != "active"
            or grant["state"] != "active"
            or grant["can_read"] is not True
        ):
            continue
        path = workspace["root_path"]
        try:
            fd = open_root(path)
            try:
                info = os.fstat(fd)
            finally:
                os.close(fd)
        except OSError as error:
            raise PermissionError(
                f"Cannot observe authorized local resource {path}: {error}"
            ) from error
        root_identity = digest(
            {
                "hostId": value["hostId"],
                "environmentSha256": environment,
                "device": info.st_dev,
                "inode": info.st_ino,
            }
        )
        require(
            workspace["environment_sha256"] == environment
            and workspace["root_identity_sha256"] == root_identity,
            "Installed resource physical/environment identity differs",
        )
        require(
            type(grant["can_write"]) is bool
            and type(workspace["revision"]) is int
            and workspace["revision"] >= 1
            and type(grant["revision"]) is int
            and grant["revision"] >= 1,
            "Installed resource access/revisions differ",
        )
        resources.append(
            {
                "workspaceId": identity,
                "workspaceRevision": workspace["revision"],
                "grantRevision": grant["revision"],
                "root": path,
                "device": info.st_dev,
                "inode": info.st_ino,
                "rootIdentitySha256": root_identity,
                "canRead": True,
                "canWrite": grant["can_write"],
            }
        )
    private = [r for r in resources if r["root"] == config["workspace"]]
    require(
        len(private) == 1 and private[0]["canWrite"] is True,
        "Installed private workspace is not in canonical read/write access",
    )
    require(
        type(value["uid"]) is int and value["uid"] != 0,
        "Installed non-root Unix identity required",
    )
    probe = subprocess.run(
        [
            "runuser",
            "-u",
            value["linuxUser"],
            "--",
            value["interpreter"],
            "-I",
            "-B",
            "-m",
            "lax_connector.purpose_resource_readiness",
            "--uid",
            str(value["uid"]),
        ],
        input=json.dumps(resources),
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if probe.returncode:
        raise PermissionError(
            "Installed resource access preflight failed: " + probe.stderr[-4096:]
        )
    require(
        len(probe.stdout.encode()) <= 131072 and json.loads(probe.stdout) == resources,
        "Installed UID resource observations differ",
    )
    return {
        "schema": "lax-installed-resource-access/v1",
        "uid": value["uid"],
        "resources": resources,
        "meaning": "Current canonical roots and actual Unix UID root access only; "
        "not recursive file, native mount-view or effect authority.",
    }, private[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uid", type=int, required=True)
    args = parser.parse_args()
    import sys

    raw = sys.stdin.buffer.read(131073)
    require(len(raw) <= 131072, "Installed resource observation input exceeds bound")
    print(json.dumps(observe(args.uid, json.loads(raw))))


if __name__ == "__main__":
    main()
