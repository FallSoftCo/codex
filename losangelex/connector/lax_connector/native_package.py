"""Preflight the canonical Linux Codex package under its execution identity.

Contract: scripts/codex_package/layout.py, layoutVersion1, codex CLI variant.
This checks package files and bounded no-model startup commands. It does not
prove sandbox/tool execution, model access or an enterprise end-to-end outcome.
"""

import argparse
import hashlib
import json
import os
import platform
import pwd
import stat
import subprocess
from pathlib import Path

SCHEMA = "lax-native-package-preflight/v1"
ASSETS = {
    "entrypoint": ("bin/codex", ["--version"]),
    "codeModeHost": ("bin/codex-code-mode-host", ["--help"]),
    "bubblewrap": ("codex-resources/bwrap", ["--version"]),
    "ripgrep": ("codex-path/rg", ["--version"]),
}


class PackageError(RuntimeError):
    def __init__(self, component, reason):
        self.details = {
            "schema": SCHEMA,
            "ready": False,
            "component": component,
            "reason": reason,
            "modelsStarted": 0,
            "toolExecutionProved": False,
        }
        super().__init__(
            f"Native package preflight failed for {component}: {reason}. "
            "Use scripts/build_codex_package.py and its complete package bin/codex."
        )


def _hash(path):
    value = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def inspect_package(binary, *, expected_uid=None):
    """Run as the actual service UID, never infer access from root's mode bits."""
    uid = os.geteuid()
    if expected_uid is not None and uid != expected_uid:
        raise PackageError("serviceIdentity", "execution UID differs")
    if platform.system() != "Linux":
        raise PackageError("target", "maintained service preflight requires Linux")
    try:
        entrypoint = Path(binary).resolve(strict=True)
    except (OSError, RuntimeError):
        raise PackageError("entrypoint", "missing or inaccessible executable") from None
    root = entrypoint.parent.parent
    manifest = root / "codex-package.json"
    try:
        if manifest.stat().st_size > 16384:
            raise ValueError("metadata budget")
        metadata = json.loads(manifest.read_bytes())
    except (OSError, ValueError):
        raise PackageError(
            "codex-package.json", "missing, inaccessible or invalid metadata"
        ) from None
    required = {
        "layoutVersion": 1,
        "variant": "codex",
        "entrypoint": "bin/codex",
        "resourcesDir": "codex-resources",
        "pathDir": "codex-path",
    }
    if not isinstance(metadata, dict) or any(
        metadata.get(k) != v for k, v in required.items()
    ):
        raise PackageError("codex-package.json", "unsupported canonical CLI layout")
    version = metadata.get("version")
    if not isinstance(version, str) or not version or len(version) > 128:
        raise PackageError("codex-package.json", "invalid package version")
    machine = {"amd64": "x86_64", "arm64": "aarch64"}.get(
        platform.machine().lower(), platform.machine().lower()
    )
    if metadata.get("target") not in {
        machine + "-unknown-linux-gnu",
        machine + "-unknown-linux-musl",
    }:
        raise PackageError("target", "package does not match the service host")
    if entrypoint != root / "bin/codex":
        raise PackageError(
            "entrypoint", "configured executable is not package bin/codex"
        )
    for name in ("bin", "codex-resources", "codex-path"):
        if not (root / name).is_dir():
            raise PackageError(name, "missing or inaccessible package directory")
    assets = {}
    # Validate the complete layout before executing even a version command.
    for label, (relative, _) in ASSETS.items():
        path = root / relative
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise PackageError(
                    relative, "required asset is not a regular package file"
                )
            if not os.access(path, os.R_OK | os.X_OK, effective_ids=True):
                raise PackageError(
                    relative, "required asset is not readable/executable by service UID"
                )
            assets[label] = {
                "path": str(path),
                "size": info.st_size,
                "device": info.st_dev,
                "inode": info.st_ino,
                "sha256": _hash(path),
            }
        except OSError:
            raise PackageError(
                relative, "missing or inaccessible required package asset"
            ) from None
    probes = []
    for label, (_, arguments) in ASSETS.items():
        try:
            result = subprocess.run(
                [assets[label]["path"], *arguments],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise PackageError(
                label, "required asset startup failed or exceeded five seconds"
            ) from None
        if result.returncode != 0:
            raise PackageError(
                label, "required asset startup exited " + str(result.returncode)
            )
        probes.append(
            {
                "asset": label,
                "arguments": arguments,
                "exitCode": 0,
                "outputSha256": hashlib.sha256(
                    result.stdout + result.stderr
                ).hexdigest(),
            }
        )
    return {
        "schema": SCHEMA,
        "ready": True,
        "uid": uid,
        "gid": os.getegid(),
        "binary": str(entrypoint),
        "packageRoot": str(root),
        "metadata": metadata,
        "metadataSha256": _hash(manifest),
        "assets": assets,
        "startupChecks": probes,
        "modelsStarted": 0,
        "toolExecutionProved": False,
        "scope": "Canonical package layout, service-identity access and bounded asset startup only",
    }


def preflight_as_owner(binary, interpreter, uid, home):
    """Administrator installer/readiness call; drop to the recorded service UID."""
    account = pwd.getpwuid(uid)
    if Path(account.pw_dir) != Path(home):
        raise PackageError(
            "serviceIdentity", "registered service home differs from NSS"
        )
    env = dict(
        os.environ,
        HOME=str(home),
        CODEX_HOME=str(Path(home) / "codex-home"),
        PYTHONDONTWRITEBYTECODE="1",
    )
    command = [
        "runuser",
        "-u",
        account.pw_name,
        "--",
        str(interpreter),
        "-I",  # Use installed modules, never the writable work cwd or PYTHONPATH.
        "-m",
        "lax_connector.native_package",
        "--binary",
        str(binary),
        "--expected-uid",
        str(uid),
    ]
    try:
        result = subprocess.run(
            command,
            cwd=Path(home) / "work",
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        value = json.loads(result.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise PackageError(
            "serviceIdentity", "package preflight unavailable under recorded UID"
        ) from None
    if result.returncode != 0:
        if (
            isinstance(value, dict)
            and value.get("schema") == SCHEMA
            and value.get("ready") is False
        ):
            raise PackageError(
                value.get("component", "package"),
                value.get("reason", "preflight failed"),
            )
        raise PackageError(
            "serviceIdentity", "package preflight failed under recorded UID"
        )
    if (
        not isinstance(value, dict)
        or value.get("schema") != SCHEMA
        or value.get("uid") != uid
        or value.get("ready") is not True
    ):
        raise PackageError(
            "serviceIdentity", "package preflight identity/result differs"
        )
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True)
    parser.add_argument("--expected-uid", type=int)
    args = parser.parse_args()
    try:
        result = inspect_package(args.binary, expected_uid=args.expected_uid)
    except PackageError as error:
        print(json.dumps(error.details))
        raise SystemExit(2) from None
    print(json.dumps(result))


if __name__ == "__main__":
    main()
