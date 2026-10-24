"""Immutable, original-host native evidence pins; never execution or selection authority.

Capture reads the entire original canonical item. Resolve reads the pinned bytes,
not a later native item version, and reauthorizes their original source each time.
This substrate is not exposed to models until the selection/refill pair qualifies.
"""
import hashlib
import json
import os
import re
import stat
import tempfile
from uuid import UUID, uuid5

from .context_action_memory import TERMINAL, load_action, scope
from .context_action_pages import authorize_source, wire
from .errors import HttpFailure

MAX_ITEM_BYTES = 32768
MAX_PIN_BYTES = 98304
FIELDS = {"schema", "reference", "authorityId", "agentId", "contextId", "hostId",
          "nativeThread", "nativeTurn", "itemId", "scopeId", "materialId",
          "sourceRequestId", "deliveryId", "sha256", "payloadBytes"}
SCHEMA = "lax-native-action-pin-metadata/v1"


def owned(runner, metadata):
    if runner.purpose != "writer":
        raise PermissionError("Native action pins belong to the original Writer")
    expected = {"authorityId": runner.config["authorityId"],
                "agentId": runner.config["agentId"],
                "contextId": runner.config["contextIds"]["writer"],
                "hostId": runner.config["hostId"], "nativeThread": runner.thread}
    if any(metadata.get(k) != v for k, v in expected.items()):
        raise PermissionError("Pinned evidence belongs to another original host/context/thread")


def root(runner):
    path = runner.state / "native-action-pins"
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise PermissionError("Native pin directory is not private original-host state")
    return path


def metadata_for(runner, owner, native_turn, item, encoded):
    metadata = {"schema": SCHEMA,
                **{k: owner[k] for k in ("authorityId", "agentId", "contextId", "hostId",
                                         "nativeThread", "materialId", "sourceRequestId",
                                         "deliveryId")},
                "nativeTurn": native_turn, "itemId": item["id"], "scopeId": owner["id"],
                "sha256": hashlib.sha256(encoded.encode()).hexdigest(),
                "payloadBytes": len(encoded.encode())}
    owned(runner, metadata)
    metadata["reference"] = "exec:" + str(uuid5(UUID(metadata["contextId"]),
        native_turn + ":" + item["id"] + ":" + metadata["sha256"]))
    return metadata


def read_private(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) & 0o077 or info.st_size > MAX_PIN_BYTES):
            raise PermissionError("Original native pin ownership or bounds changed")
        return stream.read(MAX_PIN_BYTES + 1)


def immutable(path, encoded):
    """Publish a fully fsynced file without ever replacing an existing pin."""
    fd, temporary = tempfile.mkstemp(prefix=".pin-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            if read_private(path) != encoded:
                raise RuntimeError("Original immutable pin changed; no replacement attempted")
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.unlink(temporary)


async def capture(runner, native_turn, item_id, expected_sha256):
    """Stage a whole terminal item. This does not adopt any retained-input mark."""
    if not isinstance(expected_sha256, str) or not re.fullmatch("[a-f0-9]{64}", expected_sha256):
        raise ValueError("Exact previously observed canonical item digest required")
    owner, item, encoded = await load_action(runner, native_turn, item_id)
    metadata = metadata_for(runner, owner, native_turn, item, encoded)
    if metadata["sha256"] != expected_sha256:
        raise RuntimeError("Original native item changed; do not substitute a later version")
    if item.get("status") not in TERMINAL:
        raise RuntimeError("Only terminal original action items can be pinned")
    if metadata["payloadBytes"] > MAX_ITEM_BYTES:
        raise ValueError("Whole original item exceeds retained-item budget; nothing was selected")
    envelope = {"schema": "lax-native-action-pin/v1", "metadata": metadata, "payload": encoded}
    data = wire(envelope).encode()
    if len(data) > MAX_PIN_BYTES:
        raise ValueError("Whole original pin exceeds storage envelope budget")
    pin_sha = hashlib.sha256(data).hexdigest()
    immutable(root(runner) / (pin_sha + ".json"), data)
    return {**metadata, "pinSha256": pin_sha}


async def resolve(runner, descriptor):
    """Current authorization gates exact historical payload, including completed Work."""
    if set(descriptor) != FIELDS | {"pinSha256"} or descriptor.get("schema") != SCHEMA:
        raise ValueError("Exact versioned native pin descriptor required")
    owned(runner, descriptor)
    pin_sha = descriptor["pinSha256"]
    if not isinstance(pin_sha, str) or not re.fullmatch("[a-f0-9]{64}", pin_sha):
        raise ValueError("Exact original pin digest required")
    owner = scope(runner, descriptor["nativeTurn"])
    if not owner or any(owner.get(k) != descriptor[k] for k in (
            "authorityId", "agentId", "contextId", "hostId", "nativeThread",
            "materialId", "sourceRequestId", "deliveryId")) or owner.get("id") != descriptor["scopeId"]:
        raise PermissionError("Original pinned execution scope no longer resolves")
    try:
        await authorize_source(runner, owner)
    except HttpFailure as error:
        if error.status != 403:
            raise
        return {"reference": descriptor["reference"], "access": "unavailable",
                "reason": "original_source_not_authorized"}
    try:
        data = read_private(root(runner) / (pin_sha + ".json"))
    except FileNotFoundError:
        return {"reference": descriptor["reference"], "access": "unavailable",
                "reason": "original_host_pin_missing"}
    if hashlib.sha256(data).hexdigest() != pin_sha:
        raise RuntimeError("Original pin integrity changed; no history substitution allowed")
    envelope = json.loads(data)
    metadata = {k: descriptor[k] for k in FIELDS}
    if (set(envelope) != {"schema", "metadata", "payload"}
            or envelope["schema"] != "lax-native-action-pin/v1"
            or envelope["metadata"] != metadata or not isinstance(envelope["payload"], str)):
        raise RuntimeError("Original pin metadata changed")
    encoded = envelope["payload"]
    if (type(metadata["payloadBytes"]) is not int
            or not 0 < metadata["payloadBytes"] <= MAX_ITEM_BYTES
            or len(encoded.encode()) != metadata["payloadBytes"]
            or hashlib.sha256(encoded.encode()).hexdigest() != metadata["sha256"]):
        raise RuntimeError("Original whole-item bytes or digest changed")
    item = json.loads(encoded)
    if (item.get("id") != metadata["itemId"] or item.get("status") not in TERMINAL
            or wire(item) != encoded):
        raise RuntimeError("Original canonical action item changed")
    if metadata_for(runner, owner, metadata["nativeTurn"], item, encoded) != metadata:
        raise RuntimeError("Original pin identity changed")
    return {"reference": descriptor["reference"], "metadata": descriptor, "payload": encoded}
