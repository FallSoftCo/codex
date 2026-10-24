"""Bounded data-only automatic refill. Manual/idle rendering stays unchanged."""
import hashlib
import json
import re

from .native_context_rebuild import refill_items

MAX_DATA = 256 * 1024
MAX_ITEMS = 256
MAX_WIRE = 1024 * 1024
IDENTITY = {"threadId", "turnId", "operationId", "contextId", "purpose"}
CUT = {"snapshotOperationId", "snapshotReadPoint", "snapshotSha256",
       "nativeActionsSha256", "selectionRevision", "totalBytes"}
REFILL = IDENTITY | {"windowId", "historyVersion", "reason", "phase"}
INSTALLED = IDENTITY | CUT | {"previousWindowId", "windowId",
                             "nativeHistoryBytes", "nativeHistorySha256"}


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def identifier(value):
    require(isinstance(value, str) and 0 < len(value.encode()) <= 256,
            "Missing or oversized original identity")
    return value


def digest(value):
    require(isinstance(value, str) and re.fullmatch("[a-f0-9]{64}", value),
            "Invalid exact digest")
    return value


def unsigned(value):
    require(type(value) is int and 0 <= value < 2**64, "Invalid unsigned revision")
    return value


def parameters(value, fields):
    require(set(value) == fields, "Automatic callback fields differ")
    for key in IDENTITY | ({"previousWindowId"} if fields == INSTALLED else set()) | {"windowId"}:
        identifier(value[key])
    require(value["purpose"] in ("reader", "writer", "responder"), "Unknown purpose")
    if fields == REFILL:
        unsigned(value["historyVersion"])
        require(value["reason"] in ("contextLimit", "modelDownshift", "compHashChanged"),
                "Unknown automatic refill reason")
        require(value["phase"] in ("preTurn", "midTurn", "postTurn"),
                "Unknown automatic refill phase")
    else:
        for key in ("snapshotOperationId", "snapshotReadPoint"):
            identifier(value[key])
        for key in ("snapshotSha256", "nativeActionsSha256", "nativeHistorySha256"):
            digest(value[key])
        for key in ("selectionRevision", "totalBytes", "nativeHistoryBytes"):
            unsigned(value[key])
        require(value["previousWindowId"] != value["windowId"], "Window did not change")
    return value


def render(snapshot, operation, actions):
    """Reuse the established renderer, enforcing the automatic wire contract."""
    identifier(operation)
    unsigned(snapshot["totalBytes"])
    require(0 < snapshot["totalBytes"] <= MAX_DATA, "Snapshot exceeds automatic cap")
    digest(snapshot["sha256"])
    offset = 0
    for chunk in snapshot["chunks"]:
        require(set(chunk) == {"offset", "content"} and type(chunk["offset"]) is int
                and chunk["offset"] == offset and isinstance(chunk["content"], str),
                "Canonical chunks are not contiguous byte fragments")
        size = len(chunk["content"].encode())
        require(0 < size <= 3072, "Canonical chunk exceeds automatic cap")
        offset += size
    require(offset == snapshot["totalBytes"], "Canonical byte count differs")
    encoded = "".join(chunk["content"] for chunk in snapshot["chunks"])
    require(hashlib.sha256(encoded.encode()).hexdigest() == snapshot["sha256"],
            "Canonical snapshot digest differs")
    action_bytes = wire(actions).encode()
    require(len(action_bytes) <= MAX_DATA, "Action descriptor exceeds automatic cap")
    # Existing renderer uses ensure_ascii=True, so its action offsets are bytes.
    items = refill_items(snapshot, operation, actions)
    require(0 < len(items) <= MAX_ITEMS and len(wire(items).encode()) <= MAX_WIRE,
            "Automatic combined item budget exceeded")
    for item in items:
        require(set(item) == {"type", "namespace", "name", "output"}
                and item["type"] == "function_call_output"
                and (item["namespace"], item["name"]) in
                    (("hollywood", "context_refill"), ("lax", "context_actions"))
                and isinstance(item["output"], str)
                and len(item["output"].encode()) <= 16 * 1024,
                "Automatic refill contains non-data output")
    return items, hashlib.sha256(action_bytes).hexdigest()
