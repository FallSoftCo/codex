"""Mechanical primary input views reconstructed from canonical Hollywood state.

A native queue acknowledgement is not durable history or interpretation.
Snapshots are refreshed for each reader inference; canonical input/work states
prevent duplicate task acceptance. Uncertain model turns keep their separate
existing admission/recovery hold. Rebuilding a view never re-posts a message or
replays a tool, task, peer request or external effect.
"""
import asyncio
import hashlib
import json
from pathlib import Path
from uuid import uuid4
from .journal import saved


class ReaderInbox:
    def __init__(self, runner):
        self.runner = runner
        self.directory = runner.state / "input-delivery"
        self.directory.mkdir(mode=0o700, exist_ok=True)
        self.delivered = {}
        self.uncertain = False

    async def recover(self):
        journals = []
        for path in self.directory.glob("*.json"):
            old = json.loads(path.read_text())
            if old.get("state") in ("intent", "appended", "accepted"):
                journals.append((path, old))
        if not journals:
            return
        self.uncertain = True
        automatic = self.runner.automatic.policy() is not None
        result = await self.runner.rpc.call("thread/read",
            {"threadId": self.runner.thread, "includeTurns": False})
        path = Path(result["thread"]["path"])
        # Only actual history items prove retention. Nested user/tool data which
        # happens to describe a function output is not a native append receipt.
        present = set()
        with path.open() as history:
            for line in history:
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("type") == "response_item":
                    items = [row["payload"]]
                elif row.get("type") == "compacted":
                    items = row.get("payload", {}).get("replacement_history") or []
                else:
                    items = []
                for item in items:
                    if (isinstance(item, dict) and item.get("type") == "function_call_output"
                            and item.get("namespace") == "hollywood"
                            and item.get("name") == "reader_input"
                            and isinstance(item.get("output"), str)):
                        present.add(hashlib.sha256(item["output"].encode()).hexdigest())

        requests = {}
        if automatic:
            # Older runtimes kept the batch as accepted after adoption, while
            # already recording the exact adoption in their normal HTTP journal.
            # Discover its original identity; never invent a new adoption/turn.
            for operation in self.runner.state.glob("operation-*.json"):
                request = json.loads(operation.read_text()).get("request", {})
                if (request.get("action") == "inbox_adopt"
                        and request.get("nativeThread") == self.runner.thread):
                    snapshot = request.get("value", {}).get("snapshotOperationId")
                    requests.setdefault(snapshot, []).append(request)

        limit = asyncio.Semaphore(4)

        async def observe(journal, old):
            retained = sum(hashlib.sha256(item["output"].encode()).hexdigest() in present
                           for item in old["items"])
            observation = {"journal": journal.name, "operation": old["operation"],
                "originalState": old["state"], "fragments": len(old["items"]),
                "retainedFragments": retained,
                "historyObserved": retained == len(old["items"])}
            if not automatic:
                return observation
            observation["adoptionVerified"] = False
            if not observation["historyObserved"]:
                observation["holdReason"] = "Original typed native input fragments unavailable"
                return observation
            candidates = requests.get(old["operation"], [])
            if len(candidates) != 1:
                observation["holdReason"] = "Original adoption request identity unavailable or ambiguous"
                return observation
            request = candidates[0]
            turn = request.get("nativeTurn")
            operation = request.get("operationId")
            if (not isinstance(turn, str) or not turn or len(turn) > 256
                    or request.get("value") != {"snapshotOperationId": old["operation"]}
                    or operation != "reader-adopt:" + turn + ":" + old["operation"]
                    or old.get("snapshot", {}).get("nativeThread") != self.runner.thread):
                observation["holdReason"] = "Original adoption request scope differs"
                return observation
            route = (f"agents/{self.runner.config['agentId']}/contexts/reader/operations/")
            try:
                async with limit:
                    snapshot = await self.runner.agent.http("reader", "GET", route + old["operation"])
                    adopted = await self.runner.agent.http("reader", "GET", route + operation)
                revisions = {chunk["reference"]: chunk["revision"]
                             for chunk in old["snapshot"]["chunks"]}
                valid = (snapshot == old["snapshot"]
                    and snapshot.get("schema") == "lax-reader-input/v1"
                    and adopted.get("snapshotOperationId") == old["operation"]
                    and adopted.get("nativeTurn") == turn
                    and adopted.get("deliveredRevisions") == revisions
                    and adopted.get("interpretationInferred") is False)
                if not valid:
                    observation["holdReason"] = "Original snapshot or adoption receipt differs"
                    return observation
                observation.update(adoptionVerified=True, adoptionOperationId=operation,
                    snapshotReceiptSha256=hashlib.sha256(json.dumps(snapshot,
                        sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                    adoptionReceiptSha256=hashlib.sha256(json.dumps(adopted,
                        sort_keys=True, separators=(",", ":")).encode()).hexdigest())
            except Exception as error:
                observation["holdReason"] = "Original receipt observation failed: " + type(error).__name__
            return observation

        observations = await asyncio.gather(*(observe(p, old) for p, old in journals))
        unresolved = [o for o in observations if not o.get("adoptionVerified")] if automatic else []
        if automatic:
            self.uncertain = bool(unresolved)
            if unresolved:
                self.runner.failed = True
                self.runner.failure_reason = (
                    f"Original reader inbox reconciliation unresolved for {len(unresolved)} batches; "
                    "inspect original snapshot/adoption receipts, do not replay input")
            # Never clear another native-turn/refill/effect hold on this runner.
        saved(self.directory / "recovery-observation.json", {
            "nativeThread": self.runner.thread, "batches": observations,
            "meaning": "Exact typed history plus original authenticated adoption receipts. "
                "Original journals unchanged. Adoption is not interpretation or new authority; "
                "current pending input is refreshed before its next admitted inference.",
            "modelTurnsStarted": 0, "operationsReplayed": 0})
        self.runner.trace("reader_input_recovery_observed", {
            "batches": len(observations),
            "incompleteHistoryBatches": sum(not o["historyObserved"] for o in observations),
            "verifiedOriginalAdoptions": sum(o.get("adoptionVerified", False) for o in observations),
            "unresolvedOriginalBatches": len(unresolved),
            "operationsReplayed": 0, "interpretationInferred": False})

    async def append(self, pending):
        runner = self.runner
        selected = pending[:16]
        operation = "reader-inbox:" + str(uuid4())
        snapshot = await runner.request("inbox", {"materialIds": [r["id"] for r in selected]},
                                       operation=operation, turn="input-delivery")
        # An old acknowledgement must not suppress a fresh canonical input view.
        # Same-process duplicate wake delivery is bounded by delivered revisions;
        # interpretation/durable Work deduplication remains in Hollywood.
        identity = hashlib.sha256(operation.encode()).hexdigest()
        journal = self.directory / (identity + ".json")
        items = []
        for chunk in snapshot["chunks"]:
            output = json.dumps({"schema": "lax-reader-fragment/v1",
                "snapshotOperationId": operation, **chunk}, sort_keys=True)
            items.append({"type": "function_call_output", "namespace": "hollywood",
                          "name": "reader_input", "output": output})
        intent = {"state": "intent", "operation": operation, "snapshot": snapshot, "items": items}
        saved(journal, intent)
        self.uncertain = True
        try:
            await runner.rpc.call("thread/inject_items", {"threadId": runner.thread, "items": items})
        except Exception as error:
            from .rpc import RpcError
            if isinstance(error, RpcError) and (error.not_sent or error.code in (-32600, -32601, -32602)):
                saved(journal, {**intent, "state": "rejected", "nativeAppendAdmitted": False,
                                "code": error.code})
            raise
        result = {**intent, "state": "accepted", "nativeHistoryDurability": "unconfirmed"}
        saved(journal, result)
        runner.trace("reader_input_accepted", {"snapshotOperationId": operation,
            "inputIds": snapshot["inputIds"], "chunks": len(items),
            "duringNativeTurn": runner.turn if runner.active and runner.accepting else None,
            "modelSelectedRetrieval": False, "nativeHistoryDurability": "unconfirmed",
            "interpretationInferred": False})
        return result

    async def adopt(self, batch):
        result = await self.runner.request("inbox_adopt",
            {"snapshotOperationId": batch["operation"]},
            operation="reader-adopt:" + self.runner.turn + ":" + batch["operation"])
        self.runner.material_ids = result["materialIds"]
        for identity in batch["snapshot"]["inputIds"]:
            self.delivered[identity] = result["deliveredRevisions"][identity]
        journal = self.directory / (hashlib.sha256(batch["operation"].encode()).hexdigest() + ".json")
        saved(journal, {**batch, "state": "adopted", "adoption": result})
        self.runner.trace("reader_input_adopted", result)
        self.uncertain = False

    async def receive(self, pending):
        runner = self.runner
        if (not runner.active or not runner.accepting or not runner.turn
                or runner.finished is None or runner.finished.done()):
            return
        incoming = [r for r in pending if self.delivered.get(r["id"]) != r["revision"]]
        slots = 100 - len(runner.material_ids)
        incoming = [r for r in incoming if r["id"] in runner.material_ids][:16] + [
            r for r in incoming if r["id"] not in runner.material_ids][:max(0, min(16, slots))]
        incoming = incoming[:16]
        if not incoming:
            return
        async with runner.effect_lock:
            if (not runner.accepting or runner.finished.done()
                    or runner.automatic.blocked):
                return
            batch = await self.append(incoming)
            await self.adopt(batch)
