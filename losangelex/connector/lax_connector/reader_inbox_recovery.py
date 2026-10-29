"""Close a Reader input *view* only against its original admission fence.

No input, append, adoption, turn or callback is replayed. A closed native turn
alone is insufficient: an admitted Reader may already have interpreted material.
"""
import json
from .context_observation import original_turn
from .errors import HttpFailure

async def terminal_unadopted(runner, batch):
    snapshot = batch.get("snapshot", {})
    if (snapshot.get("schema") != "lax-reader-input/v1"
            or snapshot.get("nativeThread") != runner.thread
            or not snapshot.get("inputIds")):
        return {"holdReason": "Original input snapshot scope unavailable"}
    records = []
    for path in runner.state.glob("operation-*.json"):
        record = json.loads(path.read_text())
        request = record.get("request", {})
        permit = (record.get("receipt") or {}).get("permit", {})
        if request.get("action") != "reserve" or request.get("nativeThread") != runner.thread:
            continue
        if (not permit or permit.get("agent") != runner.config["agentId"]
                or permit.get("purpose") != "reader"
                or permit.get("context_id") != runner.config["contextIds"]["reader"]
                or permit.get("native_thread") != runner.thread
                or not set(snapshot["inputIds"]) <= set(permit.get("material_ids", []))):
            continue
        if batch.get("permitId") and permit["id"] != batch["permitId"]:
            continue
        records.append(record)
    if len(records) != 1:
        return {"holdReason": "Original Reader reservation identity unavailable or ambiguous"}
    record = records[0]
    reserve_operation = record["request"]["operationId"]
    route = f"agents/{runner.config['agentId']}/contexts/reader/operations/"

    async def missing(operation):
        try:
            await runner.agent.http("reader", "GET", route + operation)
        except HttpFailure as error:
            if error.status == 404 and error.code == "CONTEXT_OPERATION_NOT_FOUND":
                return True
            raise
        return False

    canonical_snapshot = await runner.agent.http("reader", "GET", route + batch["operation"])
    reserve = await runner.agent.http("reader", "GET", route + reserve_operation)
    immutable = lambda value: {k: v for k, v in value.items() if k != "currentPermit"}
    if (canonical_snapshot != snapshot
            or immutable(reserve) != immutable(record["receipt"])):
        return {"holdReason": "Original Reader snapshot/reservation receipt differs"}
    current = reserve.get("currentPermit") or {}
    original = record["receipt"]["permit"]
    if (current.get("id") != original["id"]
            or any(current.get(k) != original.get(k) for k in
                   ("agent", "purpose", "context_id", "native_thread", "host", "material_ids"))
            or current.get("state") != "released"):
        return {"holdReason": "Original Reader reservation is not definitively closed"}
    turn = current.get("native_turn")
    if turn is None:
        released = await runner.agent.http("reader", "GET",
                                          route + "release-unused:" + current["id"])
        if (released.get("permitId") != current["id"]
                or released.get("state") != "released"
                or released.get("nativeTurn") is not None
                or released.get("disposition") != "unused_reservation"
                or released.get("workCompletionInferred") is not False):
            return {"holdReason": "Original unused reservation release is unconfirmed"}
        disposition = "unused_reservation"
    else:
        # The released permit fences late begin attempts. Check actual native
        # terminality and original end; a missing operation alone is no proof.
        ended = await runner.agent.http("reader", "GET", route + "context-end:" + turn)
        native = await original_turn(runner, turn)
        if (native.get("status") not in ("completed", "interrupted", "failed")
                or ended.get("nativeTurn") != turn
                or ended.get("state") != native["status"]
                or ended.get("admission", {}).get("capacityReleased") is not True
                or ended.get("admission", {}).get("permitId") != current["id"]
                or current.get("terminal_status") != native["status"]):
            return {"holdReason": "Original native terminal/admission release is unconfirmed"}
        if not await missing("context-begin:" + turn):
            return {"holdReason": "Original Reader was admitted; reconcile its original callbacks"}
        if not await missing("reader-adopt:" + turn + ":" + batch["operation"]):
            return {"holdReason": "Original Reader adoption exists; reconcile its original receipt"}
        disposition = "terminal_before_reader_admission"
    return {
        "closedBeforeAdmissionVerified": True,
        "viewDisposition": disposition,
        "originalReservationOperationId": reserve_operation,
        "originalPermitId": current["id"],
        "originalNativeTurn": turn,
        "viewRefreshAllowed": True,
        "adoptionVerified": False,
        "interpretationInferred": False,
        "newExecutionAdmitted": False,
        "operationsReplayed": 0,
    }
