"""Observe settled original actions before continuing accepted preparation.

Only an explicit operator mode may recover this known local refusal. An accepted
snapshot is reused; absent installation receipts alone never permit a reset.
"""
import asyncio
import hashlib
import json

from .automatic_refill_data import require
from .automatic_refill_recovery import connection
from .automatic_refill_terminal import history_before_snapshot
from .context_action_memory import collect
from .context_observation import TERMINAL, original_turn
from .errors import HttpFailure

ACTION_PENDING = "Original native action is not terminal; preserve its running context before rebuilding"


async def inspect_actions_settled(idle, path):
    r = idle.runner
    require(getattr(r.agent, "rebuild_only", False),
            "Action preparation recovery requires explicit --rebuild-context-only")
    original_bytes = path.read_bytes()
    op = json.loads(original_bytes)
    require(idle.owned(op) and op.get("state") == "held"
            and op.get("holdReason") == ACTION_PENDING
            and not any(key in op for key in (
                "response", "preflight", "nativeDispatchIntent", "installed",
                "hostReceipt", "nativeResult", "nativeRejection")),
            "Original action preparation has a dispatched or unknown outcome")
    require(r.purpose == "writer" and all(op.get(key) == value for key, value in (
        ("agentId", r.config["agentId"]), ("contextId", r.config["contextIds"][r.purpose]),
        ("purpose", r.purpose), ("nativeThread", r.thread))),
        "Original action preparation belongs to another identity")
    request = op["request"]
    require(all(request.get(key) == value for key, value in (
        ("operationId", op["operationId"]), ("threadId", r.thread),
        ("contextId", op["contextId"]), ("purpose", r.purpose))),
        "Original prepared native identity differs")
    local_path = r.state / ("operation-" + hashlib.sha256(
        op["snapshotOperationId"].encode()).hexdigest() + ".json")
    local_bytes = local_path.read_bytes()
    local = json.loads(local_bytes)
    selected = local.get("request", {}).get("value", {}).get("materialIds")
    snapshot = local.get("receipt")
    require(local.get("state") == "accepted" and isinstance(snapshot, dict)
            and isinstance(selected, list) and len(selected) <= 1
            and local.get("request") == {
                "operationId": op["snapshotOperationId"], "action": "rebuild_snapshot",
                "nativeThread": r.thread, "nativeTurn": request["turnId"],
                "value": {"materialIds": selected}}
            and ("snapshot" not in op or op["snapshot"] == snapshot),
            "Original accepted snapshot or exact selection differs")
    captured = connection(r)
    prefix = f"agents/{r.config['agentId']}/contexts/{r.purpose}/operations/"
    canonical = await r.agent.http(r.purpose, "GET", prefix + op["snapshotOperationId"])
    require(canonical == snapshot, "Original canonical snapshot differs")
    try:
        await r.agent.http(r.purpose, "GET", prefix + op["installedOperationId"])
    except HttpFailure as error:
        require(error.status == 404 and error.code == "CONTEXT_OPERATION_NOT_FOUND",
                "Original installed receipt unavailable, not known absent")
    else:
        raise RuntimeError("Original installation exists; observe it")
    pending = await r.request("pending")
    require(pending.get("contextRebuild", {}).get("requestedOperationId") ==
            op["requestOperationId"], "Original canonical rebuild request changed")
    turn = await original_turn(r, request["turnId"])
    require(turn["status"] in TERMINAL, "Original inference is not terminal")
    cut = (await r.rpc.call("thread/contextWindow/read", {"threadId": r.thread}))["state"]
    # historyVersion is process-local and is reconstructed on cold resume.
    # Bind the durable window/last-turn plus the independent rollout proof,
    # then use this observed current counter for native preflight.
    require({k: v for k, v in cut.items() if k != "historyVersion"} ==
            {k: v for k, v in op["nativeState"].items() if k != "historyVersion"}
            and cut["idle"] is True
            and cut["activeTurnId"] is None and cut["heldOperationId"] is None
            and cut["lastStartedTurnId"] == request["turnId"],
            "Original native idle cut changed")
    encoded = "".join(chunk["content"] for chunk in snapshot["chunks"]).encode()
    require(len(encoded) == snapshot["totalBytes"]
            and hashlib.sha256(encoded).hexdigest() == snapshot["sha256"],
            "Original snapshot bytes differ from its digest")
    content = json.loads(encoded)
    require(content["agentId"] == op["agentId"] and content["contextId"] == op["contextId"]
            and content["nativeThread"] == r.thread and content["purpose"] == r.purpose,
            "Original snapshot content belongs to another identity")
    # collect rejects every still-running action and unknown callback receipt.
    # Failed actions remain failed evidence; this does not replay them.
    actions = await asyncio.to_thread(collect, r, content)
    observed = await asyncio.to_thread(
        history_before_snapshot, op["originalHistory"], op["operationId"])
    require(not r.agent.stop.is_set() and connection(r) == captured
            and path.read_bytes() == original_bytes and local_path.read_bytes() == local_bytes,
            "Original action preparation or owner changed")
    return {"operation": op, "originalBytes": original_bytes, "selected": selected,
            "nativeState": cut, "connection": captured, "snapshot": snapshot,
            "proof": {"schema": "lax-idle-settled-actions-recovery/v1",
                      "originalJournalSha256": hashlib.sha256(original_bytes).hexdigest(),
                      "snapshotJournalSha256": hashlib.sha256(local_bytes).hexdigest(),
                      "originalNativeTerminalStatus": turn["status"],
                      "canonicalSnapshotCommitted": True,
                      "canonicalInstalledReceiptAbsent": True,
                      "terminalActionCount": len(actions),
                      "terminalActionsSha256": hashlib.sha256(json.dumps(
                          actions, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                      "nativeObservation": observed,
                      "newInferenceAdmitted": False, "nativeReplacementDispatched": False}}
