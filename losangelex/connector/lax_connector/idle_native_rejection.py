"""Explicit recovery of a known native refusal with no original durable intent.

A matched negative reply is not by itself proof that no checkpoint was written.
The exact original history, idle cut and canonical snapshot/receipt observations
must also agree. Unknown, incomplete or installed outcomes remain held.
"""
import asyncio
import hashlib
import json

from .automatic_refill_data import require
from .automatic_refill_recovery import connection
from .automatic_refill_terminal import history_before_snapshot
from .context_observation import TERMINAL, original_turn
from .errors import HttpFailure

REFUSAL = "native idle replacement refused or held: native context cut changed or remains held"
LEGACY_REFUSAL = str({"code": -32600, "message": REFUSAL})


async def inspect_native_rejected(idle, path):
    r = idle.runner
    require(getattr(r.agent, "rebuild_only", False),
            "Native preparation recovery requires explicit --rebuild-context-only")
    original_bytes = path.read_bytes()
    operation = json.loads(original_bytes)
    require(idle.owned(operation) and operation.get("state") == "held"
            and all(key in operation for key in ("snapshot", "response", "preflight"))
            and not any(key in operation for key in ("installed", "hostReceipt", "nativeResult")),
            "Original native refusal has an installed or unknown checkpoint")
    known = operation.get("nativeRejection")
    require(operation.get("holdReason") == LEGACY_REFUSAL
            and (known is None or known == {"code": -32600, "message": REFUSAL}),
            "Original native result is not the exact confirmed refusal")
    require(all(operation.get(key) == value for key, value in (
        ("agentId", r.config["agentId"]), ("contextId", r.config["contextIds"][r.purpose]),
        ("purpose", r.purpose), ("nativeThread", r.thread))),
        "Original rejected native packet belongs to another owner")
    request = operation["request"]
    require(request["operationId"] == operation["operationId"]
            and request["threadId"] == r.thread
            and request["contextId"] == operation["contextId"]
            and request["purpose"] == r.purpose
            and operation["preflight"]["state"] == operation["nativeState"]
            and operation["preflight"]["operationId"] == operation["operationId"],
            "Original native packet identity or preflight differs")
    local_path = r.state / ("operation-" + hashlib.sha256(
        operation["snapshotOperationId"].encode()).hexdigest() + ".json")
    local_bytes = local_path.read_bytes()
    local = json.loads(local_bytes)
    selected = local.get("request", {}).get("value", {}).get("materialIds")
    require(local.get("state") == "accepted"
            and local.get("receipt") == operation["snapshot"]
            and isinstance(selected, list) and len(selected) <= 1
            and local.get("request") == {
                "operationId": operation["snapshotOperationId"], "action": "rebuild_snapshot",
                "nativeThread": r.thread, "nativeTurn": request["turnId"],
                "value": {"materialIds": selected}},
            "Original accepted snapshot or exact material selection differs")
    captured = connection(r)
    prefix = f"agents/{r.config['agentId']}/contexts/{r.purpose}/operations/"
    snapshot = await r.agent.http(r.purpose, "GET", prefix + operation["snapshotOperationId"])
    require(snapshot == operation["snapshot"],
            "Original canonical snapshot changed; do not create another snapshot")
    try:
        await r.agent.http(r.purpose, "GET", prefix + operation["installedOperationId"])
    except HttpFailure as error:
        require(error.status == 404 and error.code == "CONTEXT_OPERATION_NOT_FOUND",
                "Original installed receipt is unavailable, not known absent")
    else:
        raise RuntimeError("Original installation already exists; observe it")
    pending = await r.request("pending")
    require(pending.get("contextRebuild", {}).get("requestedOperationId")
            == operation["requestOperationId"], "Original canonical rebuild request changed")
    turn = await original_turn(r, request["turnId"])
    require(turn["status"] in TERMINAL, "Original inference is not known terminal")
    cut = (await r.rpc.call("thread/contextWindow/read", {"threadId": r.thread}))["state"]
    require(cut["idle"] is True and cut["activeTurnId"] is None
            and cut["heldOperationId"] is None
            and cut["threadId"] == r.thread and cut["contextId"] == operation["contextId"]
            and cut["purpose"] == r.purpose
            and cut["windowId"] == operation["nativeState"]["windowId"]
            and cut["lastStartedTurnId"] == request["turnId"],
            "Original idle window or last inference changed")
    observed = await asyncio.to_thread(
        history_before_snapshot, operation["originalHistory"], operation["operationId"])
    require(not r.agent.stop.is_set() and connection(r) == captured
            and path.read_bytes() == original_bytes and local_path.read_bytes() == local_bytes,
            "Original owner, native refusal or snapshot journal changed")
    return {"operation": operation, "originalBytes": original_bytes, "selected": selected,
            "nativeState": cut, "connection": captured, "snapshot": snapshot,
            "proof": {"schema": "lax-idle-native-refusal-recovery/v1",
                      "originalJournalSha256": hashlib.sha256(original_bytes).hexdigest(),
                      "snapshotJournalSha256": hashlib.sha256(local_bytes).hexdigest(),
                      "originalNativeTerminalStatus": turn["status"],
                      "canonicalSnapshotCommitted": True,
                      "canonicalInstalledReceiptAbsent": True,
                      "originalNativeNegativeReply": known or {"code": -32600, "message": REFUSAL},
                      "nativeObservation": observed,
                      "newInferenceAdmitted": False,
                      "nativeDurableIntentObserved": False}}
