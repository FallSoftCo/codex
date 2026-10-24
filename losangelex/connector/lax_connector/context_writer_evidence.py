"""Reader access to its own Writer's exact original native receipt, never effects."""
import hashlib
import json
import re
import stat
from pathlib import Path

MAX_RECEIPT_BYTES = 128 * 1024 * 1024
CHUNK_CHARS = 3072


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def evidence_path(config, turn):
    if not isinstance(turn, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", turn):
        raise ValueError("Exact original native turn required")
    return Path(config["state"]) / "writer" / ("writer-native-evidence-" + turn + ".json")


async def read(runner, value, operation):
    if runner.purpose != "reader" or set(value) - {"inputId", "pageOffset", "itemId", "offset", "sha256"}:
        raise PermissionError("Reader-only exact original evidence read required")
    scope = await runner.request("writer_evidence_authorize", {"inputId": value["inputId"]},
                                 operation=operation + ":scope")
    expected = {"authorityId": runner.config["authorityId"], "agentId": runner.config["agentId"],
        "hostId": runner.config["hostId"], "contextId": runner.config["contextIds"]["writer"]}
    if any(scope.get(k) != v for k, v in expected.items()) or scope.get("readOnly") is not True:
        raise PermissionError("Original evidence requires its authorized host route; no cross-host filesystem assumption")
    path = evidence_path(runner.config, scope["nativeTurn"])
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_RECEIPT_BYTES:
        raise RuntimeError("Original native receipt is unavailable or exceeds bounded reader capacity")
    with path.open("rb") as stream:
        raw = stream.read(MAX_RECEIPT_BYTES + 1)
    if len(raw) > MAX_RECEIPT_BYTES:
        raise RuntimeError("Original native receipt exceeded bounded reader capacity")
    receipt = json.loads(raw)
    expected.update(nativeThread=scope["nativeThread"], nativeTurn=scope["nativeTurn"],
                    nativeItemsSha256=scope["nativeItemsSha256"])
    if any(receipt.get(k) != v for k, v in expected.items()):
        raise PermissionError("Original native receipt ownership/digest differs")
    entries = receipt["entries"]
    if (hashlib.sha256(encoded(entries).encode()).hexdigest() != scope["nativeItemsSha256"]
            or scope["itemCount"] is not None and len(entries) != scope["itemCount"]
            or any(e["turnId"] != scope["nativeTurn"] for e in entries)):
        raise RuntimeError("Exact original native evidence is not verified")
    item_id = value.get("itemId")
    if item_id is None:
        if set(value) - {"inputId", "pageOffset"}:
            raise ValueError("Index read takes only inputId/pageOffset")
        start = value.get("pageOffset", 0)
        if type(start) is not int or not 0 <= start <= len(entries):
            raise ValueError("Invalid original native index offset")
        items = []
        for entry in entries[start:start + 8]:
            item = entry["item"]
            descriptor = {k: item[k] for k in ("id", "type", "tool", "namespace", "status", "success") if k in item}
            descriptor["sha256"] = hashlib.sha256(encoded(item).encode()).hexdigest()
            if item.get("type") == "agentMessage":
                descriptor["textChars"] = len(item.get("text", ""))
            items.append(descriptor)
        following = start + len(items)
        return {"schema": "lax-native-evidence-index/v1", "inputId": value["inputId"],
            "nativeTurn": scope["nativeTurn"], "nativeItemsSha256": scope["nativeItemsSha256"],
            "totalItems": len(entries), "pageOffset": start, "items": items,
            "nextRead": {"inputId": value["inputId"], "pageOffset": following} if following < len(entries) else None,
            "meaning": "Exact original native API receipt index; read selected items. Native logs may themselves have bounded output; no effect is replayed."}
    if "pageOffset" in value:
        raise ValueError("Select either index paging or exact item chunks")
    matched = [entry["item"] for entry in entries if entry["item"].get("id") == item_id]
    if len(matched) != 1:
        raise PermissionError("Item not in this original authorized native turn")
    content = encoded(matched[0]);sha = hashlib.sha256(content.encode()).hexdigest()
    offset = value.get("offset", 0)
    if (type(offset) is not int or not 0 <= offset < max(1, len(content))
            or offset and value.get("sha256") != sha
            or value.get("sha256") not in (None, sha)):
        raise ValueError("Exact original item offset/digest required; use previous nextRead")
    following = offset + CHUNK_CHARS
    return {"schema": "lax-native-evidence-item/v1", "inputId": value["inputId"],
        "nativeTurn": scope["nativeTurn"], "itemId": item_id, "sha256": sha,
        "totalBytes": len(content), "offset": offset, "content": content[offset:following],
        "nextRead": {"inputId": value["inputId"], "itemId": item_id, "offset": following, "sha256": sha}
                    if following < len(content) else None,
        "effectsReplayed": False}
