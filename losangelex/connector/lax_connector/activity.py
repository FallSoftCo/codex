"""Local durable log outbox; observing an item never invokes another model."""

import asyncio
import hashlib
import json


class Activity:
    def __init__(self, connector):
        self.connector = connector
        self.pending = {}
        self.task = None
        self.wake = asyncio.Event()

    def record(self, method, params):
        from .connector import saved

        c = self.connector
        if (
            method not in ("item/started", "item/completed")
            or params.get("threadId") != c.thread
        ):
            return
        record = json.loads(c.journal.read_text())
        turn = record.get("nativeTurn")
        if not turn or params.get("turnId") != turn:
            raise RuntimeError("Native activity belongs to another captured turn")
        item = params["item"]
        kind = item["type"]
        if kind in ("userMessage", "hookPrompt", "reasoning", "functionCallOutput"):
            return
        if kind == "agentMessage" and (
            method != "item/completed" or item.get("phase") == "final_answer"
        ):
            return  # Final result already has its own durable delivery receipt.
        phase = method.split("/")[1]
        status = "inProgress" if phase == "started" else item.get("status", "completed")
        if status not in ("inProgress", "completed", "failed", "declined"):
            status = "unknown"
        if phase == "completed" and status == "inProgress":
            status = "unknown"
        truncated = False

        def excerpt(value, budget):
            nonlocal truncated
            if value is None:
                return None
            value = str(value).replace(c.config["token"], "[REDACTED]")
            encoded = value.encode()
            if len(encoded) > budget:
                truncated = True
                return encoded[:budget].decode(errors="ignore")
            return value

        detail = None
        changes = None
        if kind == "commandExecution":
            title = "Command"
            detail = item.get("aggregatedOutput")
        elif kind == "fileChange":
            title = "File changes"
            changes = []
            for change in item.get("changes", [])[:50]:
                changes.append(
                    {
                        "path": excerpt(change.get("path", ""), 256),
                        "kind": change.get("kind"),
                        "diff": excerpt(change.get("diff", ""), 600),
                    }
                )
                if len(json.dumps(changes).encode()) > 5000:
                    changes.pop()
                    truncated = True
                    break
            truncated |= len(changes) < len(item.get("changes", []))
        elif kind in ("dynamicToolCall", "mcpToolCall", "collabAgentToolCall"):
            title = str(item.get("tool", kind))
            # A read tool may return another room's private history or a protected
            # credential capability. Never republish arbitrary tool payloads into
            # the originating room. The full item stays in the private journal.
            detail = "Native tool payload retained in the protected execution journal."
        elif kind in ("agentMessage", "plan"):
            title = "Message" if kind == "agentMessage" else "Plan"
            detail = item.get("text")
        else:
            title = kind
            detail = json.dumps(item, ensure_ascii=False, default=str)
        output = excerpt(
            detail,
            6000
            if kind in ("agentMessage", "plan")
            else (3000 if changes is None else 500),
        )
        public = {
            "nativeType": kind,
            "title": excerpt(title, 1000),
            "status": status,
            "command": excerpt(item.get("command"), 2500),
            "cwd": excerpt(item.get("cwd"), 1024),
            "output": output,
            "outputTruncated": detail is not None and output != str(detail),
            "detailsTruncated": truncated,
            "changes": changes,
            "exitCode": item.get("exitCode"),
            "durationMs": item.get("durationMs"),
        }
        raw_digest = hashlib.sha256(
            json.dumps(item, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        d = c.active["delivery"]
        payload = {
            "claimId": d["claim_id"],
            "generation": d["generation"],
            "nativeThread": c.thread,
            "nativeTurn": turn,
            "itemId": item["id"],
            "phase": phase,
            "nativeItemDigest": raw_digest,
            "item": public,
        }
        # The API bounds encoded bytes, not Python characters. Preserve explicit
        # excerpt flags for Unicode and JSON-escaped output too.
        while len(json.dumps(payload).encode()) > 13000:
            field = max(
                ("output", "command", "title", "cwd"),
                key=lambda key: len(json.dumps(public.get(key)).encode()),
            )
            value = public[field]
            if not value or len(value) < 2:
                public["changes"] = None
            else:
                public[field] = value[: max(1, len(value) // 2)]
            public["detailsTruncated"] = True
            if field == "output":
                public["outputTruncated"] = True
        identity = hashlib.sha256(
            json.dumps([d["id"], d["generation"], turn, item["id"], phase]).encode()
        ).hexdigest()
        path = c.state / ("activity-" + identity + ".json")
        if path.exists():
            old = json.loads(path.read_text())
            if old["payload"] != payload:
                raise RuntimeError("Native activity changed immutable identity")
            if old["state"] == "accepted":
                return
        else:
            saved(
                path,
                {
                    "state": "intent",
                    "deliveryId": d["id"],
                    "payload": payload,
                    "nativeItem": item,
                },
            )
        self.pending[path] = d["id"]
        self.wake.set()

    def start(self):
        c = self.connector
        for path in c.state.glob("activity-*.json"):
            record = json.loads(path.read_text())
            if (
                record["state"] != "accepted"
                and record["deliveryId"] == c.active["delivery"]["id"]
            ):
                self.pending[path] = record["deliveryId"]
        self.task = asyncio.create_task(self.drain())
        self.wake.set()

    async def drain(self):
        from .connector import saved

        c = self.connector
        while True:
            await self.wake.wait()
            self.wake.clear()
            for path, delivery in list(self.pending.items()):
                record = json.loads(path.read_text())
                try:
                    receipt = await c.http(
                        "POST",
                        "connector/deliveries/" + delivery + "/activity",
                        record["payload"],
                    )
                    saved(path, {**record, "state": "accepted", "receipt": receipt})
                    del self.pending[path]
                except Exception as error:
                    # Retry only this immutable log operation; never any command,
                    # model turn, approval or replacement execution.
                    saved(
                        c.state / "activity-observation-gap.json",
                        {
                            "deliveryId": delivery,
                            "error": type(error).__name__,
                            "journal": path.name,
                            "executionReplayed": False,
                        },
                    )
                    break
            if self.pending:
                await asyncio.sleep(1)
                self.wake.set()

    async def flush(self, timeout=15):
        async def settled():
            while self.pending:
                self.wake.set()
                await asyncio.sleep(0.1)

        await asyncio.wait_for(settled(), timeout)

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
