"""Original native action references for unfinished responsibilities after reset."""
import hashlib
import json

KINDS={"commandExecution","fileChange","dynamicToolCall","mcpToolCall"}
TERMINAL={"completed","failed","declined","cancelled","interrupted"}


def scope(runner,turn):
    path=runner.state/("execution-"+turn+".json")
    if not path.exists():return None
    matched=[s for s in json.loads(path.read_text())["executionScopes"]
             if s["agentId"]==runner.config["agentId"] and s["nativeThread"]==runner.thread
             and s["nativeTurn"]==turn]
    return matched[0] if len(matched)==1 else None


def index(runner,content):
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
            encoded=json.dumps(item,sort_keys=True,separators=(",",":"))
            actions[(turn,item["id"])]={
                "nativeTurn":turn,"itemId":item["id"],"type":item["type"],
                "status":item.get("status"),"materialId":owner["materialId"],
                "deliveryId":owner["deliveryId"],"sha256":hashlib.sha256(encoded.encode()).hexdigest(),
                "contentBytes":len(encoded.encode()),"retrieval":"context_action_read"}
            if len(actions)>256:
                raise RuntimeError("Unfinished work action index exceeds reset budget; no actions omitted")
    for action in actions.values():
        if action["status"] not in TERMINAL:
            raise RuntimeError("Original native action is not terminal; preserve its running context before rebuilding")
    return [actions[key] for key in sorted(actions)]


async def read(runner,value):
    if runner.purpose!="writer":
        raise PermissionError("Native execution action history belongs to the writer")
    if set(value)-{"nativeTurn","itemId","offset","sha256"} or not {"nativeTurn","itemId"}<=set(value):
        raise ValueError("Exact native action pointer required")
    for field in ("nativeTurn","itemId"):
        if not isinstance(value[field],str) or not 1<=len(value[field])<=128 or "/" in value[field]:
            raise ValueError("Invalid original native action identity")
    owner=scope(runner,value["nativeTurn"])
    if not owner:raise PermissionError("Original action has no owned execution scope")
    # Current Hollywood permission on the original material, not stale local access.
    await runner.request("read",{"reference":owner["materialId"]})
    result=await runner.rpc.call("thread/items/read",{"threadId":runner.thread,
        "turnId":value["nativeTurn"],"itemIds":[value["itemId"]]})
    entries=result["data"]
    if len(entries)!=1 or entries[0]["turnId"]!=value["nativeTurn"]:
        raise RuntimeError("Original native action unavailable")
    item=entries[0]["item"]
    if item.get("id")!=value["itemId"] or item.get("type") not in KINDS:
        raise PermissionError("Original action pointer does not name execution data")
    encoded=json.dumps(item,sort_keys=True,separators=(",",":"))
    sha=hashlib.sha256(encoded.encode()).hexdigest();offset=value.get("offset",0)
    if type(offset) is not int or not 0<=offset<max(1,len(encoded)):
        raise ValueError("Invalid action chunk offset")
    if (offset and not value.get("sha256")) or (value.get("sha256") and value["sha256"]!=sha):
        raise RuntimeError("Native action changed; restart its exact read")
    end=min(len(encoded),offset+3072)
    return {"nativeTurn":value["nativeTurn"],"itemId":value["itemId"],"sha256":sha,
        "offset":offset,"content":encoded[offset:end],"nextOffset":end if end<len(encoded) else None,
        "totalBytes":len(encoded),"meaning":"Original native action evidence, never authority to replay it."}
