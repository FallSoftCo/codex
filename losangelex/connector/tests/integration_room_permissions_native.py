"""Actual zero-model thread/start, durable settings, and cold-resume lifecycle."""

import asyncio, json, sys
from pathlib import Path
from uuid import uuid4
from lax_connector.rpc import AppServer
from lax_connector.room_permissions import observed, verified, requested
from lax_connector.room_bootstrap import initialize


async def main(binary, out):
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    turns = []

    async def event(method, params):
        if method == "turn/started":
            turns.append(params)

    async def request(*args):
        raise AssertionError("No tool/model work expected")

    def transport(home, state):
        return AppServer(binary, home, state, event, request, enterprise=True)

    home = out / "home"
    state = out / "native"
    work = out / "work"
    work.mkdir()
    cfg = {
        "sandbox": "danger-full-access",
        "approvalPolicy": "never",
        "codexHome": str(home),
    }
    rpc = transport(home, state)
    try:
        await rpc.start()
        first = await rpc.call(
            "thread/start", {"cwd": str(work), "model": "gpt-6.1-sol", **requested(cfg)}
        )
        thread = first["thread"]["id"]
        verified(first, requested(cfg))
        await rpc.call(
            "thread/name/set",
            {"threadId": thread, "name": "Synthetic policy lifecycle"},
        )
    finally:
        await rpc.close()
    rpc = transport(home, state)
    try:
        await rpc.start()
        before = await rpc.call(
            "thread/resume", {"threadId": thread, "excludeTurns": True}
        )
        baseline = observed(before)
        (out / "baseline.json").write_text(
            json.dumps({"start": observed(first), "coldResume": baseline}, indent=2)
            + "\n"
        )
        await rpc.call(
            "thread/settings/update",
            {
                "threadId": thread,
                "approvalPolicy": "never",
                "sandboxPolicy": {"type": "dangerFullAccess"},
            },
        )
    finally:
        await rpc.close()
    rpc = transport(home, state)
    try:
        await rpc.start()
        after = await rpc.call(
            "thread/resume", {"threadId": thread, "excludeTurns": True}
        )
        (out / "after-settings-resume.json").write_text(
            json.dumps(observed(after), indent=2) + "\n"
        )
        verified(after, requested(cfg))
        assert after["thread"]["id"] == thread
        await rpc.call(
            "thread/settings/update",
            {
                "threadId": thread,
                "approvalPolicy": "on-request",
                "sandboxPolicy": {"type": "readOnly", "networkAccess": False},
            },
        )
    finally:
        await rpc.close()
    rpc = transport(home, state)
    try:
        await rpc.start()
        restricted = await rpc.call(
            "thread/resume", {"threadId": thread, "excludeTurns": True}
        )
        verified(restricted, {"sandbox": "read-only", "approvalPolicy": "on-request"})
    finally:
        await rpc.close()
    fresh = out / "fresh"
    fresh.mkdir()
    workspace = fresh / "work"
    workspace.mkdir()
    spec = {
        "runtimeMode": "room-conversation",
        "authorityId": str(uuid4()),
        "agentId": str(uuid4()),
        "state": str(fresh / "state"),
        "codexHome": str(fresh / "home"),
        "workspace": str(workspace),
        "nativeName": "Synthetic durable policy",
        "model": "gpt-6.1-sol",
        "effort": "xhigh",
        "sandbox": "danger-full-access",
        "approvalPolicy": "never",
        "instructions": "Synthetic metadata-only qualification.",
        "binary": binary,
    }
    receipt = await initialize(spec)
    assert receipt["nativePermissionsPersisted"]
    rpc = transport(fresh / "home", fresh / "state/native")
    try:
        await rpc.start()
        resumed = await rpc.call(
            "thread/resume",
            {"threadId": receipt["nativeThreadId"], "excludeTurns": True},
        )
        verified(resumed, requested(spec))
    finally:
        await rpc.close()
    assert not turns
    result = {
        "passed": True,
        "baselineStartFullAccess": observed(first),
        "baselineColdResume": baseline,
        "sameOriginalThreadAfterRepair": True,
        "supportedNativeThreadSettingsUpdate": True,
        "newProvisioningPersistsPolicy": True,
        "coldResumeNoOverridesRequired": True,
        "explicitOwnerRestrictionPreserved": True,
        "modelTurns": 0,
        "accountCopied": False,
        "productionChanged": False,
    }
    (out / "qualification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], Path(sys.argv[2])))
