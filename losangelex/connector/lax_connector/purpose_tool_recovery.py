"""Recover original purpose-native tool receipts through owned native history reads."""
import hashlib
import json
from pathlib import Path
from .journal import saved
from .native_tool_session import NativeToolSession

async def reconcile(runner):
    root = runner.state / "native-tools"
    if not root.exists():
        return []
    pending = []
    for path in root.glob("tool-*.json"):
        value = json.loads(path.read_text())
        if value.get("state") != "completed" and value.get("nativeThread") == runner.thread:
            pending.append((path, value))
    if not pending:
        return []
    # Old journals omitted turn identity. Use the actual captured event only to
    # locate it, then verify the exact callback again through the native RPC.
    missing = {value["callId"] for _, value in pending if not value.get("nativeTurn")}
    turns = {}
    if missing:
        trace = runner.state / "events.jsonl"
        with trace.open("rb") as stream:
            offset = max(0, trace.stat().st_size - 8 * 1024 * 1024)
            stream.seek(offset)
            if offset:
                stream.readline()
            for line in stream:
                event = json.loads(line)
                item = event.get("item") or {}
                if (event.get("event") == "item/completed" and event.get("threadId") == runner.thread
                        and item.get("id") in missing and event.get("turnId")):
                    turns[item["id"]] = event["turnId"]
    outcomes = []
    for path, tool in pending[:32]:
        try:
            turn = tool.get("nativeTurn") or turns.get(tool["callId"])
            if not turn:
                raise RuntimeError("Original callback turn unavailable")
            original = json.loads((runner.state / ("execution-" + turn + ".json")).read_text())
            scopes = [value for value in original["executionScopes"]
                if value["sourceRequestId"] == tool["requestId"] and value["nativeThread"] == runner.thread
                and value["nativeTurn"] == turn and value["agentId"] == runner.config["agentId"]]
            if len(scopes) != 1:
                raise RuntimeError("Original execution scope unavailable")
            scope = scopes[0]
            page = await runner.rpc.call("thread/items/read", {
                "threadId": runner.thread, "turnId": turn, "itemIds": [tool["callId"]]}, timeout=15)
            entries = page["data"]
            if len(entries) != 1 or entries[0]["turnId"] != turn:
                raise RuntimeError("Original native callback unavailable")
            item = entries[0]["item"]
            if item.get("id") != tool["callId"]:
                raise RuntimeError("Original native callback identity differs")
            accepted = await runner.agent.http("writer", "GET", "deliveries/" + scope["deliveryId"])
            role = await runner.agent.http("writer", "GET", "connector/deliveries/" + scope["deliveryId"] + "/context")
            session = NativeToolSession(accepted=accepted, scope=scope, config=runner.config,
                state=root, rpc=runner.rpc, role=role,
                transport=lambda method, route, payload=None, **kw: runner.agent.http("writer", method, route, payload, **kw))
            recovered = await session.effects.reconcile(
                {"nativeThread": runner.thread, "nativeTurn": turn}, {"id": turn, "items": [item]})
            outcomes.append({"callId": tool["callId"], "nativeTurn": turn, "recovered": recovered,
                             "nativeCallbackReplayed": False})
        except Exception as error:
            # One unresolved original responsibility does not authorize replay or
            # block independent Work. Its own tool scope remains held.
            outcomes.append({"callId": tool["callId"], "held": type(error).__name__,
                             "nativeCallbackReplayed": False})
    saved(runner.state / "native-tool-recovery.json", {
        "outcomes": outcomes, "modelsStarted": 0, "callbacksReplayed": False})
    runner.trace("native_tool_startup_recovery", {"outcomes": outcomes, "modelsStarted": 0})
    return outcomes
