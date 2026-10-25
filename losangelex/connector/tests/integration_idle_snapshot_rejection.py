"""Real captured rollout scan with explicit fake HTTP/native observations.

No model call, native replacement or canonical mutation is made. Production
recovery and useful subsequent work require separately retained live evidence.
"""
import argparse
import asyncio
import copy
import hashlib
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from lax_connector.errors import HttpFailure
from lax_connector.idle_context_rebuild import IdleContextRebuild
from lax_connector.idle_context_rejection import inspect_rejected


async def main(source, output):
    source_bytes = source.read_bytes()
    operation = json.loads(source_bytes)
    rejection_name = "operation-" + hashlib.sha256(
        operation["snapshotOperationId"].encode()).hexdigest() + ".json"
    rejection_bytes = (source.parent.parent / rejection_name).read_bytes()
    checks = []
    with tempfile.TemporaryDirectory(dir=output.parent) as scratch:
        root = Path(scratch)
        journal = root / "context-rebuild" / source.name
        journal.parent.mkdir()
        (root / rejection_name).write_bytes(rejection_bytes)

        def runner(value, *, explicit=True, accepted=False, changed_turn=False):
            journal.write_text(json.dumps(value))
            calls = []
            async def http(purpose, method, path):
                calls.append(("http", method))
                if accepted:
                    return {"sha256": "already-accepted"}
                raise HttpFailure(404, "Original absent",
                                  code="CONTEXT_OPERATION_NOT_FOUND")
            async def request(action):
                calls.append(("context", action))
                assert action == "pending"
                return {"contextRebuild": {"requestedOperationId":
                                           operation["requestOperationId"]}}
            async def rpc(method, params, **kwargs):
                calls.append(("native", method))
                if method == "thread/turns/list":
                    return {"data": [{"id": operation["request"]["turnId"],
                                      "status": "completed"}], "nextCursor": None}
                assert method == "thread/contextWindow/read"
                cut = copy.deepcopy(operation["nativeState"])
                if changed_turn:
                    cut["lastStartedTurnId"] = "another-turn"
                return {"state": cut}
            r = SimpleNamespace(
                config={"agentId": operation["agentId"],
                        "contextIds": {"writer": operation["contextId"]}},
                purpose="writer", thread=operation["nativeThread"], state=root,
                rpc=SimpleNamespace(call=rpc),
                agent=SimpleNamespace(http=http, stop=asyncio.Event(),
                                      rebuild_only=explicit),
                request=request)
            return IdleContextRebuild(r), calls

        idle, calls = runner(operation)
        proof = await inspect_rejected(idle, journal)
        assert proof["selected"] == json.loads(rejection_bytes)["request"]["value"]["materialIds"]
        assert proof["operation"]["operationId"] == operation["operationId"]
        assert proof["proof"]["nativeObservation"]["prefixSha256"] == operation["originalHistory"]["beforeSha256"]
        assert calls == [("http", "GET"), ("context", "pending"),
                         ("native", "thread/turns/list"),
                         ("native", "thread/contextWindow/read")]
        checks.append("captured real history scanned; observations only, original operation/material retained")

        async def rejects(value, phrase, **kwargs):
            idle, calls = runner(value, **kwargs)
            try:
                await inspect_rejected(idle, journal)
            except RuntimeError as error:
                assert phrase in str(error), str(error)
            else:
                raise AssertionError("Broken control was accepted")
            assert not any(method in ("POST", "turn/start", "thread/contextWindow/replaceIdle")
                           for _, method in calls)

        await rejects(operation, "explicit --rebuild-context-only", explicit=False)
        checks.append("ordinary service start cannot retry the rejected preparation")
        await rejects(operation, "snapshot was accepted", accepted=True)
        checks.append("accepted snapshot is not treated as a pre-data rejection")
        dispatched = copy.deepcopy(operation)
        dispatched["response"] = {"disclosed": "dispatch-bound prepared packet"}
        await rejects(dispatched, "may have reached native dispatch")
        checks.append("dispatch-capable journal remains observation-only")
        await rejects(operation, "idle window or last inference changed", changed_turn=True)
        checks.append("changed original native turn blocks resumption")
        altered = copy.deepcopy(operation)
        copy_path = root / "changed-native-history.jsonl"
        raw = Path(operation["originalHistory"]["path"]).read_bytes()
        copy_path.write_bytes(b" " + raw[1:])
        info = copy_path.stat()
        altered["originalHistory"].update(path=str(copy_path), device=info.st_dev, inode=info.st_ino)
        await rejects(altered, "prefix changed")
        checks.append("changed original rollout prefix rejected")
    assert source.read_bytes() == source_bytes
    result = {"checks": checks, "passed": len(checks), "modelCalls": 0,
              "canonicalWrites": 0, "nativeReplacementCalls": 0,
              "scope": "Real captured rollout scan; HTTP/native transports explicitly fake. "
                       "No live recovery or semantic completion claim."}
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists()
    asyncio.run(main(args.operation, args.output))
