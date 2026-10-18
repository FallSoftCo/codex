"""Local durable log outbox; observing an item never invokes another model."""

import asyncio
import hashlib
import json


class Activity:
    def __init__(self, connector=None, *, state=None, scope=None, send=None, secrets=()):
        self.connector = connector
        self.state = connector.state if connector is not None else state
        self.scope = scope
        self.send = send
        self.secrets = tuple(secrets) if connector is None else (connector.config["token"],)
        if connector is None and (state is None or scope is None or send is None):
            raise ValueError("An explicit execution scope and log transport are required")
        self.pending = {}
        self.task = None
        self.wake = asyncio.Event()

    def record(self, method, params):
        from .journal import saved

        c = self.connector
        captured = self.scope() if self.scope is not None else None
        if self.scope is not None and captured is None:
            return
        if captured is not None:
            execution_scope = captured.as_dict()
            thread, turn = execution_scope["nativeThread"], execution_scope["nativeTurn"]
            d = {"id": execution_scope["deliveryId"], "claim_id": execution_scope["claimId"],
                 "generation": execution_scope["generation"]}
        else:
            execution_scope = None
            thread = c.thread
            turn = json.loads(c.journal.read_text()).get("nativeTurn")
            d = c.active["delivery"]
        if (
            method in ("turn/plan/updated", "hollywood/goalProgress")
            and params.get("threadId") == thread
        ):
            raw = {"method": method, "params": params}
            item = {
                "type": "planUpdate" if method == "turn/plan/updated" else "goalState",
                "id": hashlib.sha256(
                    json.dumps(raw, sort_keys=True).encode()
                ).hexdigest(),
                "status": "completed",
            }
            if method == "turn/plan/updated":
                item.update(
                    plan=params["plan"],
                    text=params.get("explanation") or "Execution plan updated",
                )
            else:
                item.update(
                    nativeGoal=params["goal"],
                    text="Native goal " + params["goal"]["status"],
                )
            params = {**params, "item": item}
            method = "item/completed"
        if (
            method not in ("item/started", "item/completed")
            or params.get("threadId") != thread
        ):
            return
        if not turn or params.get("turnId") != turn:
            raise RuntimeError("Native activity belongs to another captured turn")
        item = params["item"]
        kind = item["type"]
        if execution_scope is not None and kind not in ("commandExecution", "fileChange", "planUpdate"):
            return  # Internal text and context tools never become outward communication.
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
            value = str(value)
            for secret in self.secrets:
                if secret:
                    value = value.replace(secret, "[REDACTED]")
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
        elif kind in ("planUpdate", "goalState"):
            title = (
                "Plan"
                if kind == "planUpdate"
                else "Goal status: " + item["nativeGoal"]["status"]
            )
            detail = item.get("text")
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
        plan = None
        if kind == "planUpdate":
            raw_plan = item.get("plan", [])
            plan = [
                {
                    "step": excerpt(step.get("step") or "(unnamed step)", 200),
                    "status": step["status"],
                }
                for step in raw_plan[:32]
            ]
            truncated |= len(plan) != len(raw_plan)
        public = {
            "nativeType": kind,
            "plan": plan,
            "nativeGoal": item.get("nativeGoal"),
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
        payload = {
            "claimId": d["claim_id"],
            "generation": d["generation"],
            "nativeThread": thread,
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
        path = self.state / ("activity-" + identity + ".json")
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
                    **({"executionScope": execution_scope} if execution_scope is not None else {}),
                    "payload": payload,
                    "nativeItem": item,
                },
            )
        self.pending[path] = d["id"]
        self.wake.set()

    def start(self):
        if self.task and not self.task.done():
            raise RuntimeError("Activity outbox already has a live scope")
        self.pending.clear()
        self.wake.clear()
        c = self.connector
        for path in self.state.glob("activity-*.json"):
            # Diagnostic files share the prefix, but are not outbox records.
            # Preserve them as evidence without letting them block later work.
            identity = path.name[len("activity-"):-len(".json")]
            if len(identity) != 64 or any(v not in "0123456789abcdef" for v in identity):
                continue
            record = json.loads(path.read_text())
            if (
                record["state"] != "accepted"
                and (self.send is not None and "executionScope" in record
                     or c is not None and record["deliveryId"] == c.active["delivery"]["id"])
            ):
                self.pending[path] = record["deliveryId"]
        self.task = asyncio.create_task(self.drain())
        self.wake.set()

    async def drain(self):
        from .journal import saved

        c = self.connector
        while True:
            await self.wake.wait()
            self.wake.clear()
            for path, delivery in list(self.pending.items()):
                record = json.loads(path.read_text())
                try:
                    if self.send is not None:
                        receipt = await self.send(record)
                    else:
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
                        self.state / "activity-observation-gap.json",
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
