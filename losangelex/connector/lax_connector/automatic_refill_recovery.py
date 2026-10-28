"""Read-only original-window reconciliation; no installation or effect replay."""
import asyncio
import hashlib
import json
from .automatic_refill_data import CUT, INSTALLED, parameters, require
from .automatic_refill_history import recovered_installed, verify
from .journal import saved

RECONCILE = "thread/contextWindow/reconcile"


def connection(runner):
    rpc = runner.rpc
    return (rpc, getattr(rpc, "process", None), getattr(rpc, "reader", None),
            runner.thread, runner.config["agentId"],
            runner.config["contextIds"][runner.purpose], runner.purpose)


async def observe(automatic, operation_id, native=None):
    r = automatic.runner
    captured = connection(r)
    path = automatic.root / (hashlib.sha256(operation_id.encode()).hexdigest() + ".json")
    original_bytes = path.read_bytes()
    original = json.loads(original_bytes)
    owner = original["owner"]
    require(all(owner[k] == v for k, v in (
        ("agentId", r.config["agentId"]), ("contextId", r.config["contextIds"][r.purpose]),
        ("purpose", r.purpose), ("threadId", r.thread))),
        "Original receipt belongs to another purpose identity")
    require(original["request"]["operationId"] == operation_id,
            "Original native operation identity changed")
    installed = original.get("installed")
    if installed is None:
        installed = await asyncio.to_thread(recovered_installed, original["originalHistory"], operation_id)
    parameters(installed, INSTALLED)
    require(native is None or native == installed, "Recovered native installation differs")
    native = {"native_mode": original["nativeContextMode"]} if "nativeContextMode" in original else {}
    await asyncio.to_thread(verify, original["originalHistory"], original["request"],
                            original["response"], installed, **native)
    op = "active-installed:" + hashlib.sha256(operation_id.encode()).hexdigest()
    try:
        receipt = await r.agent.http(r.purpose, "GET",
            f"agents/{r.config['agentId']}/contexts/{r.purpose}/operations/{op}")
    except Exception as error:
        from .errors import HttpFailure
        if not (isinstance(error, HttpFailure) and error.status == 404
                and error.code == "CONTEXT_OPERATION_NOT_FOUND"
                and getattr(r.agent, "reconcile_only", False)):
            raise
        # Explicit operator reconciliation only. Never install another window,
        # restart the terminal inference or rewrite the original held journal.
        from .automatic_refill_installed_recovery import acknowledge
        receipt = await acknowledge(automatic, original, installed, op)
    binding = receipt["binding"]
    require(receipt.get("schema") == "lax-active-context-installed/v1"
            and receipt.get("status") == "recorded"
            and receipt.get("operationId") == operation_id
            and receipt.get("installedOperationId") == op
            and receipt.get("historyVersion") == original["request"]["historyVersion"],
            "Original Hollywood installation is not recorded")
    require(all(binding[k] == v for k, v in (
        ("agentId", owner["agentId"]), ("contextId", owner["contextId"]),
        ("purpose", owner["purpose"]), ("nativeThread", owner["threadId"]),
        ("nativeTurn", owner["turnId"]), ("permitId", owner["permitId"]),
        ("materialIds", owner["materialIds"]))),
        "Original Hollywood receipt purpose/turn/material binding differs")
    require(all(receipt[k] == installed[k] for k in CUT | {
        "previousWindowId", "windowId", "nativeHistoryBytes", "nativeHistorySha256"}),
        "Original Hollywood installation cut differs")
    require(not r.agent.stop.is_set() and connection(r) == captured
            and path.read_bytes() == original_bytes, "Original owner connection/journal changed")
    return {"operationId": operation_id, "status": "recorded"}


async def startup(automatic):
    """Resolve only this operation hold; never clear another failure cause."""
    r = automatic.runner
    unresolved = []
    await automatic.idle.startup()
    automatic.recovering = True
    try:
        for path in sorted(automatic.root.glob("*.json")):
            original = json.loads(path.read_text())
            if original["state"] == "ack_written":
                continue
            op = original["request"]["operationId"]
            try:
                if original["state"] == "held" and not any(
                        key in original for key in ("response", "installed", "hostReceipt")):
                    from .automatic_refill_terminal import observe_terminal
                    await observe_terminal(automatic, path, path.read_bytes())
                else:
                    await observe(automatic, op)
            except Exception as error:
                unresolved.append({"operationId": op, "reason": str(error)})
        automatic.held = bool(unresolved)
        saved(r.state / "automatic-refill-recovery.json", {
            "unresolved": unresolved, "modelsStarted": 0, "effectsReplayed": 0,
            "originalJournalsRewritten": False})
        if unresolved:
            r.failed = True
            r.failure_reason = "Original automatic refill outcome unconfirmed: " + unresolved[0]["reason"]
    finally:
        automatic.recovering = False


async def callback(automatic, raw):
    r = automatic.runner
    require("_rpcRequestId" in raw, "Original native reconciliation request required")
    params = {k: v for k, v in raw.items() if k != "_rpcRequestId"}
    parameters(params, INSTALLED)
    require(automatic.policy() is not None and automatic.pending is None,
            "Fresh explicit canonical owner required")
    require(not automatic.recovering, "Original receipt reconciliation already active")
    automatic.recovering = True
    try:
        return await observe(automatic, params["operationId"], params)
    finally:
        automatic.recovering = False
