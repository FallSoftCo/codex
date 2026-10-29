"""Explicit continuation of a rejected idle snapshot before native dispatch.

This is preparation recovery, not replay of replaceIdle. A missing receipt alone
is insufficient: exact local rejection, native history and current idle identity
must all agree before the existing rebuild-only operator path can proceed.
"""
import asyncio
import hashlib
import json

from .automatic_refill_data import require
from .automatic_refill_recovery import connection
from .automatic_refill_terminal import history_before_snapshot
from .context_observation import TERMINAL, original_turn
from .errors import HttpFailure


async def inspect_rejected(idle, path):
    r = idle.runner
    require((getattr(r.agent, "rebuild_only", False)
             or getattr(r.agent, "acquire_context_operation", None)),
            "Pre-snapshot retry requires explicit --rebuild-context-only")
    original_bytes = path.read_bytes()
    operation = json.loads(original_bytes)
    from .idle_prefix_rejection import PREFIX_REFUSAL, inspect_prefix_rejected
    from .native_context_acquisition import PRODUCER_REFUSAL
    if operation.get("holdReason") == PRODUCER_REFUSAL:
        return await inspect_prefix_rejected(idle, path, refusal=PRODUCER_REFUSAL)
    if operation.get("holdReason") == PREFIX_REFUSAL:
        return await inspect_prefix_rejected(idle, path)
    from .idle_action_recovery import ACTION_PENDING, inspect_actions_settled
    if operation.get("holdReason") == ACTION_PENDING:
        return await inspect_actions_settled(idle, path)
    if "snapshot" in operation or "preflight" in operation:
        from .idle_native_rejection import inspect_native_rejected
        return await inspect_native_rejected(idle, path)
    require(idle.owned(operation) and operation.get("state") == "held"
            and not any(key in operation for key in (
                "response", "snapshot", "preflight", "installed", "hostReceipt", "nativeResult")),
            "Original idle operation may have reached native dispatch")
    require(all(operation.get(key) == value for key, value in (
        ("agentId", r.config["agentId"]), ("contextId", r.config["contextIds"][r.purpose]),
        ("purpose", r.purpose), ("nativeThread", r.thread))),
        "Rejected original idle operation belongs to another identity")
    request = operation["request"]
    require(request["operationId"] == operation["operationId"]
            and request["threadId"] == r.thread
            and request["contextId"] == operation["contextId"]
            and request["purpose"] == r.purpose,
            "Original prepared native identity differs")
    rejection_path = r.state / ("operation-" + hashlib.sha256(
        operation["snapshotOperationId"].encode()).hexdigest() + ".json")
    rejection_bytes = rejection_path.read_bytes()
    rejection = json.loads(rejection_bytes)
    payload = rejection.get("request", {})
    selected = payload.get("value", {}).get("materialIds")
    require(rejection.get("state") == "rejected" and rejection.get("status") == 409
            and isinstance(selected, list) and len(selected) <= 1
            and payload == {
                "operationId": operation["snapshotOperationId"], "action": "rebuild_snapshot",
                "nativeThread": r.thread, "nativeTurn": request["turnId"],
                "value": {"materialIds": selected}},
            "Original snapshot is not an exact confirmed pre-data rejection")
    captured = connection(r)
    try:
        await r.agent.http(r.purpose, "GET",
            f"agents/{r.config['agentId']}/contexts/{r.purpose}/operations/" +
            operation["snapshotOperationId"])
    except HttpFailure as error:
        require(error.status == 404 and error.code == "CONTEXT_OPERATION_NOT_FOUND",
                "Original snapshot receipt unavailable; no retry")
    else:
        raise RuntimeError("Original snapshot was accepted; use original receipt observation")
    pending = await r.request("pending")
    require(pending.get("contextRebuild", {}).get("requestedOperationId") ==
            operation["requestOperationId"],
            "Original canonical rebuild request changed")
    turn = await original_turn(r, request["turnId"])
    require(turn["status"] in TERMINAL, "Original inference is not terminal")
    cut = (await r.rpc.call("thread/contextWindow/read", {"threadId": r.thread}))["state"]
    require(cut["idle"] is True and cut["activeTurnId"] is None
            and cut["heldOperationId"] is None
            and cut["threadId"] == r.thread and cut["contextId"] == operation["contextId"]
            and cut["purpose"] == r.purpose
            and cut["windowId"] == operation["nativeState"]["windowId"]
            and cut["lastStartedTurnId"] == request["turnId"],
            "Original native idle window or last inference changed")
    observed = await asyncio.to_thread(
        history_before_snapshot, operation["originalHistory"], operation["operationId"])
    require(not r.agent.stop.is_set() and connection(r) == captured
            and path.read_bytes() == original_bytes
            and rejection_path.read_bytes() == rejection_bytes,
            "Original idle owner or rejection journal changed")
    return {"operation": operation, "originalBytes": original_bytes, "selected": selected,
            "nativeState": cut, "connection": captured,
            "proof": {"schema": "lax-idle-snapshot-rejection-recovery/v1",
                      "originalJournalSha256": hashlib.sha256(original_bytes).hexdigest(),
                      "rejectionJournalSha256": hashlib.sha256(rejection_bytes).hexdigest(),
                      "originalNativeTerminalStatus": turn["status"],
                      "canonicalSnapshotCommitted": False,
                      "nativeObservation": observed,
                      "newInferenceAdmitted": False, "nativeReplacementDispatched": False}}
