"""Reconcile original captured human questions after a proven native caller failure.

This module reads receipts and closes that caller's attention. It never repeats
a tool, creates a question, submits a response or starts a model turn.
"""

import hashlib
import json
from uuid import UUID, uuid5

from .journal import saved


def includes(expected, actual):
    """Allow server-added defaults, preserving every captured value and list entry."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and includes(value, actual[key])
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(expected) == len(actual)
            and all(includes(a, b) for a, b in zip(expected, actual))
        )
    return expected == actual


async def reconcile_failed_questions(connector, execution, turn):
    c = connector
    if turn["status"] not in ("completed", "failed", "interrupted"):
        raise RuntimeError("Native caller is not terminal")
    d = c.active["delivery"]
    items = {item["id"]: item for item in turn.get("items", [])}
    reconciled = []
    for path in sorted(c.state.glob("tool-*.json")):
        tool = json.loads(path.read_text())
        if tool["state"] == "completed" or tool.get("tool") != "hollywood_ask":
            continue
        if (
            tool.get("requestId") != c.active["request"]["id"]
            or tool.get("nativeThread") != execution["nativeThread"]
        ):
            continue
        item = items.get(tool["callId"])
        if (
            not item
            or item.get("type") != "dynamicToolCall"
            or item.get("tool") != "hollywood_ask"
            or not (
                item.get("status") in ("failed", "declined")
                or item.get("status") == "completed" and item.get("success") is False
            )
        ):
            continue
        fingerprint = hashlib.sha256(
            json.dumps([tool["tool"], tool["arguments"]], sort_keys=True).encode()
        ).hexdigest()
        key = hashlib.sha256(
            (tool["nativeThread"] + tool["callId"]).encode()
        ).hexdigest()
        if fingerprint != tool["digest"] or path.name != "tool-" + key + ".json":
            raise RuntimeError("Captured question tool identity changed")
        arguments = tool["arguments"]
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        identity = str(uuid5(UUID(d["id"]), "hollywood/question:" + tool["callId"]))
        attention_path = c.state / ("attention-" + identity + ".json")
        if not attention_path.exists():
            # A missing receipt is not proof that no question was created.
            continue
        local = json.loads(attention_path.read_text())
        payload = local["payload"]
        expected = {
            "id": identity,
            "deliveryId": d["id"],
            "claimId": d["claim_id"],
            "generation": d["generation"],
            "nativeThread": execution["nativeThread"],
            "nativeTurn": execution["nativeTurn"],
            "nativeSlot": tool["callId"],
            "method": "hollywood/question",
        }
        if any(payload.get(k) != value for k, value in expected.items()):
            raise RuntimeError("Captured attention owner changed")
        if not includes(
            {"questions": arguments["questions"]}, payload.get("request")
        ):
            raise RuntimeError("Captured question arguments changed")
        current = await c.http("GET", "attention/" + identity)
        row, scope = current["attention"], current["scope"]
        if any(
            row.get(field) != value
            for field, value in {
                "id": identity,
                "delivery": d["id"],
                "agent": d["agent"],
                "claim_id": d["claim_id"],
                "generation": d["generation"],
                "native_thread": execution["nativeThread"],
                "native_turn": execution["nativeTurn"],
                "native_slot": tool["callId"],
                "method": "hollywood/question",
            }.items()
        ) or not includes(payload["request"], row["request"]):
            raise RuntimeError("Authoritative question receipt changed")
        prior = local.get("receipt")
        if prior and prior["scope"] != scope:
            raise RuntimeError("Original attention scope changed")
        state = row["state"]
        if state not in ("expired", "closed"):
            target = "closed" if state == "native_submitted" else "expired"
            if state not in ("pending", "response_submitted", "unknown", "native_submitted"):
                raise RuntimeError("Unrecognized original attention state")
            acknowledgement = {
                "operationId": "lax-question-terminal:" + identity + ":" + target,
                "claimId": d["claim_id"],
                "generation": d["generation"],
                "scope": scope,
                "state": target,
            }
            saved(attention_path, {**local, "acknowledgementIntent": acknowledgement})
            current = await c.http(
                "POST", "attention/" + identity + "/acknowledge", acknowledgement
            )
            if current["scope"] != scope or current["attention"]["state"] != target:
                raise RuntimeError("Original attention close is unconfirmed")
            state = target
        saved(
            attention_path,
            {
                **local,
                "state": state,
                "receipt": current,
                "reconciled": True,
                "observedNativeTerminal": turn["status"],
                "nativeResponseReplayed": False,
            },
        )
        result = {
            "success": False,
            "contentItems": [{
                "type": "inputText",
                "text": json.dumps({
                    "error": "AttentionExpired",
                    "effect": "original-native-call-failed",
                    "attentionId": identity,
                    "nativeReplay": False,
                    "nativeConsumptionInferred": False,
                }),
            }],
        }
        saved(
            path,
            {
                **tool,
                "state": "completed",
                "result": result,
                "reconciled": True,
                "nativeTerminal": turn["status"],
                "attentionReceipt": current,
            },
        )
        reconciled.append(identity)
    return reconciled
