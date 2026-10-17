"""Carry owner-authenticated briefing metadata from the actual managed guardian.

This local metadata port never admits a model or grants a filesystem effect.
Only the registered connector guardian can publish; child shells/native tools
cannot choose this source. Receipt/observation is not model-comprehension proof.
"""

import asyncio
import json
import socket
import struct
from pathlib import Path
from uuid import UUID

from . import service_observer as observer
from .collaboration_bridge import digest, protected_directory, require, receive
from .collaboration_capture import installed_native_owner
from .journal import saved

PORT = "owner-briefing/v1"
FIELDS = {
    "schema",
    "authorityId",
    "agentId",
    "roomId",
    "deliveryId",
    "generation",
    "claimId",
    "asOfSequence",
}


def guardian_peer(capture, peer):
    actual = observer.process(peer[0])
    require(
        actual and actual["uid"] == peer[1], "Owner guardian kernel identity vanished"
    )
    authority, host = capture.config["authorityId"], capture.config["hostId"]
    agent, _ = installed_native_owner(authority, peer[1])
    uid, home, binary = observer.expected_owner(authority, agent)
    info = observer.properties(observer.installed_unit(authority, agent))
    require(
        info["ActiveState"] == "active"
        and int(info["MainPID"]) == peer[0]
        and actual["uid"] == uid
        and actual["controlGroup"] == info["ControlGroup"],
        "Briefing source is not the actual managed connector guardian",
    )
    root = observer.directory(authority, host, agent)
    baseline = observer.protected(root / "enrollment.json")
    image = Path(binary).resolve(strict=True).stat()
    expected = {
        "schema": "lax-service-enrollment/v1",
        "authorityId": authority,
        "hostId": host,
        "agentId": agent,
        "uid": uid,
        "home": str(home),
        "unit": info["Id"],
        "unitDefinitionDigest": observer.unit_definition(info),
        "binary": str(Path(binary).resolve()),
        "binaryDevice": image.st_dev,
        "binaryInode": image.st_ino,
        "machineIdentity": observer.machine_identity(),
        "killMode": "control-group",
    }
    require(baseline == expected, "Owner guardian enrollment changed")
    invocation = UUID(info["InvocationID"]).hex
    binding = {
        **baseline,
        "schema": "lax-service-incarnation/v1",
        "bootId": observer.boot_id(),
        "serviceInvocation": invocation,
        "controlGroup": info["ControlGroup"],
        "guardianPid": actual["pid"],
        "guardianStart": actual["start"],
    }
    require(
        observer.protected(root / (invocation + ".json")) == binding,
        "Owner guardian protected incarnation differs",
    )
    return {"agentId": agent, "actual": actual, "bindingDigest": digest(binding)}


def identity(base):
    return {
        key: base[key]
        for key in (
            "authorityId",
            "hostId",
            "agentId",
            "deliveryId",
            "generation",
            "claimId",
            "contextId",
            "nativeThread",
            "roleRevision",
        )
    }


def carry(capture, peer, frame, owner):
    require(
        set(frame)
        == {
            "schema",
            "briefing",
            "responseSha256",
            "contextId",
            "nativeThread",
            "roleRevision",
        }
        and frame["schema"] == "lax-owner-briefing/v1",
        "Typed owner briefing projection required",
    )
    current = guardian_peer(capture, peer)
    require(current == owner, "Owner guardian changed while reading metadata")
    brief = frame["briefing"]
    require(
        set(brief) == FIELDS
        and brief["schema"] == "lax-work-briefing/v1"
        and type(brief["asOfSequence"]) is int
        and brief["asOfSequence"] >= 0,
        "Exact authenticated owner briefing scope required",
    )
    snapshot = capture.admin_http("GET", "deliveries/" + str(UUID(brief["deliveryId"])))
    delivery, event, binding = (
        snapshot["delivery"],
        snapshot["request"],
        snapshot["agentContextBinding"],
    )
    require(
        delivery["state"] in {"claimed", "running"}
        and not delivery["cancellation_requested"]
        and (
            delivery["agent"],
            delivery["host"],
            delivery["generation"],
            delivery["claim_id"],
        )
        == (
            owner["agentId"],
            capture.config["hostId"],
            brief["generation"],
            brief["claimId"],
        )
        and (brief["authorityId"], brief["agentId"], brief["roomId"])
        == (capture.config["authorityId"], owner["agentId"], event["room"]),
        "Owner briefing differs from its current canonical execution",
    )
    require(
        (
            binding["delivery"],
            binding["generation"],
            binding["principal"],
            binding["context_id"],
            binding["native_thread"],
            binding["role_revision"],
        )
        == (
            delivery["id"],
            delivery["generation"],
            owner["agentId"],
            frame["contextId"],
            frame["nativeThread"],
            frame["roleRevision"],
        ),
        "Owner briefing context binding changed",
    )
    role = capture.admin_http("GET", "agents/" + owner["agentId"] + "/role")
    require(role["revision"] == frame["roleRevision"], "Owner briefing role changed")
    require(
        isinstance(frame["responseSha256"], str)
        and len(frame["responseSha256"]) == 64
        and all(c in "0123456789abcdef" for c in frame["responseSha256"]),
        "Owner response digest required",
    )
    base = {
        **{
            key: brief[key]
            for key in ("authorityId", "agentId", "deliveryId", "generation", "claimId")
        },
        "hostId": capture.config["hostId"],
        "contextId": frame["contextId"],
        "nativeThread": frame["nativeThread"],
        "roleRevision": frame["roleRevision"],
    }
    record = {
        "schema": "lax-captured-owner-briefing/v1",
        "source": identity(base),
        "briefing": brief,
        "responseSha256": frame["responseSha256"],
        "guardian": owner["actual"],
        "serviceBindingDigest": owner["bindingDigest"],
        "modelsStarted": 0,
        "mayApply": False,
    }
    root = protected_directory(capture.state / "briefings")
    path = root / (digest(identity(base)) + "-" + str(brief["asOfSequence"]) + ".json")
    if path.exists():
        require(
            observer.protected(path) == record,
            "Original protected owner briefing changed",
        )
    else:
        saved(path, record)
    return {
        "success": True,
        "result": {
            "schema": "lax-owner-briefing-receipt/v1",
            "asOfSequence": brief["asOfSequence"],
            "projectionSha256": digest(record),
            "mayApply": False,
        },
        "canonicalReceipt": None,
        "holdReason": None,
    }


def sequence(bridge, record):
    base = identity(record["sourceBase"])
    prefix = digest(base) + "-"
    paths = list((bridge.state / "briefings").glob(prefix + "*.json"))
    require(
        paths and len(paths) <= 128, "Protected matching owner briefing unavailable"
    )
    path = max(paths, key=lambda path: int(path.stem[len(prefix) :]))
    value = observer.protected(path)
    require(
        value["schema"] == "lax-captured-owner-briefing/v1"
        and value["source"] == base
        and value["serviceBindingDigest"] == record["serviceBindingDigest"]
        and value["mayApply"] is False
        and type(value["briefing"]["asOfSequence"]) is int
        and value["briefing"]["asOfSequence"] == int(path.stem[len(prefix) :]),
        "Protected owner briefing belongs to another source/incarnation",
    )
    return value["briefing"]["asOfSequence"]


def _publish(c, value):
    authority, host = c.active["request"]["authority"], c.config["hostId"]
    descriptor_path = Path(
        c.config.get("nativeCollaborationChannel")
        or Path("/etc/harness") / authority / "collaboration" / host / "channel.json"
    )
    if not descriptor_path.exists():
        return None
    protected_directory(descriptor_path.parent)
    descriptor = observer.protected(descriptor_path)
    require(
        set(descriptor) == {"schema", "socket", "ports"}
        and descriptor["schema"] == "lax-native-collaboration-channel/v1",
        "Protected local channel descriptor differs",
    )
    if PORT not in descriptor["ports"]:
        return None  # Legacy plans remain explicit; this does not enable direct edits.
    frame = {
        "schema": "lax-owner-briefing/v1",
        "briefing": {key: value[key] for key in FIELDS},
        "responseSha256": digest(value),
        "contextId": c.context_id,
        "nativeThread": c.thread,
        "roleRevision": c.role_context.value["roleRevision"],
    }
    wire = json.dumps(frame, separators=(",", ":")).encode()
    require(len(wire) <= 65536, "Owner metadata projection exceeds frame bound")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        stream.settimeout(5)
        stream.connect(descriptor["socket"])
        stream.sendall(struct.pack("!I", len(wire)) + wire)
        size = struct.unpack("!I", receive(stream, 4))[0]
        require(0 < size <= 65536, "Bounded owner metadata reply required")
        reply = json.loads(receive(stream, size))
    result = reply.get("result") or {}
    require(
        reply.get("success") is True
        and result.get("mayApply") is False
        and result.get("schema") == "lax-owner-briefing-receipt/v1"
        and result.get("asOfSequence") == value["asOfSequence"],
        "Owner metadata was not captured; no mutation authority inferred",
    )
    return reply["result"]


async def publish(c, value):
    if not getattr(c, "thread", None) or not getattr(c, "context_id", None):
        return None
    try:
        return await asyncio.to_thread(_publish, c, value)
    except Exception as error:
        # Read/command execution survives optional editing infrastructure gaps.
        saved(
            c.state / "owner-briefing-gap.json",
            {
                "error": type(error).__name__,
                "deliveryId": c.active["delivery"]["id"],
                "editingAdmitted": False,
                "modelsStarted": 0,
            },
        )
        return None
