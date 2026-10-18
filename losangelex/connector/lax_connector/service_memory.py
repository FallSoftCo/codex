"""Reviewed service cgroup ceilings, separate from canonical admission estimates."""

import hashlib
import json
import os
import re
from pathlib import Path
from uuid import UUID

DEFAULT_BYTES = 8 * 1024**3
LEGACY_WORKER_BYTES = 2 * 1024**3
LEGACY_GLOBAL_BYTES = 4 * 1024**3


def validate(value):
    if type(value) is not int or not 256 * 1024**2 <= value <= 1024**4:
        raise ValueError("Service memory ceiling must be an integer256MiB..1TiB")
    return value


def provisioning_spec(spec, intent):
    """Pin a fresh default, while retaining the exact original legacy spec."""
    value = dict(spec)
    original = (
        json.loads(Path(intent).read_text())["spec"] if Path(intent).exists() else None
    )
    if "serviceMemoryMaxBytes" not in value:
        if original is None:
            value["serviceMemoryMaxBytes"] = DEFAULT_BYTES
            value["automaticRestartRegistration"] = True
        elif "serviceMemoryMaxBytes" in original:
            value["serviceMemoryMaxBytes"] = original["serviceMemoryMaxBytes"]
            if "automaticRestartRegistration" in original:
                value["automaticRestartRegistration"] = original[
                    "automaticRestartRegistration"
                ]
    if original is None:
        value.setdefault("automaticRestartRegistration", True)
    elif (
        "automaticRestartRegistration" not in value
        and "automaticRestartRegistration" in original
    ):
        value["automaticRestartRegistration"] = original["automaticRestartRegistration"]
    if "serviceMemoryMaxBytes" in value:
        validate(value["serviceMemoryMaxBytes"])
    if "workerServiceMemoryMaxBytes" in value:
        validate(value["workerServiceMemoryMaxBytes"])
    if (
        "automaticRestartRegistration" in value
        and type(value["automaticRestartRegistration"]) is not bool
    ):
        raise ValueError("Explicit restart registration policy must be boolean")
    return value


def unit_limit(spec, legacy):
    return (
        str(validate(spec["serviceMemoryMaxBytes"]))
        if "serviceMemoryMaxBytes" in spec
        else legacy
    )


def approved_spec(authority, agent):
    from .service_observer import protected

    authority, agent = str(UUID(authority)), str(UUID(agent))
    base = Path("/var/lib/harness") / authority
    try:
        global_receipt = protected(base / "global-admin-receipt.json")
    except FileNotFoundError:
        # A host can execute enrolled workers without hosting enterprise Global.
        # Malformed or unprotected existing receipts still fail closed.
        global_receipt = None
    global_agent = global_receipt is not None and global_receipt["agentId"] == agent
    record = base if global_agent else base / "workers" / str(UUID(agent))
    intent = record / (
        "global-admin-intent.json" if global_agent else "provision-intent.json"
    )
    receipt = (
        global_receipt if global_agent else protected(record / "provision-receipt.json")
    )
    return protected(intent)["spec"], receipt, global_agent


def inspection(authority, agent, info):
    spec, _, is_global = approved_spec(authority, agent)
    definition = Path(info["FragmentPath"]).read_text()
    directives = re.findall(r"(?m)^MemoryMax=([^\n]*)$", definition)
    return {
        "approvedProvisioningMemoryMaxBytes": spec.get(
            "serviceMemoryMaxBytes",
            LEGACY_GLOBAL_BYTES if is_global else LEGACY_WORKER_BYTES,
        ),
        "definitionMemoryMax": directives[0] if len(directives) == 1 else None,
        "runtimeMemoryMax": info.get("MemoryMax"),
        "currentBytes": info.get("MemoryCurrent"),
        "peakBytes": info.get("MemoryPeak"),
        "freshInstallDefaultBytes": DEFAULT_BYTES,
        "historicalApprovedSpecPreserved": True,
        "scope": "Hard service cgroup ceiling including descendants; not a canonical admission estimate or reservation",
        "runtimeOverrideMayDiffer": True,
        "memoryLeakFixed": False,
    }


def prepare(
    authority, host, agent, limit, expected_enrollment, expected_definition, output
):
    from . import service_observer as observer
    from .collaboration_install import protected_tree, write_original
    from .native_image_upgrade import registry_lock, require_settled_transition

    if os.geteuid() != 0:
        raise PermissionError("Verified installation administrator required")
    authority, host, agent = [str(UUID(v)) for v in (authority, host, agent)]
    limit = validate(limit)
    root = observer.directory(authority, host, agent)
    with registry_lock(root) as fd:
        require_settled_transition(fd)
        enrollment = observer.protected(root / "enrollment.json")
        if observer.digest(enrollment) != expected_enrollment:
            raise ValueError("Original enrollment CAS changed")
        info = observer.properties(observer.installed_unit(authority, agent))
        if observer.unit_definition(info) != expected_definition:
            raise ValueError("Original unit definition CAS changed")
        unit = Path(info["FragmentPath"])
        before = unit.read_bytes()
        text = before.decode()
        after, count = re.subn(
            r"(?m)^MemoryMax=[^\n]*$", "MemoryMax=" + str(limit), text
        )
        if count != 1:
            raise ValueError("Exactly one reviewed MemoryMax directive required")
        spec, receipt, _ = approved_spec(authority, agent)
        manifest = {
            "schema": "lax-reviewed-service-memory/v1",
            "authorityId": authority,
            "hostId": host,
            "agentId": agent,
            "unitPath": str(unit),
            "expectedEnrollment": expected_enrollment,
            "expectedDefinition": expected_definition,
            "newDefinition": hashlib.sha256(after.encode()).hexdigest(),
            "serviceMemoryMaxBytes": limit,
            "originalSpecDigest": observer.digest(spec),
            "originalReceiptDigest": observer.digest(receipt),
            "historicalApprovedSpecPreserved": True,
            "liveUnitChanged": False,
            "modelsStarted": 0,
            "servicesStarted": 0,
            "activation": "Root disables admission and drains, reviews/publishes exact unit, reloads, then uses existing explicit definition upgrade and restart-policy approval. No automatic live resource change.",
        }
        target = protected_tree(output, 0o700)
        write_original(target / "service.before", before)
        write_original(target / "service.prepared", after.encode())
        write_original(target / "memory-plan.json", manifest)
        return {**manifest, "manifest": str(target / "memory-plan.json")}
