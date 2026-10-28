"""Actual live kernel/service observation with explicit CLI fault injection.

Reads one provided current executor/installation. No model/native call, service
mutation, canonical write or fake provider is involved. Authenticated native
continuation must be qualified separately after a guarded deployment.
"""
import argparse
import copy
import json
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

from lax_connector import purpose_observer, service_observer
from lax_connector.kernel_incarnation import guardian, invocation


def main(fixture, output):
    data = json.loads(fixture.read_text())
    value, config, row = data["installation"], data["controller"], data["executor"]
    d = row["descriptor"]
    binding = service_observer.protected(Path(value["config"]).parent.parent /
                                        "incarnations" / (d["serviceInvocation"] + ".json"))
    checks = []
    assert invocation(binding["unit"]) == binding["serviceInvocation"]
    actual = guardian(value, binding)
    assert (actual["pid"], actual["start"], actual["uid"], actual["controlGroup"]) == (
        binding["guardianPid"], binding["guardianStart"], binding["uid"], binding["controlGroup"])
    checks.append("Actual current manager export/trusted cgroup ID/guardian image+launch+membership agree")
    start = time.monotonic()
    with patch.object(service_observer, "properties",
                      side_effect=subprocess.TimeoutExpired(["systemctl", "show"], 15)) as unavailable:
        fact = purpose_observer.observe(config, row)
        assert fact["state"] == "live"
        assert fact["evidence"]["serviceBindingDigest"] == service_observer.digest(binding)
        unavailable.assert_not_called()
    elapsed = time.monotonic() - start
    checks.append("Actual positive native/guardian kernel observation succeeds without any CLI call under injected CLI outage")

    def rejects_binding(name, key, changed):
        broken = copy.deepcopy(binding)
        broken[key] = changed
        try:
            guardian(value, broken)
        except (PermissionError, RuntimeError):
            checks.append(name)
        else:
            raise AssertionError("Broken live binding accepted: " + name)

    rejects_binding("Old/wrong invocation rejected", "serviceInvocation", "0" * 32)
    rejects_binding("Wrong boot rejected", "bootId", "00000000-0000-0000-0000-000000000000")
    rejects_binding("Wrong registered UID rejected", "uid", binding["uid"] + 1)
    rejects_binding("Wrong guardian PID rejected", "guardianPid", 1)
    rejects_binding("Reused/wrong guardian birth rejected", "guardianStart", binding["guardianStart"] + "1")
    rejects_binding("Wrong cgroup rejected", "controlGroup", "/system.slice/ssh.service")
    rejects_binding("Changed unit definition rejected", "unitDefinitionDigest", "0" * 64)
    rejects_binding("Wrong purpose/unit rejected", "purpose", "reader" if binding["purpose"] == "writer" else "writer")
    rejects_binding("Wrong enrolled image rejected", "binaryInode", binding["binaryInode"] + 1)
    rejects_binding("Foreign authority rejected", "authorityId", "00000000-0000-0000-0000-000000000000")

    for name, key, changed in [
        ("Guardian cannot impersonate native image", "nativePid", binding["guardianPid"]),
        ("Wrong native birth cannot become live", "nativeStart", d["nativeStart"] + "1"),
        ("Foreign service descriptor cannot become live", "serviceInvocation", "0" * 32),
    ]:
        broken = copy.deepcopy(row)
        broken["descriptor"][key] = changed
        with patch.object(service_observer, "properties",
                          side_effect=subprocess.TimeoutExpired(["systemctl", "show"], 15)):
            try:
                result = purpose_observer.observe(config, broken)
                assert result["state"] != "live", name
            except (PermissionError, RuntimeError, ValueError, subprocess.TimeoutExpired):
                pass
        checks.append(name)
    result = {"at": time.time(), "checks": checks, "passed": len(checks),
              "positiveKernelObserveSeconds": elapsed, "modelCalls": 0, "canonicalWrites": 0,
              "nativeCalls": 0, "serviceMutations": 0,
              "evidenceLevel": "Actual current kernel/process identities; CLI failure explicitly injected. "
                               "Broken bindings are in-memory negative copies. Not native socket/model proof."}
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists()
    main(args.fixture, args.output)
