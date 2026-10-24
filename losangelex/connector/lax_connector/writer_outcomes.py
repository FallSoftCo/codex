"""Observe a terminal Writer through native metadata; never replay its effects."""
import hashlib
import json
from collections import Counter
from .context_observation import original_turn
from .context_action_memory import KINDS, TERMINAL
from .purpose_tool_recovery import reconcile
from .journal import saved


async def record(runner, turn):
    if runner.purpose != "writer" or turn.get("status") not in ("failed", "completed"):
        return None
    identity = turn["id"]
    observed = await original_turn(runner, identity)
    if observed["status"] != turn["status"]:
        raise RuntimeError("Original native outcome changed")
    execution = json.loads((runner.state / ("execution-" + identity + ".json")).read_text())
    requests = {s["sourceRequestId"] for s in execution["executionScopes"]
                if s["nativeThread"] == runner.thread and s["nativeTurn"] == identity
                and s["agentId"] == runner.config["agentId"]}
    if len(requests) != 1:
        raise RuntimeError("One exact original Work execution scope required")
    await reconcile(runner)
    effects_settled = all(
        value.get("state") == "completed"
        for path in (runner.state / "native-tools").glob("tool-*.json")
        for value in [json.loads(path.read_text())]
        if value.get("requestId") in requests)
    entries, projection, cursor = [], [], None
    counts = Counter()
    for _ in range(64):
        page = await runner.rpc.call("thread/items/list", {
            "threadId": runner.thread, "turnId": identity, "limit": 100,
            **({"cursor": cursor} if cursor else {})}, timeout=15)
        for entry in page["data"]:
            if entry["turnId"] != identity:
                raise RuntimeError("Native outcome evidence belongs to another turn")
            item = entry["item"]
            if item.get("type") in KINDS and item.get("status") not in TERMINAL:
                effects_settled = False
            entries.append(entry)
            counts[item["type"]] += 1
            descriptor = {k: item[k] for k in ("id", "type", "status", "tool", "namespace", "success")
                          if k in item}
            descriptor["sha256"] = hashlib.sha256(json.dumps(item, sort_keys=True,
                separators=(",", ":")).encode()).hexdigest()
            if item.get("type") == "agentMessage":
                text = item.get("text", "")
                descriptor["textChars"] = len(text)
                descriptor["textSha256"] = hashlib.sha256(text.encode()).hexdigest()
            projection.append(descriptor)
            projection = projection[-8:]
        cursor = page.get("nextCursor")
        if not cursor:
            break
    else:
        raise RuntimeError("Original native outcome exceeds bounded observation")
    sha = hashlib.sha256(json.dumps(entries, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()
    from .context_writer_evidence import evidence_path
    artifact = evidence_path(runner.config, identity)
    original = {"schema": "lax-native-evidence-receipt/v1",
        "authorityId": runner.config["authorityId"], "agentId": runner.config["agentId"],
        "hostId": runner.config["hostId"], "contextId": runner.config["contextIds"]["writer"],
        "nativeThread": runner.thread, "nativeTurn": identity,
        "nativeItemsSha256": sha, "entries": entries}
    if artifact.exists():
        if json.loads(artifact.read_text()) != original:
            raise RuntimeError("Original native evidence receipt changed")
    else:
        saved(artifact, original)
    error = (observed.get("error") or {}).get("message", "")
    value = {"nativeTurn": identity, "status": observed["status"],
        "effectsReconciled": effects_settled, "nativeItemsSha256": sha, "items": projection,
        "itemCount": len(entries), "itemCounts": dict(counts),
        "projectionComplete": len(projection) == len(entries),
        "error": error if len(error) <= 1000 else error[:1000] + "\n[Diagnostic preview; full original native error retained]",
        "errorChars": len(error), "errorSha256": hashlib.sha256(error.encode()).hexdigest()}
    result = await runner.request("observe_writer_outcome", value,
        operation="writer-outcome:" + identity, turn=identity)
    if (result.get("schema") != "lax-writer-outcome/v2"
            or result.get("nativeThread") != runner.thread or result.get("nativeTurn") != identity):
        raise RuntimeError("Original native-outcome receipt differs")
    available = await runner.request("writer_evidence_available", {
        "nativeTurn": identity, "nativeItemsSha256": sha},
        operation="writer-evidence-available:" + hashlib.sha256((runner.thread + identity + sha).encode()).hexdigest(),
        turn=identity)
    saved(runner.state / ("writer-outcome-" + identity + ".json"),
          {"result": result, "evidence": value, "evidenceAvailability": available, "modelsStarted": 0, "effectsReplayed": False})
    return result
