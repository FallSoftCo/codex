"""Explicit immutable ownership for the shared native tool session.

This snapshot carries accepted ownership only. Native process admission and
Hollywood permission/effect fences remain independent checks.
"""
import json


def capture(accepted, *, thread, turn, agent, host):
    # Copy accepted wire data so a later scheduler change cannot retarget an
    # already running callback. Returning a new snapshot also avoids aliases.
    value = json.loads(json.dumps(accepted))
    delivery, request = value["delivery"], value["request"]
    if (delivery["agent"] != agent or delivery["host"] != host
            or delivery["event"] != request["id"]
            or delivery["authority"] != request["authority"]
            or delivery["generation"] < 1 or not delivery["claim_id"]):
        raise PermissionError("Captured native participation identity differs")
    value.update(nativeThread=thread, nativeTurn=turn)
    return value


def participation(participant):
    # The effect ContextVar pins the owner for the entire callback, including
    # awaits and administrative child requests. Other tasks cannot retarget it.
    effects = getattr(participant, "effects", None)
    current = effects.current.get() if effects else None
    owner = current.get("owner") if current else None
    return json.loads(json.dumps(owner)) if owner is not None else participant.captured_execution()
