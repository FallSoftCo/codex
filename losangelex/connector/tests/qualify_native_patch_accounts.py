"""Linux integration check for native patching by two actual Unix accounts.

Run explicitly as root with an empty owned output directory and an actual
candidate codex binary. No model, account transport, service or Goal is started.
The same shared temp directory and an inaccessible legacy lock directory
reproduce the captured multi-account deployment failure.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--first-user", required=True)
    parser.add_argument("--second-user", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    assert os.geteuid() == 0, "Explicit root-run Linux qualification only"
    users = [pwd.getpwnam(n) for n in (args.first_user, args.second_user)]
    assert len({u.pw_uid for u in users}) == 2 and all(u.pw_uid > 0 for u in users)
    assert args.binary.is_file() and args.binary.is_absolute()
    out = args.output
    assert out.is_absolute() and not out.exists(), "Fresh owned output required; never replay a probe"
    out.mkdir(mode=0o711)
    temp, work = out / "shared-temp", out / "workspace"
    temp.mkdir(mode=0o1777)
    temp.chmod(0o1777)
    work.mkdir(mode=0o700)
    subprocess.run(["setfacl", "-m", ",".join(f"u:{u.pw_uid}:rwx" for u in users), str(work)],
                   check=True)
    legacy = temp / "codex-apply-patch-locks"
    legacy.mkdir(mode=0o700)
    os.chown(legacy, users[0].pw_uid, users[0].pw_gid)
    before = legacy.stat()
    receipt = {"schema": "native-unix-patch-lock-qualification/v1",
               "binarySha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
               "users": [u.pw_uid for u in users], "effects": [], "modelsStarted": 0,
               "scope": "local native patch/lock primitive; not cross-account collaboration proof"}
    (out / "intent.json").write_text(json.dumps(receipt, indent=2))
    for index, user in enumerate(users):
        path = work / f"account-{index}.txt"
        text = f"native patch from independent account {user.pw_uid}"
        patch = f"*** Begin Patch\n*** Add File: {path}\n+{text}\n*** End Patch"
        command = ["runuser", "-u", user.pw_name, "--", str(args.binary),
                   "--codex-run-as-apply-patch", patch]
        env = {**os.environ, "HOME": user.pw_dir, "TMPDIR": str(temp)}
        result = subprocess.run(command, env=env, cwd=work, capture_output=True, text=True,
                                timeout=30)
        entry = {"uid": user.pw_uid, "returncode": result.returncode,
                 "stdout": result.stdout, "stderr": result.stderr, "path": str(path)}
        receipt["effects"].append(entry)
        (out / "observed.json").write_text(json.dumps(receipt, indent=2))
        assert result.returncode == 0, entry
        assert path.read_text() == text + "\n"
        lock_root = temp / f"codex-apply-patch-locks-v2-{user.pw_uid}"
        info = lock_root.lstat()
        assert stat.S_ISDIR(info.st_mode) and info.st_uid == user.pw_uid
        assert stat.S_IMODE(info.st_mode) == 0o700
    # A tampered per-account lock root is an explicit refusal, not a fallback.
    victim = users[0]
    victim_root = temp / f"codex-apply-patch-locks-v2-{victim.pw_uid}"
    os.chown(victim_root, users[1].pw_uid, users[1].pw_gid)
    target = work / "must-not-exist.txt"
    patch = f"*** Begin Patch\n*** Add File: {target}\n+refused\n*** End Patch"
    result = subprocess.run(
        ["runuser", "-u", victim.pw_name, "--", str(args.binary),
         "--codex-run-as-apply-patch", patch],
        env={**os.environ, "HOME": victim.pw_dir, "TMPDIR": str(temp)}, cwd=work,
        capture_output=True, text=True, timeout=30)
    receipt["tamperedRootRefusal"] = {"returncode": result.returncode, "stderr": result.stderr}
    (out / "observed.json").write_text(json.dumps(receipt, indent=2))
    assert result.returncode != 0 and not target.exists()
    assert "private owned nonsymlink apply_patch lock root required" in result.stderr
    after = legacy.stat()
    assert (before.st_ino, before.st_uid, before.st_mode) == (
        after.st_ino, after.st_uid, after.st_mode)
    receipt.update(state="passed", originalLegacyLockRootPreserved=True)
    (out / "passed.json").write_text(json.dumps(receipt, indent=2))
    print(json.dumps({"state": "passed", "actualUnixAccounts": 2, "nativePatches": 2,
                      "modelsStarted": 0}))


if __name__ == "__main__":
    main()
