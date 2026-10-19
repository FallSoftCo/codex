"""Bounded original edit receipts through the existing protected local channel."""
import asyncio,json,re,socket,struct
from pathlib import Path
from uuid import UUID
from .collaboration_bridge import protected_directory,require,receive
from .owner_briefing import guardian_peer
from .service_observer import protected

FIELDS={"schema","agentId","deliveryId","generation","claimId","contextId","nativeThread","nativeTurn","roleRevision","after"}

def carry(capture,peer,frame,owner):
    require(set(frame)==FIELDS,"Exact native edit-status request required")
    current=guardian_peer(capture,peer)
    require(current==owner and frame["agentId"]==owner["agentId"],"Original installed guardian changed")
    snapshot=capture.admin_http("GET","deliveries/"+str(UUID(frame["deliveryId"])))
    d,scope=snapshot["delivery"],snapshot.get("purposeExecutionScope")
    require(scope is not None and d["state"]=="running" and not d["cancellation_requested"],
            "Current admitted purpose writer required for edit receipt inspection")
    require(all(scope[k]==frame[k] for k in
        ("agentId","deliveryId","generation","claimId","contextId","nativeThread","nativeTurn","roleRevision")),
        "Edit receipt query differs from captured original work")
    after=frame["after"]
    require(after is None or isinstance(after,str) and re.fullmatch(r"[a-f0-9]{64}",after),
            "Bounded original edit cursor required")
    paths=sorted((capture.state/"commands").glob("*.json"))
    require(len(paths)<=4096,"Original command registry needs bounded archival before inspection")
    rows=[]
    for path in paths:
        if not re.fullmatch(r"[a-f0-9]{64}",path.stem) or after is not None and path.stem<=after:
            continue
        old=protected(path);wire=old.get("wire") or {};source=wire.get("source") or {}
        if (source.get("agentId"),source.get("deliveryId"),source.get("generation"))!=(
                frame["agentId"],frame["deliveryId"],frame["generation"]):
            continue
        command=wire.get("command") or {}
        phase=command.get("action")
        if phase not in ("preflight","begin","settle"):
            continue
        rejected=old["state"]=="rejected" and old.get("status") in (400,403,409)
        boundary=("preflight_rejected_no_admission" if rejected and phase=="preflight"
            else "inspect_original_permit" if old["state"]=="completed" else "original_effect_unsettled")
        rows.append({"cursor":path.stem,"operationId":wire["operationId"],"nativeThread":source["nativeThread"],
            "nativeTurn":source["nativeTurn"],"callId":source["callId"],"phase":phase,
            "receiptState":old["state"],"httpStatus":old.get("status"),
            "confirmedPostRejected":rejected,"effectBoundary":boundary,
            "proposedPermitId":command.get("permitId"),"rejection":old.get("rejection"),
            "automaticRetryAuthorized":False})
        if len(rows)==17:
            break
    next_cursor=rows[15]["cursor"] if len(rows)>16 else None
    rows=[{k:v for k,v in row.items() if k!="cursor"} for row in rows[:16]]
    # The public source contract describes native behavior; it is not a claim
    # that an absent journal proves no effect.
    return {"success":True,"result":{"schema":"lax-native-edit-status/v1",
        "agentId":frame["agentId"],"deliveryId":frame["deliveryId"],"generation":frame["generation"],
        "operations":rows,"nextCursor":next_cursor,"mayApply":False,
        "meaning":"Original protected receipts. A confirmed preflight HTTP rejection admitted no mutation; a missing record alone proves nothing. Pending/unknown or begun effects retain their original receipts and locks."},
        "canonicalReceipt":None,"holdReason":None}

def read(c,arguments):
    descriptor=Path(c.config["nativeCollaborationChannel"])
    protected_directory(descriptor.parent);channel=protected(descriptor)
    require("edit-status/v1" in channel["ports"],"Installed edit-status metadata port unavailable")
    scope=c.purpose_scope
    require(scope is not None,"Current accepted purpose scope required")
    frame={"schema":"lax-native-edit-status/v1","after":arguments.get("after"),**{k:scope[k] for k in
       ("agentId","deliveryId","generation","claimId","contextId","nativeThread","nativeTurn","roleRevision")}}
    wire=json.dumps(frame,separators=(",",":")).encode()
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as sock:
        sock.settimeout(15);sock.connect(channel["socket"])
        sock.sendall(struct.pack("!I",len(wire))+wire)
        size=struct.unpack("!I",receive(sock,4))[0]
        require(0<size<=65536,"Bounded original receipt response required")
        result=json.loads(receive(sock,size))
    require(result.get("success") is True and result.get("result",{}).get("mayApply") is False,
        str(result.get("holdReason") or "Original edit-status inspection failed"))
    return result["result"]

async def inspect(c,arguments):
    return await asyncio.to_thread(read,c,arguments)
