"""Explicit recovery of an accepted snapshot before native prefix preparation.

No replaceIdle call is retried here. The original snapshot and rollout must
agree with the still-pending request and idle owner, with no installed receipt
or durable native intent. Unknown outcomes remain held.
"""
import asyncio
import hashlib
import json

from .automatic_refill_data import require
from .automatic_refill_recovery import connection
from .automatic_refill_terminal import history_before_snapshot
from .context_observation import TERMINAL, original_turn
from .errors import HttpFailure

PREFIX_REFUSAL = str({
    "code": -32600,
    "message": "native preflight refused: native prefix unavailable: "
               "native core prefix exceeds its aggregate bound",
})


async def inspect_prefix_rejected(idle, path, *, refusal=PREFIX_REFUSAL):
    r = idle.runner
    require((getattr(r.agent, "rebuild_only", False)
             or getattr(r.agent, "acquire_context_operation", None)),
            "Prefix preparation recovery requires explicit --rebuild-context-only")
    original_bytes = path.read_bytes()
    operation = json.loads(original_bytes)
    require(idle.owned(operation) and operation.get("state") == "held"
            and operation.get("holdReason") == refusal
            and all(key in operation for key in ("request", "nativeState", "originalHistory"))
            and not any(key in operation for key in (
                "response", "preflight", "nativeDispatchIntent", "installed", "hostReceipt", "nativeResult",
                "nativeRejection")),
            "Original prefix preparation is not the exact pre-dispatch refusal")
    require(all(operation.get(key) == value for key, value in (
        ("agentId", r.config["agentId"]), ("contextId", r.config["contextIds"][r.purpose]),
        ("purpose", r.purpose), ("nativeThread", r.thread))),
        "Original prefix preparation belongs to another owner")
    request = operation["request"]
    require(request["operationId"] == operation["operationId"]
            and request["threadId"] == r.thread
            and request["contextId"] == operation["contextId"]
            and request["purpose"] == r.purpose,
            "Original prefix request identity differs")
    local_path = r.state / ("operation-" + hashlib.sha256(
        operation["snapshotOperationId"].encode()).hexdigest() + ".json")
    local_bytes = local_path.read_bytes()
    local = json.loads(local_bytes)
    selected = local.get("request", {}).get("value", {}).get("materialIds")
    require(local.get("state") == "accepted" and isinstance(selected, list)
            and len(selected) <= 1 and isinstance(local.get("receipt"), dict)
            and local.get("request") == {
                "operationId": operation["snapshotOperationId"], "action": "rebuild_snapshot",
                "nativeThread": r.thread, "nativeTurn": request["turnId"],
                "value": {"materialIds": selected}},
            "Original accepted prefix snapshot journal differs")
    captured = connection(r)
    prefix = f"agents/{r.config['agentId']}/contexts/{r.purpose}/operations/"
    snapshot = await r.agent.http(r.purpose, "GET", prefix + operation["snapshotOperationId"])
    require(snapshot == local["receipt"]
            and ("snapshot" not in operation or operation["snapshot"] == snapshot),
            "Original accepted prefix snapshot receipt changed")
    try:
        await r.agent.http(r.purpose, "GET", prefix + operation["installedOperationId"])
    except HttpFailure as error:
        require(error.status == 404 and error.code == "CONTEXT_OPERATION_NOT_FOUND",
                "Original installed receipt is unavailable, not known absent")
    else:
        raise RuntimeError("Original prefix replacement already installed; observe it")
    pending = await r.request("pending")
    require(pending.get("contextRebuild", {}).get("requestedOperationId")
            == operation["requestOperationId"], "Original prefix rebuild request changed")
    turn = await original_turn(r, request["turnId"])
    require(turn["status"] in TERMINAL, "Original prefix inference is not terminal")
    cut = (await r.rpc.call("thread/contextWindow/read", {"threadId": r.thread}))["state"]
    require(cut["idle"] is True and cut["activeTurnId"] is None
            and cut["heldOperationId"] is None and cut["threadId"] == r.thread
            and cut["contextId"] == operation["contextId"] and cut["purpose"] == r.purpose
            and cut["windowId"] == operation["nativeState"]["windowId"]
            and cut["lastStartedTurnId"] == request["turnId"],
            "Original prefix idle window or last inference changed")
    observed = await asyncio.to_thread(
        history_before_snapshot, operation["originalHistory"], operation["operationId"])
    require(not r.agent.stop.is_set() and connection(r) == captured
            and path.read_bytes() == original_bytes and local_path.read_bytes() == local_bytes,
            "Original prefix owner or journals changed")
    return {"operation": operation, "originalBytes": original_bytes, "selected": selected,
            "nativeState": cut, "connection": captured, "snapshot": snapshot,
            "proof": {"schema": "lax-idle-prefix-rejection-recovery/v1",
                      "originalJournalSha256": hashlib.sha256(original_bytes).hexdigest(),
                      "snapshotJournalSha256": hashlib.sha256(local_bytes).hexdigest(),
                      "originalNativeTerminalStatus": turn["status"],
                      "canonicalSnapshotCommitted": True,
                      "canonicalInstalledReceiptAbsent": True,
                      "nativeObservation": observed, "newInferenceAdmitted": False,
                      "nativeDurableIntentObserved": False}}

