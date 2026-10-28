"""Preserve the authoritative host enrollment when placing a native peer."""

import hashlib
from pathlib import Path
from uuid import UUID

from .errors import ToolValidationError
from .tool_execution import participation


async def fingerprint(connector):
    host = str(UUID(connector.config["hostId"]))
    authority = participation(connector)["request"]["authority"]
    page = await connector.http("GET", "hosts/" + host + "/admission")
    row = page.get("enrollment")
    if not isinstance(row, dict) or row.get("schema") != "hollywood-host-enrollment/v1":
        raise ToolValidationError(
            "HOST_ENROLLMENT_UNAVAILABLE",
            "Authoritative host enrollment metadata is unavailable; no placement was sent.",
            "Use a compatible Hollywood host-admission endpoint; do not invent or rewrite a host identity.",
        )
    if (row.get("authorityId"), row.get("hostId")) != (authority, host):
        raise PermissionError("Host enrollment belongs to another authority or host")
    # Historical Linux workers hashed the complete file. Purpose-native host
    # attestations hash its stripped contents. Preserve the already accepted
    # opaque enrollment only when it describes this exact local machine.
    raw = Path("/etc/machine-id").read_bytes()
    accepted = {hashlib.sha256(raw).hexdigest(), hashlib.sha256(raw.strip()).hexdigest()}
    value = row.get("identityFingerprint")
    if not isinstance(value, str) or value not in accepted:
        raise ToolValidationError(
            "HOST_ENROLLMENT_MACHINE_MISMATCH",
            "Enrolled host fingerprint does not match this execution host; no placement was sent.",
            "Inspect the enrolled host and controller identity; do not overwrite enrollment or retry on another host.",
        )
    return value
