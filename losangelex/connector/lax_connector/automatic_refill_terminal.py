"""Recover only a known rejected, terminal writer refill before any snapshot."""
import asyncio
import hashlib
import json
import os

from .automatic_refill_data import require
from .automatic_refill_history import _open, _prefix
from .context_observation import TERMINAL, original_turn


def history_before_snapshot(original, operation_id):
    stream, info = _open(original["path"])
    with stream:
        require((info.st_dev, info.st_ino) == (original["device"], original["inode"]),
                "Original rollout identity changed")
        require(0 < original["beforeBytes"] <= info.st_size <= 256 * 1024**2
                and info.st_size - original["beforeBytes"] <= 16 * 1024**2,
                "Original native history observation exceeds bounds")
        require(_prefix(stream, original["beforeBytes"]) == original["beforeSha256"],
                "Original native history prefix changed")
        stream.seek(original["beforeBytes"] - 1)
        require(stream.read(1) == b"\n", "Original prefix ends inside a record")
        while stream.tell() < info.st_size:
            line = stream.readline(8 * 1024**2 + 1)
            require(line.endswith(b"\n") and len(line) <= 8 * 1024**2,
                    "Original native history has an incomplete/oversized record")
            row = json.loads(line)
            require(isinstance(row, dict), "Original native history record is malformed")
            body = row.get("payload", {})
            require(not (row.get("type") == "event_msg" and isinstance(body, dict)
                         and body.get("type") in (
                             "context_window_refill_intent",
                             "context_window_refill_installed")
                         and body.get("operationId") == operation_id),
                    "Original operation acquired a native cut; inspect installation")
        observed_sha = _prefix(stream, info.st_size)
        after = os.fstat(stream.fileno())
        require((after.st_dev, after.st_ino, after.st_size) ==
                (info.st_dev, info.st_ino, info.st_size),
                "Original history changed during observation")
    current = os.stat(original["path"], follow_symlinks=False)
    require((current.st_dev, current.st_ino, current.st_size) ==
            (info.st_dev, info.st_ino, info.st_size),
            "Original native rollout was replaced during observation")
    return {"operationId": operation_id, "observedBytes": info.st_size,
            "observedSha256": observed_sha, "prefixBytes": original["beforeBytes"],
            "prefixSha256": original["beforeSha256"]}


async def observe_terminal(automatic, path, original_bytes):
    from .automatic_refill_recovery import connection
    r = automatic.runner
    captured = connection(r)
    require(automatic.pending is None and r.purpose == "writer",
            "Only inactive original writer recovery is supported")
    original = json.loads(original_bytes)
    owner, request = original["owner"], original["request"]
    require(original["state"] == "held"
            and not any(key in original for key in ("response", "installed", "hostReceipt")),
            "Original operation may have acquired snapshot data")
    require(all(owner[key] == value for key, value in (
        ("agentId", r.config["agentId"]), ("contextId", r.config["contextIds"][r.purpose]),
        ("purpose", r.purpose), ("threadId", r.thread)))
        and all(request[key] == owner[other] for key, other in (
            ("threadId", "threadId"), ("turnId", "turnId"),
            ("purpose", "purpose"), ("contextId", "contextId"))),
        "Original refill belongs to another native identity")
    op = request["operationId"]
    rejection_path = r.state / ("operation-" + hashlib.sha256(op.encode()).hexdigest() + ".json")
    rejection_bytes = rejection_path.read_bytes()
    rejection = json.loads(rejection_bytes)
    expected = {key: owner[key] for key in ("contextId", "permitId", "materialIds")}
    expected.update({key: request[key] for key in (
        "operationId", "windowId", "historyVersion", "reason", "phase")})
    require(rejection.get("state") == "rejected"
            and rejection.get("status") in (400, 403, 409, 413, 422)
            and rejection["request"] == {
                "operationId": op, "action": "active_snapshot",
                "nativeThread": owner["threadId"], "nativeTurn": owner["turnId"],
                "value": expected},
            "Original snapshot was not a confirmed pre-data rejection")
    turn = await original_turn(r, owner["turnId"])
    require(turn["status"] in TERMINAL, "Original native inference is not known terminal")
    observed = await asyncio.to_thread(history_before_snapshot, original["originalHistory"], op)
    value = {key: expected[key] for key in (
        "operationId", "contextId", "permitId", "materialIds", "windowId", "historyVersion")}
    value.update(nativeTerminalStatus=turn["status"], prefixBytes=observed["prefixBytes"],
                 prefixSha256=observed["prefixSha256"])
    if request["phase"] == "preTurn" and turn["status"] == "failed":
        from .automatic_refill_preturn import failed_before_model
        value.update(await asyncio.to_thread(
            failed_before_model, original["originalHistory"], request, owner))
    disposition_op = "active-terminal:" + hashlib.sha256(op.encode()).hexdigest()
    await r.request("active_terminal", value, operation=disposition_op, turn=owner["turnId"])
    receipt = await r.agent.http(r.purpose, "GET",
        f"agents/{r.config['agentId']}/contexts/{r.purpose}/operations/{disposition_op}")
    require(receipt.get("schema") == "lax-active-context-terminal-uninstalled/v1"
            and receipt.get("status") == "terminal_uninstalled"
            and receipt.get("agentId") == owner["agentId"]
            and receipt.get("purpose") == r.purpose
            and receipt.get("nativeThread") == r.thread
            and receipt.get("nativeTurn") == owner["turnId"]
            and receipt.get("newExecutionAdmitted") is False
            and all(receipt.get(key) == value[key] for key in value),
            "Original terminal-before-snapshot disposition differs")
    require(observed == await asyncio.to_thread(
        history_before_snapshot, original["originalHistory"], op),
        "Original history changed during terminal disposition")
    require(not r.agent.stop.is_set() and connection(r) == captured
            and path.read_bytes() == original_bytes
            and rejection_path.read_bytes() == rejection_bytes,
            "Original owner or operation journal changed")
    if receipt.get("continuationAllowed") is True:
        require(value.get("failedBeforeModel") is True,
                "Continuation requires original pre-model failure evidence")
        candidates = getattr(automatic, "failed_preturn_candidates", [])
        candidate = {"nativeTurn": owner["turnId"], "dispositionOperationId": disposition_op}
        if candidate not in candidates:
            candidates.append(candidate)
        automatic.failed_preturn_candidates = candidates
    return {"operationId": op, "status": "terminal_uninstalled",
            "originalNativeStatus": turn["status"], "observation": observed}
