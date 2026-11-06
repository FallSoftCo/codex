"""Preserve native tool bindings across host-runtime ownership handoff.

Transport startup is distinct from loading a new native context. Loaded
attachments atomically validate their declarations and carry no config
overrides. Otherwise native can cold-reload an idle cache from older rollout
tools. Cold resumes restore the complete reviewed configuration and tools.
No archive/fork/shared-server restart.
"""
import hashlib,json

# Exact generic SDK24413-tool schema, not account/host/runtime data.
# Exact retained SDK254 room tools and the first255 project bindings.
SUPPORTED_PREVIOUS_DECLARATIONS = frozenset({'fc5a0b6288eff6e6b7cadd8798ff55b62df16f4f593011eb069208b53e28f103','85a9442bea5b7501d8100a700411fd7c554c739d880410e6b30bdbba005fd1a7','9c92b3c860bae8856ba44c8ef6e184d275550b0b08c9a94b8db961b5013a11db','642adab0db28a4fea73ce9ce26e90997c894a0ca2b1a6c90875f70812ac9c0a2'})

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
    if status in ("idle","active","systemError"):
        # Even an identical config override can make native rebuild an idle,
        # unsubscribed cache. Do not turn a transport reattach into a config
        # change or fall back to the original rollout's older tool declarations.
        # Native accepts identical tools and rejects a mismatched loaded owner
        # atomically, including if its state changes after this metadata read.
        allowed={"threadId","excludeTurns","initialTurnsPage"}
        return {**{k:v for k,v in params.items() if k in allowed},"dynamicTools":declarations}
    raise RuntimeError("Native loading state unavailable; preserve original context and bindings")


async def resume_configured(rpc,params,declarations,*,reviewed_instructions=None):
    """Validate warm bindings; repair only a proven stale, idle owned cache.

    The exact native validation rejection precedes any resume mutation. Unknown
    responses, transport failures and all other errors are never retried here.
    The established cold boundary refuses active turns/background commands and
    waits for actual release. It never restarts the shared native process.
    """
    from .rpc import RpcError
    expected="cannot replace dynamic tools on loaded thread "+params["threadId"]+"; release it at an idle ownership boundary before cold resume"
    request=await configured_resume(rpc,params,declarations)
    repaired=False
    try:
        result=await rpc.call("thread/resume",request)
    except RpcError as error:
        if not reviewed_instructions or error.code!=-32600 or not isinstance(error.detail,dict) or error.detail.get("message")!=expected:
            raise
        from .project_adoption import cold
        await cold(rpc,params["threadId"],reviewed_instructions=reviewed_instructions)
        result=await rpc.call("thread/resume",{**params,**reviewed_instructions,"dynamicTools":declarations})
        repaired=True
    return result,{"declarationsSha256":hashlib.sha256(json.dumps(declarations,sort_keys=True,separators=(",",":")).encode()).hexdigest(),
                   "loadedBindingsValidated":True,"idleCacheRebound":repaired}
