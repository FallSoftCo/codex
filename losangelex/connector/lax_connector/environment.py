"""Approved non-secret installation routes, independent of model instructions."""

import json
import os
import stat
from pathlib import Path
from uuid import UUID

SCHEMA = "lax-installation-environment/v1"
KEYS = {
    "schema",
    "authorityId",
    "repositories",
    "sshAliases",
    "sshRoutes",
    "github",
    "build",
    "verificationReceipt",
}


def validate(value, authority):
    if (
        not isinstance(value, dict)
        or set(value) - KEYS
        or value.get("schema") != SCHEMA
        or value.get("authorityId") != str(UUID(authority))
    ):
        raise ValueError("Installation environment identity/fields differ")
    for key, fields in {
        "github": {"login", "providerFile"},
        "build": {"owner", "entrypoint", "cargoHome", "rustupHome", "path"},
    }.items():
        if key in value and (
            not isinstance(value[key], dict)
            or set(value[key]) - fields
            or any(not isinstance(v, str) for v in value[key].values())
        ):
            raise ValueError("Environment contains unsupported route data")
    if "repositories" in value:
        if (
            not isinstance(value["repositories"], list)
            or len(value["repositories"]) > 128
        ):
            raise ValueError("Invalid repository routes")
        for row in value["repositories"]:
            if (
                not isinstance(row, dict)
                or set(row)
                - {
                    "name",
                    "path",
                    "hostId",
                    "sourceOwnerId",
                    "publicationRemote",
                    "access",
                }
                or any(not isinstance(v, str) for v in row.values())
            ):
                raise ValueError("Unsupported repository route")
    if "sshAliases" in value and (
        not isinstance(value["sshAliases"], list)
        or any(not isinstance(v, str) for v in value["sshAliases"])
    ):
        raise ValueError("Invalid SSH aliases")
    if "sshRoutes" in value:
        if not isinstance(value["sshRoutes"], list) or len(value["sshRoutes"]) > 32:
            raise ValueError("Invalid SSH route list")
        for route in value["sshRoutes"]:
            if (
                not isinstance(route, dict)
                or set(route) != {"name", "command"}
                or not isinstance(route["name"], str)
                or not isinstance(route["command"], list)
                or not route["command"]
                or len(route["command"]) > 32
                or any(not isinstance(v, str) for v in route["command"])
            ):
                raise ValueError("Invalid explicit SSH route")
    return value


def snapshot(authority):
    path = Path("/etc/harness") / str(UUID(authority)) / "environment.json"
    if not path.exists():
        return {
            "state": "not-configured",
            "profileFile": str(path),
            "meaning": "Host execution remains available; approved repository/account/control routes have not been declared.",
        }
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError("Installation environment is not administrator-owned")
    return {
        "state": "configured",
        "profileFile": str(path),
        "facts": validate(json.loads(path.read_text()), authority),
        "meaning": "Approved non-secret routes; verify current capabilities before effects. No account or model startup is implied.",
    }


def install(authority, source):
    if os.geteuid() != 0:
        raise PermissionError("Installation administrator required")
    value = validate(json.loads(Path(source).read_text()), authority)
    root = Path("/etc/harness")
    root.mkdir(mode=0o755, exist_ok=True)
    root_info = root.lstat()
    if not stat.S_ISDIR(root_info.st_mode) or root_info.st_uid != 0 or root_info.st_mode & 0o022:
        raise PermissionError("Installation metadata root is not protected")
    root.chmod(stat.S_IMODE(root_info.st_mode) | 0o111)
    path = root / str(UUID(authority)) / "environment.json"
    path.parent.mkdir(mode=0o755, exist_ok=True)
    info = path.parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise PermissionError("Installation environment directory is not protected")
    # This directory contains declared non-secret installation metadata. An
    # installer's private umask must not hide it from the installed agent.
    path.parent.chmod(0o755)
    if path.exists() and json.loads(path.read_text()) != value:
        raise ValueError(
            "Existing environment differs; explicit installation reconciliation required"
        )
    from .journal import saved

    saved(path, value)
    path.chmod(0o644)
    return str(path)
