"""Preserve native tool bindings across host-runtime ownership handoff.

Transport startup is distinct from loading a new native context. Existing
contexts retain installed declarations; only notLoaded contexts receive
cold-resume declarations. No archive/fork/shared-server restart.
"""
import hashlib,json

# Exact generic SDK24413-tool schema, not account/host/runtime data.
SUPPORTED_PREVIOUS_DECLARATIONS = frozenset({'85a9442bea5b7501d8100a700411fd7c554c739d880410e6b30bdbba005fd1a7'})

def supported_declarations(value,current,legacy):
    if value==current or value==legacy:return True
    if not isinstance(value,list):return False
    try:digest=hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    except (TypeError,ValueError):return False
    return digest in SUPPORTED_PREVIOUS_DECLARATIONS

async def configured_resume(rpc,params,declarations):
    thread=params["threadId"]
    if getattr(rpc,"shared",False):rpc.bind_thread(thread)
    result=await rpc.call("thread/read",{"threadId":thread,"includeTurns":False})
    value=result.get("thread",{})
    if value.get("id")!=thread:raise ValueError("Native resume metadata belongs to another agent thread")
    status=value.get("status",{}).get("type")
    if status=="notLoaded":return {**params,"dynamicTools":declarations}
    if status in ("idle","active","systemError"):return dict(params)
    raise RuntimeError("Native loading state unavailable; preserve original context and bindings")
