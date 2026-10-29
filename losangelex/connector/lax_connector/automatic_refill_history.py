"""Independently observe the original plain JSONL prefix and adjacent receipt.

Observation is not a filesystem sync proof: the strict native recorder must
perform checked flush+sync_all before sending its installed request.
"""
import hashlib
import json
import math
import os
import stat
from pathlib import Path

from .automatic_refill_data import CUT, IDENTITY, require


def _open(path):
    require(Path(path).is_absolute() and str(Path(path).resolve()) == path
            and Path(path).suffix == ".jsonl", "Original local plain rollout required")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    stream = os.fdopen(fd, "rb")
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
        stream.close()
        raise RuntimeError("Original history is not a regular file")
    return stream, info


def _prefix(stream, count):
    stream.seek(0)
    digest = hashlib.sha256()
    while count:
        block = stream.read(min(count, 1024 * 1024))
        require(block, "Original history prefix is incomplete")
        digest.update(block)
        count -= len(block)
    return digest.hexdigest()


def capture(thread, expected):
    require(thread["id"] == expected and thread["ephemeral"] is False,
            "Original materialized non-ephemeral thread required")
    path = thread["path"]
    stream, info = _open(path)
    with stream:
        require(0 < info.st_size <= 256 * 1024**2, "Original history exceeds scan cap")
        stream.seek(-1, os.SEEK_END)
        require(stream.read(1) == b"\n", "Original history has an unfinished record")
        digest = _prefix(stream, info.st_size)
    return {"path": path, "device": info.st_dev, "inode": info.st_ino,
            "beforeBytes": info.st_size, "beforeSha256": digest}



def native_base_metadata(value, count, turn):
    """Validate typed native attribution, never execution or permission claims.

    Source: protocol/src/models.rs::InternalChatMessageMetadataPassthrough and
    models/item_metadata.rs. Initial-context messages may carry these fields;
    tool-cell/call inventories cannot belong to this non-tool base prefix.
    """
    require(isinstance(value, dict) and set(value) <= {
        "turn_id", "create_time", "content_item_kinds", "content_item_metadata"},
        "Unexpected native base metadata")
    if "turn_id" in value:
        require(value["turn_id"] == turn, "Native base metadata belongs to another turn")
    if "create_time" in value:
        stamp = value["create_time"]
        require(type(stamp) in (int, float) and math.isfinite(stamp) and stamp > 0,
                "Invalid native base creation time")
    if "content_item_kinds" in value:
        kinds = value["content_item_kinds"]
        require(isinstance(kinds, list) and len(kinds) == count
                and all(isinstance(k, str) and 0 < len(k.encode()) <= 512 for k in kinds),
                "Native base classifications do not align with content")
    if "content_item_metadata" not in value:
        return
    parts = value["content_item_metadata"]
    require(isinstance(parts, list) and len(parts) == count,
            "Native base attribution does not align with content")
    for part in parts:
        require(isinstance(part, dict) and set(part) == {"provenance"},
                "Unexpected native content attribution")
        origin = part["provenance"]
        require(isinstance(origin, dict) and isinstance(origin.get("type"), str),
                "Native content provenance missing")
        kind = origin["type"]
        if kind in ("unknown", "skills", "agents_md", "user"):
            require(set(origin) == {"type"}, "Unexpected simple native provenance")
        elif kind == "harness":
            require(set(origin) == {"type", "hook"} and type(origin["hook"]) is bool,
                    "Invalid native harness provenance")
        elif kind == "developer_instructions":
            require(set(origin) == {"type", "from_additional_requirements"}
                    and type(origin["from_additional_requirements"]) is bool,
                    "Invalid native developer provenance")
        else:
            require(kind == "tool" and set(origin) <= {"type", "namespace"},
                    "Unknown native content provenance")
            if "namespace" in origin:
                require(isinstance(origin["namespace"], str)
                        and 0 < len(origin["namespace"].encode()) <= 512,
                        "Invalid native tool namespace")


def verify(original, request, response, installed, *, native_mode=None, native_preflight=None):
    """Accept one exact intent/checkpoint/receipt, never recursive membership."""
    expected = {k: response[k] for k in IDENTITY | CUT}
    require(all(installed[k] == v for k, v in expected.items())
            and installed["previousWindowId"] == request["windowId"],
            "Installed callback differs from the original cut")
    intent = {k: response[k] for k in IDENTITY | CUT}
    intent.update({k: request[k] for k in ("windowId", "historyVersion", "reason", "phase")})
    intent["nextWindowId"] = installed["windowId"]
    stream, info = _open(original["path"])
    with stream:
        require((info.st_dev, info.st_ino) == (original["device"], original["inode"]),
                "Original rollout file identity changed")
        require(_prefix(stream, original["beforeBytes"]) == original["beforeSha256"],
                "Original history prefix changed")
        # A known installed receipt bounds its original installation span.
        # Later legitimate turns must not invalidate that immutable checkpoint.
        # Whole-file scanning stays bounded independently; unknown-receipt
        # discovery retains its stricter recovery scan cap below.
        require(original["beforeBytes"] < installed["nativeHistoryBytes"]
                <= info.st_size <= 256 * 1024**2
                and installed["nativeHistoryBytes"] - original["beforeBytes"]
                    <= 16 * 1024**2,
                "Native receipt prefix/scan bounds differ")
        require(_prefix(stream, installed["nativeHistoryBytes"]) ==
                installed["nativeHistorySha256"], "Native history prefix digest differs")
        stream.seek(original["beforeBytes"])
        previous = []
        matches = 0
        while stream.tell() < info.st_size:
            line = stream.readline(8 * 1024**2 + 1)
            require(line.endswith(b"\n") and len(line) <= 8 * 1024**2,
                    "Incomplete or oversized original history line")
            end = stream.tell()
            row = json.loads(line)
            if (row.get("type") == "event_msg" and
                    row.get("payload", {}).get("type") == "context_window_refill_installed"
                    and row["payload"].get("operationId") == request["operationId"]):
                require(len(previous) == 2, "Native receipt has no adjacent checkpoint")
                (start, first, _), (checkpoint_end, checkpoint, checkpoint_raw) = previous
                require(first == {"type": "context_window_refill_intent", **intent},
                        "Native intent differs from original cut")
                require(checkpoint.get("type") == "compacted"
                        and checkpoint_end == installed["nativeHistoryBytes"],
                        "Native receipt is not immediately outside checkpoint prefix")
                body = checkpoint["payload"]
                require(body.get("message") == ""
                        and body.get("previous_window_id") == installed["previousWindowId"]
                        and body.get("window_id") == installed["windowId"],
                        "Native replacement checkpoint windows differ")
                history = body["replacement_history"]
                require(isinstance(history, list), "Native replacement history missing")
                # Native reconstructs typed base instructions/context first;
                # the ENTIRE remaining tail must be the exact canonical data.
                # Filtering by namespace would silently admit unsafe extra items.
                count = len(response["items"])
                require(count > 0 and len(history) >= count
                        and history[-count:] == response["items"],
                        "Exact canonical replacement tail differs")
                base = history[:-count]
                require(len(base) <= 256, "Native base prefix exceeds item cap")
                if native_mode is None:
                    for index, item in enumerate(base):
                        if isinstance(item, dict) and item.get("type") == "additional_tools":
                            # core::build_initial_context emits this typed tool
                            # vocabulary before message context. It is not a
                            # model call/result or retained client data.
                            require(index == 0
                                    and set(item) <= {"type", "role", "tools", "id"}
                                    and item.get("id") is None
                                    and item.get("role") == "developer"
                                    and isinstance(item.get("tools"), list)
                                    and all(isinstance(tool, dict) for tool in item["tools"])
                                    and len(json.dumps(item, ensure_ascii=False).encode()) <= 262144,
                                    "Invalid native base tool vocabulary")
                            continue
                        require(isinstance(item, dict)
                                and {"type", "role", "content"} <= set(item)
                                and set(item) <= {"type", "role", "content", "id",
                                                  "internal_chat_message_metadata_passthrough"}
                                and item.get("id") is None and item["type"] == "message"
                                and item["role"] in ("system", "developer", "user")
                                and isinstance(item["content"], list) and item["content"],
                                "Unexpected item in native base prefix")
                        for part in item["content"]:
                            require(isinstance(part, dict) and set(part) == {"type", "text"}
                                    and part["type"] == "input_text" and isinstance(part["text"], str),
                                    "Unsafe content in native base prefix")
                        if "internal_chat_message_metadata_passthrough" in item:
                            native_base_metadata(item["internal_chat_message_metadata_passthrough"],
                                                 len(item["content"]), request["turnId"])
                else:
                    from .native_context_checkpoint import verify_checkpoint
                    verify_checkpoint(checkpoint_raw, body, base, request, response, native_mode,
                                      preflight=native_preflight)
                require(row["payload"] == {"type": "context_window_refill_installed", **installed},
                        "Original native installed receipt differs")
                matches += 1
            previous.append((end, row["payload"] if row.get("type") == "event_msg"
                             and row.get("payload", {}).get("type") ==
                             "context_window_refill_intent" else row, line))
            previous = previous[-2:]
        require(_prefix(stream, original["beforeBytes"]) == original["beforeSha256"]
                and _prefix(stream, installed["nativeHistoryBytes"]) ==
                    installed["nativeHistorySha256"], "History changed after receipt scan")
        after = os.fstat(stream.fileno())
        require((after.st_dev, after.st_ino, after.st_size) ==
                (info.st_dev, info.st_ino, info.st_size), "History changed during observation")
    require(matches == 1, "Exactly one original native receipt required")
    require(os.stat(original["path"], follow_symlinks=False).st_ino == original["inode"],
            "Original rollout path was replaced")

def recovered_installed(original, operation_id):
    """Locate a bounded typed original receipt; verify() proves its checkpoint."""
    stream, info = _open(original["path"])
    with stream:
        require((info.st_dev, info.st_ino) == (original["device"], original["inode"]),
                "Original native history identity changed")
        require(0 <= info.st_size - original["beforeBytes"] <= 16 * 1024**2,
                "Original native installation observation exceeds bounds")
        stream.seek(original["beforeBytes"])
        matches = []
        while stream.tell() < info.st_size:
            line = stream.readline(8 * 1024**2 + 1)
            require(line.endswith(b"\n") and len(line) <= 8 * 1024**2,
                    "Incomplete or oversized original native history")
            row = json.loads(line)
            body = row.get("payload", {})
            if (row.get("type") == "event_msg"
                    and body.get("type") == "context_window_refill_installed"
                    and body.get("operationId") == operation_id):
                matches.append({k: v for k, v in body.items() if k != "type"})
    require(len(matches) == 1, "Original native installation is not uniquely confirmed")
    return matches[0]
