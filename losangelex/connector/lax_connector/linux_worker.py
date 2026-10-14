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

from .connector import saved
from .linux_admin import run


def provision(spec):
    if os.geteuid() != 0:
        raise PermissionError("Worker provisioning requires a verified administrator")
    authority, agent = str(UUID(spec["authorityId"])), str(UUID(spec["agentId"]))
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
        return {
            **receipt,
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
    config = {
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
        "sandbox": "workspace-write",
        "instructions": "You are a scoped enterprise worker. Your primary responsibility and room are captured in the authoritative LAX role context. Execute only explicitly addressed work within that scope. Observe other room communication without initiating work. Communicate through Hollywood and publish attributable evidence. Do not escalate host privileges, inspect another agent's private state, create workers or resume historical work. Complete each admitted request and wait.",
    }
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
    sudo = subprocess.run(
        ["runuser", "-u", user, "--", "sudo", "-n", "/usr/bin/id", "-u"],
        capture_output=True,
        timeout=5,
        check=False,
    )
    if sudo.returncode == 0:
        raise PermissionError("Worker unexpectedly has administrator access")
    unit = (
        "lax-worker-"
        + authority.replace("-", "")[:8]
        + "-"
        + agent.replace("-", "")[:12]
    )
    unit_file = Path("/etc/systemd/system") / (unit + ".service")
    content = f"""[Unit]
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
NoNewPrivileges=yes
KillMode=control-group
TimeoutStopSec=30
[Install]
WantedBy=multi-user.target
"""
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
        "authorityId": authority,
        "agentId": agent,
        "linuxUser": user,
        "uid": account.pw_uid,
        "workspace": config["workspace"],
        "unit": unit,
        "state": "resident-enabled",
        "administrator": False,
        "modelsStartedByProvisioning": 0,
        "modelAccountProved": False,
    }
    saved(record / "provision-receipt.json", receipt)
    return receipt


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(provision(json.loads(args.spec.read_text()))))


if __name__ == "__main__":
    main()
