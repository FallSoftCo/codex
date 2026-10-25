"""Actual native process/history integration with declared scripted provider/H metadata.

This is not real-model behavior, Hollywood authorization or human-API approval proof.
"""
import argparse
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from aiohttp import WSMsgType, web
from lax_connector.rpc import AppServer
from lax_connector.idle_context_rebuild import IdleContextRebuild


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class MetadataFixture:
    """Declared in-memory H metadata; native RPC and history are never mocked."""
    def __init__(self):
        self.receipts = {}
        self.generation = 0

    async def http(self, purpose, method, path):
        return self.receipts[path.rsplit("/", 1)[1]]

    async def request(self, runner, action, value, operation, turn):
        if action == "rebuild_snapshot":
            content = {"schema": "lax-context-rebuild/v1", "agentId": runner.config["agentId"],
                "contextId": runner.config["contextIds"]["writer"], "purpose": "writer",
                "nativeThread": runner.thread, "selection": {"selectionRevision": 1, "marks": []},
                "nextMaterialIds": [], "obligations": [],
                "records": [{"reference": "role", "content": {"role": "writer",
                             "fact": "SELECTED_FACT_NAUTICAL_LOCALE"}}]}
            encoded = wire(content)
            return {"schema": "lax-context-rebuild-snapshot/v1",
                "sha256": hashlib.sha256(encoded.encode()).hexdigest(), "totalBytes": len(encoded.encode()),
                "snapshotReadPoint": "declared-metadata-fixture",
                "chunks": [{"offset": n, "content": encoded[n:n+3072]} for n in range(0, len(encoded), 3072)],
                "selectionRevision": 1, "requestOperationId": runner.requested,
                "nativeThread": runner.thread, "contextId": runner.config["contextIds"]["writer"]}
        assert action == "rebuild_installed", action
        self.generation += 1
        result = {**value, "status": "recorded", "generation": self.generation}
        self.receipts[operation] = result
        return result


async def main(args):
    os.umask(0o077)
    root = args.evidence
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    requests, events, processes, checks = [], [], [], []
    fixture = MetadataFixture()
    stopped = asyncio.Event()
    completed = asyncio.Event()
    fixture.stop = stopped
    config = {"agentId": str(uuid4()), "contextIds": {"writer": str(uuid4())},
              "nativeActionRetention": 1, "contextRebuildEnabled": True}
    state, home = root / "state", root / "home"
    state.mkdir(); home.mkdir()
    r = SimpleNamespace(config=config, purpose="writer", state=state, agent=fixture,
        active=False, accepting=False, closing=False, failed=False, effect_lock=asyncio.Lock(),
        retained_context_contract=True, automatic=SimpleNamespace(blocked=False))
    r.trace = lambda name, data: events.append({"event": name, "data": data})

    async def request(action, value=None, *, operation=None, turn=None):
        return await fixture.request(r, action, value, operation, turn)
    r.request = request

    def scripted():
        number = len(requests)
        return [
            {"type": "response.created", "response": {"id": "fixture-" + str(number)}},
            {"type": "response.output_item.done", "item": {"type": "message", "role": "assistant",
             "id": "message-" + str(number), "content": [{"type": "output_text", "text": "Declared scripted completion"}]}},
            {"type": "response.completed", "response": {"id": "fixture-" + str(number),
             "usage": {"input_tokens": 0, "input_tokens_details": None, "output_tokens": 0,
                       "output_tokens_details": None, "total_tokens": 0}}}]

    async def provider(incoming):
        ws = web.WebSocketResponse()
        if ws.can_prepare(incoming).ok:
            await ws.prepare(incoming)
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    requests.append(json.loads(msg.data))
                    for event in scripted():
                        await ws.send_json(event)
            return ws
        if incoming.method != "POST":
            return web.json_response({"error": "fixture accepts Responses only"}, status=404)
        requests.append(await incoming.json())
        body = "".join("data: " + json.dumps(event) + "\n\n" for event in scripted())
        return web.Response(text=body, content_type="text/event-stream")

    app = web.Application()
    app.router.add_route("*", "/{path:.*}", provider)
    server = web.AppRunner(app, access_log=None)
    await server.setup()
    site = web.TCPSite(server, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    (home / "config.toml").write_text(
        'model = "mock-model"\napproval_policy = "never"\nsandbox_mode = "read-only"\n'
        'model_provider = "review_fixture"\n[model_providers.review_fixture]\n'
        'name = "Declared local protocol fixture"\nwire_api = "responses"\n'
        'base_url = "http://127.0.0.1:' + str(port) + '/v1"\n'
        'supports_websockets = true\nrequest_max_retries = 0\nstream_max_retries = 0\n')
    policy = {"type": "canonicalRetainedActions",
              "contextId": config["contextIds"]["writer"], "purpose": "writer"}

    async def event(method, params):
        events.append({"method": method, "params": params})
        if method == "turn/completed":
            assert params["turn"]["status"] == "completed", params
            completed.set()

    async def callback(method, params):
        if method == "thread/contextWindow/idleInstalled":
            return await r.idle.callback(params)
        assert method == "thread/contextWindow/reconcile", method
        return await r.idle.reconcile(params)

    async def submitted(method, params, success):
        await r.idle.submitted(params, success)

    async def spawned(rpc):
        processes.append({"pid": rpc.process.pid, "startTicks":
            Path("/proc/" + str(rpc.process.pid) + "/stat").read_text().rsplit(")", 1)[1].split()[19]})

    async def connect(resume=None):
        r.rpc = AppServer(str(args.binary), home, state / "rpc", event, callback,
                          on_submission=submitted, on_spawn=spawned, isolated_process_group=True)
        await r.rpc.start()
        method = "thread/start" if resume is None else "thread/resume"
        params = {"automaticContextRefill": policy, "cwd": str(root)}
        if resume is not None:
            params["threadId"] = resume
        response = await r.rpc.call(method, params)
        r.thread = response["thread"]["id"]
        r.history = Path(response["thread"]["path"])
        r.idle = IdleContextRebuild(r)

    async def turn(text):
        completed.clear()
        await r.rpc.call("turn/start", {"threadId": r.thread,
            "input": [{"type": "text", "text": text, "textElements": []}]})
        await asyncio.wait_for(completed.wait(), 45)

    async def cut():
        return (await r.rpc.call("thread/contextWindow/read", {"threadId": r.thread}))["state"]

    async def refused(awaitable, contains):
        try:
            await awaitable
        except RuntimeError as error:
            assert contains in str(error), str(error)
        else:
            raise AssertionError("Expected explicit pre-dispatch refusal: " + contains)

    try:
        await connect()
        await turn("OMIT_ARCHIVE_CANARY -- original discarded-window fixture")
        assert len(requests) == 1
        before, original_cut = r.history.read_bytes(), await cut()
        r.requested = "review-preparation-original"
        prepared = await r.idle.prepare_for_review(r.requested, [])
        assert prepared["state"] == "review_prepared" and r.idle.blocked
        approval = prepared["approvalDigest"]
        await asyncio.sleep(0.2)
        assert r.history.read_bytes() == before and await cut() == original_cut and len(requests) == 1
        assert "nativeDispatchIntent" not in prepared
        checks.append("Prepared real native packet waits without history change, replacement gate or provider request")
        await refused(r.idle.apply_prepared(prepared, approved_digest="0"*64), "Exact reviewed")
        config["reviewMutation"] = "changed"
        await refused(r.idle.apply_prepared(prepared, approved_digest=approval), "configuration changed")
        config.pop("reviewMutation")
        prepared["snapshot"]["totalBytes"] += 1
        await refused(r.idle.apply_prepared(prepared, approved_digest=approval), "no-dispatch proof changed")
        prepared["snapshot"]["totalBytes"] -= 1
        assert not r.failed and r.history.read_bytes() == before and len(requests) == 1
        checks.append("Wrong approval, changed configuration and altered packet refuse before dispatch; owner remains usable")
        receipt = await r.idle.apply_prepared(prepared, approved_digest=approval)
        assert receipt["generation"] == 1 and len(requests) == 1
        assert (await cut())["windowId"] != original_cut["windowId"]
        assert not r.idle.blocked and prepared["state"] == "native_result_confirmed"
        await refused(r.idle.cancel_prepared(prepared), "owner connection changed")
        await turn("Continue the same declared fixture after the explicit reviewed install")
        assert len(requests) == 2
        encoded = wire(requests[-1])
        assert "SELECTED_FACT_NAUTICAL_LOCALE" in encoded and "OMIT_ARCHIVE_CANARY" not in encoded
        assert requests[-1].get("previous_response_id") is None
        checks.append("Explicit apply independently verifies original checkpoint; next provider input uses selected fact and omits old canary/cache")
        r.requested = "explicit-cancelled-review"
        unchanged = r.history.read_bytes()
        cancelled = await r.idle.prepare_for_review(r.requested, [])
        await r.idle.cancel_prepared(cancelled)
        assert r.history.read_bytes() == unchanged and not r.idle.blocked and len(requests) == 2
        checks.append("Known prepared-only cancellation preserves history and unblocks this owner")
        r.requested = "unchanged-immediate-rebuild-path"
        assert (await r.idle.rebuild(r.requested, []))["generation"] == 2
        assert len(requests) == 2
        checks.append("Original immediate rebuild still installs under its original receipt lifecycle")
        r.requested = "review-survives-cold-owner"
        cold = await r.idle.prepare_for_review(r.requested, [])
        cold_digest, thread = cold["approvalDigest"], r.thread
        await r.rpc.close()
        await connect(resume=thread)
        await r.idle.startup()
        assert not r.failed and r.idle.pending["operationId"] == cold["operationId"]
        assert r.idle.pending["approvalDigest"] == cold_digest and len(requests) == 2
        assert await cut() != cold["preflight"]["state"]
        unchanged = r.history.read_bytes()
        await refused(r.idle.apply_prepared(r.idle.pending, approved_digest=cold_digest),
                      "cut changed")
        assert r.history.read_bytes() == unchanged and len(requests) == 2 and not r.failed
        await r.idle.cancel_prepared(r.idle.pending)
        assert not r.idle.blocked
        checks.append("Cold owner restores pending review without inference; stale cut refuses before dispatch and can be explicitly cancelled")
        rows = [json.loads(line) for line in r.history.read_text().splitlines()]
        intents = [x for x in rows if x.get("payload", {}).get("type") == "context_window_refill_intent"]
        assert len(intents) == 2
        assert all(value["operationId"] == fixture.receipts["context-refill-installed:" +
            value["operationId"].rsplit(":", 1)[1]]["nativeReceipt"]["operationId"] for value in
            (x["payload"] for x in intents))
        result = {"state": "native_review_lifecycle_passed", "checks": checks,
            "actualNative": True, "scriptedProviderRequests": len(requests),
            "realModel": False, "hollywoodAuthorizationProved": False,
            "humanApprovalApiProved": False, "productionChanged": False,
            "nativeInstalls": len(intents), "binarySha256": hashlib.sha256(args.binary.read_bytes()).hexdigest()}
        (root / "result.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
    finally:
        if getattr(r, "rpc", None):
            await r.rpc.close()
        await server.cleanup()
        (root / "requests.json").write_text(json.dumps(requests, indent=2))
        (root / "events.json").write_text(json.dumps(events, indent=2))
        (root / "processes.json").write_text(json.dumps(processes, indent=2))
        assert all(not Path("/proc/" + str(p["pid"])).exists() or
            Path("/proc/" + str(p["pid"]) + "/stat").read_text().rsplit(")", 1)[1].split()[19] != p["startTicks"]
            for p in processes), "Owned original process still exists"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    asyncio.run(asyncio.wait_for(main(parser.parse_args()), 120))
