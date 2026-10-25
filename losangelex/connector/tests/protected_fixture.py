"""Disk-backed protected fixture roots; no product permission behavior changes."""
import os
import subprocess
from pathlib import Path
from lax_connector.collaboration_bridge import protected_directory


def disk_fixture_root():
    root = Path(os.environ.get("LAX_TEST_ROOT", "/var/lib/lax-connector-test-fixtures"))
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    protected_directory(root)
    filesystem = subprocess.check_output(["stat", "-f", "-c", "%T", str(root)], text=True).strip()
    if filesystem in ("tmpfs", "ramfs"):
        raise ValueError("Disk-backed fixture root required")
    return str(root)
