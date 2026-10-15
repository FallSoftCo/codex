"""One-shot human steering; recover original message identities, never resend unknown input."""

import asyncio
import json
from .journal import saved
from .rpc import RpcError

CAPABILITY = "native-human-controls/v1"


class NativeControls:
    def __init__(self, connector):
        self.c = connector
        self.lock = asyncio.Lock()

    async def acknowledge(self, row, state, evidence):
        c = self.c
        d = c.active["delivery"]
        return await c.http("POST", "connector/native-controls/" + row["control"]["id"], {
            "operationId": "native-control:" + row["control"]["id"] + ":" + state,
            "claimId": d["claim_id"], "generation": d["generation"],
            "scope": row["scope"], "state": state, "evidence": evidence,
        })

    def matches(self, row, turn_id):
        c = self.c
        d, request = c.active["delivery"], c.active["request"]
        expected = {
            "authorityId": request["authority"], "deliveryId": d["id"],
            "agentId": c.config["agentId"], "roomId": request["room"],
            "hostId": c.config["hostId"], "generation": d["generation"],
            "nativeThread": c.thread, "nativeTurn": turn_id,
            "sourceRequestId": request["id"], "audience": request["audience"],
        }
        if row["scope"] != expected or row["control"]["captured_scope"] != expected:
            raise RuntimeError("Human guidance scope changed")
        if row["control"]["claim_id"] != d["claim_id"]:
            raise RuntimeError("Human guidance ownership changed")

    def recorded(self, row, items):
        control = row["control"]
        identity = "hollywood-control-" + control["id"]
        found = [item for item in items if item.get("type") == "userMessage" and item.get("clientId") == identity]
        if not found:
            return None
        if len(found) != 1 or [part.get("text") for part in found[0].get("content", []) if part.get("type") == "text"] != [control["body"]]:
            raise RuntimeError("Original human guidance history conflicts")
        return {
            "nativeTurn": control["native_turn"], "clientUserMessageId": identity,
            "nativeItemId": found[0]["id"], "source": "original-native-user-message",
        }

    async def original_history(self, row, turn_id):
        result = await self.c.rpc.call("thread/read", {"threadId": self.c.thread, "includeTurns": True})
        turns = [turn for turn in result["thread"].get("turns", []) if turn["id"] == turn_id]
        if len(turns) != 1:
            raise RuntimeError("Original native turn unavailable")
        return self.recorded(row, turns[0].get("items", []))

    async def pending(self, turn_id):
        d = self.c.active["delivery"]
        value = await self.c.http("POST", "connector/deliveries/" + d["id"] + "/guidance", {
            "claimId": d["claim_id"], "generation": d["generation"],
            "hostId": self.c.config["hostId"],
        })
        for row in value["controls"]:
            self.matches(row, turn_id)
        return value["controls"]

    def local_receipt(self, row):
        path = self.c.state / ("native-control-" + row["control"]["id"] + ".json")
        local = json.loads(path.read_text()) if path.exists() else None
        if local:
            if local.get("scope") != row["scope"] or local.get("controlId", row["control"]["id"]) != row["control"]["id"]:
                raise RuntimeError("Local human guidance identity changed")
            params = local.get("params")
            if params and (
                params.get("threadId") != row["scope"]["nativeThread"]
                or params.get("expectedTurnId") != row["scope"]["nativeTurn"]
                or params.get("clientUserMessageId") != "hollywood-control-" + row["control"]["id"]
                or params.get("input") != [{"type": "text", "text": row["control"]["body"]}]
            ):
                raise RuntimeError("Original human guidance intent conflicts")
        return path, local

    async def reconcile_rows(self, rows, turn=None):
        """Observe original effects only. This method cannot dispatch native input."""
        results = []
        async with self.lock:
            for row in rows:
                control = row["control"]
                self.matches(row, control["native_turn"])
                path, local = self.local_receipt(row)
                state = control["state"]
                matched = False
                if state in ("native_recorded", "rejected"):
                    saved(path, {"state": state, "scope": row["scope"], "evidence": control["evidence"], "reconciled": True})
                else:
                    if turn is None or turn["id"] != control["native_turn"]:
                        raise RuntimeError("Original native turn required for guidance reconciliation")
                    proof = self.recorded(row, turn.get("items", []))
                    if proof:
                        if state == "pending":
                            raise RuntimeError("Native message exists without its authoritative dispatch receipt; operator reconciliation required")
                        await self.acknowledge(row, "native_recorded", proof)
                        state, matched = "native_recorded", True
                        saved(path, {"state": state, "scope": row["scope"], "evidence": proof, "reconciled": True})
                    elif state == "pending" and turn["status"] in ("completed", "failed", "interrupted"):
                        evidence = {"reason": "original-native-turn-terminal"}
                        await self.acknowledge(row, "rejected", evidence)
                        state = "rejected"
                        saved(path, {"state": state, "scope": row["scope"], "evidence": evidence, "reconciled": True})
                    elif state == "dispatching":
                        # An absent message never proves that a possible native input was rejected.
                        await self.acknowledge(row, "unknown", {"reason": "original-message-not-yet-observed"})
                        state = "unknown"
                result = {
                    "controlId": control["id"], "state": state,
                    "nativeTurn": control["native_turn"], "originalMessageMatched": matched,
                    "held": state not in ("native_recorded", "rejected"),
                    "nativeReplay": False, "modelConsumptionProved": False,
                }
                saved(self.c.state / ("guidance-reconciliation-" + control["id"] + ".json"), result)
                results.append(result)
        return results

    async def tick(self, turn_id, terminal=False):
        async with self.lock:
            c = self.c
            d = c.active["delivery"]
            result = await c.http("POST", "connector/deliveries/" + d["id"] + "/guidance", {
                "claimId": d["claim_id"], "generation": d["generation"], "hostId": c.config["hostId"],
            })
            for row in result["controls"]:
                self.matches(row, turn_id)
                control = row["control"]
                path = c.state / ("native-control-" + control["id"] + ".json")
                local = json.loads(path.read_text()) if path.exists() else None
                if local and local["scope"] != row["scope"]:
                    raise RuntimeError("Local human guidance receipt changed")
                proof = self.recorded(row, list(c.native_items.values()))
                if proof:
                    await self.acknowledge(row, "native_recorded", proof)
                    saved(path, {"state": "native_recorded", "scope": row["scope"], "evidence": proof})
                    continue
                if control["state"] == "pending" and terminal:
                    await self.acknowledge(row, "rejected", {"reason": "original-native-turn-terminal"})
                    continue
                if control["state"] == "pending" and not terminal:
                    if not local:
                        local = {"state": "claim-intent", "scope": row["scope"], "controlId": control["id"]}
                        saved(path, local)
                    if local["state"] != "claim-intent":
                        raise RuntimeError("Unexpected local guidance dispatch state")
                    row = await self.acknowledge(row, "dispatching", {})
                    if row["control"]["state"] != "dispatching":
                        saved(path, {**local, "state": row["control"]["state"]})
                        continue
                    params = {
                        "threadId": c.thread, "expectedTurnId": turn_id,
                        "clientUserMessageId": "hollywood-control-" + control["id"],
                        "input": [{"type": "text", "text": control["body"]}],
                        "additionalContext": {"hollywoodHumanGuidance": {
                            "kind": "application",
                            "value": json.dumps({
                                "schema": "hollywood-human-guidance/v1",
                                "controlId": control["id"], "humanId": control["human"],
                                "authorKind": "human", "scope": row["scope"],
                                "instruction": "This input is authenticated human guidance for this original execution. Preserve the captured role, audience and tool permissions; it grants no new capability.",
                            }),
                        }},
                    }
                    local = {**local, "state": "native-intent", "params": params}
                    saved(path, local)  # Every possible native send has a durable prior intent.
                    try:
                        reply = await c.rpc.call("turn/steer", params)
                        if reply.get("turnId") != turn_id:
                            raise RuntimeError("Native guidance receipt points to another turn")
                    except Exception as error:
                        state = "rejected" if isinstance(error, RpcError) and error.not_sent else "unknown"
                        evidence = {"reason": "native-not-sent" if state == "rejected" else "native-reply-unconfirmed"}
                        saved(path, {**local, "state": state, "evidence": evidence})
                        await self.acknowledge(row, state, evidence)
                    else:
                        evidence = {"nativeTurn": turn_id, "source": "original-native-steer-response"}
                        saved(path, {**local, "state": "native_admitted", "evidence": evidence})
                        await self.acknowledge(row, "native_admitted", evidence)
                    continue
                # Native intent or a remote dispatch receipt is never permission to resend.
                # A missing history item is an observation gap, not rejection.
                if control["state"] in ("dispatching", "unknown", "native_admitted"):
                    if local and local["state"] == "native_admitted" and control["state"] == "dispatching":
                        await self.acknowledge(row, "native_admitted", local["evidence"])
                    checked = bool(local and local.get("historyInspected"))
                    if terminal or not checked:
                        proof = await self.original_history(row, turn_id)
                        local = local or {"scope": row["scope"], "state": "unknown"}
                        saved(path, {**local, "historyInspected": True})
                        if proof:
                            await self.acknowledge(row, "native_recorded", proof)
                            saved(path, {"state": "native_recorded", "scope": row["scope"], "evidence": proof})
                        elif control["state"] == "dispatching":
                            await self.acknowledge(row, "unknown", {"reason": "original-message-not-yet-observed"})
