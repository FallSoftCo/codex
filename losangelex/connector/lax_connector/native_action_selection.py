"""Stage exact native evidence, measure the real native prefix, then adopt CAS.

Pin creation and read-only preflight confer no work or execution authority.
"""
import asyncio

from .automatic_refill_data import require
from .context_action_memory import index
from .native_action_pins import capture
from .retained_context_packet import enabled, frame


async def retain(runner, arguments, operation):
    require(enabled(runner) and runner.retained_context_contract,
            "Paired retained-native Writer contract required")
    require(set(arguments) == {"nativeTurn", "itemId", "sha256", "selectionRevision", "reason"},
            "Exact original action selection fields required")
    require(type(arguments["selectionRevision"]) is int and arguments["selectionRevision"] >= 0,
            "Exact selection revision required")
    require(isinstance(arguments["reason"], str) and 0 < len(arguments["reason"]) <= 500,
            "Bounded relevance reason required")
    metadata = await capture(runner, arguments["nativeTurn"], arguments["itemId"], arguments["sha256"])
    preflight_op = operation + ":native-prepare"
    proposed = await runner.request("action_prepare", {
        "selectionRevision": arguments["selectionRevision"],
        "nativeAction": metadata, "reason": arguments["reason"]}, operation=preflight_op)
    state = (await runner.rpc.call("thread/contextWindow/read", {"threadId": runner.thread}))["state"]
    require(state["activeTurnId"] == runner.turn and state["idle"] is False
            and state["heldOperationId"] is None,
            "Original native inference changed during evidence selection")
    params = {key: state[key] for key in ("threadId", "contextId", "purpose",
                                         "windowId", "historyVersion")}
    params.update(operationId=preflight_op, turnId=runner.turn,
                  reason="contextLimit", phase="midTurn")
    snapshot = proposed["snapshot"]
    import json
    content = json.loads("".join(chunk["content"] for chunk in snapshot["chunks"]))
    actions = await asyncio.to_thread(index, runner, content)
    packet, budget = await frame(runner, snapshot, params, actions)
    measured = (await runner.rpc.call("thread/contextWindow/preflight", {
        "threadId": runner.thread, "state": state, "packet": packet}))["preflight"]
    require(measured["state"] == state and measured["operationId"] == preflight_op,
            "Native selection measurement belongs to another cut")
    selected = await runner.request("action_commit", {
        "preflightOperationId": preflight_op, "preflightSha256": snapshot["sha256"],
        "budget": budget}, operation=operation + ":native-commit")
    runner.trace("native_action_retained", {
        "reference": metadata["reference"], "selectionRevision": selected["selectionRevision"],
        "nativePreflight": measured})
    return {"reference": metadata["reference"],
            "selectionRevision": selected["selectionRevision"],
            "originalItemSha256": metadata["sha256"],
            "retainedItemBytes": metadata["payloadBytes"],
            "nativeMeasurement": {key: measured[key] for key in (
                "prefixItemCount", "replacementItemCount", "replacementWireBytes")}, "meaning":
            "Whole original terminal evidence selected. Historical data grants no role, "
            "execution or publication permission; unavailable sources remain explicit."}
