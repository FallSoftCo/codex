"""Recover original bootstrap or confirmed terminal metadata, never execution.

Missing receipts do not authorize retrying an effect. Terminal reconciliation
requires the exact bound native thread, original wake/permit and a fresh terminal
native observation. Hollywood still validates the original binding and permit.
"""
import json
from .errors import HttpFailure
from .journal import saved


async def original_receipt(runner, payload, operation, journal, old):
    path = f"agents/{runner.config['agentId']}/contexts/{runner.purpose}"
    try:
        return await runner.agent.http(
            runner.purpose, "GET", path + "/operations/" + operation
        )
    except HttpFailure as error:
        if not (
            error.status == 404
            and error.code == "CONTEXT_OPERATION_NOT_FOUND"
            and old.get("request") == payload
            and old.get("state") in ("intent", "unknown")
        ):
            raise
        absent = error
    bootstrap = (
        payload["action"] == "bind"
        and payload["nativeTurn"] == "bootstrap"
        and payload["value"].get("runtimeProtocol") == "lax-purpose-runtime/v3"
    )
    terminal = (
        payload["action"] == "end"
        and operation == "context-end:" + payload["nativeTurn"]
        and payload["nativeThread"] == runner.thread
        and set(payload["value"]) == {"status", "permitId"}
        and payload["value"]["status"] in {"completed", "interrupted", "failed"}
    )
    if not bootstrap and not terminal:
        raise absent
    key = "bindRecovery" if bootstrap else "terminalRecovery"
    recovery = {
        "reason": "authenticated_original_bootstrap_bind_receipt_absent",
        "lookupStatus": 404,
        "lookupCode": "CONTEXT_OPERATION_NOT_FOUND",
        "count": old.get(key, {}).get("count", 0) + 1,
    }
    if terminal:
        from .context_observation import original_turn
        wake = json.loads((runner.state / "wake.json").read_text())
        if (
            wake.get("state") not in {"submission_intent", "running", "unknown"}
            or wake.get("nativeThread") != runner.thread
            or wake.get("nativeTurn") != payload["nativeTurn"]
            or wake.get("permitId") != payload["value"]["permitId"]
            or not wake.get("permitId")
        ):
            raise RuntimeError("Original terminal wake identity changed; settlement held")
        observed = await original_turn(runner, payload["nativeTurn"])
        if observed["status"] != payload["value"]["status"]:
            raise RuntimeError("Original native terminal status changed; settlement held")
        recovery.update(
            reason="confirmed_original_native_terminal_receipt_absent",
            nativeThread=runner.thread,
            nativeTurn=payload["nativeTurn"],
            permitId=wake["permitId"],
            terminalStatus=observed["status"],
            modelTurnsStarted=0,
            executionEffectsReplayed=0,
        )
    # Same immutable operation only. This settles terminal metadata; it cannot
    # begin/reserve inference, repeat input, execute a tool or publish a message.
    saved(journal, {**old, "state": "intent", key: recovery})
    runner.trace("terminal_receipt_absent" if terminal else "bootstrap_bind_receipt_absent",
                 {"operationId": operation, "recovery": recovery})
    return await runner.agent.http(runner.purpose, "POST", path, payload)
