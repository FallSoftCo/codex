"""Passive agent observations, one durable outstanding item, no execution admission.

All transports/capture/binding/readback inputs MUST be supplied by the trusted
connector owner, never a model tool or peer body. No listener, task, timer,
thread load/resume, turn start/steer, or native reader is created here.
"""

import asyncio
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from uuid import UUID

MAX_HINTS = 8
MAX_ITEM_BYTES = 960  # exact json.dumps(item) ASCII bytes, including escapes
MAX_RECORD_BYTES = 98304
FIELDS = (
    "id",
    "authority",
    "room",
    "author",
    "recipient",
    "kind",
    "audience",
    "source",
    "body",
    "data",
    "seq",
)


class Held(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def need(value, code):
    if not value:
        raise Held(code)


def uuid(value):
    try:
        need(isinstance(value, str) and str(UUID(value)) == value, "BAD_ID")
    except (ValueError, TypeError, AttributeError):
        raise Held("BAD_ID") from None
    return value


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")


def sha(value):
    return hashlib.sha256(wire(value)).hexdigest()


def event(value):
    need(isinstance(value, dict) and all(k in value for k in FIELDS), "BAD_EVENT")
    for k in ("id", "authority", "room", "author"):
        uuid(value[k])
    for k in ("source", "recipient"):
        if value[k] is not None:
            uuid(value[k])
    need(
        value["audience"] in ("room", "direct")
        and isinstance(value["body"], str)
        and isinstance(value["data"], dict)
        and type(value["seq"]) is int
        and value["seq"] > 0,
        "BAD_EVENT",
    )
    need(value["audience"] != "direct" or value["recipient"] is not None, "BAD_EVENT")
    need(len(value["body"].encode()) <= 65536, "EVENT_TOO_LARGE")
    return value


def event_sha(value):
    return sha({k: value[k] for k in FIELDS})


def private_scope(origin, current, actor):
    # Same guard as Global causal-context r04; a private exchange cannot widen.
    if origin["audience"] == "direct":
        need(
            current["audience"] == "direct"
            and current["room"] == origin["room"]
            and {current["author"], current["recipient"]}
            <= {origin["author"], origin["recipient"]}
            and actor in (origin["author"], origin["recipient"]),
            "PRIVATE_SCOPE",
        )


def eligibility(row, current, actor):
    if row["kind"] != "message":
        return "not_passive_message"
    if row["data"].get("authorKind") != "agent":
        return "not_agent"
    if row["author"] == actor:
        return "own_message"
    if row["data"].get("expectsReply") or row["data"].get("type") in (
        "peerCompletion",
        "executionState",
        "nativeControl",
        "attention",
        "executionActivity",
    ):
        return "not_passive_message"
    if row["audience"] == "room":
        return (
            None
            if row["room"] == current["room"] and row["recipient"] is None
            else "other_room_or_target"
        )
    if row["recipient"] != actor:
        return "not_addressed_to_principal"
    try:
        private_scope(row, current, actor)
    except Held:
        return "private_scope_incompatible"
    return None


def item_for(row, actor):
    """A native agent_message, never user/developer input or a forged tool result."""
    body = row["body"].encode()
    envelope = {
        "schema": "hollywood-passive/v1",
        "eventId": row["id"],
        "authorKind": "agent",
        "audience": row["audience"],
        "sourceEventId": row["source"],
        "sequence": row["seq"],
        "text": "",
        "bodySha256": hashlib.sha256(body).hexdigest(),
        "read": {
            "tool": "hollywood_read_room",
            "roomId": row["room"],
            "after": row["seq"] - 1,
            "limit": 1,
        },
        "obligation": "observe-only",
        "contentAuthority": "agent-data",
        "requiresDeeperRead": True,
    }
    item = {
        "type": "agent_message",
        "id": row["id"],
        "author": row["author"],
        "recipient": actor,
        "content": [{"type": "input_text", "text": ""}],
    }
    for budget in range(192, -1, -8):
        envelope["text"] = body[:budget].decode("utf-8", "ignore")
        item["content"][0]["text"] = json.dumps(envelope)
        if len(json.dumps(item).encode()) <= MAX_ITEM_BYTES:
            return item
    raise Held("ITEM_BUDGET")


class Journal:
    """Connector-owned private state outside model workspace, one writer lock.

    Protection means owner/0700 directories,0600 regular single-link files,
    no symlink traversal, atomic fsynced checkpoint and immutable event phases.
    It does not resist root administrators or code running under the same
    execution UID, including model-launched commands.
    """

    def __init__(self, directory):
        self.root = Path(directory)
        self.uid = os.geteuid()
        self._directory(self.root)
        self._directory(self.root / "events")

    def _directory(self, path):
        path.mkdir(mode=0o700, exist_ok=True)
        s = path.lstat()
        need(
            stat.S_ISDIR(s.st_mode) and s.st_uid == self.uid and not s.st_mode & 0o077,
            "UNPROTECTED_DIRECTORY",
        )

    def _file(self, path):
        s = path.lstat()
        need(
            stat.S_ISREG(s.st_mode)
            and s.st_uid == self.uid
            and not s.st_mode & 0o077
            and s.st_nlink == 1
            and s.st_size <= MAX_RECORD_BYTES,
            "UNPROTECTED_FILE",
        )

    def get(self, name):
        path = self.root / name
        try:
            self._file(path)
        except FileNotFoundError:
            return None
        try:
            value = json.loads(path.read_text())
        except (ValueError, OSError):
            raise Held("BAD_JOURNAL") from None
        need(isinstance(value, dict), "BAD_JOURNAL")
        return value

    def put(self, name, value, *, immutable=False):
        path = self.root / name
        self._directory(path.parent)
        data = wire(value)
        need(len(data) <= MAX_RECORD_BYTES, "RECORD_BUDGET")
        if path.exists() or path.is_symlink():
            self._file(path)
        fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            if immutable:
                try:
                    os.link(temporary, path)
                except FileExistsError:
                    need(path.read_bytes() == data, "IMMUTABLE_PHASE_CONFLICT")
            else:
                os.replace(temporary, path)
            d = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(d)
            finally:
                os.close(d)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def lock(self):
        path = self.root / "writer.lock"
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            self._file(path)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(fd)
            raise
        return fd

    def phase(self, event_id, name, value=None):
        relative = "events/" + uuid(event_id)
        self._directory(self.root / relative)
        if value is not None:
            self.put(relative + "/" + name + ".json", value, immutable=True)
        return self.get(relative + "/" + name + ".json")


class PassiveReceiver:
    def __init__(self, directory, *, authority_id, principal_id, context_id, thread_id):
        self.binding = {
            "authorityId": uuid(authority_id),
            "principalId": uuid(principal_id),
            "contextId": context_id,
            "threadId": uuid(thread_id),
        }
        need(
            isinstance(context_id, str)
            and len(context_id) == 64
            and all(c in "0123456789abcdef" for c in context_id),
            "BAD_CONTEXT",
        )
        self.journal = Journal(directory)

    async def _get(self, get, path):
        try:
            value = await get(path)
        except Exception:
            raise Held("AUTHORITY_READ_UNAVAILABLE") from None
        need(isinstance(value, dict), "BAD_AUTHORITY_RESPONSE")
        return value

    async def current(self, get, captured):
        d = captured["delivery"]
        e = captured["request"]
        value = await self._get(get, "deliveries/" + uuid(d["id"]))
        actual, row, binding = (
            value.get("delivery", {}),
            event(value.get("request")),
            value.get("agentContextBinding", {}),
        )
        need(
            all(
                actual.get(k) == d.get(k)
                for k in ("id", "authority", "agent", "generation", "claim_id", "host")
            )
            and all(
                row.get(k) == e.get(k)
                for k in ("id", "authority", "room", "author", "recipient", "audience")
            ),
            "CURRENT_CAPTURE_CHANGED",
        )
        need(
            actual.get("authority") == self.binding["authorityId"]
            and actual.get("agent") == self.binding["principalId"]
            and binding.get("principal") == self.binding["principalId"]
            and binding.get("context_id") == self.binding["contextId"]
            and binding.get("native_thread") == self.binding["threadId"]
            and row["recipient"] in (None, self.binding["principalId"]),
            "CURRENT_CONTEXT_CHANGED",
        )
        need(
            actual.get("state") in ("claimed", "running")
            and not actual.get("cancellation_requested"),
            "CURRENT_DELIVERY_CLOSED",
        )
        # Only privacy metadata enters local evidence; no private request body copied.
        return {
            "deliveryId": actual["id"],
            "generation": actual["generation"],
            "claimId": actual["claim_id"],
            "room": row["room"],
            "author": row["author"],
            "recipient": row["recipient"],
            "audience": row["audience"],
            "requestId": row["id"],
            "state": actual["state"],
            "nativeTurn": actual.get("native_turn"),
        }

    def checkpoint(self):
        cp = self.journal.get("checkpoint.json")
        if cp is not None:
            need(
                cp.get("schema") == "lax-passive-cursor/v1"
                and cp.get("binding") == self.binding
                and type(cp.get("cursor")) is int
                and cp["cursor"] >= 0,
                "CURSOR_SCOPE_CHANGED",
            )
            if cp.get("pending") is not None:
                uuid(cp["pending"])
        return cp

    def _advance(self, cp, sequence):
        need(sequence >= cp["cursor"], "CURSOR_REGRESSION")
        value = {**cp, "cursor": sequence, "pending": None}
        self.journal.put("checkpoint.json", value)
        return value

    def _complete_pending(self, cp):
        event_id = cp["pending"]
        intent = self.journal.phase(event_id, "00-intent")
        done = self.journal.phase(event_id, "02-readback")
        need(intent is not None, "PENDING_INTENT_MISSING")
        if done is None:
            return None
        need(
            done["itemSha256"] == intent["itemSha256"] and done["eventId"] == event_id,
            "READBACK_CONFLICT",
        )
        return self._advance(cp, intent["sequence"])

    def _read_pending(self, cp, readback):
        completed = self._complete_pending(cp)
        if completed is not None:
            return completed
        if readback is None:
            return None
        intent = self.journal.phase(cp["pending"], "00-intent")
        evidence = readback.probe(intent)
        if evidence is None:
            return None
        self._confirm_locked(cp, evidence)
        return self.checkpoint()

    async def tick(
        self, get, inject, *, captured, loaded, connection_epoch, readback=None
    ):
        """One finite feed page / at most one inject, called by existing owner pump.

        inject MUST enqueue on the already-open shared AppServer.call connection.
        Never call this from AppServer._read/on_event while awaiting its reply.
        No normal load means zero HTTP/native activity. Idle already-loaded
        contexts are permitted while the current delivery remains claimed.
        """
        if not loaded:
            return {"state": "deferred_unloaded"}
        need(
            isinstance(connection_epoch, str) and 0 < len(connection_epoch) <= 128,
            "BAD_CONNECTION_EPOCH",
        )
        try:
            fd = self.journal.lock()
        except BlockingIOError:
            return {"state": "busy"}
        try:
            current = await self.current(get, captured)
            if readback is not None:
                need(readback.binding == self.binding, "READBACK_SCOPE_CHANGED")
                readback.check_capture(captured)
            cp = self.checkpoint()
            if cp is not None and cp.get("pending"):
                completed = self._read_pending(cp, readback)
                if completed is None:
                    return {
                        "state": "held_native_readback",
                        "eventId": cp["pending"],
                        "cursor": cp["cursor"],
                    }
                cp = completed
            if cp is None:
                head = await self._get(get, "inbox?limit=" + str(MAX_HINTS))
                self._feed(head, 0, bootstrap=True)
                cp = {
                    "schema": "lax-passive-cursor/v1",
                    "binding": self.binding,
                    "cursor": head["nextCursor"],
                    "startedAt": head["nextCursor"],
                    "pending": None,
                }
                self.journal.put("checkpoint.json", cp)
                return {"state": "initialized_forward_only", "cursor": cp["cursor"]}
            page = await self._get(
                get, "inbox?after=" + str(cp["cursor"]) + "&limit=" + str(MAX_HINTS)
            )
            self._feed(page, cp["cursor"])
            for hint in page["events"]:
                event_id = hint["eventId"]
                sequence = hint["sequence"]
                filtered = self.journal.phase(event_id, "00-filtered")
                if filtered:
                    need(filtered["sequence"] == sequence, "EVENT_SEQUENCE_CHANGED")
                    cp = self._advance(cp, sequence)
                    continue
                old = self.journal.phase(event_id, "00-intent")
                if old:
                    need(
                        old["sequence"] == sequence and old["binding"] == self.binding,
                        "EVENT_SCOPE_CHANGED",
                    )
                    cp = {**cp, "pending": event_id}
                    self.journal.put("checkpoint.json", cp)
                    if self._read_pending(cp, readback) is None:
                        return {
                            "state": "held_native_readback",
                            "eventId": event_id,
                            "cursor": cp["cursor"],
                        }
                    return {"state": "reconciled_original", "eventId": event_id}
                row = None
                if hint["kind"] != "message":
                    reason = "not_passive_message"
                elif hint["roomId"] != current["room"]:
                    reason = "other_room"
                else:
                    result = await self._get(get, "inbox/events/" + event_id)
                    row = event(result.get("event"))
                    need(
                        row["id"] == event_id
                        and row["seq"] == sequence
                        and row["authority"] == self.binding["authorityId"]
                        and row["room"] == hint["roomId"]
                        and row["kind"] == hint["kind"],
                        "HINT_EVENT_CHANGED",
                    )
                    reason = eligibility(row, current, self.binding["principalId"])
                if reason:
                    self.journal.phase(
                        event_id,
                        "00-filtered",
                        {
                            "eventId": event_id,
                            "sequence": sequence,
                            "binding": self.binding,
                            "current": current,
                            "reason": reason,
                        },
                    )
                    cp = self._advance(cp, sequence)
                    continue
                item = item_for(row, self.binding["principalId"])
                # Fence the exact same current delivery/privacy immediately before intent.
                need(
                    await self.current(get, captured) == current,
                    "CURRENT_CAPTURE_CHANGED",
                )
                need(readback is not None, "READBACK_PROVIDER_REQUIRED")
                readback.prepare(event_id, item)
                intent = {
                    "schema": "lax-passive-intent/v1",
                    "eventId": event_id,
                    "sequence": sequence,
                    "binding": self.binding,
                    "current": current,
                    "connectionEpoch": connection_epoch,
                    "eventSha256": event_sha(row),
                    "item": item,
                    "itemSha256": sha(item),
                    "method": "thread/inject_items",
                    "modelConsumptionProved": False,
                }
                self.journal.phase(event_id, "00-intent", intent)
                cp = {**cp, "pending": event_id}
                self.journal.put("checkpoint.json", cp)
                try:
                    reply = await inject(
                        "thread/inject_items",
                        {"threadId": self.binding["threadId"], "items": [item]},
                    )
                    need(reply == {}, "UNEXPECTED_NATIVE_REPLY")
                except BaseException as error:
                    self.journal.phase(
                        event_id,
                        "01-native",
                        {
                            "state": "unknown",
                            "eventId": event_id,
                            "error": type(error).__name__,
                            "resend": False,
                            "modelConsumptionProved": False,
                        },
                    )
                    if isinstance(
                        error, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)
                    ):
                        raise
                    return {
                        "state": "held_native_readback",
                        "eventId": event_id,
                        "cursor": cp["cursor"],
                    }
                self.journal.phase(
                    event_id,
                    "01-native",
                    {
                        "state": "native_acknowledged_pending_readback",
                        "eventId": event_id,
                        "reply": reply,
                        "modelConsumptionProved": False,
                        "cursorAdvanced": False,
                    },
                )
                return {
                    "state": "native_acknowledged_pending_readback",
                    "eventId": event_id,
                    "cursor": cp["cursor"],
                }
            cp = self._advance(cp, page["nextCursor"])
            return {"state": "observed_filtered_page", "cursor": cp["cursor"]}
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _feed(self, page, cursor, *, bootstrap=False):
        need(
            page.get("authorityId") == self.binding["authorityId"]
            and page.get("principalId") == self.binding["principalId"]
            and isinstance(page.get("events"), list)
            and len(page["events"]) <= MAX_HINTS
            and type(page.get("nextCursor")) is int
            and type(page.get("head")) is int
            and cursor <= page["nextCursor"] <= page["head"],
            "BAD_FEED",
        )
        if bootstrap:
            need(
                not page["events"] and page["nextCursor"] == page["head"],
                "BAD_BOOTSTRAP",
            )
        previous = cursor
        for h in page["events"]:
            need(
                isinstance(h, dict)
                and h.get("authorityId") == self.binding["authorityId"]
                and h.get("principalId") == self.binding["principalId"]
                and type(h.get("sequence")) is int
                and previous < h["sequence"] <= page["nextCursor"],
                "BAD_FEED_ORDER",
            )
            uuid(h.get("eventId"))
            uuid(h.get("roomId"))
            need(
                h.get("kind") in ("message", "result", "question", "approval"),
                "BAD_FEED_KIND",
            )
            previous = h["sequence"]

    def confirm_readback(self, evidence):
        """Trusted INTERNAL integration boundary, not an agent tool/HTTP endpoint.

        The owner must derive this evidence from an exact native persisted raw
        ResponseItem/journal read already tied to this loaded context. A synthetic
        fixture, caller digest, queue ack, absence or item-ID-only match is not a
        production provider. Its actual native route is an integration gate.
        This proves durable item readback ONLY; never model consumption.
        """
        fd = self.journal.lock()
        try:
            cp = self.checkpoint()
            need(cp and cp.get("pending"), "NO_PENDING_ITEM")
            return self._confirm_locked(cp, evidence)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _confirm_locked(self, cp, evidence):
        intent = self.journal.phase(cp["pending"], "00-intent")
        need(
            isinstance(evidence, dict)
            and evidence.get("schema") == "lax-passive-native-readback/v1"
            and evidence.get("binding") == self.binding
            and evidence.get("eventId") == cp["pending"]
            and evidence.get("item") == intent["item"]
            and evidence.get("persisted") is True
            and isinstance(evidence.get("nativeJournalLocator"), str)
            and 0 < len(evidence["nativeJournalLocator"]) <= 512,
            "READBACK_NOT_EXACT",
        )
        self.journal.phase(
            cp["pending"],
            "02-readback",
            {
                "eventId": cp["pending"],
                "itemSha256": intent["itemSha256"],
                "evidenceSha256": sha(evidence),
                "nativeJournalLocator": evidence["nativeJournalLocator"],
                "durableItemReadback": True,
                "modelConsumptionProved": False,
            },
        )
        self._advance(cp, intent["sequence"])
        return {
            "state": "durable_item_readback",
            "eventId": intent["eventId"],
            "modelConsumptionProved": False,
        }
