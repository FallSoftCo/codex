from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path("/home/ai/Development/losangelex")
DEFAULT_CODEX_TARGET_DIR = REPO_ROOT / "codex-rs" / "target" / "losangelex-launcher"
DEFAULT_CODEX = DEFAULT_CODEX_TARGET_DIR / "debug" / "codex"


def ensure_default_codex(codex: Path) -> None:
    if codex != DEFAULT_CODEX:
        return
    subprocess.run(
        [
            "cargo",
            "+stable",
            "build",
            "--target-dir",
            str(DEFAULT_CODEX_TARGET_DIR),
            "-p",
            "codex-cli",
            "--bin",
            "codex",
        ],
        cwd=REPO_ROOT / "codex-rs",
        check=True,
    )
