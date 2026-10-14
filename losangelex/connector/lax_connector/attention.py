"""Deliver authenticated Hollywood human controls to the exact waiting LAX call."""

import asyncio
import json
from uuid import UUID, uuid5

QUESTION = ("hollywood/question", "item/tool/requestUserInput")
APPROVAL = ("item/commandExecution/requestApproval", "item/fileChange/requestApproval")


class AttentionExpired(Exception):
    """The original execution ended; no response or approval was inferred."""


class Attention:
    def __init__(self, connector):
        self.connector = connector
        self.pending = {}
        self.rpc_slots = {}

    async def wait(self, method, params, *, slot):
        from .connector import saved

        c = self.connector
        journal = json.loads(c.journal.read_text())
        turn = journal.get("nativeTurn")
        if (
            not turn
            or params.get("threadId", c.thread) != c.thread
            or params.get("turnId", turn) != turn
        ):
            raise RuntimeError("Human control belongs to another native execution")
        delivery = c.active["delivery"]
        identity = str(uuid5(UUID(delivery["id"]), method + ":" + str(slot)))
        path = c.state / ("attention-" + identity + ".json")
        if path.exists():
            raise RuntimeError(
                "Original native attention intent exists; reconcile it without replay"
            )
        if method in QUESTION:
            request = {"questions": params["questions"], "isBlocking": True}
            summary = "\n".join(q["question"] for q in params["questions"])
        elif method in APPROVAL:
            item = c.native_items.get(params.get("itemId"), {})
            request = {
                "command": params.get("command"),
                "cwd": params.get("cwd"),
                "reason": params.get("reason"),
                "changes": item.get("changes"),
            }
            summary = (
                "Approval required for command " + request["command"]
                if request["command"]
                else "Approval required for file changes"
            )
        else:
            raise ValueError("Unsupported native human control")
        payload = {
            "id": identity,
            "deliveryId": delivery["id"],
            "claimId": delivery["claim_id"],
            "generation": delivery["generation"],
            "nativeThread": c.thread,
            "nativeTurn": turn,
            "nativeSlot": str(slot),
            "method": method,
            "request": request,
            "summary": summary,
        }
        saved(path, {"state": "create-intent", "payload": payload})
        try:
            receipt = await c.http("POST", "attention", payload)
        except Exception:
            # Read the SAME deterministic identity after an unconfirmed create.
            # Failure to establish it holds the original call; no replacement.
            receipt = await c.http("GET", "attention/" + identity)
            captured = receipt["scope"]
            if (
                captured["deliveryId"],
                captured["nativeThread"],
                captured["nativeTurn"],
            ) != (delivery["id"], c.thread, turn):
                raise RuntimeError(
                    "Attention readback belongs to another native execution"
                )
        self.pending[str(slot)] = {
            "identity": identity,
            "path": path,
            "receipt": receipt,
        }
        self.rpc_slots[str(params["_rpcRequestId"])] = str(slot)
        saved(path, {"state": "waiting", "payload": payload, "receipt": receipt})
        while not c.finished.done():
            try:
                current = await c.http("GET", "attention/" + identity)
            except Exception as error:
                from .connector import HttpFailure

                if isinstance(error, HttpFailure) and error.status in (400, 403, 409):
                    raise
                saved(
                    c.state / "attention-observation-gap.json",
                    {
                        "attentionId": identity,
                        "error": type(error).__name__,
                        "nativeResponseReplayed": False,
                    },
                )
                await asyncio.sleep(1)
                continue
            state = current["attention"]["state"]
            if state == "response_submitted":
                # Persist before returning into the JSON-RPC write boundary. A
                # subsequent crash cannot justify resending the response slot.
                saved(
                    path,
                    {
                        "state": "native-response-intent",
                        "payload": payload,
                        "receipt": current,
                        "response": current["attention"]["response"],
                    },
                )
                self.pending[str(slot)]["receipt"] = current
                return current["attention"]["response"]
            if state != "pending":
                if state in ("expired", "closed"):
                    saved(
                        path, {"state": state, "payload": payload, "receipt": current}
                    )
                    raise AttentionExpired("Original native attention expired")
                raise RuntimeError(
                    "Original native attention no longer accepts this response"
                )
            await asyncio.sleep(1)
        try:
            await self.acknowledge(str(slot), "expired")
        except Exception as error:
            saved(
                c.state / "attention-expiry-gap.json",
                {
                    "attentionId": identity,
                    "error": type(error).__name__,
                    "nativeResponseReplayed": False,
                },
            )
        raise AttentionExpired("Original native turn ended before the human response")

    async def acknowledge(self, slot, state):
        from .connector import saved

        c = self.connector
        item = self.pending.get(str(slot))
        if not item:
            return
        d = c.active["delivery"]
        payload = {
            "operationId": "lax-attention:" + item["identity"] + ":" + state,
            "claimId": d["claim_id"],
            "generation": d["generation"],
            "scope": item["receipt"]["scope"],
            "state": state,
        }
        record = json.loads(item["path"].read_text())
        saved(item["path"], {**record, "acknowledgementIntent": payload})
        result = await c.http(
            "POST", "attention/" + item["identity"] + "/acknowledge", payload
        )
        saved(item["path"], {**record, "state": state, "acknowledgement": result})

    async def submitted(self, method, params, success):
        slot = self.rpc_slots.get(str(params.get("_rpcRequestId")))
        if slot not in self.pending:
            return
        record = json.loads(self.pending[slot]["path"].read_text())
        if record["state"] in ("closed", "expired"):
            return
        await self.acknowledge(
            slot,
            "native_submitted"
            if success and record["state"] == "native-response-intent"
            else "unknown",
        )
