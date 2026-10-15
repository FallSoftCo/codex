"""Provision Global's real Linux identity without granting workers shared sudo.

This is an installation primitive, not the completed enterprise installer.
Root supplies verified component artifacts and approved model credentials.
"""

import argparse
import hashlib
import json
import os
import platform
import pwd
import shutil
import subprocess
from pathlib import Path
from uuid import UUID

from .journal import saved


def run(*args):
    return subprocess.run(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )


def provision(spec):
    if os.geteuid() != 0 or platform.system() != "Linux":
        raise PermissionError("A verified Linux administrator must perform bootstrap")
    installation = json.loads(Path(spec["installationIntent"]).read_text())
    identity = str(UUID(installation["authorityId"]))
    slug = identity.replace("-", "")[:12]
    user = "hglobal-" + slug
    base = Path("/var/lib/harness")
    base.mkdir(mode=0o711, exist_ok=True)
    if base.is_symlink() or base.stat().st_uid != 0:
        raise ValueError("Harness installation root is not administrator-owned")
    base.chmod(0o711)
    state = base / identity
    state.mkdir(parents=True, exist_ok=True, mode=0o711)
    state.chmod(0o711)
    intent = state / "global-admin-intent.json"
    fingerprint = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    if intent.exists():
        original = json.loads(intent.read_text())
        if original["digest"] != fingerprint:
            raise ValueError(
                "Installation intent changed; explicit upgrade reconciliation required"
            )
    else:
        saved(
            intent,
            {
                "digest": fingerprint,
                "spec": spec,
                "user": user,
                "authorityId": identity,
            },
        )
    home = state / "global"
    try:
        account = pwd.getpwnam(user)
        if account.pw_dir != str(home):
            raise ValueError("Existing Linux identity belongs to another installation")
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
    sudo_file = Path("/etc/sudoers.d") / ("harness-global-" + slug)
    expected = f"{user} ALL=(ALL:ALL) NOPASSWD: ALL\n"
    if sudo_file.exists() and sudo_file.read_text() != expected:
        raise ValueError("Existing administrator policy changed; do not overwrite")
    candidate = state / "global-sudoers.candidate"
    candidate.write_text(expected)
    candidate.chmod(0o440)
    run("visudo", "-cf", str(candidate))
    shutil.copyfile(candidate, sudo_file)
    sudo_file.chmod(0o440)
    run("visudo", "-c")
    for name in ("work", "state", "codex-home"):
        path = home / name
        path.mkdir(mode=0o700, exist_ok=True)
        os.chown(path, account.pw_uid, account.pw_gid)
    auth = home / "codex-home/auth.json"
    source = Path(spec["approvedModelAuthFile"])
    if not source.is_file():
        raise ValueError("Approved model credentials not provisioned")
    if auth.exists() and auth.read_bytes() != source.read_bytes():
        raise ValueError(
            "Existing model credentials differ; explicit rotation required"
        )
    if not auth.exists():
        shutil.copyfile(source, auth)
    auth.chmod(0o600)
    os.chown(auth, account.pw_uid, account.pw_gid)
    binary = Path(spec["binary"])
    interpreter = Path(spec["interpreter"])
    # A role label cannot hide inaccessible runtime artifacts or absent sudo.
    run("runuser", "-u", user, "--", str(binary), "--version")
    run(
        "runuser",
        "-u",
        user,
        "--",
        str(interpreter),
        "-c",
        "import lax_connector.roles",
    )
    root_id = run(
        "runuser", "-u", user, "--", "sudo", "-n", "/usr/bin/id", "-u"
    ).stdout.strip()
    if root_id != "0":
        raise PermissionError("Global administrator capability verification failed")
    config = {
        "hollywoodUrl": spec["hollywoodUrl"],
        "token": installation["credentials"]["Global"]["token"],
        "agentId": installation["credentials"]["Global"]["principalId"],
        "hostId": spec["hostId"],
        "state": str(home / "state"),
        "binary": str(binary),
        "codexHome": str(home / "codex-home"),
        "workspace": str(home / "work"),
        "model": spec["model"],
        "effort": spec["effort"],
        "sandbox": "danger-full-access",
        "requireAdministrator": True,
        "instructions": "You are Global: the enterprise coordinator and ultimate administrator. You may provision and repair the enrolled environment within the human's authorized work. Communicate through Hollywood; assign scoped work to accountable owners and observe their rooms without routine replies or creating shadow contexts. Your actual host administrator capability is checked at startup. Protect credentials; never print or publish tokens. Preserve accepted work and uncertain effects. Do not restart stopped historical workers or schedules.",
    }
    config_file = home / "connector.json"
    saved(config_file, config)
    os.chown(config_file, account.pw_uid, account.pw_gid)
    receipt = {
        "authorityId": identity,
        "agentId": config["agentId"],
        "linuxUser": user,
        "uid": account.pw_uid,
        "home": str(home),
        "connectorConfig": str(config_file),
        "sudoVerifiedUid": 0,
        "workerPrivilegesChanged": False,
        "modelAccountProved": False,
        "enterpriseInstallationComplete": False,
    }
    saved(state / "global-admin-receipt.json", receipt)
    return receipt


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(provision(json.loads(args.spec.read_text()))))


if __name__ == "__main__":
    main()
