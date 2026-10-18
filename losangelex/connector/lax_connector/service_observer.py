"""Protected systemd invocation registry and independent executor observations.

No process is started/stopped here. Empty groups, not timeouts, establish drainage.
"""

import hashlib
import json
import os
import pwd
import stat
import subprocess
from pathlib import Path
from uuid import UUID
from .host import machine_identity
from .journal import saved


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def boot_id():
    return str(UUID(Path("/proc/sys/kernel/random/boot_id").read_text().strip()))


def process(pid):
    path = Path("/proc") / str(int(pid))
    try:
        fields = (path / "stat").read_text().rsplit(")", 1)[1].split()
        uid = int(next(line.split()[1] for line in (path / "status").read_text().splitlines()
                       if line.startswith("Uid:")))
        groups = [line.split(":", 2)[2] for line in (path / "cgroup").read_text().splitlines()
                  if line.startswith("0::")]
        executable = (path / "exe").resolve(strict=True)
        image = executable.stat()
        return {"pid": int(pid), "start": fields[19], "uid": uid,
                "controlGroup": groups[0] if len(groups) == 1 else None,
                "executable": str(executable), "executableDevice": image.st_dev,
                "executableInode": image.st_ino}
    except (FileNotFoundError, ProcessLookupError):
        return None


def properties(unit):
    result = subprocess.run(
        ["systemctl", "show", unit, "--no-pager",
         "-p", "Id", "-p", "ActiveState", "-p", "MainPID", "-p", "InvocationID",
         "-p", "ControlGroup", "-p", "User", "-p", "KillMode", "-p", "FragmentPath",
         "-p", "MemoryMax", "-p", "MemoryCurrent", "-p", "MemoryPeak",
         "-p", "NeedDaemonReload"],
        check=True, capture_output=True, text=True,
    )
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


def protected(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise PermissionError("Service observation registry is not administrator protected")
    return json.loads(path.read_text())


def directory(authority, host, agent):
    values = [str(UUID(v)) for v in (authority, host, agent)]
    return Path("/var/lib/harness") / values[0] / "hosts" / values[1] / "services" / values[2]


def expected_owner(authority, agent):
    from .service_memory import approved_spec

    authority, agent = str(UUID(authority)), str(UUID(agent))
    base = Path("/var/lib/harness") / authority
    intent, receipt, global_agent = approved_spec(authority, agent)
    if global_agent:
        from .native_release import active_spec
        software = active_spec(intent, authority, intent["hostId"], agent)
        return receipt["uid"], Path(receipt["home"]), software["binary"]
    record = base / "workers" / agent
    if (intent["authorityId"], intent["agentId"]) != (authority, agent):
        raise PermissionError("Worker provisioning owner differs")
    user = "hworker-" + authority.replace("-", "")[:8] + "-" + agent.replace("-", "")[:12]
    account = pwd.getpwnam(user)
    home = record / "home"
    if account.pw_dir != str(home):
        raise PermissionError("Worker account home differs")
    from .native_release import active_spec
    software = active_spec(intent, authority, intent["hostId"], agent)
    return account.pw_uid, home, software["binary"]


def installed_unit(authority, agent):
    """Only the administrator-installed participant unit is auto-enrolled."""
    from .service_memory import approved_spec

    _, receipt, global_agent = approved_spec(authority, agent)
    if global_agent and not receipt.get("unit"):
        raise PermissionError(
            "Global installation needs explicit managed-service upgrade"
        )
    return properties(receipt["unit"])["Id"]


def unit_definition(info):
    path = Path(info["FragmentPath"])
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
        raise PermissionError("Service definition is not administrator owned")
    if info["KillMode"] != "control-group":
        raise PermissionError("Service must use systemd control-group lifecycle")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _register(authority, host, agent, unit, *, expected_binding=None):
    """Root installer records an actual running, owned service incarnation."""
    if os.geteuid() != 0:
        raise PermissionError("Root service registration required")
    authority, host, agent = [str(UUID(v)) for v in (authority, host, agent)]
    if not unit.startswith("lax-") or not unit.endswith(".service") or "/" in unit:
        raise ValueError("Explicit LAX service unit required")
    uid, home, binary = expected_owner(authority, agent)
    info = properties(unit)
    if info["ActiveState"] != "active" or int(info["MainPID"]) < 2:
        raise ValueError("Only an actual live service may be registered")
    guardian = process(int(info["MainPID"]))
    if not guardian or guardian["uid"] != uid or guardian["controlGroup"] != info["ControlGroup"]:
        raise PermissionError("Actual service guardian owner differs")
    if pwd.getpwnam(info["User"]).pw_uid != uid:
        raise PermissionError("Service user differs from installed agent")
    from .service_runtime import require_configured_guardian
    require_configured_guardian(authority, agent, home=home, service=info, guardian=guardian)
    definition = unit_definition(info)
    image = Path(binary).resolve(strict=True).stat()
    baseline = {"schema": "lax-service-enrollment/v1", "authorityId": authority,
                "hostId": host, "agentId": agent, "uid": uid, "home": str(home),
                "unit": unit, "unitDefinitionDigest": definition, "binary": str(Path(binary).resolve()),
                "binaryDevice": image.st_dev, "binaryInode": image.st_ino,
                "machineIdentity": machine_identity(), "killMode": "control-group"}
    root = directory(authority, host, agent)
    # The enrolled host directory is root/private; never create another installation.
    parent = root.parent.parent
    if not parent.is_dir() or parent.is_symlink() or parent.stat().st_uid != 0:
        raise PermissionError("Protected enrolled host required")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink() or root.stat().st_uid != 0:
        raise PermissionError("Service registry owner changed")
    root.chmod(0o700)
    enrollment = root / "enrollment.json"
    if enrollment.exists() and protected(enrollment) != baseline:
        raise ValueError("Service definition changed; explicit drain/upgrade required")
    if not enrollment.exists():
        saved(enrollment, baseline)
    invocation = str(UUID(info["InvocationID"])).replace("-", "")
    manifest = {**baseline, "schema": "lax-service-incarnation/v1", "bootId": boot_id(),
                "serviceInvocation": invocation, "controlGroup": info["ControlGroup"],
                "guardianPid": guardian["pid"], "guardianStart": guardian["start"]}
    if expected_binding is not None and manifest != expected_binding:
        raise ValueError("Observed restart incarnation changed before publication")
    target = root / (invocation + ".json")
    if target.exists() and protected(target) != manifest:
        raise ValueError("Original registered service incarnation changed")
    if not target.exists():
        saved(target, manifest)
    return {"registered": True, "agentId": agent, "unit": unit,
            "serviceInvocation": invocation, "bindingDigest": digest(manifest),
            "modelOrServiceStarted": False}



def register(authority, host, agent, unit):
    """Explicit registration; only fresh reviewed provisioning can seed approval."""
    from .service_restart import validate_fresh
    validate_fresh(authority, host, agent)
    root = directory(authority, host, agent)
    if not root.exists():
        result = _register(authority, host, agent, unit)
    else:
        from .native_image_upgrade import registry_lock, require_settled_transition
        with registry_lock(root) as fd:
            require_settled_transition(fd)
            result = _register(authority, host, agent, unit)
    from .service_restart import approve_fresh
    approval = approve_fresh(authority, host, agent)
    return {**result, **({"automaticRestartApproval": approval} if approval else {})}


def approve_drained_upgrade(authority, host, agent, expected_enrollment, expected_definition):
    """Definition-only upgrade; its original native-image prohibition is retained."""
    from .native_image_upgrade import registry_lock, require_settled_transition
    with registry_lock(directory(authority, host, agent)) as fd:
        require_settled_transition(fd)
        return _approve_drained_upgrade(authority, host, agent, expected_enrollment, expected_definition)


def _approve_drained_upgrade(authority, host, agent, expected_enrollment, expected_definition):
    """Root CAS upgrade of an enrolled service after its prior invocations drained.

    The new resident guardian may be running, but it must be alone in its group.
    Old invocation manifests remain immutable evidence. This grants no model turn.
    """
    if os.geteuid() != 0:
        raise PermissionError("Service upgrade requires verified administration")
    authority, host, agent = [str(UUID(v)) for v in (authority, host, agent)]
    root = directory(authority, host, agent)
    enrollment = root / "enrollment.json"
    old = protected(enrollment)
    if digest(old) != expected_enrollment:
        raise ValueError("Enrolled service changed; inspect the original upgrade")
    uid, home, binary = expected_owner(authority, agent)
    info = properties(installed_unit(authority, agent))
    definition = unit_definition(info)
    if definition != expected_definition:
        raise ValueError("New protected service definition differs")
    guardian = process(int(info["MainPID"]))
    if (
        info["ActiveState"] != "active" or not guardian
        or guardian["uid"] != uid
        or guardian["controlGroup"] != info["ControlGroup"]
        or pwd.getpwnam(info["User"]).pw_uid != uid
        or members(info["ControlGroup"]) != {guardian["pid"]}
    ):
        raise ValueError("New resident guardian is not alone in its owned group")
    for path in root.glob("*.json"):
        manifest = protected(path)
        if manifest.get("schema") != "lax-service-incarnation/v1":
            continue
        previous = process(manifest["guardianPid"])
        if previous and previous["start"] == manifest["guardianStart"]:
            raise ValueError("A prior registered guardian is still running")
    image = Path(binary).resolve(strict=True).stat()
    if (
        old["authorityId"], old["hostId"], old["agentId"], old["uid"],
        old["home"], old["unit"], old["binaryDevice"], old["binaryInode"],
        old["machineIdentity"], old["killMode"]
    ) != (
        authority, host, agent, uid, str(home), info["Id"], image.st_dev,
        image.st_ino, machine_identity(), "control-group"
    ):
        raise ValueError("This upgrade cannot change identity, native image or host")
    upgraded = {**old, "unitDefinitionDigest": definition}
    receipt_path = root / ("upgrade-" + expected_enrollment + "-" + definition + ".json")
    if receipt_path.exists():
        raise ValueError("Original upgrade evidence exists; inspect it without replay")
    archive = root / ("enrollment-before-" + expected_enrollment + ".json")
    if archive.exists():
        if protected(archive) != old:
            raise ValueError("Original enrollment archive differs")
    else:
        saved(archive, old)
    intent = {"schema": "lax-service-upgrade/v1", "priorEnrollmentDigest": expected_enrollment,
              "newDefinitionDigest": definition, "priorInvocationsDrained": True,
              "currentGuardianPid": guardian["pid"], "currentGuardianStart": guardian["start"],
              "currentGuardianAlone": True, "modelsStarted": 0, "state": "intent"}
    saved(receipt_path, intent)
    saved(enrollment, upgraded)
    receipt = {**intent, "state": "accepted", "newEnrollmentDigest": digest(upgraded)}
    saved(receipt_path, receipt)
    return receipt

def members(group):
    path = Path("/sys/fs/cgroup") / group.lstrip("/")
    if ".." in path.parts or not group.startswith("/"):
        raise ValueError("Invalid registered control group")
    if not path.exists():
        return set()
    result = set()
    for file in path.rglob("cgroup.procs"):
        try:
            result.update(int(v) for v in file.read_text().split())
        except FileNotFoundError:
            pass
    return result


def observe(config, row):
    """Return a conclusive signed-in-controller fact or explicit unknown."""
    if os.geteuid() != 0 or machine_identity() != config["machineIdentity"]:
        raise PermissionError("Protected local host controller required")
    d = row["descriptor"]
    root = directory(config["authorityId"], config["hostId"], row["agent"])
    manifest_path = root / (d["serviceInvocation"] + ".json")
    if not manifest_path.exists():
        # The controller's separate approved-service pass has the complete host
        # executor view, including idle restarts. A single row is insufficient.
        raise ValueError("Managed incarnation awaits protected controller registration")
    binding = protected(manifest_path)
    expected = {
        "authorityId": config["authorityId"],
        "hostId": config["hostId"],
        "agentId": str(row["agent"]),
        "unit": d["serviceUnit"],
        "serviceInvocation": d["serviceInvocation"],
        "controlGroup": d["controlGroup"],
        "guardianPid": d["guardianPid"],
        "guardianStart": d["guardianStart"],
        "bootId": d["bootId"],
        "machineIdentity": d["machineIdentity"],
    }
    if any(binding.get(k) != v for k, v in expected.items()):
        raise PermissionError("Original executor/service incarnation mismatch")
    evidence = {
        "originalBootId": d["bootId"],
        "observedBootId": boot_id(),
        "serviceBindingDigest": digest(binding),
        "originalServiceInvocation": d["serviceInvocation"],
        "serviceUnit": d["serviceUnit"],
        "guardianPid": d["guardianPid"],
        "guardianStart": d["guardianStart"],
        "nativePid": d["nativePid"],
        "nativeStart": d["nativeStart"],
        "externalEffectsUndone": False,
    }
    if evidence["observedBootId"] != d["bootId"]:
        return {
            "state": "stopped",
            "evidence": {**evidence, "reason": "machine-boot-changed"},
        }
    native = process(d["nativePid"]) if d["nativePid"] is not None else None
    native_original = native is not None and native["start"] == d["nativeStart"]
    info = properties(binding["unit"])
    if info["InvocationID"] != binding["serviceInvocation"] or info["ActiveState"] in (
        "inactive",
        "failed",
    ):
        if native_original:
            return {
                "state": "unknown",
                "evidence": {**evidence, "reason": "old-native-process-still-exists"},
            }
        return {
            "state": "stopped",
            "evidence": {
                **evidence,
                "reason": "registered-invocation-settled",
                "currentServiceInvocation": info["InvocationID"],
                "currentServiceState": info["ActiveState"],
            },
        }
    if unit_definition(info) != binding["unitDefinitionDigest"]:
        raise PermissionError("Registered service definition changed")
    guardian = process(d["guardianPid"])
    guardian_ok = (
        guardian
        and guardian["start"] == d["guardianStart"]
        and guardian["uid"] == binding["uid"]
        and guardian["controlGroup"] == binding["controlGroup"]
        and int(info["MainPID"]) == d["guardianPid"]
    )
    if guardian_ok and (row.get("launch_phase") == "reserved" or native_original):
        from .service_memory import approved_spec
        from .service_restart import inspection as restart_inspection
        restart_policy = restart_inspection(config["authorityId"], config["hostId"], str(row["agent"]))
        spec, _, _ = approved_spec(config["authorityId"], str(row["agent"]))
        if restart_policy.get("reason") == "restart-approval-changed" or (spec.get("automaticRestartRegistration") and not restart_policy["enabled"]):
            guardian_ok = False
    current = members(binding["controlGroup"])
    if row.get("launch_phase") == "reserved":
        return {
            "state": "unknown",
            "evidence": {
                **evidence,
                "reason": "registered-launch-pending"
                if guardian_ok
                else "launch-guardian-unverified",
                "nativeBirthUnconfirmed": True,
            },
        }
    if native_original:
        valid = (
            guardian_ok
            and native["uid"] == binding["uid"]
            and native["controlGroup"] == binding["controlGroup"]
        )
        valid = (
            valid
            and native["executableDevice"] == binding["binaryDevice"]
            and native["executableInode"] == binding["binaryInode"]
        )
        valid = valid and native["pid"] in current and guardian["pid"] in current
        if valid:
            return {
                "state": "live",
                "evidence": {**evidence, "reason": "matched-live-incarnation"},
            }
        return {
            "state": "unknown",
            "evidence": {
                **evidence,
                "reason": "native-incarnation-not-owned-by-registered-service",
            },
        }
    allowed = {d["guardianPid"]} if guardian_ok else set()
    remaining = sorted(current - allowed)
    if guardian_ok and not remaining and members(binding["controlGroup"]) <= allowed:
        return {
            "state": "stopped",
            "evidence": {
                **evidence,
                "reason": "registered-unit-drained",
                "remainingWorkPids": [],
                "remainingWorkProcessCount": 0,
                "remainingWorkProcessDigest": digest([]),
            },
        }
    return {
        "state": "unknown",
        "evidence": {
            **evidence,
            "reason": "registered-unit-not-drained",
            "remainingWorkPids": remaining[:64],
            "remainingWorkProcessCount": len(remaining),
            "remainingWorkProcessDigest": digest(remaining),
        },
    }
