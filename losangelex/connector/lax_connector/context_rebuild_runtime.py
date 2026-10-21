"""Native context rebuild lifecycle; state observation never starts inference."""
import hashlib,json
from .native_context_rebuild import install
from .journal import saved


async def rebuild(runner,request_id,pending):
    if not runner.config.get("contextRebuildEnabled",False):
        raise RuntimeError("Context rebuild requires an explicitly qualified native profile")
    if runner.active or runner.accepting or runner.closing:
        raise RuntimeError("Original native inference must settle before context rebuild")
    key=hashlib.sha256((runner.config["contextIds"][runner.purpose]+":"+request_id).encode()).hexdigest()
    snapshot_op="context-refill-snapshot:"+key
    selected=[x["id"] for x in pending if not x["cancelled"]][:(1 if runner.purpose=="writer" else 16)]
    snapshot=await runner.request("rebuild_snapshot",{"materialIds":selected},
        operation=snapshot_op,turn="context-maintenance")
    operation="context-refill-native:"+key
    from .context_action_memory import index
    content=json.loads("".join(x["content"] for x in snapshot["chunks"]))
    actions=index(runner,content)
    receipt=await install(runner,snapshot,operation,actions)
    installed=await runner.request("rebuild_installed",{
        "snapshotOperationId":snapshot_op,"sha256":snapshot["sha256"],
        "checkpointTurnId":receipt["checkpointTurnId"],
        "nativeHistorySha256":receipt["nativeHistorySha256"],
        "nativeHistoryBytes":receipt["nativeHistoryBytes"],"nativeActionsSha256":receipt["nativeActionsSha256"]},
        operation="context-refill-installed:"+key,turn="context-maintenance")
    # This token permits a new inference for still-pending original work. It is
    # not a replay of an old native turn or any business operation.
    saved(runner.state/"context-rebuild-generation.json",installed)
    if runner.inbox:runner.inbox.delivered.clear()
    return installed
