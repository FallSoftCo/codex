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
from .native_package import preflight_as_owner


def run(*args):
    return subprocess.run(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )


def ensure_supervision(spec, installation, state):
    """Fresh installation wiring; preserve every existing policy and deliberate stop."""
    from .host import request

    agent = installation["credentials"]["Global"]["principalId"]
    token = installation["credentials"]["Owner"]["token"]
    route = "agents/" + agent + "/supervision"
    current = request(spec["hollywoodUrl"], token, "GET", route)["policy"]
    if current is None and spec.get("enablePortfolioSupervision", True):
        payload = {
            "operationId": "installer:global-supervision:" + installation["authorityId"],
            "revision": 0, "roomId": installation["globalRoomId"], "enabled": True,
            "reviewsPerWindow": spec.get("portfolioReviewsPerWindow", 4),
            "windowSeconds": spec.get("portfolioWindowSeconds", 60),
        }
        intent = state / "global-supervision-intent.json"
        if intent.exists() and json.loads(intent.read_text()) != payload:
            raise ValueError("Original Global supervision intent changed")
        if not intent.exists():
            saved(intent, payload)
        try:
            request(spec["hollywoodUrl"], token, "PUT", route, payload)
        except Exception as error:
            from urllib.error import HTTPError
            if isinstance(error, HTTPError) and error.code in (400, 403, 409):
                raise
            # Observe the persisted identity after an uncertain reply; never
            # replay setup or turn on a policy that an operator disabled.
            current = request(spec["hollywoodUrl"], token, "GET", route)["policy"]
            if current is None:
                raise RuntimeError("Original Global supervision setup remains unconfirmed") from None
            if (current["room"], current["enabled"], current["reviews_per_window"],
                    current["window_seconds"]) != (
                    payload["roomId"], True, payload["reviewsPerWindow"], payload["windowSeconds"]):
                raise RuntimeError("Global supervision changed; explicit reconciliation required") from None
        current = request(spec["hollywoodUrl"], token, "GET", route)["policy"]
        preserved = False
    else:
        preserved = current is not None
    result = {
        "enabled": bool(current and current["enabled"]),
        "revision": current["revision"] if current else None,
        "activationSequence": current["activation_seq"] if current else None,
        "preservedExistingPolicy": preserved,
        "historicalWorkResumed": False, "modelOrServiceStarted": False,
        "semantics": "Only new typed material after activation can admit a deduplicated review. Passive chat and unchanged observations create no work.",
    }
    saved(state / "global-supervision-receipt.json", result)
    return result


def provision(spec):
    if os.geteuid() != 0 or platform.system() != "Linux":
        raise PermissionError("A verified Linux administrator must perform bootstrap")
    installation = json.loads(Path(spec["installationIntent"]).read_text())
    identity = str(UUID(installation["authorityId"]))
    if spec.get("environmentProfileFile"):
        from .environment import install
        install(identity,spec["environmentProfileFile"])
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
    accepted = state / "global-admin-receipt.json"
    if accepted.exists():
        receipt = json.loads(accepted.read_text())
        account = pwd.getpwnam(receipt["linuxUser"])
        if (
            receipt["authorityId"] != identity
            or account.pw_uid != receipt["uid"]
            or account.pw_dir != receipt["home"]
        ):
            raise ValueError("Existing Global installation identity changed")
        package = preflight_as_owner(spec["binary"], spec["interpreter"], account.pw_uid, Path(receipt["home"]))
        return {**receipt, "reconciled": True, "modelOrServiceRestarted": False,
                "nativePackage": package}
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
    package = preflight_as_owner(binary, interpreter, account.pw_uid, home)
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
    unit = "lax-global-" + slug + ".service"
    unit_file = Path("/etc/systemd/system") / unit
    content = f"""[Unit]
Description=LAX Hollywood Global {identity}
After=network-online.target
StartLimitIntervalSec=60
StartLimitBurst=3
[Service]
Type=simple
User={user}
WorkingDirectory={home / "work"}
ExecStart={interpreter} -m lax_connector.connector --config {config_file} --serve
Restart=on-failure
RestartSec=10
UMask=0077
MemoryMax=4G
CPUQuota=200%
KillMode=control-group
TimeoutStopSec=30
[Install]
WantedBy=multi-user.target
"""
    if unit_file.exists() and unit_file.read_text() != content:
        raise ValueError(
            "Existing Global service differs; explicit drain/upgrade required"
        )
    if not unit_file.exists():
        unit_file.write_text(content)
        unit_file.chmod(0o644)
        run("systemctl", "daemon-reload")
    supervision = ensure_supervision(spec, installation, state)
    receipt = {
        "portfolioSupervision": supervision,
        "authorityId": identity,
        "agentId": config["agentId"],
        "linuxUser": user,
        "uid": account.pw_uid,
        "home": str(home),
        "connectorConfig": str(config_file),
        "unit": unit,
        "serviceInstalled": True,
        "serviceStarted": False,
        "sudoVerifiedUid": 0,
        "workerPrivilegesChanged": False,
        "modelAccountProved": False,
        "nativePackage": package,
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
