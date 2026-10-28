"""Declared controller code and actual effective-service verification.

This is installation/admission validation, not an edit-callback dependency.
Existing undeclared installations retain their original lifecycle contract.
"""
import hashlib
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

from .service_observer import process


def declaration(interpreter, config, unit):
    if not re.fullmatch(r"lax-[A-Za-z0-9_.@:-]+\.service", unit):
        raise ValueError("Explicit installed controller service required")
    return {"schema": "lax-controller-runtime/v1", "unit": unit,
            "interpreter": str(interpreter), "pythonRoot": str(Path(interpreter).parent.parent),
            "module": "lax_connector.host", "config": str(config),
            "arguments": ["-I", "-B", "-m", "lax_connector.host", "--serve", str(config)]}


def checked(value):
    if (not isinstance(value, dict) or set(value) !=
            {"schema", "unit", "interpreter", "pythonRoot", "module", "config", "arguments"}
            or value != declaration(value["interpreter"], value["config"], value["unit"])
            or not Path(value["pythonRoot"]).is_absolute()):
        raise PermissionError("Declared controller runtime changed")
    return [value["interpreter"], *value["arguments"]]


def validate_self(config, path, module_path):
    bridge_path = config.get("nativeCollaborationCaptureConfig")
    if not bridge_path:
        return
    from .service_observer import protected
    expected = protected(Path(bridge_path)).get("controllerRuntime")
    if expected is None:
        return
    command = checked(expected)
    actual = Path("/proc/self/cmdline").read_bytes().rstrip(b"\0").decode().split("\0")
    root = Path(expected["pythonRoot"])
    if (Path(path) != Path(expected["config"]) or actual != command
            or Path(sys.prefix) != root or not Path(module_path).is_relative_to(root)):
        raise PermissionError("Actual controller code/launcher differs from declared runtime")


def observe(value):
    command = checked(value)
    result = subprocess.run(
        ["systemctl", "show", value["unit"], "--no-pager", "-p", "MainPID",
         "-p", "ActiveState", "-p", "User", "-p", "FragmentPath", "-p", "DropInPaths"],
        check=True, capture_output=True, text=True, timeout=15)
    info = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    actual = process(int(info["MainPID"]))
    image = Path(value["interpreter"]).resolve(strict=True).stat()
    if (info["ActiveState"] != "active" or info["User"] not in ("root", "0", "")
            or actual is None or actual["uid"] != 0
            or (actual["executableDevice"], actual["executableInode"]) != (image.st_dev, image.st_ino)):
        raise PermissionError("Declared root controller is not the live service")
    args = Path("/proc", str(actual["pid"]), "cmdline").read_bytes().rstrip(b"\0").decode().split("\0")
    if args != command:
        raise PermissionError("Effective controller command differs from reviewed runtime; inspect unit overrides")
    files = {}
    for name in [info["FragmentPath"], *info.get("DropInPaths", "").split()]:
        path = Path(name)
        if not path.is_absolute() or any(c.isspace() or c == "\\" for c in name):
            raise PermissionError("Controller unit path cannot be verified exactly")
        entry = path.lstat()
        if not stat.S_ISREG(entry.st_mode) or entry.st_uid != 0 or entry.st_mode & 0o022:
            raise PermissionError("Effective controller definition is not protected")
        files[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    if process(actual["pid"]) != actual:
        raise PermissionError("Controller incarnation changed during verification")
    return {"declaration": value, "actualProcess": actual, "dependencyFiles": files}
