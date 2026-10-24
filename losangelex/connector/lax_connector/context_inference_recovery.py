"""Explicit same-Work continuation after native success without Work settlement.

No automatic retry loop, input replay, effect replay or second acceptance ledger.
"""
import hashlib
import json
from .context_action_memory import KINDS, TERMINAL
from .context_observation import original_turn
from .journal import saved
from .purpose_tool_recovery import reconcile


async def resume_unsettled(runner, identity):
    if runner.purpose != "writer" or runner.active or runner.accepting or runner.failed:
        raise RuntimeError("An idle, recovered original writer is required")
    wake = json.loads((runner.state / "wake.json").read_text())
    if (wake.get("state") != "finished" or wake.get("nativeThread") != runner.thread
            or wake.get("nativeTurn") != identity
            or wake.get("turn", {}).get("status") != "completed"):
        raise RuntimeError("Exact latest completed original writer receipt required")
    observed = await original_turn(runner, identity)
    if observed["status"] != "completed":
        raise RuntimeError("Original native completion is unconfirmed")
    outcomes = await reconcile(runner)
    if any(x.get("held") for x in outcomes):
        raise RuntimeError("Original native effects remain unresolved; no continuation")
    # Do not restart a Work while one of its older admitted native effects is
    # unknown, even when the latest completed inference itself only read context.
    root = runner.state / "native-tools"
    if any(json.loads(p.read_text()).get("state") != "completed"
           for p in root.glob("tool-*.json")):
        raise RuntimeError("Original native callback outcome remains unresolved")
    entries, cursor = [], None
    for _ in range(64):
        page = await runner.rpc.call("thread/items/list", {
            "threadId": runner.thread, "turnId": identity, "limit": 100,
            **({"cursor": cursor} if cursor else {})}, timeout=15)
        for entry in page["data"]:
            item = entry["item"]
            if entry["turnId"] != identity:
                raise RuntimeError("Native item belongs to another original turn")
            if item.get("type") in KINDS and item.get("status") not in TERMINAL:
                raise RuntimeError("An original native action is not terminal")
            entries.append(entry)
        cursor = page.get("nextCursor")
        if not cursor:
            break
    else:
        raise RuntimeError("Original native item recovery exceeds bounded pages")
    if not entries:
        raise RuntimeError("Original native item evidence unavailable")
    sha = hashlib.sha256(json.dumps(entries, sort_keys=True,
                        separators=(",", ":")).encode()).hexdigest()
    result = await runner.request("resume_unsettled", {
        "nativeTurn": identity, "effectsReconciled": True, "nativeItemsSha256": sha},
        operation="explicit-resume-unsettled:" + identity, turn=identity)
    receipt = {"nativeThread": runner.thread, "nativeTurn": identity,
               "nativeItemsSha256": sha, "nativeItemCount": len(entries),
               "result": result, "modelTurnsStarted": 0,
               "originalInputRepeated": False, "callbacksReplayed": False}
    saved(runner.state / ("resume-unsettled-" + identity + ".json"), receipt)
    return receipt
