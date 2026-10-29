"""Operator-only recovery of a diagnosed failed, nonexecuting Reader turn.

The original failure and input sources remain immutable. No original callback,
message, native turn or business effect is resubmitted.
"""
import hashlib,json
from .context_observation import original_turn
from .context_action_memory import TERMINAL
from .errors import HttpFailure
from .journal import saved

SCHEMA = "lax-reader-failure-review/v1"
DIAGNOSIS = "Host-tool inference ended without authenticated tool settlement"

def path(runner, identity):
    return runner.state / ("reviewed-reader-failure-" + identity + ".json")

async def receipt(runner, identity):
    return await runner.agent.http("reader", "GET",
        f"agents/{runner.config['agentId']}/contexts/reader/operations/review-reader-failure:{identity}")

def validate(runner, identity, value, digest):
    expected={"schema":SCHEMA,"contextId":runner.config["contextIds"]["reader"],
              "purpose":"reader","nativeThread":runner.thread,"nativeTurn":identity,
              "nativeItemsSha256":digest,"failedOriginalRetained":True,
              "newExecutionAdmitted":False,"originalInputReposted":False,
              "workCompletionInferred":False}
    if any(value.get(k)!=v for k,v in expected.items()):
        raise RuntimeError("Original Reader recovery receipt differs")

async def original_resolution(runner, wake):
    if runner.purpose != "reader" or not path(runner,wake["nativeTurn"]).exists():
        return False
    local=json.loads(path(runner,wake["nativeTurn"]).read_text())
    observed=await original_turn(runner,wake["nativeTurn"])
    if observed["status"] != "failed" or DIAGNOSIS not in (observed.get("error") or {}).get("message",""):
        raise RuntimeError("Original reviewed Reader failure changed")
    canonical=await receipt(runner,wake["nativeTurn"])
    validate(runner,wake["nativeTurn"],canonical,local["nativeItemsSha256"])
    if canonical != local["receipt"]:
        raise RuntimeError("Original canonical Reader recovery changed")
    return True

async def inspect_original(runner, identity):
    """Read-only original native/canonical evidence; never bind, recover or infer."""
    if runner.purpose != "reader":
        raise RuntimeError("Nonexecuting Reader evidence only")
    wake=json.loads((runner.state/"wake.json").read_text())
    if (wake.get("state")!="finished" or wake.get("nativeThread")!=runner.thread
            or wake.get("nativeTurn")!=identity or wake.get("turn",{}).get("status")!="failed"):
        raise RuntimeError("Exact latest finished failed Reader required")
    observed=await original_turn(runner,identity)
    if observed["status"]!="failed" or DIAGNOSIS not in (observed.get("error") or {}).get("message",""):
        raise RuntimeError("Only the diagnosed nonsettling Reader failure is supported")
    entries,cursor=[],None
    for _ in range(64):
        page=await runner.rpc.call("thread/items/list",{
            "threadId":runner.thread,"turnId":identity,"limit":100,
            **({"cursor":cursor} if cursor else {})},timeout=15)
        for entry in page["data"]:
            if entry["turnId"]!=identity:
                raise RuntimeError("Another original turn entered recovery")
            item=entry["item"]
            if item.get("type")=="dynamicToolCall":
                if (item.get("namespace") is not None or item.get("tool") not in runner.allowed
                        or item.get("status") not in TERMINAL):
                    raise RuntimeError("Original Reader callback is unresolved or outside its tool set")
            elif item.get("type") not in {"userMessage","agentMessage","reasoning",
                                         "functionCallOutput","contextCompaction"}:
                raise RuntimeError("Reader original contains execution or unsupported native evidence")
            entries.append(entry)
        cursor=page.get("nextCursor")
        if not cursor:break
    else:raise RuntimeError("Original Reader item evidence exceeds bounded pages")
    if not entries:raise RuntimeError("Original Reader native evidence unavailable")
    operations=[]
    for p in sorted(runner.state.glob("operation-*.json")):
        old=json.loads(p.read_text());req=old.get("request",{})
        if req.get("nativeTurn")!=identity:continue
        if req.get("nativeThread")!=runner.thread:
            raise RuntimeError("Original callback thread differs")
        if old.get("receipt") is not None:
            result=await runner.agent.http("reader","GET",
                f"agents/{runner.config['agentId']}/contexts/reader/operations/{req['operationId']}")
            if result!=old["receipt"]:
                raise RuntimeError("Original Reader callback receipt changed")
            disposition="committed_original"
        elif old.get("state")=="rejected" and old.get("status") in {400,403,409,413,422}:
            disposition="definitively_rejected"
        else:
            try:
                result=await runner.agent.http("reader","GET",
                    f"agents/{runner.config['agentId']}/contexts/reader/operations/{req['operationId']}")
            except HttpFailure as error:
                if error.status!=404 or error.code!="CONTEXT_OPERATION_NOT_FOUND":raise
                disposition="definitively_no_canonical_receipt"
            else:disposition="committed_original"
        operations.append({"operationId":req["operationId"],"disposition":disposition,
                           "journalSha256":hashlib.sha256(p.read_bytes()).hexdigest()})
    if not operations:raise RuntimeError("Original Reader callback journals missing")
    digest=hashlib.sha256(json.dumps(entries,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    return {"nativeItemsSha256":digest,"nativeItemCount":len(entries),
            "originalOperations":operations,"originalTurn":observed,"modelTurnsStarted":0,
            "callbacksReplayed":False,"originalInputReposted":False}

async def acknowledge(runner, identity):
    if getattr(runner, "reader_failure_review", 0) != 1:
        raise RuntimeError("Paired Hollywood explicit Reader recovery unavailable")
    if runner.purpose != "reader" or runner.active or runner.accepting:
        raise RuntimeError("Only an idle original Reader may be reviewed")
    if path(runner,identity).exists():
        value=json.loads(path(runner,identity).read_text())
        current=await receipt(runner,identity)
        validate(runner,identity,current,value["nativeItemsSha256"])
        if current != value["receipt"]:
            raise RuntimeError("Original Reader recovery differs")
        return value
    inspected=await inspect_original(runner,identity)
    digest=inspected["nativeItemsSha256"]
    canonical=await runner.request("acknowledge_reader_failure",{
        "nativeTurn":identity,"nativeItemsSha256":digest,"callbacksReconciled":True},
        operation="review-reader-failure:"+identity,turn=identity)
    validate(runner,identity,canonical,digest)
    result={"nativeThread":runner.thread,"nativeTurn":identity,
            "nativeItemsSha256":digest,"nativeItemCount":inspected["nativeItemCount"],
            "originalOperations":inspected["originalOperations"],"receipt":canonical,
            "modelTurnsStarted":0,"callbacksReplayed":False,"originalInputReposted":False}
    saved(path(runner,identity),result)
    saved(runner.state/"restart-recovery.json",{
        "id":"review-reader-failure:"+identity,"nativeThread":runner.thread,
        "nativeTurn":identity,"modelTurnsStarted":0,"originalInputsReposted":False})
    runner.failed=False;runner.failure_reason=None
    return result
