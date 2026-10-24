"""Pure selection/refill preflight for the negotiated retained-action packet.

Nothing here installs history or adopts a selection. The same complete packet
must pass native validation before a future consumer can replace a window.
"""
import hashlib
import json

from .context_action_memory import KINDS, TERMINAL
from .context_action_pages import wire
from .native_context_rebuild import refill_items

MAX_ITEM = 32768
MAX_RAW = 65536
MAX_BUNDLE = 98304
MAX_CANONICAL = 98304
MAX_DESCRIPTOR = 16384
MAX_DECODED = 262144
MAX_ITEMS = 256
MAX_WIRE = 1048576


def require(condition, message):
    if not condition:
        raise ValueError(message)


def render(snapshot, operation, actions, entries):
    encoded = "".join(x["content"] for x in snapshot["chunks"])
    require(len(encoded.encode()) == snapshot["totalBytes"]
            and hashlib.sha256(encoded.encode()).hexdigest() == snapshot["sha256"],
            "Original canonical snapshot changed")
    require(0 < len(encoded.encode()) <= MAX_CANONICAL, "Canonical snapshot budget exceeded")
    offset = 0
    for part in snapshot["chunks"]:
        require(part["offset"] == offset and 0 < len(part["content"].encode()) <= 3072,
                "Canonical fragment order or budget differs")
        offset += len(part["content"].encode())
    content = json.loads(encoded)
    require(content["purpose"] == "writer", "Native retained evidence belongs to Writer")
    marks = content["selection"]["marks"]
    selected = {x["reference"]: x["native_action"] for x in marks if "native_action" in x}
    require(len(marks) <= 16 and len(selected) <= 8, "Retained selection count budget exceeded")
    require(isinstance(entries, list) and len(entries) == len(selected), "Exact selected pin set required")
    require(len({x["reference"] for x in entries}) == len(entries)
            and {x["reference"] for x in entries} == set(selected), "Pin selection identity differs")
    records = {x["reference"]: x for x in content["records"]}
    require({"role", *content["nextMaterialIds"]} <= set(records),
            "Mandatory current role/work records are missing")
    raw_bytes = 0
    for entry in entries:
        metadata = selected[entry["reference"]]
        record = records.get(entry["reference"], {})
        if entry.get("access") == "unavailable":
            require(set(entry) == {"reference", "access", "reason"}
                    and entry["reason"] in ("original_source_not_authorized", "original_host_pin_missing"),
                    "Explicit unavailable pin metadata required")
            continue
        require(record.get("content", {}).get("nativeAction") == metadata,
                "Selected native source is no longer authorized in the canonical cut")
        require(set(entry) == {"reference", "metadata", "payload"} and entry["metadata"] == metadata,
                "Original pin metadata differs")
        payload = entry["payload"]
        require(isinstance(payload, str), "Whole canonical pin payload required")
        size = len(payload.encode())
        require(0 < size <= MAX_ITEM and size == metadata["payloadBytes"],
                "Whole canonical item exceeds retained-item budget")
        require(hashlib.sha256(payload.encode()).hexdigest() == metadata["sha256"],
                "Whole canonical item digest differs")
        item = json.loads(payload)
        require(wire(item) == payload and item.get("id") == metadata["itemId"]
                and item.get("type") in KINDS and item.get("status") in TERMINAL,
                "Original whole terminal action item differs")
        raw_bytes += size
    require(raw_bytes <= MAX_RAW, "Aggregate raw retained-item budget exceeded")
    value = {"schema": "lax-retained-native-actions/v1", "agentId": content["agentId"],
             "contextId": content["contextId"], "purpose": "writer",
             "nativeThread": content["nativeThread"], "selectionRevision": content["selection"]["selectionRevision"],
             "canonicalSnapshotSha256": snapshot["sha256"],
             "entries": sorted(entries, key=lambda x: x["reference"])}
    data = wire(value)
    descriptor = wire(actions)
    require(len(data.encode()) <= MAX_BUNDLE, "Serialized retained bundle budget exceeded")
    require(len(descriptor.encode()) <= MAX_DESCRIPTOR, "Action descriptor budget exceeded")
    decoded = len(encoded.encode()) + len(descriptor.encode()) + len(data.encode())
    require(decoded <= MAX_DECODED, "Combined decoded refill budget exceeded")
    items = refill_items(snapshot, operation, actions)
    bundle_sha = hashlib.sha256(data.encode()).hexdigest()
    for position in range(0, len(data), 3072):
        fragment = {"schema": "lax-retained-native-actions-fragment/v1",
                    "sha256": bundle_sha, "offset": position,
                    "totalBytes": len(data.encode()), "content": data[position:position+3072]}
        items.append({"type": "function_call_output", "namespace": "lax",
                      "name": "retained_actions", "output": wire(fragment)})
    size = len(wire(items).encode())
    require(0 < len(items) <= MAX_ITEMS and size <= MAX_WIRE, "Rendered native refill budget exceeded")
    require(all(len(x["output"].encode()) <= 16384 for x in items),
            "Rendered native fragment budget exceeded")
    return items, {"rawBytes": raw_bytes, "bundleBytes": len(data.encode()),
                   "descriptorBytes": len(descriptor.encode()), "decodedBytes": decoded,
                   "renderedItems": len(items), "wireBytes": size,
                   "bundleSha256": bundle_sha,
                   "descriptorSha256": hashlib.sha256(descriptor.encode()).hexdigest(),
                   "unavailableReferences": sorted(x["reference"] for x in entries if x.get("access")=="unavailable")}
