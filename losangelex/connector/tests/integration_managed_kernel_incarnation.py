"""Read-only real managed guardian verification during injected systemctl outage.

No native turn, admission, service mutation or canonical write is performed.
"""
import argparse
import copy
import json
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

from lax_connector import service_observer as observer
from lax_connector import service_restart
from lax_connector.kernel_incarnation import invocation, managed_guardian


def main(authority, host, agent, unit, output):
    root = observer.directory(authority, host, agent)
    binding = observer.protected(root / (invocation(unit) + ".json"))
    started = time.monotonic()
    with patch.object(observer, "properties", side_effect=subprocess.TimeoutExpired("systemctl", 15)) as unavailable:
        actual = managed_guardian(binding)
        unavailable.assert_not_called()
    elapsed = time.monotonic() - started
    assert (actual["pid"], actual["start"], actual["uid"], actual["controlGroup"]) == (
        binding["guardianPid"], binding["guardianStart"], binding["uid"], binding["controlGroup"])
    # Exercise the actual host-tick entry point, not just its kernel primitive.
    # The existing registry lock must already exist: no test enrollment or
    # receipt creation is allowed in the installed registry.
    assert (root / "registry.lock").is_file(), "Existing registry lock required"
    originals = {name: (root / name).read_bytes() for name in
                 ("enrollment.json", service_restart.POLICY, binding["serviceInvocation"] + ".json")}
    started = time.monotonic()
    with patch.object(observer, "properties", side_effect=subprocess.TimeoutExpired("systemctl", 15)) as unavailable:
        tick = service_restart.reconcile_one({"authorityId": authority, "hostId": host,
            "machineIdentity": observer.machine_identity()}, agent, [])
        unavailable.assert_not_called()
    tick_elapsed = time.monotonic() - started
    assert tick == {"state": "registered", "changed": False, "agentId": agent,
                   "observationSource": "kernel-incarnation", "managerStateInspected": False}
    assert all((root / name).read_bytes() == data for name, data in originals.items())
    rejected = []
    for key, value in (
        ("serviceInvocation", "0" * 32), ("bootId", "00000000-0000-0000-0000-000000000000"),
        ("uid", binding["uid"] + 1), ("guardianPid", 1),
        ("guardianStart", binding["guardianStart"] + "1"),
        ("controlGroup", "/system.slice/ssh.service"), ("unitDefinitionDigest", "0" * 64),
        ("binaryInode", binding["binaryInode"] + 1),
    ):
        broken = copy.deepcopy(binding)
        broken[key] = value
        try:
            managed_guardian(broken)
        except (PermissionError, RuntimeError, ValueError):
            rejected.append(key)
        else:
            raise AssertionError("Altered binding accepted: " + key)
    result = {"guardianPid": actual["pid"], "positiveSeconds": elapsed,
              "hostTickSeconds": tick_elapsed, "hostTick": tick,
              "rejectedAlterations": rejected, "systemctlCalls": 0,
              "modelCalls": 0, "canonicalWrites": 0, "serviceMutations": 0,
              "limitation": "Live guardian only; no running native child or effect admission claimed"}
    with output.open("x") as file:
        json.dump(result, file, indent=2)
        file.write("\n")
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("authority", "host", "agent", "unit"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    main(args.authority, args.host, args.agent, args.unit, args.output)
