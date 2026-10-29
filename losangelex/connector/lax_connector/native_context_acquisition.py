"""Explicit idle collection for an existing native context, never a preview fallback.

The local journal records admission, not server-side deduplication. A lost reply
blocks further work until native original-operation observation and independent
file proof agree. It never permits another collect.
"""
import asyncio
import hashlib
import json
import os

from .automatic_refill_data import require
from .automatic_refill_history import _open, _prefix, capture
from .automatic_refill_recovery import connection
from .idle_context_review import runtime_identity
from .journal import saved

SCHEMA = "lax-native-context-acquisition/v1"
PRODUCER_REFUSAL = str({
    "code": -32600,
    "message": "native preflight refused: native prefix unavailable: "
               "complete native producer unavailable, invalid or changed; normal acquisition required",
})


def verify_append(original, cut, operation_id):
    """Observe native-owned records, not model text or an execution certificate."""
    stream, info = _open(original["path"])
    with stream:
        require((info.st_dev, info.st_ino) == (original["device"], original["inode"])
                and 0 < original["beforeBytes"] < info.st_size <= 256 * 1024**2
                and info.st_size - original["beforeBytes"] <= 2 * 1024**2,
                "Original native acquisition append is absent or exceeds bounds")
        require(_prefix(stream, original["beforeBytes"]) == original["beforeSha256"],
                "Original pre-acquisition history changed")
        stream.seek(original["beforeBytes"])
        rows = []
        while stream.tell() < info.st_size:
            raw = stream.readline(2 * 1024**2 + 1)
            require(raw.endswith(b"\n") and len(raw) <= 2 * 1024**2,
                    "Native acquisition record is incomplete or oversized")
            rows.append(json.loads(raw))
            require(len(rows) <= 258, "Native acquisition record count exceeds bounds")
        require(len(rows) >= 2
                and all(row.get("type") == "response_item" for row in rows[:-2])
                and rows[-2].get("type") == "turn_context"
                and rows[-1].get("type") == "world_state",
                "Original acquisition span contains a task, effect or replacement")
        reference, checkpoint = rows[-2]["payload"], rows[-1]["payload"]
        producer = checkpoint.get("native_context_producer", {})
        source = producer.get("source", {})
        require(checkpoint.get("full") is True
                and source.get("schema") == "lax-native-context-producer/v1"
                and source.get("thread_id") == cut["threadId"]
                and source.get("context_id") == cut["contextId"]
                and source.get("acquisition") == {"operation_id": operation_id, "state": cut}
                and source.get("reference") == reference
                and source.get("acquired_step") == reference
                and reference.get("turn_id") == cut["lastStartedTurnId"]
                and source.get("template", {}).get("snapshot")
                    == checkpoint.get("state")
                and isinstance(producer.get("sha256"), str)
                and len(producer["sha256"]) == 64,
                "Original native acquisition producer binding differs")
        from .native_context_checkpoint import canonical_native, _member
        raw_checkpoint = _member(raw.decode("utf-8"), "payload")
        raw_producer = _member(raw_checkpoint, "native_context_producer")
        raw_source = _member(raw_producer, "source")
        require(hashlib.sha256(canonical_native(raw_source)).hexdigest() == producer["sha256"],
                "Original acquisition source digest differs")
        digest = _prefix(stream, info.st_size)
        after = os.fstat(stream.fileno())
        require((info.st_dev, info.st_ino, info.st_size) ==
                (after.st_dev, after.st_ino, after.st_size),
                "Original acquisition changed during observation")
    return {"historyBytes": info.st_size, "historySha256": digest,
            "producerSha256": producer["sha256"], "modelTurnsStarted": 0,
            "windowReplaced": False, "effectsReplayed": False}


class NativeContextAcquisition:
    def __init__(self, runner):
        self.runner = runner
        self.root = runner.state / "native-context-acquisition"
        self.unresolved = {
            path.name for path in self.root.glob("*.json")
            if json.loads(path.read_text()).get("state") != "confirmed"
        }

    @property
    def blocked(self):
        return bool(self.unresolved)

    async def run(self, operation_id):
        r = self.runner
        require(getattr(r.agent, "acquire_context_operation", None) == operation_id
                and r.purpose == "writer" and isinstance(operation_id, str)
                and 0 < len(operation_id.encode()) <= 256,
                "Explicit Writer-only native acquisition operation required")
        key = hashlib.sha256(operation_id.encode()).hexdigest()
        path = self.root / (key + ".json")
        captured = connection(r)
        identity = {"agentId": r.config["agentId"],
                    "contextId": r.config["contextIds"][r.purpose],
                    "purpose": r.purpose, "threadId": r.thread}
        if path.exists():
            original_bytes = path.read_bytes()
            old = json.loads(original_bytes)
            require(old.get("schema") == SCHEMA and old.get("operationId") == operation_id
                    and old.get("identity") == identity, "Original acquisition owner changed")
            if old.get("state") == "confirmed":
                return old
            # Native verifies its current producer and original admission source.
            # No collect is sent on this branch, including after cold restart.
            return await self.observe(path, captured)
        async with r.effect_lock:
            require(not self.blocked and not r.automatic.blocked and not r.failed
                    and not r.active and not r.accepting and not r.closing
                    and not r.agent.stop.is_set(),
                    "Original context has another active or unresolved operation")
            self.root.mkdir(mode=0o700, exist_ok=True)
            require(not path.exists(), "Original acquisition already exists; inspect it")
            observed = await r.rpc.call("thread/read", {"threadId": r.thread, "includeTurns": False})
            history = await asyncio.to_thread(capture, observed["thread"], r.thread)
            cut = (await r.rpc.call("thread/contextWindow/read", {"threadId": r.thread}))["state"]
            require(all(cut.get(k) == v for k, v in identity.items() if k != "agentId")
                    and cut["idle"] is True and cut["activeTurnId"] is None
                    and cut["heldOperationId"] is None and cut["lastStartedTurnId"]
                    and "producerSha256" in cut and cut["producerSha256"] is None
                    and connection(r) == captured, "Original context is not an owned idle cut")
            old = {"schema": SCHEMA, "operationId": operation_id, "identity": identity,
                   "state": "dispatch_intent", "before": cut, "originalHistory": history,
                   "runtime": runtime_identity(r)}
            saved(path, old)
            self.unresolved.add(path.name)
        try:
            result = await r.rpc.call("thread/contextWindow/acquireIdle",
                                      {"threadId": r.thread, "state": cut, "operationId": operation_id}, timeout=75)
            after = result["state"]
            require(set(after) == set(cut)
                    and all(after[k] == v for k, v in cut.items() if k != "producerSha256")
                    and isinstance(after["producerSha256"], str)
                    and len(after["producerSha256"]) == 64,
                    "Native acquisition did not expose the new producer at the original idle cut")
            return await self.observe(path, captured)
        except BaseException as error:
            # The dispatch intent stays durable even if cancellation or I/O fails.
            r.trace("native_context_acquisition_held",
                    {"operationId": operation_id, "error": str(error)[:1000],
                     "collectionRepeated": False})
            raise

    async def observe(self, path, captured):
        r = self.runner
        original_bytes = path.read_bytes()
        old = json.loads(original_bytes)
        require(runtime_identity(r) == old["runtime"],
                "Original acquisition runtime changed; no release")
        result = await r.rpc.call("thread/contextWindow/readAcquisition", {
            "threadId": r.thread, "operationId": old["operationId"]})
        after, receipt = result["state"], result["receipt"]
        before = old["before"]
        require(set(after) == set(before)
                and all(after[k] == v for k, v in before.items()
                        if k not in ("historyVersion", "producerSha256"))
                and before.get("producerSha256") is None
                and isinstance(after.get("producerSha256"), str)
                and type(after["historyVersion"]) is int and after["historyVersion"] >= 0
                and set(receipt) == {"operationId", "sourceState", "producerSha256"}
                and receipt["operationId"] == old["operationId"]
                and receipt["sourceState"] == before,
                "Original acquisition native receipt/cut differs")
        proof = await asyncio.to_thread(
            verify_append, old["originalHistory"], before, old["operationId"])
        require(after["producerSha256"] == receipt["producerSha256"] == proof["producerSha256"],
                "Native original-operation receipt differs from recorded producer")
        async with r.effect_lock:
            require(connection(r) == captured and not r.agent.stop.is_set()
                    and path.read_bytes() == original_bytes,
                    "Original acquisition changed while observing")
            old.update(state="confirmed", after=after, nativeAppend=proof,
                       nativeObservation=receipt)
            saved(path, old)
            self.unresolved.discard(path.name)
        return old

