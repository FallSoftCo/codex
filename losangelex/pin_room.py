"""Install immutable room packages and a Linux user service; never restart active work."""

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def install_package(source, name, extras, destination):
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=source, text=True
    ).strip()
    epoch = subprocess.check_output(
        ["git", "show", "-s", "--format=%ct", "HEAD"], cwd=source, text=True
    ).strip()
    with tempfile.TemporaryDirectory(prefix="losangelex-package-") as temporary:
        staging = Path(temporary)
        subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", str(staging)],
            cwd=source,
            env=dict(os.environ, SOURCE_DATE_EPOCH=epoch),
            check=True,
        )
        requirements = staging / "requirements.txt"
        export = [
            "uv",
            "export",
            "--locked",
            "--no-dev",
            "--no-emit-project",
            "--no-header",
            "--format",
            "requirements-txt",
            "--output-file",
            str(requirements),
        ]
        for extra in extras:
            export.extend(["--extra", extra])
        subprocess.run(export, cwd=source, check=True, stdout=subprocess.DEVNULL)
        wheel = next(staging.glob("*.whl"))
        digest = hashlib.sha256(
            wheel.read_bytes() + requirements.read_bytes()
        ).hexdigest()
        release = destination / name / digest
        if not (release / "receipt.json").exists():
            release.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["uv", "venv", "--python", "3.11.15", str(release / "venv")], check=True
            )
            interpreter = release / "venv/bin/python"
            subprocess.run(
                [
                    "uv",
                    "pip",
                    "sync",
                    "--python",
                    str(interpreter),
                    "--require-hashes",
                    str(requirements),
                ],
                check=True,
            )
            subprocess.run(
                [
                    "uv",
                    "pip",
                    "install",
                    "--python",
                    str(interpreter),
                    "--no-deps",
                    str(wheel),
                ],
                check=True,
            )
            shutil.copy2(wheel, release / wheel.name)
            shutil.copy2(requirements, release / "requirements.txt")
            receipt = {
                "sourceCommit": commit,
                "wheelSha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
                "requirementsSha256": hashlib.sha256(
                    requirements.read_bytes()
                ).hexdigest(),
                "python": "3.11.15",
                "package": name,
            }
            (release / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        return release


def systemd_argument(value):
    value = str(value)
    if any(ord(char) < 32 for char in value):
        raise ValueError("Control characters are not allowed in service paths")
    return (
        '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hollywood-source", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--codex", type=Path, required=True)
    parser.add_argument(
        "--auth-file", type=Path, default=Path.home() / ".codex/auth.json"
    )
    parser.add_argument(
        "--state", type=Path, default=Path.home() / ".local/state/hollywood-room"
    )
    parser.add_argument("--firebase-credentials", type=Path)
    parser.add_argument("--firebase-project")
    parser.add_argument("--model", default="gpt-6-astra")
    parser.add_argument("--port", type=int, default=18766)
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error(
            "This installer configures a Linux user service; use the package CLIs on other hosts"
        )
    for path in (args.codex, args.auth_file):
        if not path.is_file():
            parser.error(f"Required installed file is missing: {path}")
    if args.firebase_credentials and not args.firebase_credentials.is_file():
        parser.error("Firebase credential file is missing")
    if args.firebase_credentials and not args.firebase_project:
        parser.error("--firebase-project is required with --firebase-credentials")
    subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=args.workspace,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    base = Path.home() / ".local/share/losangelex/room-releases"
    backend = install_package(
        args.hollywood_source.resolve(), "hollywood", ["room", "push"], base
    )
    client = install_package(
        Path(__file__).resolve().parent / "room-client", "client", [], base
    )
    state = args.state.resolve()
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    state.chmod(0o700)
    runtime_home = state / "codex-home"
    runtime_home.mkdir(mode=0o700, exist_ok=True)
    auth_link = runtime_home / "auth.json"
    # The same sign-in remains in its original location. No credential values are copied.
    if not auth_link.exists() and not auth_link.is_symlink():
        auth_link.symlink_to(args.auth_file.resolve())
    elif auth_link.resolve() != args.auth_file.resolve():
        parser.error(
            "Runtime auth already points elsewhere; select a separate state directory"
        )
    config = runtime_home / "config.toml"
    if not config.exists():
        config.write_text('cli_auth_credentials_store = "file"\n')
        config.chmod(0o600)
    # User skills and rules remain available without sharing runtime databases.
    for name in ("skills", "rules"):
        source = args.auth_file.parent / name
        target = runtime_home / name
        if source.is_dir() and not target.exists():
            target.symlink_to(source.resolve(), target_is_directory=True)
    argv = [
        str(backend / "venv/bin/hollywood-room"),
        "--state",
        str(state),
        "--workspace",
        str(args.workspace.resolve()),
        "--codex",
        str(args.codex.resolve()),
        "--codex-home",
        str(runtime_home),
        "--model",
        args.model,
        "--port",
        str(args.port),
    ]
    if args.firebase_credentials:
        argv.extend(
            [
                "--firebase-credentials",
                str(args.firebase_credentials.resolve()),
                "--firebase-project",
                args.firebase_project,
            ]
        )
    unit = Path.home() / ".config/systemd/user/hollywood-room.service"
    unit.parent.mkdir(parents=True, exist_ok=True)
    active = (
        subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", unit.name], check=False
        ).returncode
        == 0
    )
    unit.write_text(
        "[Unit]\nDescription=Hollywood shared team room\nAfter=network-online.target\n\n"
        "[Service]\nType=simple\nUMask=0077\n"
        "Environment=PYTHONDONTWRITEBYTECODE=1\n"
        "ExecStart=" + " ".join(map(systemd_argument, argv)) + "\n"
        "Restart=on-failure\nRestartSec=5\nTimeoutStopSec=30\n\n"
        "[Install]\nWantedBy=default.target\n"
    )
    launcher = Path.home() / ".local/bin/losangelex-room"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    client_argv = [
        str(client / "venv/bin/losangelex-room"),
        "--url",
        f"http://127.0.0.1:{args.port}",
        "--token-file",
        str(state / "client-token"),
    ]
    temporary = launcher.with_suffix(".new")
    temporary.write_text("#!/bin/sh\nexec " + shlex.join(client_argv) + ' "$@"\n')
    temporary.chmod(0o755)
    temporary.replace(launcher)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    if not active:
        subprocess.run(
            ["systemctl", "--user", "enable", "--now", unit.name], check=True
        )
    print(
        json.dumps(
            {
                "backend": str(backend),
                "client": str(client),
                "state": str(state),
                "existingRuntimeKeptRunning": active,
                "launch": "losangelex-room",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
