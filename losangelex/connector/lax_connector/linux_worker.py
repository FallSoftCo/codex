"""Provision a distinct Linux execution identity and deterministic resident connector."""

import argparse
import hashlib
import json
import os
import pwd
import shutil
import subprocess
from pathlib import Path
from uuid import UUID

from .journal import saved
from .linux_admin import run


def execution_profile(spec, override=None):
    profile = override or spec.get("executionProfile", "unrestricted")
    if profile not in ("unrestricted", "restricted"):
        raise ValueError("Unknown host execution profile")
    return profile


def expected_configuration(spec, authority, agent, home, profile=None):
    profile = execution_profile(spec, profile)
    return {
        "hollywoodUrl": spec["hollywoodUrl"],
        "token": spec["credential"],
        "agentId": agent,
        "hostId": spec["hostId"],
        "state": str(home / "state"),
        "binary": spec["binary"],
        "codexHome": str(home / "codex-home"),
        "workspace": str(home / "work"),
        "model": spec["model"],
        "effort": spec["effort"],
        "sandbox": "danger-full-access" if profile == "unrestricted" else "workspace-write",
        "instructions": (
            "You are an accountable enterprise agent. Your responsibility and room are captured in the authoritative LAX role context. Execute the owner's addressed work and communicate through Hollywood with attributable evidence. This installation authorizes full host execution and passwordless sudo when needed for that work. Protect credentials and preserve other agents' work, accepted operations and unknown effects. Host access does not authorize unrelated business actions or resuming stopped historical work. Complete each admitted request and wait."
            if profile == "unrestricted" else
            "You are a scoped enterprise worker. Your primary responsibility and room are captured in the authoritative LAX role context. Execute only explicitly addressed work within that scope. Observe other room communication without initiating work. Communicate through Hollywood and publish attributable evidence. Do not escalate host privileges, inspect another agent's private state, create workers or resume historical work. Complete each admitted request and wait."
        ),
    }

def expected_unit(spec, agent, user, home, profile=None):
    profile = execution_profile(spec, profile)
    config_file = home / "connector.json"
    return f"""[Unit]
Description=LAX Hollywood worker {agent}
After=network-online.target
StartLimitIntervalSec=60
StartLimitBurst=3
[Service]
Type=simple
User={user}
WorkingDirectory={home / "work"}
ExecStart={spec["interpreter"]} -m lax_connector.connector --config {config_file} --serve
Restart=on-failure
RestartSec=10
UMask=0077
MemoryMax=2G
CPUQuota=200%
NoNewPrivileges={"no" if profile == "unrestricted" else "yes"}
KillMode=control-group
TimeoutStopSec=30
[Install]
WantedBy=multi-user.target
"""

def protected(path):
    import stat
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError("Original provisioning evidence is not protected")
    return json.loads(path.read_text())

def service_readiness(authority, host, agent):
    # Inspection must never silently enable a deliberately stopped service.
    from .service_admin import inspect
    return inspect(authority, str(UUID(host)), agent)


def inspect_completed(spec):
    """Read conclusive original setup acceptance without making setup changes."""
    if os.geteuid() != 0:
        raise PermissionError("Provisioning inspection requires verified administration")
    authority, agent = str(UUID(spec["authorityId"])), str(UUID(spec["agentId"]))
    machine = hashlib.sha256(Path("/etc/machine-id").read_bytes()).hexdigest()
    if spec.get("machineIdentity") != machine:
        raise ValueError("Original provisioning host identity differs")
    base = Path("/var/lib/harness") / authority
    record = base / "workers" / agent
    for path in (base, base / "workers", record):
        info = path.lstat()
        if path.is_symlink() or not path.is_dir() or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("Original provisioning owner changed")
    intent = protected(record / "provision-intent.json")
    fingerprint = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    if intent.get("digest") != fingerprint or intent.get("spec") != spec:
        raise ValueError("Original provisioning specification differs")
    receipt = protected(record / "provision-receipt.json")
    if receipt.get("schema") != "lax-worker-provision/v1" or receipt.get("specDigest") != fingerprint:
        raise ValueError("Conclusive original provisioning receipt unavailable")
    user = "hworker-" + authority.replace("-", "")[:8] + "-" + agent.replace("-", "")[:12]
    unit = "lax-worker-" + authority.replace("-", "")[:8] + "-" + agent.replace("-", "")[:12]
    home = record / "home"
    account = pwd.getpwnam(user)
    if (receipt["authorityId"], receipt["agentId"], receipt["linuxUser"], receipt["uid"],
        receipt["workspace"], receipt["unit"], account.pw_dir) != (
        authority, agent, user, account.pw_uid, str(home / "work"), unit, str(home)
    ):
        raise ValueError("Original worker identity differs")
    for path in (home, home / "work", home / "state", home / "codex-home"):
        if path.is_symlink() or not path.is_dir() or path.stat().st_uid != account.pw_uid:
            raise ValueError("Original worker path ownership changed")
    config_file = home / "connector.json"
    if config_file.is_symlink() or config_file.stat().st_uid != account.pw_uid:
        raise ValueError("Worker configuration owner changed")
    policy_file = record / "execution-policy-upgrade-receipt.json"
    policy = protected(policy_file) if policy_file.exists() else None
    if policy and policy.get("originalSpecDigest") != fingerprint:
        raise ValueError("Execution policy upgrade belongs to another provisioning")
    profile = (policy or receipt).get("executionProfile", "restricted")
    expected = expected_configuration(spec, authority, agent, home, profile)
    config = json.loads(config_file.read_text())
    checked_configuration = config if policy else expected
    if policy and any(config.get(key) != expected.get(key) for key in ("agentId", "hostId", "state", "workspace", "codexHome", "sandbox")):
        raise ValueError("Execution policy changed worker identity or execution scope")
    config_digest = hashlib.sha256(json.dumps(checked_configuration, sort_keys=True).encode()).hexdigest()
    if config != checked_configuration or (policy or receipt).get("configurationDigest") != config_digest:
        raise ValueError("Original worker configuration differs")
    unit_file = Path("/etc/systemd/system") / (unit + ".service")
    info = unit_file.lstat()
    content = unit_file.read_text() if policy else expected_unit(spec, agent, user, home, profile)
    if unit_file.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError("Worker service is not administrator protected")
    if unit_file.read_text() != content or (policy or receipt).get("unitDigest") != hashlib.sha256(content.encode()).hexdigest():
        raise ValueError("Original worker service definition differs")
    current = {}
    for name in ("ActiveState", "UnitFileState", "MainPID"):
        current[name] = run("systemctl", "show", unit, "-p", name, "--value").stdout.strip()
    return {
        **receipt, "executionProfile": profile, "effectiveHostAdministrator": profile == "unrestricted",
        "executionPolicyUpgrade": policy, "recoveredBy": "protected-original-provisioning-read",
        "inspection": {"hostIdentityMatched": True, "currentService": current,
                       "executionRegistration": service_readiness(authority, spec["hostId"], agent),
                       "configurationMatched": True, "modelOrServiceRestarted": False,
                       "setupRepeated": False},
    }

def provision(spec):
    if os.geteuid() != 0:
        raise PermissionError("Worker provisioning requires a verified administrator")
    authority, agent = str(UUID(spec["authorityId"])), str(UUID(spec["agentId"]))
    if spec.get("machineIdentity") and spec["machineIdentity"] != hashlib.sha256(Path("/etc/machine-id").read_bytes()).hexdigest():
        raise ValueError("Provisioning host identity differs")
    base = Path("/var/lib/harness") / authority
    if base.is_symlink() or not base.is_dir() or base.stat().st_uid != 0:
        raise ValueError("Administrator-owned enterprise installation required")
    workers = base / "workers"
    if workers.is_symlink():
        raise ValueError("Worker state cannot be a symlink")
    workers.mkdir(mode=0o711, exist_ok=True)
    workers.chmod(0o711)
    record = workers / agent
    if record.is_symlink():
        raise ValueError("Worker identity directory cannot be a symlink")
    record.mkdir(mode=0o711, exist_ok=True)
    record.chmod(0o711)
    intent = record / "provision-intent.json"
    fingerprint = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    if intent.exists():
        if json.loads(intent.read_text())["digest"] != fingerprint:
            raise ValueError(
                "Original worker provisioning changed; explicit upgrade required"
            )
    else:
        saved(intent, {"digest": fingerprint, "spec": spec})
    user = (
        "hworker-" + authority.replace("-", "")[:8] + "-" + agent.replace("-", "")[:12]
    )
    home = record / "home"
    if home.is_symlink():
        raise ValueError("Worker home cannot be a symlink")
    prior_receipt = record / "provision-receipt.json"
    if prior_receipt.exists():
        receipt = json.loads(prior_receipt.read_text())
        account = pwd.getpwnam(receipt["linuxUser"])
        if account.pw_uid != receipt["uid"] or account.pw_dir != str(home):
            raise ValueError("Existing worker ownership changed")
        # Re-running install must preserve a deliberately stopped worker. Never
        # overwrite files in its now-untrusted home or silently enable its unit.
        state = run(
            "systemctl", "show", receipt["unit"], "-p", "ActiveState", "--value"
        ).stdout.strip()
        policy_file = record / "execution-policy-upgrade-receipt.json"
        policy = protected(policy_file) if policy_file.exists() else receipt
        profile = policy.get("executionProfile", "restricted")
        return {
            **receipt,
            "executionProfile": profile,
            "effectiveHostAdministrator": profile == "unrestricted",
            "executionRegistration": service_readiness(authority, spec["hostId"], agent),
            "reconciled": True,
            "serviceActiveState": state,
            "modelOrServiceRestarted": False,
        }
    try:
        account = pwd.getpwnam(user)
        if account.pw_dir != str(home):
            raise ValueError("Existing Linux identity belongs to another worker")
    except KeyError:
        run(
            "useradd",
            "--system",
            "--user-group",
            "--create-home",
            "--home-dir",
            str(home),
            "--shell",
            "/bin/bash",
            user,
        )
        account = pwd.getpwnam(user)
    home.chmod(0o700)
    for name in ["work", "state", "codex-home"]:
        path = home / name
        if path.is_symlink():
            raise ValueError("Worker private path cannot be a symlink")
        path.mkdir(mode=0o700, exist_ok=True)
        path.chmod(0o700)
        os.chown(path, account.pw_uid, account.pw_gid)
    config = expected_configuration(spec, authority, agent, home)
    config_file = home / "connector.json"
    if config_file.exists() and json.loads(config_file.read_text()) != config:
        raise ValueError(
            "Existing connector configuration changed; explicit upgrade required"
        )
    saved(config_file, config)
    os.chown(config_file, account.pw_uid, account.pw_gid)
    source_auth = Path(spec["approvedModelAuthFile"])
    auth = home / "codex-home/auth.json"
    if auth.exists() and auth.read_bytes() != source_auth.read_bytes():
        raise ValueError("Model credential rotation requires explicit reconciliation")
    if not auth.exists():
        shutil.copyfile(source_auth, auth)
    auth.chmod(0o600)
    os.chown(auth, account.pw_uid, account.pw_gid)
    run("runuser", "-u", user, "--", spec["binary"], "--version")
    run(
        "runuser",
        "-u",
        user,
        "--",
        spec["interpreter"],
        "-c",
        "import lax_connector.connector",
    )
    profile = execution_profile(spec)
    if profile == "unrestricted":
        sudo_file = Path("/etc/sudoers.d") / ("harness-worker-" + authority.replace("-", "")[:8] + "-" + agent.replace("-", "")[:12])
        expected_sudo = f"{user} ALL=(ALL:ALL) NOPASSWD: ALL\n"
        if sudo_file.exists() and sudo_file.read_text() != expected_sudo:
            raise ValueError("Existing worker sudo policy differs; explicit reconciliation required")
        candidate = record / "worker-sudoers.candidate"
        candidate.write_text(expected_sudo)
        candidate.chmod(0o440)
        run("visudo", "-cf", str(candidate))
        if not sudo_file.exists():
            shutil.copyfile(candidate, sudo_file)
            sudo_file.chmod(0o440)
        run("visudo", "-c")
    sudo = subprocess.run(
        ["runuser", "-u", user, "--", "sudo", "-n", "/usr/bin/id", "-u"],
        capture_output=True,
        timeout=5,
        check=False,
    )
    if (sudo.returncode == 0) != (profile == "unrestricted"):
        raise PermissionError("Worker host privileges do not match the requested execution profile")
    unit = (
        "lax-worker-"
        + authority.replace("-", "")[:8]
        + "-"
        + agent.replace("-", "")[:12]
    )
    unit_file = Path("/etc/systemd/system") / (unit + ".service")
    content = expected_unit(spec, agent, user, home)
    if unit_file.exists() and unit_file.read_text() != content:
        raise ValueError(
            "Existing worker unit differs; explicit upgrade/drain required"
        )
    if not unit_file.exists():
        unit_file.write_text(content)
        unit_file.chmod(0o644)
        run("systemctl", "daemon-reload")
    run("systemctl", "enable", "--now", unit)
    receipt = {
        "schema": "lax-worker-provision/v1",
        "specDigest": fingerprint,
        "configurationDigest": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
        "unitDigest": hashlib.sha256(content.encode()).hexdigest(),
        "authorityId": authority,
        "agentId": agent,
        "linuxUser": user,
        "uid": account.pw_uid,
        "workspace": config["workspace"],
        "unit": unit,
        "state": "resident-enabled",
        "administrator": profile == "unrestricted",
        "executionProfile": profile,
        "modelsStartedByProvisioning": 0,
        "modelAccountProved": False,
    }
    saved(record / "provision-receipt.json", receipt)
    # The owner receipt is required by the protected service registry. Do not
    # report a usable executor from systemd health alone.
    from .service_observer import register
    registration = register(authority, str(UUID(spec["hostId"])), agent, unit + ".service")
    saved(record / "service-registration-receipt.json", registration)
    readiness = service_readiness(authority, spec["hostId"], agent)
    if not readiness["ready"]:
        raise RuntimeError("Installed worker execution registration is not ready")
    return {**receipt, "executionRegistration": readiness}


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--inspect", action="store_true")
    args = parser.parse_args()
    method = inspect_completed if args.inspect else provision
    print(json.dumps(method(json.loads(args.spec.read_text()))))


if __name__ == "__main__":
    main()
