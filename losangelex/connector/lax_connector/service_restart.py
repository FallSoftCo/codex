"""Controller-only registration of an approved, already running restart incarnation.

This metadata path starts no service, enables no placement and changes no task,
executor or external-effect state. Initial enrollment and changed pins are explicit.
"""

import hashlib
import json
import os
from pathlib import Path
from uuid import UUID

from . import service_observer as observer
from .journal import saved
from .native_image_upgrade import (
    registry_lock,
    require_settled_transition,
    _identity,
    _open_directory,
)

POLICY = "restart-approval.json"


class ServiceStopped(ValueError):
    pass


def file_hash(path, uid):
    path = Path(path)
    parent = _open_directory(path.parent, uid)
    try:
        handle = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
        )
        try:
            import stat

            before = os.fstat(handle)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != uid
                or before.st_mode & 0o022
            ):
                raise PermissionError("Approved file owner/type changed")
            h = hashlib.sha256()
            while data := os.read(handle, 1024 * 1024):
                h.update(data)
            if _identity(os.fstat(handle)) != _identity(before):
                raise ValueError("Approved file changed while hashing")
            return h.hexdigest(), list(_identity(before))
        finally:
            os.close(handle)
    finally:
        os.close(parent)


def file_identity(path, uid=0):
    from .native_image_upgrade import _owned

    path = Path(path)
    parent = _open_directory(path.parent, uid)
    try:
        handle = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
        )
        try:
            info = os.fstat(handle)
            _owned(info, uid)
            return list(_identity(info))
        finally:
            os.close(handle)
    finally:
        os.close(parent)


def actual(authority, host, agent):
    uid, home, binary = observer.expected_owner(authority, agent)
    info = observer.properties(observer.installed_unit(authority, agent))
    if info["ActiveState"] != "active" or int(info["MainPID"]) < 2:
        raise ServiceStopped("Service is stopped; registration never starts it")
    guardian = observer.process(int(info["MainPID"]))
    if (
        not guardian
        or guardian["uid"] != uid
        or guardian["controlGroup"] != info["ControlGroup"]
    ):
        raise PermissionError("Actual managed guardian identity differs")
    import pwd

    if pwd.getpwnam(info["User"]).pw_uid != uid:
        raise PermissionError("Managed service user differs")
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
    binding = {
        **baseline,
        "schema": "lax-service-incarnation/v1",
        "bootId": observer.boot_id(),
        "serviceInvocation": UUID(info["InvocationID"]).hex,
        "controlGroup": info["ControlGroup"],
        "guardianPid": guardian["pid"],
        "guardianStart": guardian["start"],
    }
    return baseline, binding, info, guardian


def settled_definitions(root):
    for path in root.glob("upgrade-*.json"):
        value = observer.protected(path)
        if (
            value.get("schema") == "lax-service-upgrade/v1"
            and value.get("state") != "accepted"
        ):
            raise ValueError("Original service definition transition remains unsettled")


def approve(
    authority,
    host,
    agent,
    expected_enrollment,
    expected_definition,
    expected_image,
    expected_configuration,
    expected_policy=None,
):
    if os.geteuid() != 0:
        raise PermissionError("Root approval required")
    authority, host, agent = [str(UUID(v)) for v in (authority, host, agent)]
    root = observer.directory(authority, host, agent)
    with registry_lock(root) as fd:
        require_settled_transition(fd)
        settled_definitions(root)
        baseline, binding, _, guardian = actual(authority, host, agent)
        enrolled = observer.protected(root / "enrollment.json")
        if (
            enrolled != baseline
            or observer.digest(enrolled) != expected_enrollment
            or baseline["unitDefinitionDigest"] != expected_definition
        ):
            raise ValueError("Reviewed enrollment/definition differs")
        if (
            observer.protected(root / (binding["serviceInvocation"] + ".json"))
            != binding
        ):
            raise ValueError(
                "Current invocation must already have explicit registration"
            )
        image, image_identity = file_hash(baseline["binary"], 0)
        configuration, _ = file_hash(
            Path(baseline["home"]) / "connector.json", baseline["uid"]
        )
        if image != expected_image or configuration != expected_configuration:
            raise ValueError("Reviewed native image/configuration differs")
        guardian_hash, guardian_identity = file_hash(guardian["executable"], 0)
        value = {
            "schema": "lax-approved-service-restarts/v1",
            "authorityId": authority,
            "hostId": host,
            "agentId": agent,
            "enrollmentDigest": observer.digest(enrolled),
            "unitDefinitionDigest": expected_definition,
            "nativeImageSha256": image,
            "guardianExecutable": {
                "path": guardian["executable"],
                "identity": guardian_identity,
                "sha256": guardian_hash,
            },
            "imageIdentity": image_identity,
            "configurationSha256": configuration,
            "approvedInvocation": binding["serviceInvocation"],
            "modelsStarted": 0,
            "servicesStarted": 0,
        }
        target = root / POLICY
        if target.exists():
            old = observer.protected(target)
            if old == value:
                return {
                    "approved": True,
                    "policyDigest": observer.digest(old),
                    "changed": False,
                }
            if observer.digest(old) != expected_policy:
                raise ValueError("Original restart approval CAS required")
        elif expected_policy is not None:
            raise ValueError("Original restart approval missing")
        from .collaboration_install import write_original

        write_original(
            root / ("restart-approval-" + observer.digest(value) + ".json"), value
        )
        saved(target, value)
        return {
            "approved": True,
            "policyDigest": observer.digest(value),
            "changed": True,
            "modelsStarted": 0,
            "servicesStarted": 0,
        }


def validate_fresh(authority, host, agent):
    """Fresh automatic approval is anchored to protected provisioning evidence."""
    from .service_memory import approved_spec

    root = observer.directory(authority, host, agent)
    if (root / POLICY).exists() or (root / "native-image-transition.json").exists():
        return False
    spec, receipt, _ = approved_spec(authority, agent)
    if not spec.get("automaticRestartRegistration"):
        return False
    uid, home, binary = observer.expected_owner(authority, agent)
    config = json.loads((home / "connector.json").read_text())
    if (
        receipt.get("configurationDigest")
        != hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    ):
        raise ValueError("Fresh approved configuration differs")
    if (
        file_hash(binary, 0)[0]
        != receipt["nativePackage"]["assets"]["entrypoint"]["sha256"]
    ):
        raise ValueError("Fresh approved native image differs")
    return True


def approve_fresh(authority, host, agent):
    from .service_memory import approved_spec

    spec, receipt, _ = approved_spec(authority, agent)
    if (
        not spec.get("automaticRestartRegistration")
        or (observer.directory(authority, host, agent) / POLICY).exists()
        or (
            observer.directory(authority, host, agent) / "native-image-transition.json"
        ).exists()
    ):
        return None
    uid, home, binary = observer.expected_owner(authority, agent)
    config = json.loads((home / "connector.json").read_text())
    approved_digest = hashlib.sha256(
        json.dumps(config, sort_keys=True).encode()
    ).hexdigest()
    if receipt.get("configurationDigest") != approved_digest:
        raise ValueError("Fresh approved configuration differs")
    image = receipt["nativePackage"]["assets"]["entrypoint"]["sha256"]
    baseline = observer.protected(
        observer.directory(authority, host, agent) / "enrollment.json"
    )
    return approve(
        authority,
        host,
        agent,
        observer.digest(baseline),
        baseline["unitDefinitionDigest"],
        image,
        file_hash(home / "connector.json", uid)[0],
    )


def reconcile_one(config, agent, rows):
    if os.geteuid() != 0 or observer.machine_identity() != config["machineIdentity"]:
        raise PermissionError("Actual Root controller on enrolled machine required")
    authority, host = str(UUID(config["authorityId"])), str(UUID(config["hostId"]))
    agent = str(UUID(agent))
    root = observer.directory(authority, host, agent)
    with registry_lock(root) as fd:
        require_settled_transition(fd)
        settled_definitions(root)
        policy = observer.protected(root / POLICY)
        baseline, binding, info, guardian = actual(authority, host, agent)
        if observer.protected(root / "enrollment.json") != baseline or policy[
            "enrollmentDigest"
        ] != observer.digest(baseline):
            raise ValueError("Changed enrollment/definition requires explicit approval")
        if (policy["authorityId"], policy["hostId"], policy["agentId"]) != (
            authority,
            host,
            agent,
        ):
            raise ValueError("Restart approval belongs to another service")
        if (
            file_hash(Path(baseline["home"]) / "connector.json", baseline["uid"])[0]
            != policy["configurationSha256"]
        ):
            raise ValueError("Approved connector configuration changed")
        if file_identity(baseline["binary"]) != policy["imageIdentity"]:
            raise ValueError("Approved native image identity changed")
        approved_guardian = policy["guardianExecutable"]
        if (
            guardian["executable"] != approved_guardian["path"]
            or file_identity(guardian["executable"]) != approved_guardian["identity"]
        ):
            raise ValueError("Approved guardian executable changed")
        target = root / (binding["serviceInvocation"] + ".json")
        if target.exists():
            if observer.protected(target) != binding:
                raise ValueError("Original registered invocation changed")
            return {"state": "registered", "changed": False, "agentId": agent}
        if observer.members(binding["controlGroup"]) != {guardian["pid"]}:
            raise ValueError("Restart guardian must be alone in its cgroup")
        # SHA256 was verified at explicit approval. Root ownership and complete
        # unchanged kernel identity fence that exact image without re-reading the
        # large CLI into the controller's cgroup page cache on each restart.
        paths = list(root.glob("*.json"))
        if len(paths) > 4096:
            raise ValueError("Bounded service history exhausted")
        previous = 0
        for path in paths:
            value = observer.protected(path)
            if value.get("schema") != "lax-service-incarnation/v1":
                continue
            previous += 1
            old = (
                observer.process(value["guardianPid"])
                if value["bootId"] == observer.boot_id()
                else None
            )
            if old and old["start"] == value["guardianStart"]:
                raise ValueError("Original guardian remains live")
            allowed = (
                {guardian["pid"]}
                if value["controlGroup"] == binding["controlGroup"]
                else set()
            )
            if observer.members(value["controlGroup"]) - allowed:
                raise ValueError("Original invocation cgroup remains occupied")
        if not previous:
            raise ValueError("An original registered incarnation is required")
        for row in rows:
            if str(row["agent"]) != agent:
                continue
            d = row["descriptor"]
            if d["serviceInvocation"] == binding["serviceInvocation"]:
                if (
                    row["launch_phase"] != "reserved"
                    or d["nativePid"] is not None
                    or d["guardianPid"] != guardian["pid"]
                    or d["guardianStart"] != guardian["start"]
                    or d["serviceUnit"] != binding["unit"]
                    or d["bootId"] != binding["bootId"]
                    or d["machineIdentity"] != binding["machineIdentity"]
                    or d["controlGroup"] != binding["controlGroup"]
                ):
                    raise ValueError(
                        "Current executor is not an original unlaunched reservation"
                    )
            elif observer.observe(config, row)["state"] != "stopped":
                raise ValueError("Original executor physical stop remains unknown")
        # Recheck actual incarnation before the existing sole registry writer.
        if actual(authority, host, agent)[1] != binding or observer.members(
            binding["controlGroup"]
        ) != {guardian["pid"]}:
            raise ValueError("Restart service changed during observation")
        result = observer._register(
            authority, host, agent, info["Id"], expected_binding=binding
        )
        return {
            "state": "registered",
            "changed": True,
            "agentId": agent,
            "registration": result,
            "newExecutionAdmitted": False,
            "originalExecutorStateChanged": False,
            "externalEffectsUndone": False,
        }


def reconcile_services(config):
    root = (
        Path("/var/lib/harness")
        / config["authorityId"]
        / "hosts"
        / config["hostId"]
        / "services"
    )
    results = []
    if not root.exists():
        return {"registered": 0, "held": 0, "servicesStarted": 0}
    from .host import request

    rows = []
    after = None
    seen = set()
    for _ in range(16):
        page = request(
            config["hollywoodUrl"],
            config["token"],
            "GET",
            "hosts/"
            + config["hostId"]
            + "/executors"
            + ("?after=" + after if after else ""),
        )
        rows.extend(page["executors"])
        after = page["nextAfter"]
        if not after:
            break
        after = str(UUID(after))
        if after in seen:
            raise ValueError("Executor cursor repeated")
        seen.add(after)
    else:
        raise ValueError("Bounded executor inspection exhausted")
    agents = [p for p in root.iterdir() if p.is_dir()]
    if len(agents) > 256:
        raise ValueError("Bounded registered service inspection exhausted")
    for path in sorted(agents):
        if not (path / POLICY).exists():
            continue
        try:
            result = reconcile_one(config, str(UUID(path.name)), rows)
        except ServiceStopped:
            result = {"state": "stopped", "agentId": path.name, "servicesStarted": 0}
        except Exception as error:
            result = {
                "state": "held",
                "agentId": path.name,
                "reason": type(error).__name__,
                "detail": str(error)[:300],
                "servicesStarted": 0,
            }
        results.append(result)
    summary = {
        "registered": sum(v.get("changed", False) for v in results),
        "held": sum(v["state"] == "held" for v in results),
        "servicesStarted": 0,
        "modelsStarted": 0,
        "results": results,
    }
    saved(Path(config["state"]) / "service-incarnation-summary.json", summary)
    return summary


def inspection(authority, host, agent):
    root = observer.directory(authority, host, agent)
    path = root / POLICY
    if not path.exists():
        return {"enabled": False, "reason": "reviewed-restart-approval-required"}
    policy = observer.protected(path)
    try:
        baseline, binding, _, guardian = actual(authority, host, agent)
        approved_guardian = policy["guardianExecutable"]
        if (
            guardian["executable"] != approved_guardian["path"]
            or file_identity(guardian["executable"]) != approved_guardian["identity"]
        ):
            raise ValueError("Changed guardian executable")
        if (
            observer.digest(baseline) != policy["enrollmentDigest"]
            or observer.protected(root / "enrollment.json") != baseline
        ):
            raise ValueError("Changed service enrollment/definition")
        if file_identity(baseline["binary"]) != policy["imageIdentity"]:
            raise ValueError("Changed native image identity")
        if (
            file_hash(Path(baseline["home"]) / "connector.json", baseline["uid"])[0]
            != policy["configurationSha256"]
        ):
            raise ValueError("Changed connector configuration")
    except ServiceStopped:
        return {
            "enabled": False,
            "reason": "service-stopped",
            "policyDigest": observer.digest(policy),
        }
    except Exception as error:
        return {
            "enabled": False,
            "reason": "restart-approval-changed",
            "policyDigest": observer.digest(policy),
            "detail": str(error)[:200],
        }
    return {
        "enabled": True,
        "reason": "approved-same-image-registration",
        "policyDigest": observer.digest(policy),
    }
