"""Original native action references for unfinished responsibilities after reset."""
import hashlib
import json

KINDS={"commandExecution","fileChange","dynamicToolCall","mcpToolCall"}
TERMINAL={"completed","failed","declined","cancelled","interrupted"}
# These are owned context retrieval handlers, not arbitrary dynamic/MCP tools.
# Their canonical read fences survive in the refill snapshot. Keep the original
# trace, but do not fill the effect replay index with completed retrievals.
CONTEXT_READS={"context_read","context_material_read","context_selection","context_action_read"}


def scope(runner,turn):
    path=runner.state/("execution-"+turn+".json")
    if not path.exists():return None
    matched=[s for s in json.loads(path.read_text())["executionScopes"]
             if s["agentId"]==runner.config["agentId"] and s["nativeThread"]==runner.thread
             and s["nativeTurn"]==turn]
    return matched[0] if len(matched)==1 else None


def collect(runner,content):
    if runner.purpose!="writer":return []
    sources={x["source"] for x in content["obligations"]}
    tools=runner.state/"native-tools"
    for path in tools.glob("tool-*.json"):
        value=json.loads(path.read_text())
        if value.get("nativeThread")==runner.thread and value.get("requestId") in sources and value.get("state")!="completed":
            raise RuntimeError("Unfinished native callback outcome must be reconciled before context reset")
    trace=runner.state/"events.jsonl"
    if not trace.exists():return []
    if trace.stat().st_size>256*1024**2:
        raise RuntimeError("Native action trace exceeds bounded reset scan; use its indexed archive before reset")
    actions={}
    scopes={}
    with trace.open() as stream:
        for line in stream:
            value=json.loads(line);item=value.get("item") or {}
            turn=value.get("turnId")
            if (value.get("event") not in ("item/started","item/completed")
                    or value.get("threadId")!=runner.thread or not turn or item.get("type") not in KINDS):
                continue
            if turn not in scopes:scopes[turn]=scope(runner,turn)
            owner=scopes[turn]
            if not owner or owner["sourceRequestId"] not in sources:continue
            key=(turn,item["id"])
            # The paired current-index/selection callbacks only reconstruct or
            # select canonical evidence. Their own in-flight callback is not an
            # unknown execution effect and must not block that reconstruction.
            metadata_callback = (runner.config.get("nativeActionRetention", 0)==1
                and item.get("tool") in ("context_action_read","retain_native_action"))
            if (item["type"]=="dynamicToolCall" and item.get("namespace") is None
                    and (metadata_callback or item.get("tool") in CONTEXT_READS
                         and item.get("status") in TERMINAL)):
                actions.pop(key,None)
                continue
            encoded=json.dumps(item,sort_keys=True,separators=(",",":"))
            actions[key]={
                "nativeTurn":turn,"itemId":item["id"],"type":item["type"],
                "status":item.get("status"),"materialId":owner["materialId"],
                "deliveryId":owner["deliveryId"],"sha256":hashlib.sha256(encoded.encode()).hexdigest(),
                "contentBytes":len(encoded.encode()),"retrieval":"context_action_read"}
            if isinstance(item.get("tool"),str):
                actions[key]["tool"]=item["tool"][:128]
            if isinstance(item.get("namespace"),str):
                actions[key]["namespace"]=item["namespace"][:128]
            if isinstance(item.get("command"),str):
                actions[key]["commandPreview"]=item["command"][:240]
            if len(actions)>50000:
                raise RuntimeError("Unfinished work action archive exceeds declared budget; no actions omitted")
    for action in actions.values():
        if action["status"] not in TERMINAL:
            raise RuntimeError("Original native action is not terminal; preserve its running context before rebuilding")
    return [actions[key] for key in sorted(actions)]


def index(runner,content):
    from .context_action_pages import store_index
    return store_index(runner,collect(runner,content))


async def load_action(runner,native_turn,item_id):
    """One complete authenticated original canonical item, without replay."""
    if runner.purpose!="writer":
        raise PermissionError("Native execution action history belongs to the writer")
    for identity in (native_turn,item_id):
        if not isinstance(identity,str) or not 1<=len(identity)<=128 or "/" in identity:
            raise ValueError("Invalid original native action identity")
    owner=scope(runner,native_turn)
    if not owner:raise PermissionError("Original action has no owned execution scope")
    from .context_action_pages import authorize_source
    await authorize_source(runner,owner)
    result=await runner.rpc.call("thread/items/read",{"threadId":runner.thread,
        "turnId":native_turn,"itemIds":[item_id]})
    entries=result["data"]
    if len(entries)!=1 or entries[0]["turnId"]!=native_turn:
        raise RuntimeError("Original native action unavailable")
    item=entries[0]["item"]
    if item.get("id")!=item_id or item.get("type") not in KINDS:
        raise PermissionError("Original action pointer does not name execution data")
    return owner,item,json.dumps(item,sort_keys=True,separators=(",",":"))


async def read(runner,value):
    if runner.purpose!="writer":
        raise PermissionError("Native execution action history belongs to the writer")
    if "current" in value:
        from .retained_context_packet import enabled
        if value!={"current":True} or not enabled(runner):
            raise ValueError("Explicit paired current-action discovery required")
        if not runner.active or not runner.accepting or runner.execution_scope is None:
            raise PermissionError("Current accepted Writer execution required")
        owner=scope(runner,runner.turn)
        if owner is None or owner!=runner.execution_scope.as_dict():
            raise PermissionError("Current original execution scope changed")
        from .context_action_pages import authorize_source
        await authorize_source(runner,owner)
        import asyncio
        result=await asyncio.to_thread(index,runner,{"obligations":[{"source":owner["sourceRequestId"]}]})
        return result or {"schema":"lax-native-action-index/v2","nativeThread":runner.thread,
            "actionCount":0,"recentActions":[],
            "meaning":"No terminal execution evidence for this original responsibility."}
    if "indexSha256" in value:
        from .context_action_pages import read_index
        return await read_index(runner,value)
    if set(value)-{"nativeTurn","itemId","offset","sha256"} or not {"nativeTurn","itemId"}<=set(value):
        raise ValueError("Exact native action pointer required")
    for field in ("nativeTurn","itemId"):
        if not isinstance(value[field],str) or not 1<=len(value[field])<=128 or "/" in value[field]:
            raise ValueError("Invalid original native action identity")
    offset=value.get("offset",0)
    if type(offset) is not int or offset<0:
        raise ValueError("Invalid action chunk offset")
    if offset and not value.get("sha256"):
        from .errors import ToolValidationError
        raise ToolValidationError(
            "ACTION_READ_DIGEST_REQUIRED",
            "A nonzero action offset requires the SHA256 returned by its first chunk.",
            "Reuse the previous chunk's nextRead arguments, or supply its exact "
            "nativeTurn/itemId/nextOffset/sha256. No native read or effect was dispatched.")
    owner,item,encoded=await load_action(runner,value["nativeTurn"],value["itemId"])
    sha=hashlib.sha256(encoded.encode()).hexdigest();offset=value.get("offset",0)
    if type(offset) is not int or not 0<=offset<max(1,len(encoded)):
        raise ValueError("Invalid action chunk offset")
    if (offset and not value.get("sha256")) or (value.get("sha256") and value["sha256"]!=sha):
        raise RuntimeError("Native action changed; restart its exact read")
    end=min(len(encoded),offset+3072)
    return {"nativeTurn":value["nativeTurn"],"itemId":value["itemId"],"sha256":sha,
        "offset":offset,"content":encoded[offset:end],"nextOffset":end if end<len(encoded) else None,
        "totalBytes":len(encoded),
        "nextRead":{"nativeTurn":value["nativeTurn"],"itemId":value["itemId"],
                    "offset":end,"sha256":sha} if end<len(encoded) else None,
        "meaning":"Original native action evidence, never authority to replay it."}
