"""Prepare existing admission data for one original native pre-inference gate."""
import asyncio
import hashlib
import json
from .journal import saved
from .material_transport import fragments

METHOD = "thread/contextInput"


async def prepare(runner, params):
    await asyncio.wait_for(runner.admitted.wait(), 30)
    expected = {"threadId", "turnId", "operationId", "contextId", "purpose", "materialIds"}
    fields = {k: v for k, v in params.items() if k != "_rpcRequestId"}
    if (set(fields) != expected or not runner.active or not runner.accepting
            or runner.failed or params["threadId"] != runner.thread
            or params["turnId"] != runner.turn
            or params["contextId"] != runner.config["contextIds"][runner.purpose]
            or params["purpose"] != runner.purpose
            or params["materialIds"] != list(runner.permit_material_ids)
            or not isinstance(params["operationId"], str)
            or not 1 <= len(params["operationId"]) <= 256):
        raise RuntimeError("Original primary-input admission is unavailable; no model authorized")
    packet = runner.primary_packet
    if (not isinstance(packet, dict) or packet.get("schema") != "lax-purpose-primary-input/v1"
            or packet.get("contextId") != params["contextId"]
            or packet.get("purpose") != runner.purpose
            or packet.get("nativeThread") != runner.thread
            or packet.get("nativeTurn") != runner.turn
            or packet.get("materialIds") != params["materialIds"]):
        raise RuntimeError("Paired Hollywood primary input missing or changed; hold this turn")
    admission = "context-begin:" + runner.turn
    outputs = []
    if runner.purpose == "reader":
        if packet.get("mode") != "reader_inbox" or runner.inbox.uncertain:
            raise RuntimeError("Original ReaderInbox adoption has not completed")
    else:
        snapshots = packet.get("snapshots", [])
        if (packet.get("mode") != "material_snapshots"
                or [s["reference"] for s in snapshots] != ["role", *params["materialIds"]]):
            raise RuntimeError("Exact role and captured purpose material required")
        for snapshot in snapshots:
            outputs.extend(item["output"] for item in fragments(snapshot, admission))
    if (len(outputs) > 64 or sum(len(s.encode()) for s in outputs) > 262144):
        raise RuntimeError("Primary input exceeds native fragment budget; no model authorized")
    response = {**fields, "admissionOperationId": admission, "fragments": outputs}
    directory = runner.state / "primary-input"
    directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / (hashlib.sha256(params["operationId"].encode()).hexdigest() + ".json")
    prior = json.loads(path.read_text()) if path.exists() else None
    if prior:
        if prior["request"] != fields or prior["response"] != response:
            raise RuntimeError("Original primary-input delivery changed; inspect its receipt")
    else:
        saved(path, {"state": "prepared", "request": fields, "response": response,
            "meaning": "Admission data prepared for the original native callback. "
                       "Not proof of native durability, comprehension or Work completion.",
            "modelTurnsStartedByPreparation": 0, "effectsReplayed": False})
    runner.trace("primary_input_prepared", {"nativeTurn": runner.turn,
        "operationId": params["operationId"], "admissionOperationId": admission,
        "purpose": runner.purpose, "materialIds": params["materialIds"],
        "fragments": len(outputs), "durableDeliveryClaim": False})
    return response
