"""Dynamic canonical access for exact already-running native deliveries."""

import os
from pathlib import Path
from uuid import UUID

from .collaboration_bridge import IMPLEMENTED_PORTS, digest, require
from .collaboration_resources import open_root, verify_native_path
from .journal import saved
from .service_observer import protected


def resources(capture, base, native, *, policy=None, structured=False):
    if structured:
        from .resource_routing import agent_rows

        rows = agent_rows(
            capture.admin_http,
            policy,
            base["authorityId"],
            base["agentId"],
            base["hostId"],
        )
        targets = [
            {
                **row["workspace"],
                "grant_revision": row["grant"]["revision"],
                "grant_state": row["grant"]["state"],
                **{
                    key: row["grant"][key]
                    for key in ("execution_host", "can_read", "can_write")
                },
            }
            for row in rows
        ]
    else:
        value = capture.bridge.http(
            "GET", "collaboration/delivery-targets/" + str(UUID(base["deliveryId"]))
        )
        require(
            value["schema"] == "hollywood-agent-physical-target-registry/v1"
            and str(value["deliveryId"]) == base["deliveryId"]
            and str(value["principalId"]) == base["agentId"]
            and value.get("mayApply") is False,
            "Exact current-agent resource registry required",
        )
        require(
            isinstance(value["targets"], list) and 1 <= len(value["targets"]) <= 32,
            "Bounded explicit canonical agent grants required",
        )
        targets = value["targets"]
    roots, physical = [], set()
    for target in targets:
        if target["state"] != "active" or target["grant_state"] != "active":
            continue
        # Mutation rights remain mandatory at each canonical permit phase too.
        if target["can_read"] is not True or target["can_write"] is not True:
            continue
        require(
            str(target["host"]) == base["hostId"]
            and str(target["execution_host"]) == base["hostId"],
            "Remote shared filesystem is not assumed",
        )
        root_path = Path(target["root_path"])
        require(str(root_path) != "/", "Filesystem-wide namespace is unavailable")
        fd = open_root(str(root_path))
        try:
            info = os.fstat(fd)
        finally:
            os.close(fd)
        environment = digest({"hostId": base["hostId"], "environmentId": "local"})
        require(
            target["environment_sha256"] == environment
            and target["root_identity_sha256"]
            == digest(
                {
                    "hostId": base["hostId"],
                    "environmentSha256": environment,
                    "device": info.st_dev,
                    "inode": info.st_ino,
                }
            ),
            "Canonical root differs from actual local filesystem identity",
        )
        identity = (info.st_dev, info.st_ino)
        require(
            identity not in physical,
            "One physical root cannot acquire multiple namespaces",
        )
        for prior in roots:
            other = Path(prior["root"])
            require(
                not root_path.is_relative_to(other)
                and not other.is_relative_to(root_path),
                "Nested physical roots require their existing shared namespace",
            )
        physical.add(identity)
        root = {
            "hostId": base["hostId"],
            "environmentId": "local",
            "root": str(root_path),
            "device": info.st_dev,
            "inode": info.st_ino,
            "workspaceId": str(UUID(target["id"])),
            "registryRevision": target["revision"],
            "agentGrantRevision": target["grant_revision"],
            "defaultForIntent": False,
        }
        verify_native_path(root, "", native["pid"])
        roots.append(root)
    require(roots, "No current canonical writable resource grant")
    # Absolute file URIs do not depend on routing. The current canonical default
    # is resolved separately when relative intent is submitted.
    return sorted(roots, key=lambda root: root["workspaceId"])


def ensure(capture, base, snapshot, row, native, fact, policy, path):
    require(
        policy.get("deliveryEdits") is True
        and policy.get("deliveryEditSchema") == "canonical-delivery-edits/v1",
        "Canonical delivery editing capability unavailable; no legacy fallback",
    )
    event, delivery = snapshot["request"], snapshot["delivery"]
    work_id = event.get("data", {}).get("workId")
    work = None
    if work_id is not None:
        work = capture.admin_http("GET", "work/" + str(UUID(work_id)))["work"]
        require(
            work["owner"] == row["agent"]
            and work["delivery"] == delivery["id"]
            and work["request_event"] == event["id"]
            and work["state"] == "assigned",
            "Current canonical structured assignment required; direct bypass forbidden",
        )
        goal = capture.admin_http("GET", "goals/" + str(UUID(work["goal"])))["goal"]
        require(
            goal["state"] == "active", "Original planned goal does not admit editing"
        )
    roots = resources(capture, base, native, policy=policy, structured=work is not None)
    if work is not None:
        from .collaboration_capture import administrative_put

        grants = capture.bridge.http(
            "GET", "collaboration/physical-targets/" + str(UUID(work_id))
        )
        for root in roots:
            matches = [
                target
                for target in grants["targets"]
                if str(target["id"]) == root["workspaceId"]
            ]
            require(len(matches) <= 1, "Ambiguous original planned resource grant")
            old = matches[0] if matches else None
            if old:
                require(
                    old["state"] == "active"
                    and old["grant_state"] == "active"
                    and old["revision"] == root["registryRevision"],
                    "Planned resource was revoked or changed",
                )
            if old is None or old["work_revision"] != work["revision"]:
                revision = old["grant_revision"] if old else 0
                payload = {
                    "operationId": "capture-grant:"
                    + digest(
                        [root["workspaceId"], work_id, work["revision"], revision]
                    ),
                    "revision": revision,
                    "workspaceRevision": root["registryRevision"],
                    "workRevision": work["revision"],
                    "state": "active",
                }
                administrative_put(
                    capture.state,
                    capture.admin_http,
                    "physical-workspaces/"
                    + root["workspaceId"]
                    + "/grants/"
                    + str(UUID(work_id)),
                    payload,
                )
        fresh = capture.bridge.http(
            "GET", "collaboration/physical-targets/" + str(UUID(work_id))
        )
        require(
            fresh["workRevision"] == work["revision"],
            "Original work revision changed during capture",
        )
        for root in roots:
            matches = [
                target
                for target in fresh["targets"]
                if str(target["id"]) == root["workspaceId"]
            ]
            require(
                len(matches) == 1
                and matches[0]["state"] == "active"
                and matches[0]["grant_state"] == "active"
                and matches[0]["work_revision"] == work["revision"],
                "Fresh original planned grant unavailable",
            )
    record = {
        "schema": "lax-captured-native-channel/v1",
        "sourceBase": base,
        "native": native,
        "executorId": str(row["id"]),
        "descriptorDigest": row["descriptor_digest"],
        "serviceBindingDigest": fact["evidence"]["serviceBindingDigest"],
        "bridgeRevision": policy["bridge"]["revision"],
        "ports": sorted(IMPLEMENTED_PORTS),
        "scope": "plan" if work is not None else "delivery",
        "work": {"id": str(work_id), "revision": work["revision"]}
        if work is not None
        else None,
        "resources": roots,
    }
    if path.exists():
        require(
            protected(path) == record,
            "Original dynamic capture authority changed; no overwrite",
        )
    else:
        if len(list((capture.state / "channels").glob("*.json"))) >= 128:
            capture.archive_closed()
        require(
            len(list((capture.state / "channels").glob("*.json"))) < 256,
            "Unsettled channel bound reached",
        )
        saved(path, record)
    return record
