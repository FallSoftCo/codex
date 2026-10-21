"""Bounded material in its original dynamic-tool response.

The native server validates and persists fragments before the next model step.
A prepared host response is not a delivery receipt or proof of comprehension.
The legacy idle-only append observer remains for historical mechanism recovery.
"""
import hashlib
import json
from pathlib import Path
from .journal import saved
from .native_context_rebuild import observe_history

class MaterialDeliveryUnknown(RuntimeError):
    pass

def fragments(snapshot,operation):
    if (snapshot.get("schema")!="lax-context-material-snapshot/v1"
            or type(snapshot.get("revision")) is not int
            or not 1<=snapshot.get("totalBytes",0)<=98304):
        raise ValueError("Invalid bounded material snapshot")
    chunks=snapshot.get("chunks")
    if not isinstance(chunks,list) or not 1<=len(chunks)<=32:
        raise ValueError("Invalid material fragment count")
    offset=0;parts=[];items=[]
    for chunk in chunks:
        content=chunk.get("content")
        if (type(chunk.get("offset")) is not int or chunk["offset"]!=offset
                or not isinstance(content,str) or not content.isascii()
                or not 1<=len(content)<=3072):
            raise ValueError("Material fragments are incomplete or out of order")
        parts.append(content);offset+=len(content)
        output=json.dumps({"schema":"lax-context-material-fragment/v1",
            "operationId":operation,"reference":snapshot["reference"],
            "revision":snapshot["revision"],"sha256":snapshot["sha256"],
            "totalBytes":snapshot["totalBytes"],**chunk},sort_keys=True,separators=(",",":"))
        if len(output.encode())>8192:
            raise ValueError("Native material fragment exceeds its delivery bound")
        items.append({"type":"function_call_output","namespace":"hollywood",
                      "name":"context_material","output":output})
    encoded="".join(parts)
    if len(encoded)!=snapshot["totalBytes"] or hashlib.sha256(encoded.encode()).hexdigest()!=snapshot["sha256"]:
        raise ValueError("Material snapshot digest differs")
    return items

async def deliver(runner,snapshot,operation):
    items=fragments(snapshot,operation)
    root=runner.state/"material-delivery";root.mkdir(mode=0o700,exist_ok=True)
    journal=root/(hashlib.sha256(operation.encode()).hexdigest()+".json")
    previous=json.loads(journal.read_text()) if journal.exists() else None
    if previous:
        if previous["nativeThread"]!=runner.thread or previous["items"]!=items:
            raise RuntimeError("Original material delivery identity changed")
        if previous["state"]=="delivered":
            return previous["receipt"]
        value=previous
    else:
        current=await runner.rpc.call("thread/read",{"threadId":runner.thread,"includeTurns":False})
        path=Path(current["thread"]["path"])
        value={"state":"intent","operationId":operation,"nativeThread":runner.thread,
            "snapshotSha256":snapshot["sha256"],"nativePath":str(path),
            "beforeBytes":path.stat().st_size,"items":items}
        saved(journal,value)
        try:
            await runner.rpc.call("thread/inject_items",{"threadId":runner.thread,"items":items})
        except Exception as error:
            saved(journal,{**value,"state":"unconfirmed","error":type(error).__name__})
            raise MaterialDeliveryUnknown("Original native material append is unconfirmed; inspect "+operation+" without replay") from error
    try:
        observed=observe_history(value["nativePath"],items,start=value["beforeBytes"])
    except Exception as error:
        raise MaterialDeliveryUnknown("Original material history observation unavailable; no append repeated") from error
    if not observed["allFragmentsObserved"]:
        raise MaterialDeliveryUnknown("Original material fragments are not durably confirmed; no append repeated")
    receipt={"schema":"lax-context-material-delivery/v1","originalOperationId":operation,
        "reference":snapshot["reference"],"revision":snapshot["revision"],
        "sha256":snapshot["sha256"],"totalBytes":snapshot["totalBytes"],
        "nativeThread":runner.thread,"fragments":len(items),"allFragmentsObserved":True,
        "modelCallsStarted":0,"effectsReplayed":0,"comprehensionProved":False,
        "meaning":"The complete authorized snapshot is present in this native history as hollywood.context_material fragments. No pagination call is needed."}
    saved(journal,{**value,"state":"delivered","receipt":receipt})
    return receipt


def tool_response(snapshot, operation):
    """Prepare exact programmatic data plus separate bounded native model fragments."""
    items = fragments(snapshot, operation)
    content = "".join(chunk["content"] for chunk in snapshot["chunks"])
    result = {"reference": snapshot["reference"], "revision": snapshot["revision"],
        "offset": 0, "encoding": "json/ascii", "content": content,
        "nextOffset": None, "totalBytes": snapshot["totalBytes"], "sha256": snapshot["sha256"],
        "meaning": "Exact serialized material at one read cut; no pagination remains. A read does not certify its assertions."}
    text = json.dumps(result)
    if len(text.encode()) > 262144:
        raise ValueError("Complete programmatic material exceeds native data bound; use explicit revision/offset reads")
    receipt = {"schema": "lax-context-material-tool-result/v2",
        "originalOperationId": operation, "reference": snapshot["reference"],
        "revision": snapshot["revision"], "sha256": snapshot["sha256"],
        "totalBytes": snapshot["totalBytes"], "offset": 0, "nextOffset": None,
        "complete": True, "fragments": len(items),
        "state": "prepared_for_original_native_callback",
        "meaning": "Complete data is returned to the calling program; separately bounded fragments accompany the model result. No pagination remains. Preparation does not prove durable delivery, comprehension or execution."}
    return {"success": True, "contentItems": [
        {"type": "inputText", "text": json.dumps(receipt)}],
        "codeModeText": text,
        "contextFragments": [item["output"] for item in items]}
