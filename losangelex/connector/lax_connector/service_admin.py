"""Explicit administrator inspection and registration of managed LAX services.

This command starts no service or model and never clears uncertain deliveries.
"""
import argparse
import json
import os
from pathlib import Path
from uuid import UUID

from . import service_observer as observer
from .native_package import PackageError, preflight_as_owner


def inspect(authority, host, agent):
    if os.geteuid() != 0:
        raise PermissionError("Protected service inspection requires administration")
    authority, host, agent = [str(UUID(v)) for v in (authority, host, agent)]
    uid, home, binary = observer.expected_owner(authority, agent)
    unit = observer.installed_unit(authority, agent)
    info = observer.properties(unit)
    result = {
        "schema": "lax-service-readiness/v1",
        "authorityId": authority, "hostId": host, "agentId": agent, "unit": unit,
        "modelOrServiceStarted": False, "deliveryOrEffectStateChanged": False,
    }
    if info["ActiveState"] != "active" or int(info["MainPID"]) < 2:
        return {**result, "ready": False, "reason": "service-stopped",
                "serviceState": info["ActiveState"]}
    guardian = observer.process(int(info["MainPID"]))
    if (not guardian or guardian["uid"] != uid
            or guardian["controlGroup"] != info["ControlGroup"]):
        raise PermissionError("Actual service guardian owner differs")
    image = Path(binary).resolve(strict=True).stat()
    baseline = {
        "schema": "lax-service-enrollment/v1", "authorityId": authority,
        "hostId": host, "agentId": agent, "uid": uid, "home": str(home),
        "unit": info["Id"], "unitDefinitionDigest": observer.unit_definition(info),
        "binary": str(Path(binary).resolve()), "binaryDevice": image.st_dev,
        "binaryInode": image.st_ino, "machineIdentity": observer.machine_identity(),
        "killMode": "control-group",
    }
    root = observer.directory(authority, host, agent)
    path = root / "enrollment.json"
    if not path.exists():
        return {**result, "ready": False, "reason": "registration-required"}
    enrollment = observer.protected(path)
    differences = sorted(k for k, v in baseline.items() if enrollment.get(k) != v)
    expected = {
        **baseline, "schema": "lax-service-incarnation/v1",
        "bootId": observer.boot_id(),
        "serviceInvocation": UUID(info["InvocationID"]).hex,
        "controlGroup": info["ControlGroup"], "guardianPid": guardian["pid"],
        "guardianStart": guardian["start"],
    }
    if differences:
        return {**result, "ready": False, "reason": "explicit-drained-upgrade-required",
                "changedFields": differences,
                "expectedEnrollment": observer.digest(enrollment),
                "expectedDefinition": baseline["unitDefinitionDigest"]}
    manifest_path = root / (expected["serviceInvocation"] + ".json")
    if not manifest_path.exists():
        return {**result, "ready": False, "reason": "invocation-registration-required"}
    binding = observer.protected(manifest_path)
    if binding != expected:
        raise PermissionError("Registered invocation differs from actual service")
    from .native_image_upgrade import registry_lock, require_settled_transition
    try:
        with registry_lock(root) as fd:
            require_settled_transition(fd)
    except (ValueError, BlockingIOError):
        return {**result, "ready": False, "reason": "native-image-transition-held"}
    base = Path("/var/lib/harness") / authority
    global_receipt = observer.protected(base / "global-admin-receipt.json")
    intent = (base / "global-admin-intent.json" if global_receipt["agentId"] == agent
              else base / "workers" / agent / "provision-intent.json")
    spec = observer.protected(intent)["spec"]
    try:
        package = preflight_as_owner(binary, spec["interpreter"], uid, home)
    except PackageError as error:
        return {**result, "ready": False, "reason": "native-package-preflight-failed",
                "nativePackage": error.details}
    result["nativePackage"] = package
    return {**result, "ready": True, "reason": "execution-registration-ready",
            "serviceInvocation": expected["serviceInvocation"],
            "bindingDigest": observer.digest(binding)}


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authority", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--agent", required=True)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--inspect", action="store_true")
    actions.add_argument("--register", action="store_true")
    actions.add_argument("--approve-drained-upgrade", action="store_true")
    actions.add_argument("--approve-image-upgrade", action="store_true",
                         help="Approve a disabled, stopped, drained exact image; grants no readiness")
    parser.add_argument("--expected-image-sha256")
    parser.add_argument("--expected-enrollment")
    parser.add_argument("--expected-definition")
    args = parser.parse_args()
    if (args.approve_drained_upgrade or args.approve_image_upgrade) != bool(args.expected_enrollment and args.expected_definition):
        parser.error("A drained upgrade requires both previously inspected digests")
    if (args.expected_enrollment or args.expected_definition) and not (args.approve_drained_upgrade or args.approve_image_upgrade):
        parser.error("Upgrade digests are only valid for an explicit drained upgrade")
    if bool(args.expected_image_sha256) != args.approve_image_upgrade:
        parser.error("Only an explicit image upgrade requires --expected-image-sha256")
    if args.approve_image_upgrade:
        from .native_image_upgrade import approve_image_upgrade
        result = approve_image_upgrade(args.authority, args.host, args.agent,
                                       args.expected_enrollment, args.expected_definition,
                                       args.expected_image_sha256)
        print(json.dumps({"imageUpgrade": result}))
        return
    result = {}
    if args.approve_drained_upgrade:
        result["upgrade"] = observer.approve_drained_upgrade(
            args.authority, args.host, args.agent,
            args.expected_enrollment, args.expected_definition)
    if args.register or args.approve_drained_upgrade:
        result["registration"] = observer.register(
            args.authority, args.host, args.agent,
            observer.installed_unit(args.authority, args.agent))
    result["inspection"] = inspect(args.authority, args.host, args.agent)
    print(json.dumps(result))
    if not result["inspection"]["ready"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
