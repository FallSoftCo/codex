"""Original report-scope pages issued to the current authenticated participation.

Coverage proves HTTP snapshot issuance, never model receipt or comprehension.
Only an explicit native briefing call populates this cache. Reporting cannot
silently fetch decisions or borrow another room's global sequence.
"""
import json
from datetime import datetime, timezone
from uuid import UUID
from .journal import saved


def expected_reader(c):
    active = c.active
    if not active:
        raise PermissionError("Current native participation required")
    result = {"authorityId":active["request"]["authority"],"agentId":c.config["agentId"],
              "hostId":c.config["hostId"],"deliveryId":active["delivery"]["id"],
              "generation":active["delivery"]["generation"],"claimId":active["delivery"]["claim_id"],
              "requestId":active["request"]["id"],"nativeThread":c.thread,"contextId":c.context_id,
              "roleRevision":c.role_context.value["roleRevision"]}
    context = c.effects.current.get()
    if context:
        result["nativeTurn"] = context["scope"]["nativeTurn"]
    return result


def same_reader(c, reader):
    return isinstance(reader, dict) and all(reader.get(k)==v for k,v in expected_reader(c).items())


async def read(c, args, operation):
    prior = str(UUID(args["deliveryId"]))
    original = await c.http("GET", "deliveries/"+prior)
    old, source = original["delivery"], original["request"]
    work_id = source.get("data",{}).get("workId")
    if not work_id or old["agent"]!=c.config["agentId"] or source["authority"]!=c.active["request"]["authority"]:
        raise PermissionError("An original owned work delivery is required for report scope")
    work_id = str(UUID(work_id))
    work = (await c.http("GET", "work/"+work_id))["work"]
    if work["delivery"]!=prior or work["owner"]!=c.config["agentId"] or work["request_event"]!=source["id"]:
        raise PermissionError("Original canonical work lineage changed")
    payload={"schema":"completed-report-scope-read/v1","operationId":operation,
             "revision":work["revision"],"priorDeliveryId":prior,
             "readId":args.get("readId"),"cursor":args.get("cursor",0),"pageSize":args.get("pageSize",1)}
    if type(payload["cursor"]) is not int or payload["cursor"]<0 or type(payload["pageSize"]) is not int or not 1<=payload["pageSize"]<=32:
        raise ValueError("Bounded ordered report-scope page required")
    reads=getattr(c,"report_scope_reads",{})
    previous=reads.get(payload["readId"]) if payload["readId"] else None
    if payload["readId"] and (not previous or not same_reader(c,previous["reader"]) or previous["nextCursor"]!=payload["cursor"]):
        raise PermissionError("Read the preceding original-scope page in this same participation")
    value=await c.http("POST","work/"+work_id+"/report-briefing",payload)
    expected={"authorityId":source["authority"],"agentId":c.config["agentId"],"workId":work_id,
              "workRevision":work["revision"],"deliveryId":prior,"roomId":source["room"],
              "requestId":source["id"],"generation":old["generation"],"claimId":old["claim_id"]}
    scope=value.get("scope",{})
    if value.get("schema")!="completed-report-briefing/v1" or any(scope.get(k)!=v for k,v in expected.items()) or not same_reader(c,value.get("reader")):
        raise PermissionError("Report briefing differs from exact original scope/current reader")
    if value.get("newExecutionAdmitted") is not False or value.get("currentParticipationUnchanged") is not True:
        raise PermissionError("Scope read cannot change current execution")
    if previous and any(value.get(k)!=previous.get(k) for k in ("readId","scopeSha256","snapshotSha256","decisionsSha256")):
        raise PermissionError("Original scope snapshot changed between pages")
    complete=value.get("complete") is True
    proof=value.get("scopeRead")
    if complete != bool(proof) or complete and (value["coveredCount"]!=value["decisionCount"] or value["nextCursor"] is not None):
        raise PermissionError("Original scope coverage is incomplete or inconsistent")
    if complete:
        validate_proof(value)
    if len(json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode()) > 8192:
        raise PermissionError("Original scope page exceeds native output bound; explicitly start a smaller-page read. A single oversized decision requires a bounded server interface.")
    reads[value["readId"]]=value
    c.report_scope_reads=reads
    cache=getattr(c,"report_scope_briefings",{})
    cache[prior]=value
    c.report_scope_briefings=cache
    saved(c.state/("report-scope-"+str(UUID(value["readId"]))+"-"+str(value["revision"])+".json"),value)
    return value


def validate_proof(value):
    proof=value.get("scopeRead") or {}
    expected={"schema":"completed-report-scope-proof/v1","readId":value["readId"],"revision":value["revision"],
              "snapshotSha256":value["snapshotSha256"],"scopeSha256":value["scopeSha256"],
              "decisionsSha256":value["decisionsSha256"],"complete":True}
    if proof!=expected or value.get("complete") is not True:
        raise PermissionError("Exact complete server-issued scope proof required")
    expiry=datetime.fromisoformat(value["expiresAt"].replace("Z","+00:00"))
    if expiry.tzinfo is None or expiry<=datetime.now(timezone.utc):
        raise PermissionError("Original scope proof expired; explicitly read current scoped decisions")
    return proof


def proof_for_report(c, work, original):
    prior=original["delivery"]["id"]
    value=getattr(c,"report_scope_briefings",{}).get(prior)
    if not value or not same_reader(c,value.get("reader")):
        raise PermissionError("Explicitly read hollywood_briefing for prior deliveryId and all returned pages before reconciliation")
    scope=value["scope"]
    if any(scope.get(k)!=v for k,v in {"workId":work["id"],"workRevision":work["revision"],
        "deliveryId":prior,"roomId":work["room"],"requestId":original["request"]["id"],
        "generation":original["delivery"]["generation"],"claimId":original["delivery"]["claim_id"]}.items()):
        raise PermissionError("Cached original scope differs from canonical report lineage")
    return validate_proof(value), value["originalRoomDecisionSequence"]
