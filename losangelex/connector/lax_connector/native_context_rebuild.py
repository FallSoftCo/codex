"""Observe native no-summary checkpoints and install exact canonical refill data.

A checkpoint receipt is distinct from model inference, work completion and
semantic sufficiency. Unknown native outcomes are held, never resubmitted here.
"""
import asyncio
import hashlib
import json
from pathlib import Path
from .journal import saved


def sha_file(path,limit=None):
    h=hashlib.sha256()
    with Path(path).open("rb") as stream:
        remaining=limit
        while remaining is None or remaining>0:
            block=stream.read(1024*1024 if remaining is None else min(1024*1024,remaining))
            if not block:break
            h.update(block)
            if remaining is not None:remaining-=len(block)
        if remaining:raise RuntimeError("Original native history prefix is incomplete")
    return h.hexdigest()


def refill_items(snapshot,operation,actions=None):
    encoded="".join(x["content"] for x in snapshot["chunks"])
    if hashlib.sha256(encoded.encode()).hexdigest()!=snapshot["sha256"]:
        raise RuntimeError("Canonical refill chunks do not match their exact snapshot digest")
    items=[{"type":"function_call_output","namespace":"hollywood","name":"context_refill",
             "output":json.dumps({"schema":"lax-context-refill-fragment/v1","operationId":operation,
                 "sha256":snapshot["sha256"],"totalBytes":snapshot["totalBytes"],**chunk},
                 sort_keys=True,separators=(",",":"))} for chunk in snapshot["chunks"]]
    actions_encoded=json.dumps(actions or [],sort_keys=True,separators=(",",":"))
    action_sha=hashlib.sha256(actions_encoded.encode()).hexdigest()
    for offset in range(0,len(actions_encoded),3072):
        items.append({"type":"function_call_output","namespace":"lax","name":"context_actions",
            "output":json.dumps({"schema":"lax-native-action-index/v1","sha256":action_sha,
                "offset":offset,"content":actions_encoded[offset:offset+3072],
                "totalBytes":len(actions_encoded),"retrieval":"context_action_read",
                "meaning":"Original action receipts for unfinished work. Never replay an effect merely because context was reset."},
                sort_keys=True,separators=(",",":"))})
    return items


def observe_history(path,items,*,start=0):
    wanted={hashlib.sha256(x["output"].encode()).hexdigest() for x in items}
    present=set();checkpoint=None
    with Path(path).open() as stream:
        stream.seek(start)
        for line in stream:
            if not line.strip():continue
            record=json.loads(line)
            if record.get("type")=="compacted":
                checkpoint=record["payload"]
            def visit(value):
                if isinstance(value,dict):
                    if value.get("type")=="function_call_output" and isinstance(value.get("output"),str):
                        present.add(hashlib.sha256(value["output"].encode()).hexdigest())
                    for child in value.values():visit(child)
                elif isinstance(value,list):
                    for child in value:visit(child)
            visit(record)
    return {"checkpoint":checkpoint,"allFragmentsObserved":wanted<=present,
            "expectedFragments":len(wanted),"observedFragments":len(wanted & present)}


async def install(runner,snapshot,operation,actions=None):
    """Requires exclusive caller ownership and a confirmed idle original thread."""
    root=runner.state/"context-rebuild"
    root.mkdir(mode=0o700,exist_ok=True)
    journal=root/(hashlib.sha256(operation.encode()).hexdigest()+".json")
    items=refill_items(snapshot,operation,actions)
    previous=json.loads(journal.read_text()) if journal.exists() else None
    if previous:
        if previous["snapshot"]!=snapshot or previous["nativeThread"]!=runner.thread or previous.get("nativeActions",[])!=(actions or []):
            raise RuntimeError("Original context rebuild changed")
        if previous["state"]=="installed":
            return previous["receipt"]
        raise RuntimeError("Original context rebuild has an uncertain/unfinished native outcome; inspect its original checkpoint and refill, do not repeat it")
    observed=await runner.rpc.call("thread/read",{"threadId":runner.thread,"includeTurns":False})
    if observed["thread"]["status"]["type"]!="idle":
        raise RuntimeError("Context rebuild cannot replace an active native inference")
    path=Path(observed["thread"]["path"])
    before_bytes=path.stat().st_size
    value={"state":"reset_intent","operationId":operation,"nativeThread":runner.thread,
        "snapshot":snapshot,"nativePath":str(path),"beforeBytes":before_bytes,
        "beforeSha256":sha_file(path,before_bytes),"items":items,"nativeActions":actions or []}
    saved(journal,value)
    future=asyncio.get_running_loop().create_future()
    original=runner.rpc.on_event
    checkpoint_turn=None
    checkpoint_item=False
    async def event(method,params):
        nonlocal checkpoint_turn,checkpoint_item
        await original(method,params)
        if params.get("threadId")!=runner.thread:return
        if method=="turn/started":
            checkpoint_turn=params["turn"]["id"]
            value["checkpointTurnId"]=checkpoint_turn
            saved(journal,value)
        if method=="item/completed" and params.get("item",{}).get("type")=="contextCompaction":
            checkpoint_item=True
        if method=="turn/completed" and params["turn"]["id"]==checkpoint_turn and not future.done():
            future.set_result(params["turn"])
    runner.rpc.on_event=event
    try:
        await runner.rpc.call("thread/compact/start",{"threadId":runner.thread})
        turn=await asyncio.wait_for(asyncio.shield(future),60)
        if turn["status"]!="completed" or not checkpoint_item:
            raise RuntimeError("Original no-summary native checkpoint did not complete")
        value["state"]="checkpoint_observed";saved(journal,value)
        # No ordinary human input, model turn, work/tool replay or synthetic reply.
        value["state"]="refill_intent";saved(journal,value)
        await runner.rpc.call("thread/inject_items",{"threadId":runner.thread,"items":items})
        history=observe_history(path,items,start=before_bytes)
        if not history["checkpoint"] or not history["allFragmentsObserved"]:
            raise RuntimeError("Native checkpoint/refill durability is unconfirmed; hold original operation")
        history_bytes=path.stat().st_size
        receipt={"checkpointTurnId":checkpoint_turn,"nativeHistorySha256":sha_file(path,history_bytes),
            "nativeHistoryBytes":history_bytes,
            "nativeActionsSha256":hashlib.sha256(json.dumps(actions or [],sort_keys=True,separators=(",",":")).encode()).hexdigest(),
            "snapshotSha256":snapshot["sha256"],"nativeThread":runner.thread,
            "fragments":history["expectedFragments"],"modelTurnsStarted":0,"effectsReplayed":0,
            "semanticSufficiencyProved":False}
        value["state"]="installed";value["receipt"]=receipt;saved(journal,value)
        runner.trace("context_rebuild_installed",receipt)
        return receipt
    finally:
        runner.rpc.on_event=original
