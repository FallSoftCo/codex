"""Captured real action/rollout scan; explicitly simulated RPC/HTTP observations.

No model call, replacement or live canonical write is made by this check.
Live original-operation continuation is separately required.
"""
import argparse
import asyncio
import copy
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace

from lax_connector.errors import HttpFailure
from lax_connector.idle_context_rebuild import IdleContextRebuild
from lax_connector.idle_context_rejection import inspect_rejected


async def main(source, output):
    raw = source.read_bytes()
    op = json.loads(raw)
    state = source.parent.parent
    local_name = "operation-" + hashlib.sha256(op["snapshotOperationId"].encode()).hexdigest() + ".json"
    local = json.loads((state / local_name).read_text())
    checks = []
    with tempfile.TemporaryDirectory(dir=output.parent) as td:
        root = Path(td)
        journal = root / "original.json"
        for p in state.glob("execution-*.json"):
            (root / p.name).symlink_to(p)
        (root / "events.jsonl").symlink_to(state / "events.jsonl")

        async def case(name, edit=None, succeeds=False):
            value, receipt = copy.deepcopy(op), copy.deepcopy(local)
            options = {"explicit": True, "installed": False, "unknown": False,
                       "status": "completed", "cut": copy.deepcopy(op["nativeState"])}
            if edit:
                edit(value, receipt, options)
            journal.write_text(json.dumps(value))
            (root / local_name).write_text(json.dumps(receipt))
            calls = []

            async def http(purpose, method, path):
                calls.append(("http", method))
                assert purpose == "writer" and method == "GET"
                if path.endswith(value["snapshotOperationId"]):
                    return receipt["receipt"]
                assert path.endswith(value["installedOperationId"])
                if options["installed"]:
                    return {"status": "recorded"}
                raise HttpFailure(503 if options["unknown"] else 404, "observation",
                                  code="UNAVAILABLE" if options["unknown"] else "CONTEXT_OPERATION_NOT_FOUND")

            async def request(action):
                calls.append(("context", action))
                assert action == "pending"
                return {"contextRebuild": {"requestedOperationId": value["requestOperationId"]}}

            async def rpc(method, params, **kwargs):
                calls.append(("native", method))
                if method == "thread/turns/list":
                    return {"data": [{"id": value["request"]["turnId"], "status": options["status"]}],
                            "nextCursor": None}
                assert method == "thread/contextWindow/read"
                return {"state": options["cut"]}

            r = SimpleNamespace(state=root, purpose="writer", thread=value["nativeThread"],
                config={"agentId": value["agentId"], "contextIds": {"writer": value["contextId"]}},
                rpc=SimpleNamespace(call=rpc), request=request,
                agent=SimpleNamespace(rebuild_only=options["explicit"], stop=asyncio.Event(), http=http))
            idle = SimpleNamespace(runner=r, owned=IdleContextRebuild.owned)
            try:
                result = await inspect_rejected(idle, journal)
                assert succeeds, (name, "unexpected acceptance")
                assert result["snapshot"] == receipt["receipt"]
                assert result["proof"]["newInferenceAdmitted"] is False
                assert result["proof"]["terminalActionCount"] > 0
                outcome = "original_actions_terminal_read_only"
            except (RuntimeError, HttpFailure) as e:
                if succeeds:
                    raise
                outcome = "refused: " + str(e)
            assert not any(method in ("POST", "turn/start", "thread/contextWindow/replaceIdle")
                           for _, method in calls)
            checks.append({"case": name, "outcome": outcome})

        await case("actual_original_history_and_actions", succeeds=True)
        await case("new_snapshot_accepted_journal", lambda o,l,x:o.update(snapshot=l["receipt"]), succeeds=True)
        await case("cold_resume_reconstructed_history_counter", lambda o,l,x:x["cut"].update(historyVersion=1), succeeds=True)
        await case("normal_service_cannot_retry", lambda o,l,x:x.update(explicit=False))
        await case("unknown_failure_is_not_action_deferral", lambda o,l,x:o.update(holdReason="RPC timeout"))
        await case("native_dispatch_intent_blocks", lambda o,l,x:o.update(nativeDispatchIntent=True))
        await case("prepared_response_blocks", lambda o,l,x:o.update(response={}))
        await case("installed_receipt_exists", lambda o,l,x:x.update(installed=True))
        await case("receipt_read_unavailable", lambda o,l,x:x.update(unknown=True))
        await case("native_inference_not_terminal", lambda o,l,x:x.update(status="inProgress"))
        await case("native_window_changed", lambda o,l,x:x["cut"].update(windowId="changed"))
        await case("newer_native_inference", lambda o,l,x:x["cut"].update(lastStartedTurnId="later-turn"))
        await case("local_accepted_snapshot_differs", lambda o,l,x:o.update(snapshot={"different":True}))
        await case("snapshot_digest_changed", lambda o,l,x:l["receipt"].update(sha256="0"*64))
        # A real started item without its eventual terminal notification must hold.
        trace = root / "events.jsonl"
        trace.unlink()
        with trace.open("w") as out:
            for line in (state / "events.jsonl").open():
                v = json.loads(line)
                if v.get("event") == "item/completed" and (v.get("item") or {}).get("id") == "exec-53277732-277b-4116-9ec8-a85c16458484":
                    continue
                out.write(line)
        await case("original_command_still_running")
        trace.unlink()
        trace.symlink_to(state / "events.jsonl")
        tools = root / "native-tools"
        tools.mkdir()
        (tools / "tool-unknown.json").write_text(json.dumps({
            "nativeThread": op["nativeThread"], "requestId": "4096ff12-4203-431c-9bc4-73370f2ca5c9",
            "state":"unknown"}))
        await case("unknown_native_callback_retained")
        (tools / "tool-unknown.json").unlink()
        native_copy = root / "native-intent-negative.jsonl"
        shutil.copyfile(op["originalHistory"]["path"], native_copy)
        with native_copy.open("a") as f:
            f.write(json.dumps({"type":"event_msg", "payload":{
                "type":"context_window_refill_intent", "operationId":op["operationId"]}})+"\n")
        def intent(o,l,x):
            info=native_copy.stat()
            o["originalHistory"].update(path=str(native_copy), device=info.st_dev, inode=info.st_ino)
        await case("durable_native_intent_not_retried", intent)
    assert source.read_bytes() == raw
    result = {"checks":checks, "passed":len(checks), "modelCalls":0,
              "canonicalWrites":0,"replacementCalls":0,
              "evidenceLevel":"Original real trace and rollout, simulated transports; not live recovery proof."}
    output.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result))


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    assert not args.output.exists()
    asyncio.run(main(args.operation,args.output))
