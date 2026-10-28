"""Explicit no-model recovery of a missing original installation acknowledgement."""
import asyncio
from .automatic_refill_data import CUT, require
from .automatic_refill_history import verify
from .context_observation import TERMINAL, original_turn


async def acknowledge(automatic, original, installed, operation):
    r = automatic.runner
    require(getattr(r.agent, "reconcile_only", False) and automatic.pending is None
            and not r.active, "Explicit inactive observation-only maintenance required")
    owner = original["owner"]
    turn = await original_turn(r, owner["turnId"])
    require(turn["status"] in TERMINAL, "Exact original native inference must be terminal")
    native = {"native_mode": original["nativeContextMode"]} if "nativeContextMode" in original else {}
    await asyncio.to_thread(verify, original["originalHistory"], original["request"],
                            original["response"], installed, **native)
    value = {k: owner[k] for k in ("contextId", "permitId", "materialIds")}
    value.update({k: installed[k] for k in CUT | {
        "operationId", "previousWindowId", "windowId", "nativeHistoryBytes", "nativeHistorySha256"}})
    value["nativeTerminalStatus"] = turn["status"]
    return await r.request("active_installed_reconcile", value, operation=operation, turn=owner["turnId"])
