"""Read-only causal context candidate. No execution, authority or outcome mutation.

``get(path)`` MUST be the connector's authenticated GET transport, never a
model-supplied reader. An origin reference is only a delivery locator: every
body, relation, audience and cancellation state is reread canonically. Missing
old locators hold; there is no transcript search or cached-body fallback.
"""

import asyncio
import hashlib
import json
from uuid import UUID


SCHEMA = "lax-causal-task-context/v2"
REFERENCE_SCHEMA = "lax-causal-origin-reference/v2"
EVENT_FIELDS = ("id", "authority", "room", "author", "recipient", "kind",
                "audience", "source", "body", "data", "seq")


class ContextHeld(ValueError):
    """Safe, body-free refusal. The caller must not start a fallback turn."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(condition, code):
    if not condition:
        raise ContextHeld(code)


def identity(value):
    try:
        require(isinstance(value, str) and str(UUID(value)) == value, "MALFORMED_ID")
    except (ValueError, TypeError, AttributeError):
        raise ContextHeld("MALFORMED_ID") from None
    return value


def strict_object(text):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "DUPLICATE_POINTER_KEY")
            result[key] = value
        return result
    require(isinstance(text, str) and len(text.encode()) <= 4096, "MALFORMED_POINTER")
    try:
        value = json.loads(text, object_pairs_hook=pairs)
    except (ValueError, TypeError):
        raise ContextHeld("MALFORMED_POINTER") from None
    require(isinstance(value, dict), "MALFORMED_POINTER")
    return value


def pointer(event):
    data = event.get("data")
    require(isinstance(data, dict), "MALFORMED_EVENT")
    if data.get("type") != "peerCompletion":
        return None
    value = strict_object(event.get("body"))
    require(set(value) == {"type", "requestId", "resultEventId",
                           "executionState", "originRequestId"}, "MALFORMED_POINTER")
    require(value["type"] == "peer_completion", "MALFORMED_POINTER")
    for name in ("requestId", "resultEventId", "originRequestId"):
        identity(value[name])
    require(value["executionState"] in ("completed", "failed"), "UNSETTLED_CHILD")
    require(data.get("replyToRequest") == value["requestId"] and
            event.get("source") == value["resultEventId"], "POINTER_LINK_MISMATCH")
    identity(data.get("replyToDelivery"))
    return value


def event(row):
    require(isinstance(row, dict) and all(k in row for k in EVENT_FIELDS), "MALFORMED_EVENT")
    for name in ("id", "authority", "room", "author"):
        identity(row[name])
    for name in ("recipient", "source"):
        if row[name] is not None:
            identity(row[name])
    require(row["audience"] in ("room", "direct") and isinstance(row["body"], str)
            and isinstance(row["data"], dict) and type(row["seq"]) is int and row["seq"] > 0,
            "MALFORMED_EVENT")
    require(row["data"].get("authorKind") in ("human", "agent", "service"),
            "ISSUER_KIND_MISSING")
    if row["audience"] == "direct":
        require(row["recipient"] is not None, "PRIVATE_RECIPIENT_MISSING")
    return row


def receipt(value):
    require(isinstance(value, dict), "MALFORMED_RECEIPT")
    d, r = value.get("delivery"), event(value.get("request"))
    require(isinstance(d, dict), "MALFORMED_RECEIPT")
    for key in ("id", "authority", "agent", "event"):
        identity(d.get(key))
    require(type(d.get("generation")) is int and d["generation"] >= 1 and
            isinstance(d.get("claim_id"), str) and bool(d["claim_id"]) and
            type(d.get("revision")) is int and
            type(d.get("cancellation_requested")) is bool and d.get("state") in
            ("pending", "claimed", "running", "completed", "failed", "cancelled",
             "cancel_requested", "unknown"), "MALFORMED_RECEIPT")
    require(d["event"] == r["id"] and d["authority"] == r["authority"] and
            r["kind"] == "request", "DELIVERY_REQUEST_MISMATCH")
    return d, r


async def read(get, path):
    try:
        return await get(path)
    except Exception:
        # No private text, credentials or server bodies in refusal output.
        raise ContextHeld("CANONICAL_READ_UNAVAILABLE") from None


def private_scope(origin, current, actor):
    if origin["audience"] == "direct":
        require(current["audience"] == "direct" and
                current["room"] == origin["room"] and
                {current["author"], current["recipient"]} <=
                {origin["author"], origin["recipient"]} and
                actor in (origin["author"], origin["recipient"]), "PRIVATE_SCOPE_HELD")


def excerpt(text, budget):
    require(text is None or isinstance(text, str), "MALFORMED_ACCEPTANCE")
    if text is None:
        return None
    raw = text.encode("utf-8")
    return {"text": raw[:budget].decode("utf-8", errors="ignore"),
            "sha256": hashlib.sha256(raw).hexdigest(), "sourceBytes": len(raw),
            "truncated": len(raw) > budget}


# Hard bounds include Unicode/JSON escaping in the exact connector serializer.
MAX_DEPTH = 4
MAX_FRAGMENT_BYTES = 960
MAX_AUDIT_BYTES = 131072
MAX_LOCATORS_PER_REQUEST = 64


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def event_digest(row):
    return digest({k: row[k] for k in EVENT_FIELDS})


def origin_reference(captured):
    d, r = receipt(captured)
    return {"schema": REFERENCE_SCHEMA, "authorityId": d["authority"],
            "agentId": d["agent"], "requestId": r["id"],
            "deliveryId": d["id"], "generation": d["generation"],
            "claimId": d["claim_id"], "hostId": d.get("host"),
            "requestSha256": event_digest(r)}


def compare_reference(reference, canonical):
    require(isinstance(reference, dict) and reference == origin_reference(canonical),
            "STALE_OR_CONFLICTING_LOCATOR")


class LocatorLedger:
    """Private append-only hints, never an authority or a mutable latest pointer.

    Every use is canonically compared by the builder. An edge pins the parent
    attempt at delegation, before a peer result exists. Old generations stay
    byte-identical; absent/ambiguous/stale lineage holds without retargeting.
    """

    def __init__(self, directory):
        from pathlib import Path
        self.directory = Path(directory)

    def _put(self, relative, value):
        import os
        import tempfile
        path = self.directory / relative
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        data = encoded(value)
        require(len(data) <= MAX_AUDIT_BYTES, "LEDGER_ITEM_TOO_LARGE")
        # Publish only a complete fsynced inode. Concurrent same-key writers
        # compare bytes; no overwrite or partially written visible record.
        fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                require(path.read_bytes() == data, "IMMUTABLE_LOCATOR_CONFLICT")
        finally:
            os.unlink(temporary)
        return value

    def _read(self, path):
        require(path.stat().st_size <= 4096, "MALFORMED_LOCATOR")
        return strict_object(path.read_text())

    def remember(self, captured):
        ref = origin_reference(captured)
        return self._put("refs/{requestId}/{deliveryId}/{generation}.json".format(**ref), ref)

    def candidates(self, request_id):
        request_id = identity(request_id)
        root = self.directory / "refs" / request_id
        paths = []
        # This is only this UUID's small private identifier index, not history.
        if root.exists():
            visited = 0
            for directory in root.iterdir():
                visited += 1
                require(visited <= 2 * MAX_LOCATORS_PER_REQUEST, "LOCATOR_LOOKUP_BOUND")
                identity(directory.name)
                require(directory.is_dir() and not directory.is_symlink(), "MALFORMED_LOCATOR")
                for path in directory.iterdir():
                    visited += 1
                    require(visited <= 2 * MAX_LOCATORS_PER_REQUEST and
                            len(paths) < MAX_LOCATORS_PER_REQUEST, "LOCATOR_LOOKUP_BOUND")
                    require(path.suffix == ".json" and path.stem.isdigit() and
                            int(path.stem) > 0 and not path.is_symlink(), "MALFORMED_LOCATOR")
                    paths.append(path)
        values = [self._read(p) for p in sorted(paths)]
        for value in values:
            require(value.get("schema") == REFERENCE_SCHEMA and
                    value.get("requestId") == request_id, "MALFORMED_LOCATOR")
        return values

    def unique(self, request_id):
        values = self.candidates(request_id)
        require(len(values) == 1, "ORIGIN_LOCATOR_MISSING_OR_AMBIGUOUS")
        return values[0]

    def edge(self, child, child_delivery, parent):
        child = event(child)
        identity(child_delivery)
        require(child["source"] == parent.get("requestId"), "EDGE_SOURCE_MISMATCH")
        value = {"schema": "lax-causal-edge/v1", "childRequestId": child["id"],
                 "childDeliveryId": child_delivery, "childRequestSha256": event_digest(child),
                 "parent": parent}
        return self._put("edges/" + child["id"] + "/" + child_delivery + ".json", value)

    def resolve(self, child, child_delivery):
        path = self.directory / "edges" / identity(child["id"]) / (identity(child_delivery) + ".json")
        if not path.exists():
            return self.unique(child["source"])
        value = self._read(path)
        require(value.get("schema") == "lax-causal-edge/v1" and
                value.get("childRequestId") == child["id"] and
                value.get("childDeliveryId") == child_delivery and
                value.get("childRequestSha256") == event_digest(child) and
                isinstance(value.get("parent"), dict) and
                value["parent"].get("requestId") == child["source"], "EDGE_CONFLICT")
        return value["parent"]

    def retain_audit(self, audit):
        return self._put("audits/" + digest(audit) + ".json", audit)


async def index_accepted_delegation(get, ledger, captured, accepted):
    """Best-effort bookkeeping AFTER an existing accepted effect; never resend.

    Call for both original POST receipt and existing lost-reply read recovery.
    Cache failure must not turn an already accepted execution into a rejection.
    The original accepted event/deliveries remain present and unchanged.
    """
    try:
        require(isinstance(accepted, dict) and accepted.get("accepted") is True,
                "ACCEPTED_RECEIPT_REQUIRED")
        child = event(accepted.get("event"))
        deliveries = accepted.get("deliveries")
        require(isinstance(deliveries, list) and len(deliveries) == 1,
                "SINGLE_CHILD_RECEIPT_REQUIRED")
        pending = deliveries[0]
        cd, ce = receipt(captured)
        require(child["kind"] == "request" and child["authority"] == cd["authority"] and
                child["author"] == cd["agent"] and child["data"].get("expectsReply") is True and
                pending.get("event") == child["id"] and
                pending.get("authority") == cd["authority"], "ACCEPTED_CHILD_MISMATCH")
        child_id = identity(pending.get("id"))
        canonical = await read(get, "deliveries/" + child_id)
        actual = canonical.get("delivery", {})
        actual_event = event(canonical.get("request"))
        require(all(actual.get(k) == pending.get(k) for k in ("id", "event", "authority", "agent"))
                and event_digest(actual_event) == event_digest(child), "ACCEPTED_CHILD_CHANGED")
        if child["source"] == ce["id"]:
            ref = ledger.remember(captured)
        else:
            ref = ledger.unique(child["source"])
        parent = await read(get, "deliveries/" + identity(ref.get("deliveryId")))
        compare_reference(ref, parent)
        pd, pe = receipt(parent)
        require(pd["agent"] == cd["agent"] and pd["authority"] == cd["authority"] and
                pe["seq"] < child["seq"] and not pd["cancellation_requested"] and
                pd["state"] not in ("cancel_requested", "cancelled", "unknown"), "PARENT_SCOPE_HELD")
        ledger.edge(child, child_id, ref)
        return {**accepted, "causalLocator": {"state": "recorded"}}
    except Exception as error:
        code = error.code if isinstance(error, ContextHeld) else "LOCATOR_IO_HELD"
        return {**accepted, "causalLocator": {"state": "held", "code": code,
                "effectAlreadyAccepted": True, "resend": False}}


def audit_event(row, delivery_id=None):
    return {"eventId": row["id"], "roomId": row["room"],
            "by": [row["data"]["authorKind"], row["author"]],
            "recipientId": row["recipient"], "audience": row["audience"],
            "sourceEventId": row["source"], "sequence": row["seq"],
            "eventSha256": event_digest(row), "body": excerpt(row["body"], 6000),
            "acceptance": excerpt(row["data"].get("acceptance"), 1800),
            "references": {k: row["data"][k] for k in ("goalId", "workId", "attemptId")
                           if row["data"].get(k) is not None},
            "read": {"tool": "hollywood_execution_read", "deliveryId": delivery_id}
                    if delivery_id else {"tool": "hollywood_read_room", "roomId": row["room"],
                    "after": row["seq"] - 1, "limit": 1, "view": "conversation"}}


def compact_fragment(task, task_delivery, result, audit, inspection):
    value = {"schema": SCHEMA, "contentAuthority": "tool-data",
             "task": {"requestId": task["id"], "deliveryId": task_delivery,
                      "by": [task["data"]["authorKind"], task["author"]],
                      "readWith": "hollywood_execution_read", "text": ""},
             "result": {"eventId": result["id"],
                        "by": [result["data"]["authorKind"], result["author"]],
                        "read": {"tool": "hollywood_read_room", "roomId": result["room"],
                                 "after": result["seq"] - 1, "limit": 1},
                        "text": ""},
             "ancestry": {"depth": len(audit["hops"]), "sha256": digest(audit)},
             "outcome": "unassessed", "accountTaskFirst": True,
             "historicalInspectionOnly": inspection, "requiresDeeperRead": True}
    # Canonical task/result references and attribution are never trimmed. The
    # audit retains fuller source excerpts/acceptance and all hop identities.
    for budget in range(160, -1, -8):
        value["task"]["text"] = task["body"].encode()[:budget].decode("utf-8", "ignore")
        value["result"]["text"] = result["body"].encode()[:budget // 2].decode("utf-8", "ignore")
        if len(json.dumps(value).encode()) <= MAX_FRAGMENT_BYTES:
            return value
    raise ContextHeld("FRAGMENT_BUDGET_EXCEEDED")


async def build_context(get, captured, resolve, *, inspection=False):
    """Read one bounded causal chain and recheck it; never admit any execution.

    resolve(child_event, child_delivery_id) returns a private identifier locator.
    Production requires a claimed current delivery; inspection permits frozen
    historical evidence only. Actor/role/context/goal/native input stay intact.
    """
    cd, ce = receipt(captured)
    if pointer(ce) is None:
        return None
    actor, authority = cd["agent"], cd["authority"]
    records = {}

    async def delivery(delivery_id):
        identity(delivery_id)
        if delivery_id not in records:
            value = await read(get, "deliveries/" + delivery_id)
            d, e = receipt(value)
            require(d["id"] == delivery_id and d["authority"] == authority,
                    "DELIVERY_SCOPE_MISMATCH")
            records[delivery_id] = value
        return records[delivery_id]

    current = await delivery(cd["id"])
    compare_reference(origin_reference(captured), current)
    d, outer = receipt(current)
    require(outer["recipient"] == actor and outer["data"]["authorKind"] == "agent",
            "COMPLETION_RECIPIENT_MISMATCH")
    if not inspection:
        require(d["state"] == "claimed", "CONTINUATION_NOT_CLAIMED")
    hops, seen, latest_result = [], set(), None
    while True:
        nd, ne = receipt(current)
        key = (ne["id"], nd["id"], nd["generation"])
        require(key not in seen, "CYCLIC_LINEAGE")
        seen.add(key)
        p = pointer(ne)
        if p is None:
            task, task_delivery = ne, nd
            break
        require(len(hops) < MAX_DEPTH, "ANCESTRY_DEPTH_HELD")
        require(nd["agent"] == actor and ne["recipient"] == actor and
                ne["data"]["authorKind"] == "agent", "COMPLETION_RECIPIENT_MISMATCH")
        child_id = ne["data"]["replyToDelivery"]
        require(child_id != nd["id"], "CYCLIC_LINEAGE")
        child = await delivery(child_id)
        dd, de = receipt(child)
        require(de["id"] == p["requestId"] and de["author"] == actor and
                de["recipient"] in (None, dd["agent"]) and dd["agent"] == ne["author"] and
                de["data"].get("authorKind") == "agent" and
                de["data"].get("expectsReply") is True and
                de["source"] == p["originRequestId"], "CHILD_ORIGIN_MISMATCH")
        ref = resolve(de, child_id)
        require(isinstance(ref, dict) and ref.get("requestId") == p["originRequestId"],
                "ORIGIN_LOCATOR_MISMATCH")
        origin = await delivery(identity(ref.get("deliveryId")))
        compare_reference(ref, origin)
        od, oe = receipt(origin)
        require((oe["id"], od["id"], od["generation"]) not in seen, "CYCLIC_LINEAGE")
        require(len({nd["id"], dd["id"], od["id"]}) == 3, "CYCLIC_LINEAGE")
        require(od["agent"] == actor and oe["recipient"] in (None, actor), "ORIGIN_ACTOR_MISMATCH")
        rv = await read(get, "inbox/events/" + p["resultEventId"])
        result = event(rv.get("event") if isinstance(rv, dict) else None)
        require(result["authority"] == authority and result["kind"] == "result" and
                result["id"] == dd.get("result_event") == p["resultEventId"] and
                result["source"] == de["id"] and result["data"]["authorKind"] == "agent" and
                result["author"] == dd["agent"] and result["data"].get("deliveryId") == child_id and
                result["data"].get("state") == dd["state"] == p["executionState"] and
                result["data"].get("generation") == dd["generation"], "CHILD_RESULT_MISMATCH")
        require(de["room"] == result["room"] == ne["room"] and
                de["audience"] == result["audience"] == ne["audience"] and
                (ne["audience"] != "direct" or result["recipient"] == actor), "RESULT_SCOPE_MISMATCH")
        require(oe["seq"] < de["seq"] < result["seq"] < ne["seq"], "LINEAGE_ORDER_MISMATCH")
        # Check every deeper private item against the outer injected audience.
        for item in (oe, de, result, ne):
            private_scope(item, outer, actor)
        hops.append({"continuation": origin_reference(current),
                     "origin": ref, "child": origin_reference(child),
                     "childRequest": audit_event(de, dd["id"]),
                     "result": audit_event(result), "completion": audit_event(ne, nd["id"])})
        if latest_result is None:
            latest_result = result
        current = origin
    require(len(records) <= 2 * MAX_DEPTH + 1, "ANCESTRY_READ_BOUND")
    cancelled = any(v["delivery"]["cancellation_requested"] or v["delivery"]["state"] in
                    ("cancel_requested", "cancelled", "unknown") for v in records.values())
    if not inspection:
        require(not cancelled, "CANCELLED_OR_UNKNOWN_LINEAGE")
    # Re-read each exact delivery once. No waiting, scanning or state mutation.
    again = await asyncio.gather(*(read(get, "deliveries/" + k) for k in records))
    for before, after in zip(records.values(), again):
        ad, ae = receipt(after)
        require(ad == before["delivery"] and event_digest(ae) == event_digest(before["request"]),
                "LINEAGE_CHANGED_DURING_READ")
    audit = {"schema": "lax-causal-audit/v2", "authorityId": authority, "agentId": actor,
             "historicalInspectionOnly": inspection, "current": origin_reference(captured),
             "task": audit_event(task, task_delivery["id"]), "hops": hops,
             "lineageCancelledOrUnknown": cancelled, "outcome": "unassessed",
             "executionStates": {k: v["delivery"]["state"] for k, v in records.items()}}
    require(len(encoded(audit)) <= MAX_AUDIT_BYTES, "AUDIT_BUDGET_EXCEEDED")
    return {"fragment": compact_fragment(task, task_delivery["id"], latest_result, audit, inspection),
            "audit": audit}


async def prepare_context(get, state_directory, captured):
    """Pre-native hook. Retain full audit privately; inject only the small fragment."""
    from pathlib import Path
    try:
        ledger = LocatorLedger(Path(state_directory) / "causal-locators-v2")
        ledger.remember(captured)
        built = await build_context(get, captured, ledger.resolve)
        if built is None:
            return None
        ledger.retain_audit(built["audit"])
        return built["fragment"]
    except ContextHeld:
        raise
    except (OSError, ValueError, TypeError):
        raise ContextHeld("LOCATOR_IO_HELD") from None
