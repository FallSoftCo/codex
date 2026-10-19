"""Explicit systemd boot membership for one installed native Global.

This is installation metadata, not another scheduler. Default reconciliation
preserves the operator's enabled/disabled state and starts no service.
"""
import os
import re
import subprocess
from pathlib import Path
from uuid import uuid4

from .journal import saved
from .purpose_install import checksum, file_once, original, protected

SCHEMA = "lax-native-startup/v1"
UNIT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.@:-]{0,180}\.service")


def snapshot(record):
    unit = record["unit"]
    current = subprocess.run(["systemctl", "is-enabled", unit],
                             capture_output=True, text=True)
    state = current.stdout.strip()
    if state not in ("enabled", "disabled"):
        raise ValueError("Native startup target is masked or has an unexpected enablement state")
    return {**record, "bootState": state, "servicesStarted": False,
            "modelSubmissionByInstaller": False}


def prepare(root, manifest, infrastructure, dependencies=None):
    if os.geteuid() != 0:
        raise PermissionError("Installation administrator required")
    path = root / "startup.json"
    previous = protected(path) if path.exists() else None
    if dependencies is None:
        dependencies = previous["additionalServices"] if previous else []
    dependencies = sorted(set(dependencies))
    native = sorted(set(manifest["units"].values()) |
                    {item["unit"] for item in infrastructure})
    members = sorted(set(native + dependencies))
    for name in members:
        if not isinstance(name, str) or not UNIT.fullmatch(name):
            raise ValueError("Literal installed systemd service names required")
        loaded = subprocess.check_output(
            ["systemctl", "show", name, "-p", "LoadState", "--value"], text=True).strip()
        if loaded != "loaded":
            raise ValueError("Native startup member is not an installed service: " + name)
    authority = manifest["authorityId"].replace("-", "")[:8]
    agent = manifest["agentId"].replace("-", "")[:8]
    unit = "lax-native-" + authority + "-" + agent + ".target"
    definition = ("[Unit]\nDescription=LAX native startup for " + manifest["agentId"]
                  + "\nWants=" + " ".join(members)
                  + "\nAfter=network-online.target\n"
                  + "[Install]\nWantedBy=multi-user.target\n")
    target = Path("/etc/systemd/system") / unit
    record = {"schema": SCHEMA, "authorityId": manifest["authorityId"],
              "agentId": manifest["agentId"], "unit": unit,
              "definition": str(target), "nativeServices": native,
              "additionalServices": dependencies, "members": members}
    # An unchanged installation cannot silently enroll another service at boot.
    original(root / "startup-intent.json", record)
    existed = target.exists()
    file_once(target, definition)
    sealed = {**record, "definitionSha256": checksum(target)}
    original(path, sealed)
    if not existed:
        subprocess.run(["systemctl", "daemon-reload"], check=True, capture_output=True)
    return snapshot(sealed)


def set_enabled(root, record, enabled):
    target = Path(record["definition"])
    if (target.is_symlink() or target.stat().st_uid != 0
            or target.stat().st_mode & 0o022
            or checksum(target) != record["definitionSha256"]):
        raise PermissionError("Native startup definition changed")
    before = snapshot(record)
    pids = {unit: subprocess.check_output(
        ["systemctl", "show", unit, "-p", "MainPID", "--value"], text=True).strip()
        for unit in record["members"]}
    # Never --now: boot policy and current execution are separate operator actions.
    subprocess.run(["systemctl", "enable" if enabled else "disable", record["unit"]],
                   check=True, capture_output=True)
    after = snapshot(record)
    if after["bootState"] != ("enabled" if enabled else "disabled"):
        raise RuntimeError("Native startup enablement is unconfirmed; inspect the same target")
    changed = {unit: subprocess.check_output(
        ["systemctl", "show", unit, "-p", "MainPID", "--value"], text=True).strip()
        for unit in record["members"]}
    if changed != pids:
        raise RuntimeError("Service state changed concurrently; inspect actual work before any lifecycle action")
    saved(root / ("startup-control-" + str(uuid4()) + ".json"),
          {"schema": SCHEMA, "unit": record["unit"], "before": before["bootState"],
           "after": after["bootState"], "requestedEnabled": enabled,
           "memberPidsUnchanged": True, "servicesStarted": False})
    return after
