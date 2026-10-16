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
    path = Path("/etc/harness") / str(UUID(authority)) / "environment.json"
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    if path.exists() and json.loads(path.read_text()) != value:
        raise ValueError(
            "Existing environment differs; explicit installation reconciliation required"
        )
    from .journal import saved

    saved(path, value)
    path.chmod(0o644)
    return str(path)
