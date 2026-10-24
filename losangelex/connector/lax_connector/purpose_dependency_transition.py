"""Explicit installation dependency transition after an accepted, drained bridge upgrade.

Live readiness remains mandatory. This admin operation reconciles only the two
shared bridge files and revision pinned by a prior seal; agent-owned installation,
identity, private workspace and environment evidence remain unchanged. Current
resource authorization is verified live; it is not frozen by installation.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
from uuid import UUID

from .collaboration_bridge import digest, protected_directory, require
from .journal import saved
from .native_image_upgrade import registry_lock
from .purpose_install import checksum, directory, protected
from .purpose_observer import installation
from .purpose_readiness import verify, require_sealed, sealed_dependencies
from .purpose_upgrade import offline, publish


def approved(before, current, transition, agent, bridge_path, channel_path,
             bridge_digest):
    require(transition["state"] == "accepted"
            and transition["schema"] == "lax-drained-bridge-upgrade/v1",
            "Accepted original bridge transition required")
    require(agent in transition["agents"]
            and all(transition[key] == before[key] == current[key]
                    for key in ("authorityId", "hostId")),
            "Dependency transition belongs to another installation")
    require(set(before) == set(current), "Readiness schema changed; explicit migration required")
    installed_before = sealed_dependencies(before)
    installed_current = sealed_dependencies(current)
    require(all(installed_before[key] == installed_current[key] for key in installed_before
                if key not in ("dependencyFiles", "bridgeRevision")),
            "Agent-owned installation changed")
    original = transition["originalArtifactHashes"]
    allowed = {bridge_path, channel_path}
    require(allowed <= set(original)
            and set(before["dependencyFiles"]) == set(current["dependencyFiles"]),
            "Original bridge dependency paths changed")
    require(all(before["dependencyFiles"][path] == original[path] for path in allowed),
            "Sealed bridge dependencies differ from the original transition")
    require(all(before["dependencyFiles"][path] == current["dependencyFiles"][path]
                for path in before["dependencyFiles"] if path not in allowed),
            "Agent-owned dependency file changed")
    require(before["bridgeRevision"] == transition["expectedBridgeRevision"]
            and current["bridgeRevision"] == transition["canonicalTransition"]["bridge"]["revision"]
            and current["bridgeRevision"] == before["bridgeRevision"] + 1
            and bridge_digest == transition["configurationSha256"],
            "Current canonical bridge differs from the reviewed transition")


def reconcile(authority, agent, operation, expected_readiness_sha256, bridge_receipt):
    require(os.geteuid() == 0, "Installation administrator required")
    authority, agent, operation = str(UUID(authority)), str(UUID(agent)), str(UUID(operation))
    require(len(expected_readiness_sha256) == 64
            and all(c in "0123456789abcdef" for c in expected_readiness_sha256),
            "Exact original readiness SHA256 required")
    record = directory(authority, agent)
    with registry_lock(record):
        value = installation(authority, agent)
        require(value is not None, "Installed purpose agent required")
        config = protected(Path(value["config"]))
        lock = os.open(Path(config["state"]) / "agent.lock", os.O_RDWR | os.O_NOFOLLOW)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            drained = offline(value, config)
            seal = record / "readiness.json"
            require(checksum(seal) == expected_readiness_sha256,
                    "Original readiness CAS changed")
            before = protected(seal)
            receipt_path = Path(bridge_receipt)
            protected_directory(receipt_path.parent)
            transition = protected(receipt_path)
            controller_path = (Path("/var/lib/harness") / authority / "hosts"
                               / value["hostId"] / "controller.json")
            controller = protected(controller_path)
            bridge_path = Path(controller["nativeCollaborationCaptureConfig"])
            bridge = protected(bridge_path)
            state = protected_directory(Path(bridge["collaborationState"]))
            operation_id = transition["operationId"]
            require(len(operation_id) == 64
                    and all(c in "0123456789abcdef" for c in operation_id),
                    "Original bridge operation digest required")
            require(receipt_path == state / "upgrades" / (operation_id + "-accepted.json")
                    and Path(transition["beforeArchive"]) == state / "upgrades" / (operation_id + "-before"),
                    "Original protected bridge receipt required; no copied approval")
            archive = protected_directory(Path(transition["beforeArchive"]))
            channel_path = Path(config["nativeCollaborationChannel"])
            for name, path in (("bridge.json", bridge_path), ("channel.json", channel_path)):
                require(checksum(archive / name) == transition["originalArtifactHashes"][str(path)],
                        "Original bridge archive changed")
            current = verify(value)  # Real live socket/peer/canonical checks; no repair/start.
            approved(before, current, transition, agent, str(bridge_path), str(channel_path), digest(bridge))
            journal = record / ("readiness-reconciliation-" + operation + ".json")
            backup = record / ("readiness-before-" + operation + ".json")
            require(not journal.exists() and not backup.exists(),
                    "Original reconciliation exists; inspect its receipt without repeating")
            new_digest = digest(current)
            intent = {"schema": "lax-purpose-dependency-transition/v1", "state": "intent",
                "operationId": operation, "authorityId": authority, "agentId": agent,
                "bridgeReceipt": str(receipt_path), "bridgeReceiptSha256": checksum(receipt_path),
                "beforeReadinessSha256": expected_readiness_sha256,
                "beforeReadiness": before, "afterReadiness": current,
                "afterSemanticDigest": new_digest, "beforeOffline": drained,
                "servicesStarted": 0, "modelsStarted": 0, "permissionsChanged": False}
            publish(backup, seal.read_bytes(), 0o600, 0)
            require(checksum(backup) == expected_readiness_sha256, "Original seal backup changed")
            saved(journal, intent)
            require(checksum(seal) == expected_readiness_sha256
                    and offline(value, config) == drained
                    and checksum(receipt_path) == intent["bridgeReceiptSha256"],
                    "Original dependency transition changed before publication")
            refreshed = verify(value)
            approved(before, refreshed, transition, agent, str(bridge_path), str(channel_path),
                     digest(protected(bridge_path)))
            require(refreshed == current, "Current readiness changed before publication")
            saved(seal, current)
            require(require_sealed(value) == current
                    and offline(value, config) == drained,
                    "Original dependency transition requires receipt reconciliation")
            accepted = {**intent, "state": "accepted",
                "acceptedReadinessSha256": checksum(seal), "originalSealRetained": str(backup),
                "installationIdentityAndHistoryPreserved": True}
            saved(journal, accepted)
            return {key: accepted[key] for key in (
                "schema", "state", "operationId", "authorityId", "agentId",
                "acceptedReadinessSha256", "originalSealRetained", "servicesStarted",
                "modelsStarted", "permissionsChanged", "installationIdentityAndHistoryPreserved")}
        finally:
            os.close(lock)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--authority", required=True)
    p.add_argument("--agent", required=True)
    p.add_argument("--operation", required=True)
    p.add_argument("--status", action="store_true")
    p.add_argument("--expected-readiness-sha256")
    p.add_argument("--bridge-receipt")
    a = p.parse_args()
    if a.status:
        require(os.geteuid() == 0, "Installation administrator required")
        path = directory(str(UUID(a.authority)), str(UUID(a.agent))) / (
            "readiness-reconciliation-" + str(UUID(a.operation)) + ".json")
        value = protected(path)
        print(json.dumps({k: value.get(k) for k in (
            "schema", "state", "operationId", "authorityId", "agentId",
            "beforeReadinessSha256", "acceptedReadinessSha256", "modelsStarted")}))
    else:
        if not a.expected_readiness_sha256 or not a.bridge_receipt:
            p.error("--expected-readiness-sha256 and --bridge-receipt required")
        print(json.dumps(reconcile(a.authority, a.agent, a.operation,
                                   a.expected_readiness_sha256, a.bridge_receipt)))

if __name__ == "__main__":
    main()
