"""Mechanical primary input views reconstructed from canonical Hollywood state.

A native queue acknowledgement is not durable history or interpretation.
Snapshots are refreshed for each reader inference; canonical input/work states
prevent duplicate task acceptance. Uncertain model turns keep their separate
existing admission/recovery hold. Rebuilding a view never re-posts a message or
replays a tool, task, peer request or external effect.
"""
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

    async def recover(self):
        journals = []
        for path in self.directory.glob("*.json"):
            old = json.loads(path.read_text())
            if old.get("state") in ("intent", "appended", "accepted"):
                journals.append((path, old))
        if not journals:
            return
        result = await self.runner.rpc.call("thread/read",
            {"threadId": self.runner.thread, "includeTurns": False})
        path = Path(result["thread"]["path"])
        def outputs(value):
            if isinstance(value, dict):
                if value.get("type") == "function_call_output":
                    yield value.get("output")
                for child in value.values():
                    yield from outputs(child)
            elif isinstance(value, list):
                for child in value:
                    yield from outputs(child)
        present = set()
        with path.open() as history:
            for line in history:
                if line.strip():
                    for output in outputs(json.loads(line)):
                        if isinstance(output, str):
                            present.add(hashlib.sha256(output.encode()).hexdigest())
        observations = []
        for journal, old in journals:
            retained = sum(hashlib.sha256(item["output"].encode()).hexdigest() in present
                           for item in old["items"])
            observations.append({"journal": journal.name, "operation": old["operation"],
                "originalState": old["state"], "fragments": len(old["items"]),
                "retainedFragments": retained,
                "historyObserved": retained == len(old["items"])})
        saved(self.directory / "recovery-observation.json", {
            "nativeThread": self.runner.thread, "batches": observations,
            "meaning": "History observation only. Original receipts unchanged. Current canonical pending inputs are refreshed before a newly admitted inference.",
            "modelTurnsStarted": 0, "operationsReplayed": 0})
        self.runner.trace("reader_input_recovery_observed", {
            "batches": len(observations),
            "incompleteHistoryBatches": sum(not o["historyObserved"] for o in observations),
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
        self.runner.trace("reader_input_adopted", result)

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
            if not runner.accepting or runner.finished.done():
                return
            batch = await self.append(incoming)
            await self.adopt(batch)
