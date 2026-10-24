"""Hash-bound pages of original native action evidence, never execution authority."""
import hashlib
import json
import os
import re
import stat

from .errors import HttpFailure
from .journal import saved

MAX_BYTES=32*1024**2
PAGE_BYTES=6144
PAGE_ENTRIES=12


def wire(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"))


async def authorize_source(runner,owner):
    # Authorization is an ordinary authenticated event read. It must not replace
    # a model-delivered complete material proof with an internal partial read.
    value=await runner.agent.http(runner.purpose,"GET",
        "connector/deliveries/"+owner["deliveryId"]+"/context")
    if (value.get("schema")!="lax-agent-context/v1"
            or value["agentId"]!=runner.config["agentId"]
            or value["requestId"]!=owner["sourceRequestId"]
            or value["briefingReference"]["deliveryId"]!=owner["deliveryId"]):
        raise PermissionError("Original action source identity changed")


def store_index(runner,actions):
    if not actions:return []
    value={"schema":"lax-native-action-cache/v1","agentId":runner.config["agentId"],
        "contextId":runner.config["contextIds"][runner.purpose],
        "nativeThread":runner.thread,"actions":actions}
    encoded=wire(value).encode()
    if len(encoded)>MAX_BYTES:
        raise RuntimeError("Original action archive exceeds declared storage budget; no actions omitted")
    digest=hashlib.sha256(encoded).hexdigest()
    directory=runner.state/"native-action-index"
    directory.mkdir(mode=0o700,exist_ok=True)
    if directory.is_symlink():raise PermissionError("Original action index directory is not private state")
    path=directory/(digest+".json")
    if path.exists():
        info=path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid():
            raise PermissionError("Original action index owner changed")
        if wire(json.loads(path.read_text())).encode()!=encoded:
            raise RuntimeError("Original action index changed")
    else:saved(path,value)
    return {"schema":"lax-native-action-index/v2","indexSha256":digest,
        "nativeThread":runner.thread,"actionCount":len(actions),"indexBytes":len(encoded),
        "retrieval":"context_action_read","pageOffset":0,"pageEntries":PAGE_ENTRIES,
        "recentActions":actions[-8:],
        "meaning":"Bounded recent preview, not the full ledger. Read pages using indexSha256 and pageOffset, then exact nativeTurn/itemId evidence. Original effects must never be replayed because context was reset."}


async def read_index(runner,value):
    if set(value)-{"indexSha256","pageOffset"}:
        raise ValueError("Choose an index page or an exact action, never both")
    digest=value["indexSha256"];offset=value.get("pageOffset",0)
    if not isinstance(digest,str) or not re.fullmatch("[a-f0-9]{64}",digest):
        raise ValueError("Exact original action-index digest required")
    if type(offset) is not int or offset<0:
        raise ValueError("Invalid action-index page offset")
    path=runner.state/"native-action-index"/(digest+".json")
    if path.parent.is_symlink():
        raise PermissionError("Original action index directory changed")
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_size>2*MAX_BYTES:
        raise PermissionError("Original action index unavailable under this identity")
    index=json.loads(path.read_text())
    if hashlib.sha256(wire(index).encode()).hexdigest()!=digest:
        raise RuntimeError("Original action index changed; do not substitute another history")
    if (index.get("schema")!="lax-native-action-cache/v1"
            or index.get("agentId")!=runner.config["agentId"]
            or index.get("contextId")!=runner.config["contextIds"][runner.purpose]
            or index.get("nativeThread")!=runner.thread):
        raise PermissionError("Original action index belongs to another context")
    actions=index["actions"]
    if offset>=len(actions):raise ValueError("Action-index offset outside original snapshot")
    result={"indexSha256":digest,"actionCount":len(actions),"pageOffset":offset,
            "entries":[],"nextPageOffset":None,
            "meaning":"Original evidence only; current source permission rechecked. No effect replay authorized."}
    authorized={}
    from .context_action_memory import scope
    for item in actions[offset:offset+PAGE_ENTRIES]:
        owner=scope(runner,item["nativeTurn"])
        if not owner or owner["materialId"]!=item["materialId"] or owner["deliveryId"]!=item["deliveryId"]:
            raise PermissionError("Original action ownership no longer resolves")
        source=owner["sourceRequestId"]
        if source not in authorized:
            try:
                await authorize_source(runner,owner)
                authorized[source]=True
            except HttpFailure as error:
                if error.status!=403:raise
                authorized[source]=False
        entry=item if authorized[source] else {"nativeTurn":item["nativeTurn"],
            "itemId":item["itemId"],"access":"unavailable"}
        result["entries"].append(entry)
        end=offset+len(result["entries"])
        result["nextPageOffset"]=end if end<len(actions) else None
        if len(wire(result).encode())>PAGE_BYTES:
            result["entries"].pop()
            end=offset+len(result["entries"])
            result["nextPageOffset"]=end
            break
    if not result["entries"]:raise RuntimeError("Original action pointer exceeds page budget")
    return result
