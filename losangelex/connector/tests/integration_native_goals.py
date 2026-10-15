"""Actual native goal/plan control with a local deterministic Responses endpoint.

This proves runtime admission/accounting/protocol behavior, not model quality or
a real multi-agent deliverable. No provider credential or real inference is used.
"""

import asyncio
import hashlib
import json
import os
import re
from pathlib import Path
from aiohttp import web
from lax_connector.rpc import AppServer, RpcError
from lax_connector.native_goals import external_admission

ROOT = Path(os.environ["NATIVE_GOAL_EVIDENCE"])
BINARY = os.environ["NATIVE_GOAL_BINARY"]
ROLE_SCOPE = os.environ.get("NATIVE_GOAL_SCOPE") == "role"


async def main():
    os.umask(0o077)
    ROOT.mkdir(mode=0o700)
    intent = ROOT / "intent.json"
    if intent.exists():
        raise RuntimeError("Reconcile original native goal probe")
    intent.write_text(
        json.dumps(
            {
                "binary": BINARY,
                "sha256": hashlib.sha256(Path(BINARY).read_bytes()).hexdigest(),
                "actualProviderInference": False,
            }
        )
    )
    events = []
    requests = []
    turn_done = asyncio.Event()

    async def event(method, params):
        events.append({"method": method, "params": params})
        (ROOT / "events.json").write_text(json.dumps(events))
        if method == "turn/completed":
            turn_done.set()

    async def request(method, params):
        raise RuntimeError("No dynamic or approval request is expected")

    async def respond(req):
        body = await req.json()
        requests.append(body)
        (ROOT / "private-responses-requests.json").write_text(json.dumps(requests))
        idx = len(requests)
        if idx == 1:
            item = {
                "id": "fc_plan",
                "type": "function_call",
                "call_id": "call_plan",
                "name": "update_plan",
                "arguments": json.dumps(
                    {
                        "plan": [
                            {
                                "step": "Verify native admission binding",
                                "status": "completed",
                            }
                        ],
                        "explanation": "Explicitly admitted fixture turn",
                    }
                ),
            }
        else:
            item = {
                "id": "msg_probe",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": "NATIVE_GOAL_ADMISSION_VERIFIED",
                        "annotations": [],
                    }
                ],
            }
        data = [
            (
                "response.created",
                {"response": {"id": "resp_" + str(idx), "status": "in_progress"}},
            ),
            ("response.output_item.done", {"output_index": 0, "item": item}),
            (
                "response.completed",
                {
                    "response": {
                        "id": "resp_" + str(idx),
                        "status": "completed",
                        "output": [item],
                        "usage": {
                            "input_tokens": 10,
                            "output_tokens": 2,
                            "total_tokens": 12,
                        },
                    }
                },
            ),
        ]
        text = "".join(
            "event: "
            + name
            + chr(10)
            + "data: "
            + json.dumps({"type": name, **value})
            + chr(10) * 2
            for name, value in data
        )
        return web.Response(text=text, content_type="text/event-stream")

    app = web.Application()
    app.router.add_post("/v1/responses", respond)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    base = "http://127.0.0.1:" + str(site._server.sockets[0].getsockname()[1]) + "/v1"
    rpc = None
    home = ROOT / "codex-home"
    native = ROOT / "native"
    workspace = ROOT / "work"
    workspace.mkdir()
    settings = {
        "cwd": str(workspace),
        "model": "gpt-6.1-sol",
        "approvalPolicy": "never",
        "sandbox": "workspace-write",
        "config": {
            "features.goal_external_admission": True,
            "features.goal_external_lifecycle": ROLE_SCOPE,
            "features.goals": True,
            "model_provider": "goal_probe",
            "tools.update_plan.enabled": True,
            "model_reasoning_effort": "xhigh",
            "model_providers.goal_probe": {
                "name": "Local native admission probe",
                "base_url": base,
                "wire_api": "responses",
                "requires_openai_auth": False,
                "request_max_retries": 0,
            },
        },
    }

    async def open_runtime():
        r = AppServer(BINARY, home, native, event, request)
        await r.start()
        await external_admission(r, ROLE_SCOPE)
        return r

    try:
        rpc = await open_runtime()
        started = await rpc.call("thread/start", settings)
        thread = started["thread"]["id"]
        (ROOT / "thread-receipt.json").write_text(json.dumps(started))
        feature = []
        cursor = None
        while True:
            page = await rpc.call(
                "experimentalFeature/list",
                {
                    "threadId": thread,
                    "limit": 100,
                    **({"cursor": cursor} if cursor else {}),
                },
            )
            feature += page["data"]
            cursor = page.get("nextCursor")
            if not cursor:
                break
        flag = next(f for f in feature if f["name"] == "goal_external_admission")
        assert flag["enabled"] is True
        # Materialize the fresh empty context through metadata, without a turn.
        # The disposable seed is explicitly cleared before either racing caller.
        seed = await rpc.call(
            "thread/goal/set",
            {
                "threadId": thread,
                "expectedGoalId": None,
                "origin": "automatic",
                "objective": "Disposable metadata materialization seed.",
                "status": "paused",
            },
        )
        (ROOT / "materialization-seed.json").write_text(json.dumps(seed))
        await rpc.call("thread/goal/clear", {"threadId": thread, "origin": "automatic"})
        assert (await rpc.call("thread/goal/get", {"threadId": thread}))["goal"] is None
        second = await open_runtime()
        try:
            try:
                await second.call(
                    "thread/resume",
                    {"threadId": thread, "excludeTurns": True, **settings},
                )
                raise AssertionError("A second native context writer was admitted")
            except RpcError as error:
                assert "active writer" in str(error), str(error)
            create = {
                "threadId": thread,
                "expectedGoalId": None,
                "origin": "automatic",
                "objective": "Exercise one explicitly admitted goal turn and persist its structured plan. Remain active for metadata readback.",
                "status": "active",
            }
            race = await asyncio.gather(
                rpc.call("thread/goal/set", create),
                second.call("thread/goal/set", create),
                return_exceptions=True,
            )
            winners = [r for r in race if isinstance(r, dict)]
            failures = [r for r in race if isinstance(r, RpcError)]
            assert len(winners) == 1 and len(failures) == 1, [
                (type(r).__name__, str(r)[:200]) for r in race
            ]
            goal = winners[0]
            assert (
                goal["goalId"]
                and (await rpc.call("thread/goal/get", {"threadId": thread}))["goalId"]
                == goal["goalId"]
            )
        finally:
            await second.close()
        (ROOT / "initial-goal.json").write_text(json.dumps(goal))
        await asyncio.sleep(2)
        assert requests == [] and not any(e["method"] == "turn/started" for e in events)
        await rpc.close()
        rpc = None
        rpc = await open_runtime()
        await rpc.call(
            "thread/resume", {"threadId": thread, "excludeTurns": True, **settings}
        )
        restored = await rpc.call("thread/goal/get", {"threadId": thread})
        assert (
            restored["goal"]["status"] == "active"
            and restored["goal"]["objective"] == goal["goal"]["objective"]
        )
        await asyncio.sleep(2)
        assert requests == [] and not any(e["method"] == "turn/started" for e in events)
        submitted = await rpc.call(
            "turn/start",
            {
                "threadId": thread,
                "input": [
                    {
                        "type": "text",
                        "text": "Run the finite native protocol probe now.",
                    }
                ],
            },
        )
        (ROOT / "explicit-turn-receipt.json").write_text(json.dumps(submitted))
        await asyncio.wait_for(turn_done.wait(), 30)
        await asyncio.sleep(2)
        final = await rpc.call("thread/goal/get", {"threadId": thread})
        plans = [e for e in events if e["method"] == "turn/plan/updated"]
        starts = [e for e in events if e["method"] == "turn/started"]
        assert len(starts) == 1, (len(starts), starts)
        assert len(requests) == 2, len(requests)

        def names(value):
            if isinstance(value, dict):
                return ({value["name"]} if "name" in value else set()).union(
                    *(names(v) for v in value.values())
                )
            if isinstance(value, list):
                return set().union(*(names(v) for v in value))
            return set()

        tool_names = names(requests[0])
        # Current Responses carries its tool catalog inside the first input item.
        # Code Mode advertises callable native tools in its typed declaration.
        tool_names.update(re.findall(r"\b(get_goal|create_goal|update_goal)\(args:", json.dumps(requests[0])))
        assert "get_goal" in tool_names, tool_names
        assert "create_goal" not in tool_names, tool_names
        assert ("update_goal" in tool_names) is not ROLE_SCOPE, tool_names
        assert plans and plans[-1]["params"]["plan"][0]["status"] == "completed", plans
        assert (
            final["goal"]["status"] == "active" and final["goal"]["tokensUsed"] > 0
        ), final
        await rpc.call(
            "thread/goal/set",
            {
                "threadId": thread,
                "expectedGoalId": goal["goalId"],
                "origin": "automatic",
                "status": "complete",
            },
        )
        replacement = await rpc.call(
            "thread/goal/set",
            {
                "threadId": thread,
                "expectedGoalId": goal["goalId"],
                "origin": "automatic",
                "objective": "A fresh explicitly authorized metadata objective.",
                "status": "active",
            },
        )
        assert (
            replacement["goalId"] != goal["goalId"]
            and replacement["goal"]["tokensUsed"] == 0
        )
        try:
            await rpc.call(
                "thread/goal/set",
                {
                    "threadId": thread,
                    "expectedGoalId": goal["goalId"],
                    "origin": "automatic",
                    "status": "paused",
                },
            )
            raise AssertionError("Stale goal mutation was accepted")
        except RpcError:
            pass
        await asyncio.sleep(1)
        current = await rpc.call("thread/goal/get", {"threadId": thread})
        assert (
            current["goalId"] == replacement["goalId"]
            and current["goal"]["status"] == "active"
        )
        assert len([e for e in events if e["method"] == "turn/started"]) == 1
        history = await rpc.call(
            "thread/read", {"threadId": thread, "includeTurns": True}
        )
        (ROOT / "history.json").write_text(json.dumps(history))
        (ROOT / "final-goal.json").write_text(json.dumps(final))
        result = {
            "state": "passed",
            "twoNativeProcessesCreateOneGoal": True,
            "nativeGoalIdentityRetained": True,
            "completedGoalReplacementFenced": True,
            "staleGoalMutationDenied": True,
            "threadId": thread,
            "turnId": submitted["turn"]["id"],
            "activeGoalSetStartedNoTurn": True,
            "coldResumeStartedNoTurn": True,
            "explicitTurns": 1,
            "automaticContinuations": 0,
            "structuredNativePlanObserved": True,
            "nativeGoalAccountingRetained": True,
            "externalLifecycle": ROLE_SCOPE,
            "modelLifecycleTools": "get only" if ROLE_SCOPE else "get/update",
            "modelGoalCreationExcluded": True,
            "provider": "local deterministic Responses fixture",
            "realModelInference": False,
            "productionChanged": False,
        }
        (ROOT / "result.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
    finally:
        if rpc:
            await rpc.close()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
