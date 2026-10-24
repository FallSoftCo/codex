"""Shared explicitly negotiated whole-native evidence packet, never task authority."""
import asyncio
import json

from .automatic_refill_data import IDENTITY, identifier, require, unsigned
from .native_action_bundle import render
from .native_action_pins import resolve

CAPABILITY = "canonical_retained_writer_context/v1"


def enabled(runner):
    version = runner.config.get("nativeActionRetention", 0)
    require(type(version) is int and version in (0, 1),
            "Explicit native-action retention version0/1 required")
    return version == 1 and runner.purpose == "writer"


async def frame(runner, snapshot, params, actions):
    require(enabled(runner), "Explicit paired whole-native Writer required")
    for name in IDENTITY | {"windowId"}:
        identifier(params[name])
    unsigned(params["historyVersion"])
    content = json.loads("".join(chunk["content"] for chunk in snapshot["chunks"]))
    require(params["threadId"] == runner.thread
            and params["contextId"] == runner.config["contextIds"]["writer"]
            and params["purpose"] == "writer"
            and content["agentId"] == runner.config["agentId"]
            and content["contextId"] == params["contextId"]
            and content["nativeThread"] == params["threadId"] and content["purpose"] == "writer",
            "Original retained snapshot belongs to another purpose/context")
    marks = content["selection"]["marks"]
    require(len(marks) <= 16, "Retained selection count exceeds contract")
    descriptors = [mark["native_action"] for mark in marks if "native_action" in mark]
    require(len(descriptors) <= 8, "Retained native pin count exceeds contract")
    entries = []
    for descriptor in descriptors:
        entries.append(await resolve(runner, descriptor))
    items, budget = await asyncio.to_thread(render, snapshot, params["operationId"], actions, entries)
    response = {key: params[key] for key in IDENTITY | {"windowId", "historyVersion"}}
    response.update(snapshotOperationId=params["operationId"],
        snapshotReadPoint=identifier(snapshot["snapshotReadPoint"]),
        snapshotSha256=snapshot["sha256"],
        nativeActionsSha256=budget["descriptorSha256"],
        selectionRevision=unsigned(snapshot["selectionRevision"]),
        totalBytes=snapshot["totalBytes"], items=items)
    return response, budget
