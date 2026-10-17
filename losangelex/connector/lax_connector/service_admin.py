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
        "authorityId": authority,
        "hostId": host,
        "agentId": agent,
        "unit": unit,
        "modelOrServiceStarted": False,
        "deliveryOrEffectStateChanged": False,
    }
    if info.get("NeedDaemonReload") == "yes":
        return {**result, "ready": False, "reason": "service-manager-reload-required"}
    from .service_memory import inspection as memory_inspection

    result["serviceMemory"] = memory_inspection(authority, agent, info)
    from .service_restart import inspection as restart_inspection

    restart_policy = restart_inspection(authority, host, agent)
    result["automaticRestartRegistration"] = restart_policy
    if restart_policy.get("reason") == "restart-approval-changed":
        return {**result, "ready": False, "reason": "restart-approval-changed"}
    if info["ActiveState"] != "active" or int(info["MainPID"]) < 2:
        return {
            **result,
            "ready": False,
            "reason": "service-stopped",
            "serviceState": info["ActiveState"],
        }
    guardian = observer.process(int(info["MainPID"]))
    if (
        not guardian
        or guardian["uid"] != uid
        or guardian["controlGroup"] != info["ControlGroup"]
    ):
        raise PermissionError("Actual service guardian owner differs")
    image = Path(binary).resolve(strict=True).stat()
    baseline = {
        "schema": "lax-service-enrollment/v1",
        "authorityId": authority,
        "hostId": host,
        "agentId": agent,
        "uid": uid,
        "home": str(home),
        "unit": info["Id"],
        "unitDefinitionDigest": observer.unit_definition(info),
        "binary": str(Path(binary).resolve()),
        "binaryDevice": image.st_dev,
        "binaryInode": image.st_ino,
        "machineIdentity": observer.machine_identity(),
        "killMode": "control-group",
    }
    root = observer.directory(authority, host, agent)
    path = root / "enrollment.json"
    if not path.exists():
        return {**result, "ready": False, "reason": "registration-required"}
    enrollment = observer.protected(path)
    from .service_restart import file_hash

    result["restartReview"] = {
        "expectedEnrollment": observer.digest(enrollment),
        "expectedDefinition": baseline["unitDefinitionDigest"],
        "expectedConfigurationSha256": file_hash(home / "connector.json", uid)[0],
    }
    differences = sorted(k for k, v in baseline.items() if enrollment.get(k) != v)
    expected = {
        **baseline,
        "schema": "lax-service-incarnation/v1",
        "bootId": observer.boot_id(),
        "serviceInvocation": UUID(info["InvocationID"]).hex,
        "controlGroup": info["ControlGroup"],
        "guardianPid": guardian["pid"],
        "guardianStart": guardian["start"],
    }
    if differences:
        return {
            **result,
            "ready": False,
            "reason": "explicit-drained-upgrade-required",
            "changedFields": differences,
            "expectedEnrollment": observer.digest(enrollment),
            "expectedDefinition": baseline["unitDefinitionDigest"],
        }
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
    except BlockingIOError:
        return {**result, "ready": False, "reason": "service-inspection-busy", "retryable": True}
    except ValueError:
        return {**result, "ready": False, "reason": "native-image-transition-held"}
    from .native_release import runtime_spec

    spec, _, _ = runtime_spec(authority, agent)
    from .service_runtime import RuntimeMismatch, require_configured_guardian

    try:
        result["serviceRuntime"] = require_configured_guardian(
            authority, agent, home=home, service=info, guardian=guardian
        )
    except RuntimeMismatch as error:
        return {**result, "ready": False, "reason": str(error)}
    if spec.get("automaticRestartRegistration") and not restart_policy["enabled"]:
        return {
            **result,
            "ready": False,
            "reason": "reviewed-restart-approval-required",
        }
    try:
        package = preflight_as_owner(binary, spec["interpreter"], uid, home)
    except PackageError as error:
        return {
            **result,
            "ready": False,
            "reason": "native-package-preflight-failed",
            "nativePackage": error.details,
        }
    result["nativePackage"] = package
    result["restartReview"]["expectedImageSha256"] = (
        package.get("assets", {}).get("entrypoint", {}).get("sha256")
    )
    return {
        **result,
        "ready": True,
        "reason": "execution-registration-ready",
        "serviceInvocation": expected["serviceInvocation"],
        "bindingDigest": observer.digest(binding),
    }


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authority", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--agent", required=True)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--inspect", action="store_true")
    actions.add_argument("--register", action="store_true")
    actions.add_argument("--approve-restarts", action="store_true")
    actions.add_argument("--prepare-memory-max-bytes", type=int)
    actions.add_argument("--approve-drained-upgrade", action="store_true")
    actions.add_argument(
        "--approve-image-upgrade",
        action="store_true",
        help="Approve a disabled, stopped, drained exact image; grants no readiness",
    )
    actions.add_argument("--prepare-release", type=Path)
    actions.add_argument("--approve-release", type=Path)
    actions.add_argument("--release-status", action="store_true")
    actions.add_argument("--reconcile-release")
    parser.add_argument("--expected-preparation-sha256")
    parser.add_argument("--expected-intent-sha256")
    parser.add_argument("--operation-id")
    parser.add_argument("--expected-image-sha256")
    parser.add_argument("--expected-enrollment")
    parser.add_argument("--expected-definition")
    parser.add_argument("--expected-configuration-sha256")
    parser.add_argument("--expected-restart-policy")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    release_action = args.prepare_release or args.approve_release or args.release_status or args.reconcile_release
    if release_action:
        if any((args.expected_image_sha256, args.expected_enrollment, args.expected_definition,
                args.expected_configuration_sha256, args.expected_restart_policy)):
            parser.error("Release review uses the exact protected preparation, not legacy image arguments")
        if args.prepare_release:
            if not args.output or args.expected_preparation_sha256 or args.expected_intent_sha256 or args.operation_id:
                parser.error("Release preparation requires only --output")
            from .native_release import prepare
            result = prepare(args.authority, args.host, args.agent,
                             observer.protected(args.prepare_release), args.output)
        elif args.approve_release:
            if not args.expected_preparation_sha256 or args.output or args.expected_intent_sha256 or args.operation_id:
                parser.error("Release approval requires only --expected-preparation-sha256")
            from .native_release_transition import approve
            result = approve(args.authority, args.host, args.agent,
                             args.approve_release, args.expected_preparation_sha256)
        else:
            import re
            operation = args.reconcile_release or args.operation_id
            if operation and not re.fullmatch(r"[a-f0-9]{64}", operation):
                parser.error("Original release operation must be an exact digest")
            if args.output or args.expected_preparation_sha256 or args.operation_id and args.reconcile_release:
                parser.error("Release inspection/reconciliation options differ")
            from .native_release_transition import status, reconcile
            if args.reconcile_release:
                if not args.expected_intent_sha256:
                    parser.error("Reconciliation requires --expected-intent-sha256")
                result = reconcile(args.authority, args.host, args.agent,
                                   operation, args.expected_intent_sha256)
            else:
                if args.expected_intent_sha256:
                    parser.error("Inspection does not accept a reconciliation digest")
                result = status(args.authority, args.host, args.agent, operation)
        print(json.dumps(result))
        return
    if args.expected_preparation_sha256 or args.expected_intent_sha256 or args.operation_id:
        parser.error("Release digest/operation options require a release action")
    reviewed = (
        args.approve_drained_upgrade
        or args.approve_image_upgrade
        or args.approve_restarts
        or args.prepare_memory_max_bytes is not None
    )
    if reviewed != bool(args.expected_enrollment and args.expected_definition):
        parser.error(
            "Reviewed metadata/definition operation requires exact enrollment and definition digests"
        )
    if (args.expected_enrollment or args.expected_definition) and not reviewed:
        parser.error("Inspection digests require an explicit reviewed operation")
    if bool(args.expected_image_sha256) != bool(
        args.approve_image_upgrade or args.approve_restarts
    ):
        parser.error(
            "An image/restart approval requires the reviewed native image SHA256"
        )
    if bool(args.expected_configuration_sha256) != bool(args.approve_restarts):
        parser.error(
            "Only restart approval requires the reviewed connector configuration SHA256"
        )
    if args.expected_restart_policy and not args.approve_restarts:
        parser.error("Restart policy CAS requires --approve-restarts")
    if bool(args.output) != (args.prepare_memory_max_bytes is not None):
        parser.error("Only memory preparation requires --output")
    if args.prepare_memory_max_bytes is not None:
        from .service_memory import prepare

        print(
            json.dumps(
                prepare(
                    args.authority,
                    args.host,
                    args.agent,
                    args.prepare_memory_max_bytes,
                    args.expected_enrollment,
                    args.expected_definition,
                    args.output,
                )
            )
        )
        return
    if args.approve_restarts:
        from .service_restart import approve

        print(
            json.dumps(
                approve(
                    args.authority,
                    args.host,
                    args.agent,
                    args.expected_enrollment,
                    args.expected_definition,
                    args.expected_image_sha256,
                    args.expected_configuration_sha256,
                    args.expected_restart_policy,
                )
            )
        )
        return
    if args.approve_image_upgrade:
        from .native_image_upgrade import approve_image_upgrade

        result = approve_image_upgrade(
            args.authority,
            args.host,
            args.agent,
            args.expected_enrollment,
            args.expected_definition,
            args.expected_image_sha256,
        )
        print(json.dumps({"imageUpgrade": result}))
        return
    result = {}
    if args.approve_drained_upgrade:
        result["upgrade"] = observer.approve_drained_upgrade(
            args.authority,
            args.host,
            args.agent,
            args.expected_enrollment,
            args.expected_definition,
        )
    if args.register or args.approve_drained_upgrade:
        result["registration"] = observer.register(
            args.authority,
            args.host,
            args.agent,
            observer.installed_unit(args.authority, args.agent),
        )
    result["inspection"] = inspect(args.authority, args.host, args.agent)
    print(json.dumps(result))
    if not result["inspection"]["ready"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
