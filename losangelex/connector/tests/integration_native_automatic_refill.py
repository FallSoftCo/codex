"""Actual public app-server/connector callback integration, NOT model evidence.

Global supplies a frozen deterministic-native provider fixture and qualified
binary/settings. This script does not provision, install, build or start a model
service. Host canonical transport is a disclosed stub, not authentication proof.
Run in a fresh disposable qualification directory; no original run is replayed.
"""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from lax_connector.automatic_context_refill import AutomaticContextRefill, METHODS
from lax_connector.automatic_refill_data import wire
from lax_connector.journal import saved
from lax_connector.rpc import AppServer


async def run(binary, fixture_path, root):
    fixture = json.loads(fixture_path.read_text())
    if fixture["kind"] != "deterministic-native" or root.exists():
        raise RuntimeError(
            "Frozen deterministic-native fixture and fresh directory required"
        )
    root.mkdir(mode=0o700)
    events, host_calls, windows = [], [], []
    r = SimpleNamespace(
        state=root,
        purpose="reader",
        thread=None,
        turn=None,
        permit="fixture-permit",
        material_ids=["fixture-input"],
        permit_material_ids=("fixture-input",),
        active=True,
        accepting=True,
        closing=False,
        failed=False,
        execution_scope=None,
        inbox=None,
        agent=SimpleNamespace(stop=asyncio.Event()),
        effect_lock=asyncio.Lock(),
        admitted=asyncio.Event(),
        finished=asyncio.get_running_loop().create_future(),
        config={
            "agentId": "fixture-agent",
            "contextIds": {"reader": "fixture-context"},
            "automaticContextRefill": {"type": "canonical"},
        },
        trace=lambda event, value: events.append({"event": event, **value}),
    )
    r.automatic = AutomaticContextRefill(r)

    async def event(method, params):
        events.append({"method": method, "params": params})
        if method == "turn/completed" and not r.finished.done():
            r.finished.set_result(params["turn"])

    async def request(action, value, **kwargs):
        host_calls.append({"action": action, "value": value, **kwargs})
        if action == "active_snapshot":
            text = wire(
                {
                    "agentId": r.config["agentId"],
                    "contextId": "fixture-context",
                    "purpose": "reader",
                    "nativeThread": r.thread,
                    "nextMaterialIds": r.material_ids,
                    "records": fixture["canonicalRecords"],
                    "obligations": fixture["obligations"],
                }
            )
            return {
                "chunks": [
                    {"offset": n, "content": text[n : n + 3072]}
                    for n in range(0, len(text), 3072)
                ],
                "sha256": hashlib.sha256(text.encode()).hexdigest(),
                "totalBytes": len(text.encode()),
                "snapshotReadPoint": "fixture-cut",
                "selectionRevision": 0,
            }
        if action != "active_installed":
            raise AssertionError("Unexpected host lifecycle action")
        # This is explicitly a fixture receipt. Native history verification has
        # already run in the actual connector before this stub is called.
        return {"operationId": value["operationId"], "status": "recorded"}

    async def callback(method, params):
        if method not in METHODS:
            raise AssertionError("Fixture must not authorize native tools or approvals")
        result = await r.automatic.call(method, params)
        windows.append({"method": method, "params": params, "result": result})
        return result

    r.request = request
    rpc = AppServer(
        binary,
        root / "home",
        root / "native",
        event,
        callback,
        on_submission=r.automatic.submitted,
        enterprise=True,
    )
    r.rpc = rpc
    try:
        await rpc.start()
        if "canonical_context_window_refill/v1" not in rpc.lax_capabilities:
            raise RuntimeError("Actual binary lacks automatic-refill capability")
        settings = dict(fixture["settings"])
        settings["automaticContextRefill"] = r.automatic.policy()
        started = await rpc.call("thread/start", settings)
        r.thread = started["thread"]["id"]
        await rpc.call(
            "thread/name/set",
            {"threadId": r.thread, "name": "automatic-refill-native-fixture"},
        )
        turn = await rpc.call("turn/start", {**fixture["turn"], "threadId": r.thread})
        r.turn = turn["turn"]["id"]
        r.admitted.set()
        terminal = await asyncio.wait_for(asyncio.shield(r.finished), 120)
        if terminal["id"] != r.turn or terminal["status"] != "completed":
            raise AssertionError("Original native turn did not complete")
        # A fixture that never reaches the automatic boundary is NOT a pass.
        prepares = [x for x in windows if x["method"] == METHODS[0]]
        installs = [x for x in windows if x["method"] == METHODS[1]]
        if not prepares or len(prepares) != len(installs) or r.automatic.blocked:
            raise AssertionError("Automatic native checkpoint/ack path not exercised")
        if any(
            x["params"]["turnId"] != r.turn or x["params"]["threadId"] != r.thread
            for x in windows
        ):
            raise AssertionError("Same native thread/turn continuity violated")
        if any(
            json.loads(p.read_text())["state"] != "ack_written"
            for p in r.automatic.root.glob("*.json")
        ):
            raise AssertionError("Original refill acknowledgement unsettled")
        saved(
            root / "result.json",
            {
                "scope": "deterministic native public-RPC plus connector, stub host",
                "fixtureSha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
                "nativeThread": r.thread,
                "nativeTurn": r.turn,
                "automaticWindows": len(prepares),
                "modelBehaviorQualified": False,
                "hostAuthenticationQualified": False,
            },
        )
    finally:
        r.admitted.set()
        if r.automatic.timer:
            r.automatic.timer.cancel()
        await rpc.close()
        saved(
            root / "observations.json",
            {"events": events, "hostCalls": host_calls, "windows": windows},
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.binary, args.fixture, args.out))
