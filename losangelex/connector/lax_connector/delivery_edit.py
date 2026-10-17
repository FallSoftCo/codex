"""Exact canonical-delivery-edits/v1 adapter on existing native patch callbacks."""

import json
import hashlib
import re
import os
import stat
from pathlib import Path
from uuid import UUID, uuid5

from .collaboration_bridge import canonical_relative, digest, local_uri, require
from .journal import saved
from .service_observer import protected, expected_owner
from .collaboration_resources import open_root

SCHEMA = "canonical-delivery-edits/v1"


def briefing_sequence(record):
    """Use the connector's existing exact-scope briefing watermark, never auto-ack.

    This is local canonical observation evidence, not model comprehension proof
    or protection from the execution UID. A later decision must still pass the
    server's current-source fence. The watermark freezes with the original permit.
    """
    base = record["sourceBase"]
    uid, home, _ = expected_owner(base["authorityId"], base["agentId"])
    fd = open_root(str(Path(home) / "state"))
    try:
        pattern = re.compile(
            r"briefing-" + re.escape(base["deliveryId"]) + r"-([0-9]+)\.json"
        )
        candidates = [
            (int(match.group(1)), name)
            for name in os.listdir(fd)
            if (match := pattern.fullmatch(name))
        ]
        require(
            candidates and len(candidates) <= 128,
            "Bounded original connector briefing evidence required",
        )
        sequence, name = max(candidates)
        handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            before = os.fstat(handle)
            require(
                stat.S_ISREG(before.st_mode)
                and before.st_uid == uid
                and not before.st_mode & 0o022
                and before.st_size <= 1024 * 1024,
                "Original connector briefing owner or bound changed",
            )
            with os.fdopen(os.dup(handle), "rb") as stream:
                data = stream.read(1024 * 1024 + 1)
            after = os.fstat(handle)
            require(
                (
                    before.st_dev,
                    before.st_ino,
                    before.st_size,
                    before.st_mtime_ns,
                    before.st_ctime_ns,
                )
                == (
                    after.st_dev,
                    after.st_ino,
                    after.st_size,
                    after.st_mtime_ns,
                    after.st_ctime_ns,
                )
                and len(data) == before.st_size,
                "Original briefing changed during observation",
            )
            value = json.loads(data)
        finally:
            os.close(handle)
    finally:
        os.close(fd)
    expected = {
        "schema": "lax-work-briefing/v1",
        "authorityId": base["authorityId"],
        "agentId": base["agentId"],
        "deliveryId": base["deliveryId"],
        "generation": base["generation"],
        "claimId": base["claimId"],
    }
    require(
        all(
            value.get(key) == expected_value for key, expected_value in expected.items()
        )
        and type(value.get("asOfSequence")) is int
        and value["asOfSequence"] == sequence,
        "Briefing watermark differs from exact captured execution",
    )
    return sequence


def normalized_envelope(body):
    """Normalize every non-target field before PhysicalTarget.actionDigest.

    Exact exported DeliveryEditCall has no omitted defaults. In particular the
    nullable sourceRevision is required and must remain an explicit JSON null.
    """
    expected = {
        "schema",
        "scope",
        "operationId",
        "bridgeRevision",
        "source",
        "executorId",
        "descriptorDigest",
        "serviceBindingDigest",
        "channel",
        "command",
    }
    require(
        set(body) == expected
        and body["schema"] == SCHEMA
        and body["scope"] == "delivery",
        "Exact delivery edit envelope required",
    )
    value = json.loads(json.dumps(body))
    value["executorId"] = str(UUID(value["executorId"]))
    command = value["command"]
    phase = command["action"]
    common = {
        "action",
        "permitId",
        "briefingSequence",
        "note",
        "sourceRevision",
        "patchSha256",
        "filesObserved",
    }
    additional = {
        "preflight": {"files", "leaseSeconds"},
        "begin": {"permitRevision"},
        "settle": {"permitRevision", "outcome"},
    }
    require(
        phase in additional and set(command) == common | additional[phase],
        "Exact native delivery edit command required",
    )
    command["permitId"] = str(UUID(command["permitId"]))
    require(
        type(command["briefingSequence"]) is int and command["briefingSequence"] >= 0,
        "Captured current briefing sequence required",
    )
    revision = command["sourceRevision"]
    require(
        revision is None
        or isinstance(revision, str)
        and re.fullmatch(r"(?:[a-f0-9]{40}|[a-f0-9]{64})", revision),
        "Explicit nullable source revision required",
    )
    require(
        isinstance(command["note"], str) and 1 <= len(command["note"]) <= 1000,
        "Bounded phase note required",
    )
    require(
        re.fullmatch(r"[a-f0-9]{64}", command["patchSha256"]),
        "Exact patch SHA256 required",
    )
    if phase == "preflight":
        require(
            type(command["leaseSeconds"]) is int and 1 <= command["leaseSeconds"] <= 30,
            "Bounded delivery preflight lease required",
        )
    else:
        require(
            type(command["permitRevision"]) is int and command["permitRevision"] >= 1,
            "Original permit CAS revision required",
        )
    if phase == "settle":
        require(
            command["outcome"] in {"applied", "notApplied", "unknown"},
            "Typed observed outcome required",
        )
    for key in (
        ["filesObserved", "files"] if phase == "preflight" else ["filesObserved"]
    ):
        files = command[key]
        require(
            isinstance(files, list) and 1 <= len(files) <= 8,
            "Bounded complete patch file set required",
        )
        paths = []
        for item in files:
            fields = (
                {"relativePath", "sha256", "size"}
                if key == "filesObserved"
                else {
                    "relativePath",
                    "beforeSha256",
                    "beforeSize",
                    "afterSha256",
                    "afterSize",
                }
            )
            require(set(item) == fields, "Exact native file metadata required")
            relative = canonical_relative(item["relativePath"])
            require(
                len(relative) <= 512,
                "Delivery patch relative path exceeds schema bound",
            )
            paths.append(relative)
            pairs = (
                [("sha256", "size")]
                if key == "filesObserved"
                else [("beforeSha256", "beforeSize"), ("afterSha256", "afterSize")]
            )
            for checksum, size in pairs:
                require(
                    isinstance(item[checksum], str)
                    and re.fullmatch(r"(?:absent|[a-f0-9]{64})", item[checksum])
                    and type(item[size]) is int
                    and 0 <= item[size] <= 16777216
                    and (item[checksum] != "absent" or item[size] == 0),
                    "Exact bounded native file bytes required",
                )
        require(len(set(paths)) == len(paths), "Duplicate physical delivery patch file")
        files.sort(key=lambda item: item["relativePath"])
    return value


def patch(bridge, record, source, frame):
    require(
        record.get("scope") == "delivery" and source["nativeGoalId"] is None,
        "Direct editing requires exact captured delivery scope, never a caller hint",
    )
    root, observed = bridge.resource(record, frame["evidence"])
    files = []
    for item in frame["evidence"]["files"]:
        files.append(
            {
                "relativePath": canonical_relative(
                    local_uri(item["pathUri"]).relative_to(root["root"]).as_posix()
                ),
                **{
                    key: item[key]
                    for key in (
                        "beforeSha256",
                        "beforeSize",
                        "afterSha256",
                        "afterSize",
                    )
                },
            }
        )
    files.sort(key=lambda item: item["relativePath"])
    phase = frame["port"]
    require(
        phase in {"patch-preflight", "patch-begin", "patch-settle"},
        "Typed native patch phase required",
    )
    key = (
        bridge.state
        / "commands"
        / ("permit-" + digest([source["nativeThread"], source["callId"]]) + ".json")
    )
    original = protected(key) if phase != "patch-preflight" else None
    sequence = (
        bridge.briefing_sequence(record)
        if original is None
        else original["briefingSequence"]
    )
    common = {
        "permitId": str(uuid5(UUID(record["executorId"]), source["callId"])),
        "briefingSequence": sequence,
        "note": "Actual protected native delivery patch phase",
        "sourceRevision": None,  # Optional evidence; Git is never base write authority.
        "patchSha256": hashlib.sha256(frame["arguments"].encode()).hexdigest(),
        "filesObserved": observed,
    }
    if phase != "patch-settle":
        require(
            {item["relativePath"]: (item["sha256"], item["size"]) for item in observed}
            == {
                item["relativePath"]: (item["beforeSha256"], item["beforeSize"])
                for item in files
            },
            "Actual file bytes changed from verified native patch baseline",
        )
    paths = [item["relativePath"] for item in observed]
    if phase == "patch-preflight":
        require(
            not key.exists(), "Original delivery patch has a permit or unknown outcome"
        )
        command = {**common, "action": "preflight", "files": files, "leaseSeconds": 15}
        result = bridge.relay(record, source, phase, command, root, paths)
        from .work_delivery import permit_authority

        authority = permit_authority(record, source, result.get("receipt", result))
        saved(
            key,
            {
                "schema": "lax-original-delivery-patch-permit/v1",
                "scope": "delivery",
                "source": source,
                "permitId": common["permitId"],
                "permitRevision": 1,
                "briefingSequence": sequence,
                "patchSha256": common["patchSha256"],
                "files": files,
                "workspaceId": root["workspaceId"],
                "workAuthority": authority,
            },
        )
        return result
    require(
        original["schema"] == "lax-original-delivery-patch-permit/v1"
        and original["scope"] == "delivery"
        and original["source"] == source
        and original["patchSha256"] == common["patchSha256"]
        and original["files"] == files
        and original["workspaceId"] == root["workspaceId"],
        "Original delivery patch source, files or namespace changed",
    )
    command = {
        **common,
        "action": "begin" if phase == "patch-begin" else "settle",
        "permitRevision": original["permitRevision"],
    }
    if phase == "patch-settle":
        command["outcome"] = frame["evidence"]["outcome"]
    result = bridge.relay(record, source, phase, command, root, paths)
    from .work_delivery import permit_authority

    authority = permit_authority(record, source, result.get("receipt", result))
    require(
        authority == original.get("workAuthority"),
        "Original server-derived Work authority changed; retain permit and locks",
    )
    if phase == "patch-begin":
        admission = result.get("admission")
        require(
            result.get("replayed") is False
            and admission
            and admission.get("mayApply") is True
            and admission.get("oneShotOriginalResponseOnly") is True
            and admission.get("permitId") == original["permitId"]
            and admission.get("patchSha256") == common["patchSha256"],
            "Receipt or replay is not an original one-shot delivery mutation grant",
        )
        original["permitRevision"] = admission["permitRevision"]
        saved(key, original)
    if phase == "patch-settle":
        snapshot = bridge.http(
            "GET", "collaboration/delivery-edits/" + original["permitId"]
        )
        require(
            snapshot.get("mayApply") is False, "Permit read must never grant mutation"
        )
        require(
            permit_authority(record, source, snapshot) == original.get("workAuthority"),
            "Original Work permit read differs; retain uncertainty",
        )
        result["settlementState"] = snapshot["effectiveState"]
    return result
