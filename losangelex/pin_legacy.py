#!/usr/bin/env python3
"""Pin the existing Linux/Bash Losangelex runtime without restarting its sessions.

This is a bridge for the legacy fork. Build new Codex candidates with upstream's
package builder. Release directories are copies, never links into Cargo output.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def atomic_write(path: Path, text: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(text.encode())
            stream.flush()
            os.fsync(stream.fileno())
            temporary.chmod(mode)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def pin(source: Path, binary: Path, store: Path, launcher: Path) -> dict:
    if os.name != "posix":
        raise ValueError("The legacy launcher requires a POSIX system with Bash.")
    source, binary, store = (path.resolve() for path in (source, binary, store))
    launcher = launcher.absolute()
    releases = store / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    inputs = {
        "codex-rs/codex": binary,
        "scripts/losangelex": source / "scripts/losangelex",
        "scripts/losangelex_team.py": source / "scripts/losangelex_team.py",
    }
    with tempfile.TemporaryDirectory(prefix=".stage-", dir=releases) as directory:
        payload = Path(directory) / "payload"
        hashes = {}
        for relative, original in inputs.items():
            before = digest(original)
            target = payload / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target)
            if digest(target) != before or digest(original) != before:
                raise ValueError(f"Source changed during snapshot: {original}")
            target.chmod(0o555)
            hashes[relative] = before
        frozen_launcher = (payload / "scripts/losangelex").read_text()
        if 'repo_root="$(cd "$script_dir/../codex-rs" && pwd)"' not in frozen_launcher:
            raise ValueError("Apply the relocatable launcher fix before pinning.")
        version = subprocess.check_output(
            [str(payload / "codex-rs/codex"), "--version"], text=True, timeout=15
        ).strip()
        release_id = hashlib.sha256(
            json.dumps(hashes, sort_keys=True).encode()
        ).hexdigest()
        release = releases / release_id
        manifest = {
            "release_id": release_id,
            "binary_version": version,
            "binary_source_commit": None,
            "launcher_source": str(source),
            "sha256": hashes,
        }
        (payload / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        if release.exists():
            for relative, expected in hashes.items():
                if digest(release / relative) != expected:
                    raise ValueError(f"Installed release was modified: {release}")
        else:
            payload.rename(release)

    # Resolve the selected release once, before starting either client or server.
    # Later installations affect future invocations only.
    wrapper = f"""#!/usr/bin/env bash
set -euo pipefail
release_dir="$(cd -P {shlex.quote(str(store / "stable"))} && pwd)"
export LOSANGELEX_CODEX_BIN="$release_dir/codex-rs/codex"
export LOSANGELEX_AUTO_BUILD=0
exec bash "$release_dir/scripts/losangelex" "$@"
"""
    if launcher.exists() and launcher.read_text() != wrapper:
        backup = launcher.with_name(
            f"{launcher.name}.before-pin-{digest(launcher)[:12]}"
        )
        if not backup.exists():
            shutil.copy2(launcher, backup)
    with tempfile.TemporaryDirectory(prefix=".select-", dir=store) as directory:
        pointer = Path(directory) / "stable"
        pointer.symlink_to(release, target_is_directory=True)
        os.replace(pointer, store / "stable")
    atomic_write(launcher, wrapper, 0o755)
    return {**manifest, "release_dir": str(release), "launcher": str(launcher)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument(
        "--store", type=Path, default=Path.home() / ".local/share/losangelex"
    )
    parser.add_argument(
        "--launcher", type=Path, default=Path.home() / ".local/bin/losangelex"
    )
    args = parser.parse_args()
    print(
        json.dumps(pin(args.source, args.binary, args.store, args.launcher), indent=2)
    )


if __name__ == "__main__":
    main()
