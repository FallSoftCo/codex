"""Automatic, journaled primary input delivery through the native context API."""
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
        uncertain = [p for p in self.directory.glob("*.json")
                     if json.loads(p.read_text()).get("state") == "intent"]
        if not uncertain:
            return
        result = await self.runner.rpc.call("thread/read",
            {"threadId": self.runner.thread, "includeTurns": False})
        path = Path(result["thread"]["path"])
        # Inspect the exact retained native record. Absence cannot authorize replay.
        records = [json.loads(line) for line in path.read_text().splitlines() if line]
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
        for record in records:
            for output in outputs(record):
                if isinstance(output, str):
                    present.add(output)
        for journal in uncertain:
            old = json.loads(journal.read_text())
            if not all(item["output"] in present for item in old["items"]):
                raise RuntimeError("Original reader append remains uncertain; inspect its exact journal/history without retry")
            saved(journal, {**old, "state": "appended", "recoveredFromNativeHistory": True})

    async def append(self, pending):
        runner = self.runner
        selected = pending[:16]
        operation = "reader-inbox:" + str(uuid4())
        snapshot = await runner.request("inbox", {"materialIds": [r["id"] for r in selected]},
                                       operation=operation, turn="input-delivery")
        fingerprint = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
        journal = self.directory / (fingerprint + ".json")
        if journal.exists():
            old = json.loads(journal.read_text())
            if old["state"] == "appended":
                return old
            if old["state"] != "rejected":
                raise RuntimeError("Original reader append is uncertain; no replacement was submitted")
            saved(journal.with_name(journal.stem + "-rejected.json"), old)
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
        result = {**intent, "state": "appended"}
        saved(journal, result)
        runner.trace("reader_input_appended", {"snapshotOperationId": operation,
            "inputIds": snapshot["inputIds"], "chunks": len(items),
            "duringNativeTurn": runner.turn if runner.active and runner.accepting else None,
            "modelSelectedRetrieval": False, "interpretationInferred": False})
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
