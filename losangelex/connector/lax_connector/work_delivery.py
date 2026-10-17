"""Consume server-derived business Work authority without inventing file plans."""

import re
from uuid import UUID

from .collaboration_bridge import digest, require
from .service_observer import protected

POLICY = "canonical-work-delivery-edits/v1"


def capability(work, policy):
    if work is not None:
        require(
            policy.get("workDeliveryEdits") is True
            and policy.get("workDeliveryEditPolicy") == POLICY,
            "Canonical Work delivery editing capability unavailable",
        )


def assignment(capture, snapshot, row, policy):
    event, delivery = snapshot["request"], snapshot["delivery"]
    data = event.get("data", {})
    work_id = data.get("workId")
    if work_id is None:
        return None
    capability(work_id, policy)
    work_id = str(UUID(work_id))
    work = capture.admin_http("GET", "work/" + work_id)["work"]
    require(
        event["kind"] == "request"
        and str(event["recipient"]) == str(row["agent"])
        and str(work["id"]) == work_id
        and work["owner"] == row["agent"]
        and work["delivery"] == delivery["id"]
        and work["request_event"] == event["id"]
        and work["state"] == "assigned"
        and type(data.get("workRevision")) is int
        and work["revision"] == data["workRevision"]
        and str(work["goal"]) == data.get("goalId")
        and data.get("attemptId") == str(delivery["id"])
        and type(data.get("attemptNumber")) is int
        and data["attemptNumber"] >= 1
        and data.get("workCompletionPolicy") == "report-required/v1"
        and str(work["room"]) == str(event["room"]),
        "Current original owned Work assignment/attempt required",
    )
    goal = capture.admin_http("GET", "goals/" + str(UUID(work["goal"])))["goal"]
    require(goal["state"] == "active", "Current original Work goal must be active")
    return {
        "id": work_id,
        "revision": work["revision"],
        "goalId": str(work["goal"]),
        "attemptId": str(delivery["id"]),
        "attemptNumber": data["attemptNumber"],
        "roomId": str(work["room"]),
    }


def permit_authority(record, source, receipt):
    """Pin the additive proof; the server remains the authority at every phase."""
    authority = receipt.get("permit", {}).get("proof", {}).get("workAuthority")
    work = record.get("work")
    if work is None:
        require(authority is None, "Ordinary permit cannot acquire Work authority")
        return None
    require(isinstance(authority, dict), "Original server Work authority required")
    expected = {
        "schema": POLICY,
        "workId": work["id"],
        "workRevision": work["revision"],
        "goalId": work["goalId"],
        "attemptId": work["attemptId"],
        "attemptNumber": work["attemptNumber"],
        "ownerId": source["agentId"],
        "requestId": source["requestId"],
        "roomId": work["roomId"],
    }
    require(
        (set(expected) | {"goalRevision", "decisionSequence", "cooperationRevision",
                          "placementRevision", "roomGrantRevision", "attemptDigest",
                          "executionDigest"}) <= set(authority)
        and all(authority.get(k) == value for k, value in expected.items())
        and source["nativeGoalId"] is None,
        "Server Work proof differs from original captured assignment/source",
    )
    for key in ("goalRevision", "placementRevision"):
        require(type(authority.get(key)) is int and authority[key] >= 1,
                "Current canonical Work revisions required")
    for key in ("cooperationRevision", "roomGrantRevision"):
        require(authority.get(key) is None or
                type(authority[key]) is int and authority[key] >= 1,
                "Canonical optional Work revision required")
    require(type(authority.get("decisionSequence")) is int
            and authority["decisionSequence"] >= 0, "Work decision sequence required")
    require(all(isinstance(authority.get(k), str)
                and re.fullmatch(r"[a-f0-9]{64}", authority[k])
                for k in ("attemptDigest", "executionDigest")),
            "Original Work attempt/execution proof digests required")
    return authority


def planned_patch(bridge, record, source, frame):
    """Only an original permit or explicit native plan callback selects a plan."""
    if record.get("work") is None:
        return False
    key = bridge.state / "commands" / (
        "permit-" + digest([source["nativeThread"], source["callId"]]) + ".json"
    )
    if frame["port"] != "patch-preflight":
        original = protected(key)
        schema = original.get("schema")
        require(schema in {"lax-original-patch-permit/v1",
                           "lax-original-delivery-patch-permit/v1"},
                "Original mutation protocol is unknown")
        return schema == "lax-original-patch-permit/v1"
    root, observed = bridge.resource(record, frame["evidence"])
    pointer = bridge.plan_pointer(record, root)
    if not pointer.exists():
        return False
    plan = bridge.http("GET", "collaboration/edit-plans/" +
                       str(UUID(protected(pointer)["planId"])))
    require(str(plan["plan"]["host"]) == root["hostId"]
            and str(plan["plan"]["workspace_id"]) == root["workspaceId"]
            and plan["plan"]["state"] in {"collecting", "ready", "settled", "withdrawn"},
            "Original explicit plan namespace/state changed")
    if plan["plan"]["state"] != "ready":
        return False
    paths = [item["relativePath"] for item in observed]
    planned = [item["relativePath"] for item in plan["manifest"]["files"]]
    # Only this explicit pointer's ready file scope selects planned editing.
    # Claims and unsettled permits remain independently enforced by the backend,
    # including when metadata is collecting, withdrawn or outside this patch.
    return any(a == b or a.startswith(b + "/") or b.startswith(a + "/")
               for a in paths for b in planned)
