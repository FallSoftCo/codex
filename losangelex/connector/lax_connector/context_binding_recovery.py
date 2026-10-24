"""Recover only the original idempotent bootstrap-binding metadata.

An absent canonical receipt never proves that a native/external effect is safe to
repeat. This exception is restricted to binding one existing context/thread.
"""

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
            and payload["action"] == "bind"
            and payload["nativeTurn"] == "bootstrap"
            and payload["value"].get("runtimeProtocol") == "lax-purpose-runtime/v3"
            and old.get("request") == payload
            and old.get("state") in ("intent", "unknown")
        ):
            raise
    previous = old.get("bindRecovery", {})
    recovery = {
        "reason": "authenticated_original_bootstrap_bind_receipt_absent",
        "lookupStatus": 404,
        "lookupCode": "CONTEXT_OPERATION_NOT_FOUND",
        "count": previous.get("count", 0) + 1,
    }
    # Keep the exact original request and operation identity. This is a binding
    # transaction, never inference/Work/tool admission or an external execution.
    saved(journal, {**old, "state": "intent", "bindRecovery": recovery})
    runner.trace(
        "bootstrap_bind_receipt_absent",
        {
            "operationId": operation,
            "recovery": recovery,
        },
    )
    return await runner.agent.http(runner.purpose, "POST", path, payload)
