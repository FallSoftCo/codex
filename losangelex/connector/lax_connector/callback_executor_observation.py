"""Publish the protected bridge's current process observation before an edit.

The bridge is the independently enrolled root controller, separate from the
model process. Reuse its existing observation API; do not relax service,
incarnation, source, freshness, grant or mutation-permit checks.
"""
import fcntl
import os
import time
from uuid import UUID, uuid4

from .collaboration_bridge import Held, require
from .journal import saved
from .service_observer import observe, protected


def refresh(bridge, record, source, native_operation):
    identity = str(UUID(record["executorId"]))
    value = bridge.http("GET", "executors/" + identity)
    row = value["executor"]
    require(value["deliveryState"] == "running"
            and value["currentDeliveryGeneration"] == source["generation"]
            and row["state"] == "live" and row["launch_phase"] == "attached"
            and str(row["id"]) == identity and str(row["agent"]) == source["agentId"]
            and str(row["delivery"]) == source["deliveryId"]
            and str(row["host"]) == source["hostId"]
            and row["claim_id"] == source["claimId"]
            and row["descriptor_digest"] == record["descriptorDigest"],
            "Original independently observed executor changed before callback")
    from .purpose_observer import observe as purpose_observe
    fact = purpose_observe(bridge.config, row) or observe(bridge.config, row)
    require(fact["state"] == "live"
            and fact["evidence"]["serviceBindingDigest"] == record["serviceBindingDigest"],
            "Current independent callback service observation unavailable")
    path = bridge.state / ("callback-observation-" + identity + ".json")
    fd = os.open(path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if path.exists():
            previous = protected(path)
            require(previous["state"] == "completed",
                    "Original callback observation is unresolved; no edit request submitted")
        payload = {"operationId": str(uuid4()), "machineIdentity": bridge.config["machineIdentity"],
                   "descriptorDigest": row["descriptor_digest"], **fact}
        journal = {"schema": "lax-callback-executor-observation/v1",
                   "nativeOperationId": native_operation, "source": source,
                   "payload": payload, "at": time.time(), "editRequestSubmitted": False}
        saved(path, {**journal, "state": "pending"})
        try:
            result = bridge.http("POST", "hosts/" + source["hostId"] + "/executors/"
                                 + identity + "/observation", payload)
        except Exception as error:
            saved(path, {**journal, "state": "unknown", "error": type(error).__name__})
            raise Held("Independent callback observation unconfirmed; no edit request submitted") from error
        observed = result["executor"]
        require(str(observed["id"]) == identity and observed["state"] == "live"
                and observed["descriptor_digest"] == record["descriptorDigest"]
                and observed["evidence"]["serviceBindingDigest"] == record["serviceBindingDigest"],
                "Independent callback observation receipt changed")
        saved(path, {**journal, "state": "completed", "receipt": result})
        return result
    finally:
        os.close(fd)

