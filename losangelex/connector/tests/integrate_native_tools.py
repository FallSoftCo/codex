"""Real existing-thread tool upgrade and history continuity, with finite model turns."""

import argparse
import asyncio
import hashlib
import json
import os
import shutil
from pathlib import Path

from lax_connector.connector import saved, spec
from lax_connector.rpc import AppServer, RpcError


async def main(args):
    os.umask(0o077)
    root = args.state
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    intent = root / "qualification-intent.json"
    recovering = intent.exists() and args.resume_rejected
    if intent.exists() and not recovering:
        raise RuntimeError(
            "Original intent exists; inspect original receipts without replay"
        )
    if not recovering:
        saved(
            intent,
            {
                "binary": str(args.binary),
                "model": "gpt-6.1-sol",
                "effort": "xhigh",
                "scenario": "existing thread cold-resume tools, warm rejection, explicit empty declarations",
            },
        )
    home, work = root / "codex-home", root / "work"
    if not recovering:
        home.mkdir(mode=0o700)
        work.mkdir(mode=0o700)
        shutil.copyfile(args.auth, home / "auth.json")
        (home / "auth.json").chmod(0o600)
    else:
        assert (
            not list(work.iterdir()) and not (root / "native-tool-calls.json").exists()
        )
        errors = []
        for path in (home / "sessions").rglob("*.jsonl"):
            for line in path.read_text().splitlines():
                item = json.loads(line)
                payload = item.get("payload", {})
                if (
                    item.get("type") == "event_msg"
                    and payload.get("type") == "task_complete"
                ):
                    errors.append(payload.get("error", {}).get("message", ""))
        assert (
            len(errors) == 1
            and "invalid_request_error" in errors[0]
            and "Unknown parameter" in errors[0]
            and '"status":400' in errors[0]
        )
        saved(
            root / "known-rejection-reconciliation.json",
            {
                "originalTurnRejectedBeforeInference": True,
                "markerEffects": 0,
                "nativeReplay": False,
            },
        )
    future = None
    calls = []
    final = ""
    expected = None
    thread = None

    async def event(method, params):
        nonlocal final
        if params.get("threadId") != thread:
            return
        if (
            method == "item/completed"
            and params.get("item", {}).get("type") == "agentMessage"
        ):
            final = params["item"].get("text", "")
        if method == "turn/completed" and future and not future.done():
            future.set_result(params["turn"])
        if method == "hollywood/runtimeLost" and future and not future.done():
            future.set_exception(
                RuntimeError("Original native turn outcome requires inspection")
            )

    async def tool(method, params):
        if (
            method != "item/tool/call"
            or params["threadId"] != thread
            or params["tool"] != expected
        ):
            raise RuntimeError(
                "Unexpected native request; no approval or substitute effect inferred"
            )
        name = params["tool"]
        marker = work / (name + ".txt")
        if marker.exists():
            raise RuntimeError("Original marker effect already exists; do not repeat")
        with marker.open("x") as file:
            file.write(name + "\n")
            file.flush()
            os.fsync(file.fileno())
        calls.append(
            {
                "tool": name,
                "callId": params["callId"],
                "threadId": params["threadId"],
                "sha256": hashlib.sha256(marker.read_bytes()).hexdigest(),
            }
        )
        saved(root / "native-tool-calls.json", calls)
        return {
            "success": True,
            "contentItems": [{"type": "inputText", "text": name + " verified"}],
        }

    def declarations(name):
        return [
            spec(
                name,
                "Write and verify this one bounded protocol marker exactly once.",
                {},
                [],
            )
        ]

    async def turn(rpc, request):
        nonlocal future, final
        future = asyncio.get_running_loop().create_future()
        final = ""
        saved(
            root / ("turn-intent-" + str(len(calls)) + ".json"),
            {"threadId": thread, "input": request},
        )
        accepted = await rpc.call(
            "turn/start",
            {
                "threadId": thread,
                "model": "gpt-6.1-sol",
                "effort": "xhigh",
                "input": [{"type": "text", "text": request}],
            },
        )
        saved(root / ("turn-receipt-" + accepted["turn"]["id"] + ".json"), accepted)
        result = await asyncio.wait_for(future, 150)
        assert (
            result["id"] == accepted["turn"]["id"] and result["status"] == "completed"
        )
        return result

    settings = {
        "cwd": str(work),
        "model": "gpt-6.1-sol",
        "sandbox": "read-only",
        "approvalPolicy": "never",
        "developerInstructions": "This is a finite protocol integration exercise. Call only the explicitly requested marker tool once. Do no other work, create no agents, poll no models, resume no historical work and do not self-chain.",
        "config": {
            "features.multi_agent": False,
            "features.multi_agent_v2": False,
            "model_reasoning_effort": "xhigh",
        },
    }
    rpc = AppServer(str(args.binary), home, root / "native", event, tool)
    try:
        await rpc.start()
        if recovering:
            thread = json.loads((root / "thread-receipt.json").read_text())["thread"][
                "id"
            ]
            result = await rpc.call(
                "thread/resume",
                {
                    **settings,
                    "threadId": thread,
                    "excludeTurns": True,
                    "dynamicTools": declarations("baseline_marker"),
                },
            )
            assert result["thread"]["id"] == thread
            saved(root / "recovered-thread-receipt.json", result)
        else:
            result = await rpc.call(
                "thread/start",
                {**settings, "dynamicTools": declarations("baseline_marker")},
            )
            thread = result["thread"]["id"]
            saved(root / "thread-receipt.json", result)
        expected = "baseline_marker"
        baseline = await turn(
            rpc,
            "Call baseline_marker exactly once, then report its actual result and finish.",
        )
        try:
            await rpc.call(
                "thread/resume",
                {
                    "threadId": thread,
                    "excludeTurns": True,
                    "dynamicTools": declarations("upgraded_marker"),
                },
            )
        except RpcError as error:
            assert "loaded thread" in str(error)
            saved(
                root / "warm-rejection.json",
                {"rejected": True, "nativeTurnUnchanged": baseline["id"]},
            )
        else:
            raise AssertionError("Loaded thread tool replacement was not rejected")
    finally:
        await rpc.close()
    rpc = AppServer(str(args.binary), home, root / "native", event, tool)
    try:
        await rpc.start()
        resumed = await rpc.call(
            "thread/resume",
            {
                **settings,
                "threadId": thread,
                "excludeTurns": True,
                "dynamicTools": declarations("upgraded_marker"),
            },
        )
        assert resumed["thread"]["id"] == thread
        saved(root / "cold-upgrade-receipt.json", resumed)
        expected = "upgraded_marker"
        upgraded = await turn(
            rpc,
            "Use upgraded_marker exactly once. The old baseline marker must not be repeated. Report the actual result and finish.",
        )
        readback = await rpc.call(
            "thread/read", {"threadId": thread, "includeTurns": True}
        )
        saved(root / "history-readback.json", readback)
        ids = [t["id"] for t in readback["thread"]["turns"]]
        assert ids[-2:] == [baseline["id"], upgraded["id"]] and len(ids) == (
            3 if recovering else 2
        )
    finally:
        await rpc.close()
    rpc = AppServer(str(args.binary), home, root / "native", event, tool)
    try:
        await rpc.start()
        cleared = await rpc.call(
            "thread/resume",
            {**settings, "threadId": thread, "excludeTurns": True, "dynamicTools": []},
        )
        assert cleared["thread"]["id"] == thread
        saved(root / "empty-declarations-receipt.json", cleared)
        expected = None
        empty = await turn(
            rpc,
            "If upgraded_marker is available, call it. Otherwise reply EMPTY_DECLARATIONS. Do no other work.",
        )
        assert "EMPTY_DECLARATIONS" in final and len(calls) == 2
        result = {
            "passed": True,
            "nativeThread": thread,
            "nativeTurns": [baseline["id"], upgraded["id"], empty["id"]],
            "sameThreadIdentity": True,
            "baselineHistoryRetained": True,
            "loadedReplacementRejected": True,
            "explicitEmptyClientToolsRemoved": True,
            "markerEffects": calls,
            "models": "three finite gpt-6.1-sol/xhigh turns",
            "productionCutover": False,
            "phoneVerified": False,
        }
        saved(root / "result.json", result)
        print(json.dumps(result))
    finally:
        await rpc.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--auth", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--resume-rejected", action="store_true")
    asyncio.run(main(parser.parse_args()))
