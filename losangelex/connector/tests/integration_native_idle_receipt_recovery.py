"""Captured real native checkpoint observation; transport branches are explicit fakes.

The input is an existing private original-operation journal, not a synthetic
completion. This test never writes to Hollywood, native history, or an agent.
Actual metadata completion and subsequent model work require separate evidence.
"""
import argparse
import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lax_connector.automatic_refill_history import verify
from lax_connector.errors import HttpFailure
from lax_connector.idle_context_rebuild import IdleContextRebuild, SCHEMA

async def main(path):
    operation = json.loads(path.read_text())
    verify(operation["originalHistory"], operation["request"], operation["response"],
           operation["installed"], native_mode="idle_request")
    expected = {"schema": SCHEMA, "status": "recorded",
                "nativeReceipt": operation["installed"], "preflight": operation["preflight"],
                "snapshotOperationId": operation["snapshotOperationId"]}
    checks = {"actual_native_checkpoint_with_complete_provenance": True}
    def runner(http):
        r = SimpleNamespace(
            rpc=SimpleNamespace(), thread=operation["nativeThread"],
            config={"agentId": operation["agentId"],
                    "contextIds": {operation["purpose"]: operation["contextId"]}},
            purpose=operation["purpose"], state=path.parent.parent,
            agent=SimpleNamespace(stop=asyncio.Event(), http=http),
            request=AsyncMock(return_value=expected))
        return r
    http = AsyncMock(return_value=expected)
    r = runner(http)
    result = await IdleContextRebuild(r).observe(path)
    checks["existing_canonical_receipt_is_read_only"] = (
        result == {"operationId": operation["operationId"], "status": "recorded"}
        and r.request.await_count == 0 and http.await_count == 1)
    http = AsyncMock(side_effect=HttpFailure(
        404, "Absent original metadata", code="CONTEXT_OPERATION_NOT_FOUND"))
    r = runner(http)
    await IdleContextRebuild(r).observe(path)
    checks["proven_original_checkpoint_completes_only_same_metadata_operation"] = (
        r.request.await_count == 1
        and r.request.await_args.args == ("rebuild_installed", {
            "schema": SCHEMA, "snapshotOperationId": operation["snapshotOperationId"],
            "nativeReceipt": operation["installed"], "preflight": operation["preflight"]})
        and r.request.await_args.kwargs == {
            "operation": operation["installedOperationId"],
            "turn": operation["installed"]["turnId"]})
    for name, error in [
        ("unavailable", HttpFailure(503, "Unavailable")),
        ("denied", HttpFailure(403, "Denied")),
        ("untyped_not_found", HttpFailure(404, "Unknown resource")),
    ]:
        r = runner(AsyncMock(side_effect=error))
        try:
            await IdleContextRebuild(r).observe(path)
        except Exception:
            checks[name + "_does_not_complete_metadata"] = r.request.await_count == 0
        else:
            checks[name + "_does_not_complete_metadata"] = False
    wrong = copy.deepcopy(operation["installed"])
    wrong["nativeHistorySha256"] = "0" * 64
    try:
        verify(operation["originalHistory"], operation["request"], operation["response"],
               wrong, native_mode="idle_request")
    except RuntimeError:
        checks["changed_original_native_prefix_refused_before_metadata"] = True
    else:
        checks["changed_original_native_prefix_refused_before_metadata"] = False
    assert all(checks.values()), checks
    print(json.dumps({"passed": True, "checks": checks, "input": str(path),
                      "modelCalls": 0, "canonicalWrites": 0,
                      "scope": "Actual serialized checkpoint observation; transport branches explicitly fake. Not live recovery or semantic delivery proof."}))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation", type=Path, required=True)
    asyncio.run(main(parser.parse_args().operation))
