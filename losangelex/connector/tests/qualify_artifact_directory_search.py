"""Linux installation qualification: actual account artifact reads, no models."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


PROBE = r"""
import hashlib,json,os,sys
from pathlib import Path
from lax_connector.collaboration_resources import open_root
from lax_connector.workflow import artifacts
target,expected,fixture=Path(sys.argv[1]),sys.argv[2],Path(sys.argv[3])
fd=open_root(target.parent)
try:
    child=os.open(target.name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
    with os.fdopen(child,"rb") as f:data=f.read(67108865)
finally:os.close(fd)
assert len(data)<=67108864 and hashlib.sha256(data).hexdigest()==expected
try:
    fd=open_root(fixture/"search-only")
except PermissionError:pass
else:
    os.close(fd);raise AssertionError("Fixture root became enumerable")
fd=open_root(fixture/"search-only",search_only=True)
try:
    evidence=artifacts({"hostId":"00000000-0000-4000-8000-000000000001","workspaceId":"00000000-0000-4000-8000-000000000002"},["project/nested/probe.txt"],root_fd=fd)
    assert len(evidence)==1 and evidence[0]["sha256"]==hashlib.sha256(b"owned-directory-search-probe"+bytes([10])).hexdigest()
finally:os.close(fd)
fd=open_root(fixture/"search-only/project/nested",search_only=True)
try:
    child=os.open("probe.txt",os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
    with os.fdopen(child,"rb") as f:assert f.read()==b"owned-directory-search-probe"+bytes([10])
finally:os.close(fd)
try:
    fd=open_root(fixture/"alias/project")
except OSError:pass
else:
    os.close(fd);raise AssertionError("Intermediate directory link accepted")
print(json.dumps({"uid":os.geteuid(),"artifactSha256":hashlib.sha256(data).hexdigest(),
                 "searchOnlyParentTraversed":True,"searchOnlyRootAndNestedReportPathsHashed":True,"intermediateLinkRefused":True,
                 "projectChanged":False}))
"""


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--artifact", type=Path, required=True)
    p.add_argument("--sha256", required=True)
    p.add_argument("--python", type=Path, required=True)
    p.add_argument("--user", action="append", required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if os.geteuid() != 0 or not hasattr(os, "O_PATH"):
        p.error("Linux installation administrator with O_PATH required")
    if not a.artifact.is_absolute() or not a.python.is_absolute():
        p.error("Explicit absolute artifact and installed interpreter required")
    if len(a.user) > 32 or not a.user:
        p.error("One to32 actual installation accounts required")
    original_hash = hashlib.sha256()
    with a.artifact.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            original_hash.update(block)
    if original_hash.hexdigest() != a.sha256:
        p.error("Original artifact hash changed before qualification")
    with tempfile.TemporaryDirectory(prefix="lax-artifact-search-", dir="/var/tmp") as tmp:
        root = Path(tmp)
        root.chmod(0o755)
        sealed = root / "search-only"
        sealed.mkdir(mode=0o711)
        project = sealed / "project"
        project.mkdir(mode=0o755)
        nested = project / "nested"
        nested.mkdir(mode=0o711)
        f = nested / "probe.txt"
        f.write_bytes(b"owned-directory-search-probe" + bytes([10]))
        f.chmod(0o644)
        (root / "alias").symlink_to(sealed, target_is_directory=True)
        script = root / "probe.py"
        script.write_text(PROBE)
        script.chmod(0o644)
        results = []
        for account in a.user:
            result = subprocess.run(
                ["/usr/sbin/runuser", "-u", account, "--", str(a.python),
                 "-I", "-B", str(script), str(a.artifact), a.sha256, str(root)],
                capture_output=True, text=True, timeout=15, check=True,
            )
            results.append(json.loads(result.stdout))
    receipt = {"state": "passed", "schema": "lax-artifact-directory-search/v1",
               "artifact": str(a.artifact), "accounts": results, "modelsStarted": 0,
               "scope": "Actual installed account reads and link refusal; no report or project write"}
    with a.output.open("x") as stream:
        json.dump(receipt, stream, indent=2)
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
