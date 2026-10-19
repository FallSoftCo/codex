"""Accepted purpose source projected from canonical admission, never model hints."""
from .collaboration_bridge import require

def source_base(snapshot, row, config):
    d,e,s=snapshot["delivery"],snapshot["request"],snapshot["purposeExecutionScope"]
    expected={"schema":"lax-execution-scope/v2","purpose":"writer",
        "authorityId":config["authorityId"],"agentId":str(row["agent"]),
        "hostId":config["hostId"],"executorId":str(row["id"]),
        "deliveryId":str(d["id"]),"claimId":d["claim_id"],"generation":d["generation"],
        "sourceRequestId":str(e["id"]),"nativeThread":d["native_thread"],"nativeTurn":d["native_turn"]}
    require(all(s.get(k)==v for k,v in expected.items()),"Exact accepted writer scope required")
    return {"schema":"hollywood-native-source/v3",**{k:s[k] for k in (
        "authorityId","agentId","hostId","executorId","deliveryId","claimId","generation",
        "nativeThread","nativeTurn","contextId","roleRevision")},
        "requestId":s["sourceRequestId"],"executionScopeId":s["id"],"nativeGoalId":None}
