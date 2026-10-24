"""Explicit known pre-inference rejection recovery on the original purpose.

No provider request, model output or business effect is replayed. Normal startup
only verifies an already accepted control receipt; acknowledgement is CLI-only.
"""
import hashlib
import json
import re
from .context_observation import original_turn
from .journal import saved
from .purpose_tool_recovery import reconcile

CAPABILITY = "host_tool_inference_auto_transport/v1"
SCHEMA = "lax-provider-rejection-resolution/v1"


def identity_path(runner, identity):
    if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", identity):
        raise ValueError("Exact original native turn required")
    return runner.state / ("provider-rejection-" + identity + ".json")


async def original_resolution(runner, wake):
    identity = wake.get("nativeTurn")
    if not identity:
        return None
    path = identity_path(runner, identity)
    if not path.exists():
        return None
    local = json.loads(path.read_text())
    if CAPABILITY not in runner.rpc.lax_capabilities:
        raise RuntimeError("Corrected provider-compatible native image required")
    operation = "acknowledge-provider-rejection:" + identity
    route = (f"agents/{runner.config['agentId']}/contexts/{runner.purpose}/operations/" + operation)
    receipt = await runner.agent.http(runner.purpose, "GET", route)
    expected = {"schema": SCHEMA, "contextId": runner.config["contextIds"][runner.purpose],
                "purpose": runner.purpose, "nativeThread": runner.thread,
                "nativeTurn": identity, "providerRejectionAcknowledged": True,
                "nativeItemsSha256": local["nativeItemsSha256"]}
    if any(receipt.get(k) != v for k, v in expected.items()) or receipt != local["receipt"]:
        raise RuntimeError("Original provider rejection acknowledgement differs")
    return local


async def acknowledge(runner, identity):
    if CAPABILITY not in runner.rpc.lax_capabilities:
        raise RuntimeError("Corrected provider-compatible native image required")
    if runner.active or runner.accepting or runner.automatic.pending is not None:
        raise RuntimeError("Original native inference/refill is not settled")
    wake = json.loads((runner.state / "wake.json").read_text())
    if (wake.get("state") != "finished" or wake.get("nativeThread") != runner.thread
            or wake.get("nativeTurn") != identity
            or wake.get("turn", {}).get("status") != "failed"):
        raise RuntimeError("Exact latest original failed native receipt required")
    prior = await original_resolution(runner, wake)
    if prior:
        return prior
    if runner.failed and getattr(runner, "provider_rejection_hold", None) != identity:
        raise RuntimeError("Another original inbox/refill/effect hold remains")
    observed = await original_turn(runner, identity)
    if observed["status"] != "failed":
        raise RuntimeError("Original native failure is unconfirmed")
    try:
        rejection = json.loads(observed["error"]["message"])
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("Exact original provider rejection unavailable") from None
    error = rejection.get("error", {})
    if (rejection.get("status") != 400 or error.get("code") != "unsupported_parameter"
            or error.get("param") != "tool_choice"):
        raise RuntimeError("This is not the known pre-inference tool-choice rejection")
    outcomes = await reconcile(runner)
    if any(item.get("held") for item in outcomes):
        raise RuntimeError("Original native tool effects remain unresolved")
    if any(json.loads(p.read_text()).get("state") != "completed"
           for p in (runner.state / "native-tools").glob("tool-*.json")):
        raise RuntimeError("An original native callback remains unresolved")
    begin = await runner.agent.http(runner.purpose, "GET",
        f"agents/{runner.config['agentId']}/contexts/{runner.purpose}/operations/context-begin:" + identity)
    if begin.get("nativeTurn") != identity or begin.get("state") != "running":
        raise RuntimeError("Original canonical native begin receipt unavailable")
    entries, cursor = [], None
    for _ in range(64):
        page = await runner.rpc.call("thread/items/list", {
            "threadId": runner.thread, "turnId": identity, "limit": 100,
            **({"cursor": cursor} if cursor else {})}, timeout=15)
        for entry in page["data"]:
            if entry["turnId"] != identity:
                raise RuntimeError("Native evidence belongs to another original turn")
            item = entry["item"]
            bootstrap = False
            if (item.get("type") == "functionCallOutput"
                    and item.get("namespace") is None
                    and item.get("name") == "context_material_available"):
                try:
                    supplied = json.loads(item["output"])
                except (KeyError, TypeError, ValueError):
                    supplied = None
                bootstrap = supplied == {
                    "purpose": runner.purpose, "materialIds": begin["materialIds"]}
            if item.get("type") not in {"userMessage", "contextCompaction"} and not bootstrap:
                raise RuntimeError("Original turn contains model output/action; no rejection-only recovery")
            entries.append(entry)
        cursor = page.get("nextCursor")
        if not cursor:
            break
    else:
        raise RuntimeError("Original native rejection evidence exceeds bounded pages")
    sha = hashlib.sha256(json.dumps(entries, sort_keys=True,
                        separators=(",", ":")).encode()).hexdigest()
    receipt = await runner.request("acknowledge_provider_rejection", {
        "nativeTurn": identity, "status": 400, "errorCode": "unsupported_parameter",
        "parameter": "tool_choice", "nativeItemsSha256": sha},
        operation="acknowledge-provider-rejection:" + identity, turn=identity)
    expected = {"schema": SCHEMA, "contextId": runner.config["contextIds"][runner.purpose],
                "purpose": runner.purpose, "nativeThread": runner.thread,
                "nativeTurn": identity, "nativeItemsSha256": sha,
                "providerRejectionAcknowledged": True}
    if any(receipt.get(k) != v for k, v in expected.items()):
        raise RuntimeError("Original provider rejection control receipt differs")
    result = {"nativeThread": runner.thread, "nativeTurn": identity,
              "nativeItemsSha256": sha, "nativeItemCount": len(entries),
              "receipt": receipt, "modelTurnsStarted": 0, "callbacksReplayed": False}
    saved(identity_path(runner, identity), result)
    saved(runner.state / "restart-recovery.json", {
        "id": "acknowledge-provider-rejection:" + identity,
        "nativeThread": runner.thread, "nativeTurn": identity,
        "modelTurnsStarted": 0, "originalInputsReposted": False})
    runner.failed = False
    runner.failure_reason = None
    runner.provider_rejection_hold = None
    return result
