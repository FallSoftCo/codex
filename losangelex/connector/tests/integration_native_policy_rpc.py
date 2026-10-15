"""Exercise the real native policy protocol without submitting any model turn."""

import asyncio
import json
import os
from pathlib import Path

from lax_connector.journal import saved
from lax_connector.rpc import AppServer, RpcError


async def main():
    root = Path(os.environ["POLICY_RPC_EVIDENCE"])
    root.mkdir(mode=0o700)
    workspace = root / "work"
    workspace.mkdir()
    binary = os.environ["POLICY_RPC_BINARY"]

    async def event(method, params):
        pass

    async def request(method, params):
        raise AssertionError("No model or tool request was authorized")

    def app():
        return AppServer(
            binary, Path(os.environ["POLICY_RPC_HOME"]), root / "native", event, request
        )

    rpc = app()
    policy = {"allowedTools": [{"name": "hollywood_read_room"}]}
    try:
        await rpc.start()
        started = await rpc.call(
            "thread/resume",
            {
                "threadId": os.environ["POLICY_RPC_THREAD"],
                "excludeTurns": True,
                "toolPolicy": policy,
            },
        )
        thread = started["thread"]["id"]
        saved(root / "start-response.json", started)
        assert {
            (t.get("namespace") or "functions", t["name"])
            for t in started["toolPolicy"]["allowedTools"]
        } == {("functions", "hollywood_read_room")}
        saved(root / "original-thread.json", {"threadId": thread, "toolPolicy": policy})
        try:
            await rpc.call(
                "thread/resume",
                {
                    "threadId": thread,
                    "excludeTurns": True,
                    "toolPolicy": {"allowedTools": []},
                },
            )
        except RpcError as error:
            assert "cannot replace tool policy on loaded thread" in str(error)
            replacement_denied = True
        else:
            raise AssertionError("Loaded thread policy replacement was accepted")
        loaded = await rpc.call(
            "thread/resume",
            {
                "threadId": thread,
                "excludeTurns": True,
            },
        )
        assert loaded["toolPolicy"] == started["toolPolicy"]
    finally:
        await rpc.close()
    rpc = app()
    try:
        await rpc.start()
        resumed = await rpc.call(
            "thread/resume",
            {
                "threadId": thread,
                "excludeTurns": True,
                "toolPolicy": {"allowedTools": []},
            },
        )
        assert resumed["thread"]["id"] == thread
        assert resumed["toolPolicy"] == {"allowedTools": []}
    finally:
        await rpc.close()
    result = {
        "passed": True,
        "actualNativeAppServer": True,
        "actualExistingThreadEffectivePolicyVerified": True,
        "loadedReplacementDenied": replacement_denied,
        "loadedResumeRetainsPolicy": True,
        "coldResumeSameThreadEmptyCeiling": True,
        "modelTurnsSubmitted": 0,
        "productionChanged": False,
    }
    saved(root / "result.json", result)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
