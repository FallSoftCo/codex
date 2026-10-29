"""Observe whole-native context provenance in the original serialized checkpoint.

No runtime policy is restored here. Raw item slices preserve native JSON numeric
and Unicode encoding when checking native source-group hashes across languages.
"""
import hashlib
import json
from uuid import UUID

from .automatic_refill_data import digest, require, unsigned

ORIGIN = {"schema", "thread_id", "context_id", "group_id", "kind", "index", "count", "sha256"}


def _space(text, cursor):
    while cursor < len(text) and text[cursor] in ' \r\n\t':
        cursor += 1
    return cursor


def _member(text, name):
    decoder = json.JSONDecoder()
    cursor = _space(text, 0)
    require(cursor < len(text) and text[cursor] == "{", "Native object missing")
    cursor += 1
    seen = set()
    found = None
    while True:
        cursor = _space(text, cursor)
        require(cursor < len(text), "Incomplete native object")
        if text[cursor] == "}":
            require(found is not None, "Native checkpoint member missing")
            return found
        key, cursor = decoder.raw_decode(text, cursor)
        require(isinstance(key, str) and key not in seen, "Duplicate native object member")
        seen.add(key)
        cursor = _space(text, cursor)
        require(text[cursor] == ":", "Native object colon missing")
        start = _space(text, cursor + 1)
        _, cursor = decoder.raw_decode(text, start)
        if key == name:
            found = text[start:cursor]
        cursor = _space(text, cursor)
        require(cursor < len(text) and text[cursor] in ",}", "Native object terminator missing")
        if text[cursor] == ",":
            cursor += 1


def _array(text):
    decoder = json.JSONDecoder()
    cursor = _space(text, 0)
    require(cursor < len(text) and text[cursor] == "[", "Native item array missing")
    cursor += 1
    result = []
    while True:
        cursor = _space(text, cursor)
        require(cursor < len(text), "Incomplete native item array")
        if text[cursor] == "]":
            return result
        start = cursor
        _, cursor = decoder.raw_decode(text, cursor)
        result.append(text[start:cursor].encode("utf-8"))
        require(len(result) <= 256, "Native checkpoint item cap exceeded")
        cursor = _space(text, cursor)
        require(cursor < len(text) and text[cursor] in ",]", "Native array terminator missing")
        if text[cursor] == ",":
            cursor += 1


def canonical_native(text):
    """Sort native JSON objects while preserving the recorder's numeric encoding."""
    decoder = json.JSONDecoder()

    def read(cursor):
        cursor = _space(text, cursor)
        start = cursor
        if text[cursor] == "{":
            cursor += 1
            pairs = {}
            while True:
                cursor = _space(text, cursor)
                if text[cursor] == "}":
                    return "{" + ",".join(pairs[key] for key in sorted(pairs)) + "}", cursor + 1
                key_start = cursor
                key, cursor = decoder.raw_decode(text, cursor)
                require(isinstance(key, str) and key not in pairs, "Duplicate native producer key")
                raw_key = text[key_start:cursor]
                cursor = _space(text, cursor)
                require(text[cursor] == ":", "Native producer colon missing")
                value, cursor = read(cursor + 1)
                pairs[key] = raw_key + ":" + value
                cursor = _space(text, cursor)
                require(text[cursor] in ",}", "Native producer object incomplete")
                if text[cursor] == ",":
                    cursor += 1
        elif text[cursor] == "[":
            cursor += 1
            values = []
            while True:
                cursor = _space(text, cursor)
                if text[cursor] == "]":
                    return "[" + ",".join(values) + "]", cursor + 1
                value, cursor = read(cursor)
                values.append(value)
                cursor = _space(text, cursor)
                require(text[cursor] in ",]", "Native producer array incomplete")
                if text[cursor] == ",":
                    cursor += 1
        _, cursor = decoder.raw_decode(text, cursor)
        return text[start:cursor], cursor

    result, cursor = read(0)
    require(_space(text, cursor) == len(text), "Trailing native producer data")
    return result.encode("utf-8")


def verify_producer(native, raw_native, request, body, preflight):
    world = native["world_state"]
    producer = world["native_context_producer"]
    require(isinstance(producer, dict) and set(producer) == {"source", "sha256"},
            "Complete native producer fields required")
    source = producer["source"]
    require(isinstance(source, dict) and set(source) in ({
                "schema", "producer_revision", "thread_id", "context_id",
                "reference", "acquired_step", "template"}, {
                "schema", "producer_revision", "thread_id", "context_id",
                "reference", "acquired_step", "template", "acquisition"})
            and source["schema"] == "lax-native-context-producer/v1"
            and isinstance(source["producer_revision"], str) and source["producer_revision"]
            and source["thread_id"] == request["threadId"]
            and source["context_id"] == request["contextId"]
            and source["reference"] == native["reference_context"]
            and isinstance(source["acquired_step"], dict)
            and isinstance(source["template"], dict)
            and source["template"].get("snapshot") == world["state"],
            "Complete native producer scope or source baseline differs")
    raw_world = _member(raw_native, "world_state")
    raw_producer = _member(raw_world, "native_context_producer")
    raw_source = _member(raw_producer, "source")
    require(len(raw_producer.encode()) <= 1048576, "Native producer exceeds byte cap")
    digest(producer["sha256"])
    require(hashlib.sha256(canonical_native(raw_source)).hexdigest() == producer["sha256"],
            "Native producer bytes differ from source digest")
    if preflight is not None:
        require(preflight.get("producerSha256") == producer["sha256"]
                and preflight.get("state", {}).get("producerSha256") == producer["sha256"]
                and preflight.get("nextWindowId") == body["window_id"]
                and preflight.get("operationId") == request["operationId"],
                "Native checkpoint differs from reviewed producer/target")
    return producer


def verify_checkpoint(raw_line, body, base, request, response, mode, *, preflight=None):
    require(mode in ("step_boundary", "idle_request"), "Explicit native checkpoint mode required")
    require(len(raw_line) <= 1048576 + 4096, "Complete native checkpoint exceeds byte cap")
    payload = _member(raw_line.decode("utf-8"), "payload")
    raw_items = _array(_member(payload, "replacement_history"))
    raw_metadata = _array(_member(payload, "replacement_history_metadata"))
    history = body["replacement_history"]
    metadata = body["replacement_history_metadata"]
    require(0 < len(base) <= len(history) <= 256
            and len(raw_items) == len(raw_metadata) == len(history) == len(metadata),
            "Native checkpoint attribution is not aligned")
    # Match native core: only an atomic, core-owned AdditionalTools prefix
    # item uses the existing aggregate allowance. Canonical data and all other
    # prefix items keep their individual 32 KiB limit. Exact native source
    # provenance and group digests are verified below before acknowledgement.
    require(all(len(raw) <= (262144 if index < len(base)
                             and history[index].get("type") == "additional_tools"
                             else 32768)
                for index, raw in enumerate(raw_items))
            and len(b"[" + b",".join(raw_items) + b"]") <= 1048576,
            "Native model item or wire budget exceeded")
    require(sum(map(len, raw_metadata[:len(base)])) <= 262144,
            "Native source metadata budget exceeded")
    require(all(value == {"client_authored": False} for value in metadata[len(base):]),
            "Canonical data acquired unexpected native attribution")
    native = (body.get("resume_metadata") or {}).get("native_context")
    require(isinstance(native, dict) and set(native) == {
        "schema", "thread_id", "context_id", "mode", "world_state", "reference_context"},
        "Complete native reconstruction metadata required")
    require(native["schema"] == "lax-native-context-checkpoint/v1"
            and native["thread_id"] == request["threadId"]
            and native["context_id"] == request["contextId"] and native["mode"] == mode,
            "Native reconstruction mode or scope differs")
    require(body["resume_metadata"].get("last_started_turn_id") == request["turnId"]
            and isinstance(native["reference_context"], dict)
            and isinstance(native["world_state"], dict)
            and set(native["world_state"]) in (
                {"full", "state"}, {"full", "state", "native_context_producer"})
            and native["world_state"]["full"] is True
            and isinstance(native["world_state"]["state"], dict),
            "Native full baseline or historical turn correlation missing")
    complete = "native_context_producer" in native["world_state"]
    if complete:
        require(mode != "idle_request" or preflight is not None,
                "Complete idle checkpoint needs its reviewed preflight")
        raw_resume = _member(payload, "resume_metadata")
        raw_native = _member(raw_resume, "native_context")
        verify_producer(native, raw_native, request, body, preflight)
        require(preflight is None or (
                    preflight.get("prefixItemCount") == len(base)
                    and preflight.get("replacementItemCount") == len(history)
                    and preflight.get("replacementWireBytes") ==
                        len(b"[" + b",".join(raw_items) + b"]")),
                "Reviewed native replacement size differs")
        if preflight is not None:
            raw_wire = b"[" + b",".join(raw_items) + b"]"
            require(hashlib.sha256(canonical_native(raw_wire.decode("utf-8"))).hexdigest()
                    == preflight.get("replacementSha256"),
                    "Native checkpoint bytes differ from reviewed replacement")
    else:
        require(preflight is None or not any(
                    k in preflight for k in ("producerSha256", "nextWindowId")),
                "Reviewed complete producer missing from checkpoint")
    decoded_data = 0
    for item in response["items"]:
        require(item.get("type") == "function_call_output"
                and item.get("name") in ("context_refill", "context_actions", "retained_actions"),
                "Noncanonical data item in native checkpoint")
        fragment = json.loads(item["output"])
        require(isinstance(fragment.get("content"), str), "Canonical fragment missing")
        decoded_data += len(fragment["content"].encode("utf-8"))
    prefix_bytes = sum(map(len, raw_items[:len(base)]))
    require(prefix_bytes <= 524288, "Native prefix exceeds its aggregate cap")
    require(decoded_data <= 262144, "Selected data exceed their decoded cap")
    require(prefix_bytes + decoded_data <= 786432,
            "Native prefix and selected data exceed combined decoded cap")
    group = None
    group_items = []
    for index, item in enumerate(base):
        attributes = metadata[index]
        origin = attributes.get("native_context_origin")
        require(isinstance(origin, dict) and set(origin) == ORIGIN
                and attributes.get("client_authored", False) is False,
                "Native source provenance missing or client-authored")
        require(origin["schema"] == "lax-native-core-context/v1"
                and origin["thread_id"] == request["threadId"]
                and origin["context_id"] == request["contextId"],
                "Native source group belongs to another context")
        unsigned(origin["index"])
        unsigned(origin["count"])
        digest(origin["sha256"])
        require(0 < origin["count"] <= 256 and isinstance(origin["group_id"], str)
                and len(origin["group_id"]) <= 128, "Native source group bounds differ")
        identity = UUID(origin["group_id"])
        require(str(identity) == origin["group_id"]
                and identity.version == (8 if complete else 7),
                "Canonical native source group identity required")
        if complete:
            require(origin["group_id"] == body["window_id"]
                    and origin["kind"] == "prefix" and origin["count"] == len(base),
                    "Complete producer must stamp one full target prefix")
        if group is None:
            require(origin["index"] == 0 and origin["kind"] == ("prefix" if index == 0 else "update"),
                    "Incomplete or reordered native source base/update")
            group = origin
        require({k:v for k,v in origin.items() if k != "index"}
                == {k:v for k,v in group.items() if k != "index"}
                and origin["index"] == len(group_items),
                "Native source group order or metadata changed")
        require(json.loads(raw_items[index]) == item, "Native item wire differs")
        group_items.append(raw_items[index])
        if len(group_items) == origin["count"]:
            raw = b"[" + b",".join(group_items) + b"]"
            require(hashlib.sha256(raw).hexdigest() == origin["sha256"],
                    "Exact native source group bytes changed")
            group = None
            group_items = []
    require(group is None, "Native source group is incomplete")
