"""Narrow native evidence for a failed original pre-turn refill before sampling."""
import json
import os

from .automatic_refill_data import require
from .automatic_refill_history import _open, _prefix


def failed_before_model(original, request, owner):
    require(request["phase"] == "preTurn" and owner["purpose"] == "writer",
            "Only an original writer pre-turn failure is supported")
    stream, info = _open(original["path"])
    with stream:
        require((info.st_dev, info.st_ino) == (original["device"], original["inode"])
                and 0 < original["beforeBytes"] <= info.st_size <= 256 * 1024**2
                and info.st_size - original["beforeBytes"] <= 16 * 1024**2,
                "Original pre-turn history identity/bounds changed")
        require(_prefix(stream, original["beforeBytes"]) == original["beforeSha256"],
                "Original pre-turn history prefix changed")
        stream.seek(0)
        starts, last = 0, None
        while stream.tell() < original["beforeBytes"]:
            line = stream.readline(min(8 * 1024**2 + 1,
                                       original["beforeBytes"] - stream.tell()))
            require(line.endswith(b"\n") and len(line) <= 8 * 1024**2,
                    "Original prefix has an incomplete/oversized record")
            last = json.loads(line)
            body = last.get("payload", {})
            if (last.get("type") == "event_msg" and isinstance(body, dict)
                    and body.get("type") == "task_started"
                    and body.get("turn_id") == owner["turnId"]):
                starts += 1
        require(starts == 1 and last.get("type") == "event_msg"
                and last.get("payload", {}).get("type") == "task_started"
                and last["payload"].get("turn_id") == owner["turnId"],
                "Original capture is not immediately after its unique native turn start")
        expected = {"purpose": "writer", "materialIds": owner["materialIds"]}
        input_id = None
        while stream.tell() < info.st_size:
            line = stream.readline(8 * 1024**2 + 1)
            require(line.endswith(b"\n") and len(line) <= 8 * 1024**2,
                    "Incomplete/oversized original failed-turn record")
            row = json.loads(line)
            body = row.get("payload", {})
            if row.get("type") == "response_item":
                require(input_id is None and body.get("type") == "function_call_output"
                        and body.get("name") == "context_material_available"
                        and body.get("internal_chat_message_metadata_passthrough", {}).get(
                            "turn_id") == owner["turnId"]
                        and json.loads(body.get("output", "")) == expected,
                        "Original turn contains model output or another tool/effect")
                input_id = body["id"]
            elif row.get("type") == "event_msg" and body.get("type") == "item_completed":
                item = body.get("item", {})
                require(input_id is not None and body.get("turn_id") == owner["turnId"]
                        and item.get("type") == "FunctionCallOutput"
                        and item.get("id") == input_id
                        and item.get("name") == "context_material_available"
                        and json.loads(item.get("output", "")) == expected,
                        "Original failed turn contains another completed item")
            else:
                require(row.get("type") == "event_msg"
                        and body.get("type") == "task_complete"
                        and body.get("turn_id") == owner["turnId"]
                        and isinstance(body.get("error"), dict) and body["error"],
                        "Original failed turn has other activity or no terminal error")
                boundary = stream.tell()
                proof = {"phase": "preTurn", "failedBeforeModel": True,
                         "failureHistoryBytes": boundary,
                         "failureHistorySha256": _prefix(stream, boundary)}
                require(_prefix(stream, original["beforeBytes"]) == original["beforeSha256"],
                        "Original prefix changed during pre-model verification")
                after = os.fstat(stream.fileno())
                require((after.st_dev, after.st_ino, after.st_size) ==
                        (info.st_dev, info.st_ino, info.st_size),
                        "Original history changed during pre-model verification")
                return proof
    raise RuntimeError("Original failed pre-model completion is not independently confirmed")
