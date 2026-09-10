import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from pin_legacy import pin


@unittest.skipUnless(os.name == "posix", "The legacy runtime requires Bash")
class PinLegacyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        (self.source / "scripts").mkdir(parents=True)
        (self.source / "codex-rs").mkdir()
        (self.source / "scripts/losangelex_team.py").write_text("# team launcher\n")
        (self.source / "scripts/losangelex").write_text("""#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../codex-rs" && pwd)"
[[ "$LOSANGELEX_AUTO_BUILD" == 0 ]]
exec "$LOSANGELEX_CODEX_BIN" "$@"
""")
        self.binary = self.root / "build/codex"
        self.binary.parent.mkdir()
        self.write_binary("v1")
        self.store = self.root / "runtime with spaces"
        self.launcher = self.root / "bin/losangelex"

    def write_binary(self, version):
        self.binary.write_text(f'''#!/usr/bin/env python3
import json
import sys
if sys.argv[1:] == ["--version"]:
    print("{version}")
elif sys.argv[1:] == ["wait"]:
    print("ready", flush=True)
    input()
    print("{version}", flush=True)
else:
    print(json.dumps(["{version}", *sys.argv[1:]]))
''')
        self.binary.chmod(0o755)

    def test_launch_survives_source_and_build_removal(self):
        installed = pin(self.source, self.binary, self.store, self.launcher)
        shutil.rmtree(self.source)
        shutil.rmtree(self.binary.parent)
        result = subprocess.check_output(
            [str(self.launcher), "argument with spaces", "$(false)"], text=True
        )
        self.assertEqual(json.loads(result), ["v1", "argument with spaces", "$(false)"])
        manifest = json.loads(
            (Path(installed["release_dir"]) / "manifest.json").read_text()
        )
        self.assertEqual(
            manifest,
            {
                k: v
                for k, v in installed.items()
                if k not in {"release_dir", "launcher"}
            },
        )

    def test_selecting_new_release_preserves_running_process(self):
        first = pin(self.source, self.binary, self.store, self.launcher)
        with subprocess.Popen(
            [str(self.launcher), "wait"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        ) as process:
            self.assertEqual(process.stdout.readline().strip(), "ready")
            self.write_binary("v2")
            second = pin(self.source, self.binary, self.store, self.launcher)
            output, _ = process.communicate("continue\n", timeout=10)
        self.assertEqual(output.strip(), "v1")
        self.assertEqual(
            subprocess.check_output(
                [str(self.launcher), "--version"], text=True
            ).strip(),
            "v2",
        )
        self.assertNotEqual(first["release_id"], second["release_id"])
        self.assertTrue(Path(first["release_dir"]).is_dir())

    def test_failed_snapshot_keeps_selection(self):
        installed = pin(self.source, self.binary, self.store, self.launcher)
        self.binary.write_text("#!/bin/sh\nexit 1\n")
        with self.assertRaises(subprocess.CalledProcessError):
            pin(self.source, self.binary, self.store, self.launcher)
        self.assertEqual(
            (self.store / "stable").resolve(), Path(installed["release_dir"])
        )
        self.assertEqual(
            subprocess.check_output(
                [str(self.launcher), "--version"], text=True
            ).strip(),
            "v1",
        )

    def test_existing_wrapper_is_backed_up_and_install_is_idempotent(self):
        self.launcher.parent.mkdir()
        self.launcher.write_text("#!/bin/sh\necho previous\n")
        first = pin(self.source, self.binary, self.store, self.launcher)
        second = pin(self.source, self.binary, self.store, self.launcher)
        self.assertEqual(first, second)
        backups = list(self.launcher.parent.glob("losangelex.before-pin-*"))
        self.assertEqual(
            [path.read_text() for path in backups], ["#!/bin/sh\necho previous\n"]
        )


if __name__ == "__main__":
    unittest.main()
