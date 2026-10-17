"""Protected observation of one stopped ordinary edit; never releases a lock."""
import argparse
import json
import os
import urllib.error
import urllib.parse
from pathlib import Path
from uuid import UUID

from .collaboration_bridge import digest, protected_directory, read_file, require
from .host import request
from .journal import saved
from .service_observer import observe, protected


def observe_permit(configuration, identity, revision, operation, note):
    require(os.geteuid() == 0, "Protected local controller observation required")
    protected_directory(Path(configuration).parent)
    config = protected(Path(configuration))
    state = protected_directory(Path(config["collaborationState"]))
    http = lambda method, path, body=None: request(
        config["hollywoodUrl"], config["token"], method, path, body)
    command = state / "commands" / ("observation-" + digest(operation) + ".json")
    intent = {"permitId": identity, "permitRevision": revision,
              "operationId": operation, "note": note}
    if command.exists():
        old = protected(command)
        require(old["intent"] == intent, "Original observation intent changed")
        if old["state"] == "completed":
            return {**old["result"], "admission": None, "replayed": True}
        require(old["state"] == "pending", "Original observation definitively rejected; inspect retained status")
        # Lost replies are observed by the original controller operation. No POST.
        profile = http("GET", "hosts/" + config["hostId"] + "/collaboration-bridge")
        result = http("GET", "collaboration/commands/" +
                      profile["bridge"]["controller"] + "/" + urllib.parse.quote(operation, safe=""))
        return {"receipt": result["acceptedResult"], "admission": None, "replayed": True}
    value = http("GET", "collaboration/delivery-edits/" + identity)
    permit = value["permit"]
    source, proof = permit["source"], permit["proof"]
    require(permit["scope_kind"] == "delivery" and permit["state"] != "settled"
            and permit["revision"] == revision, "Exact unsettled ordinary permit required")
    require(source["hostId"] == config["hostId"]
            and source["authorityId"] == config["authorityId"],
            "Original authority and execution host required")
    executor = http("GET", "executors/" + proof["executorId"])["executor"]
    fact = observe(config, executor)
    require(executor["state"] == "stopped" and fact["state"] == "stopped"
            and fact["evidence"]["serviceBindingDigest"] == proof["serviceBindingDigest"],
            "Original executor is not independently drained; no observation admitted")
    paths = list((state / "channels").glob("*.json"))
    require(len(paths) <= 256, "Protected captured registry exceeds bound")
    matches = [record for record in (protected(path) for path in paths)
               if record["executorId"] == proof["executorId"]
               and record["sourceBase"]["deliveryId"] == source["deliveryId"]]
    require(len(matches) == 1, "One exact original protected captured channel required")
    channel = matches[0]
    require(channel["sourceBase"]["deliveryId"] == source["deliveryId"]
            and channel["executorId"] == proof["executorId"]
            and channel["descriptorDigest"] == proof["descriptorDigest"]
            and channel["serviceBindingDigest"] == proof["serviceBindingDigest"],
            "Original protected captured channel required")
    roots = [r for r in channel["resources"] if r["workspaceId"] == proof["workspaceId"]
             and r["hostId"] == config["hostId"]]
    require(len(roots) == 1, "One original physical resource required")
    root = roots[0]
    environment = digest({"hostId": root["hostId"], "environmentId": root["environmentId"]})
    root_digest = digest({"hostId": root["hostId"], "environmentSha256": environment,
                          "device": root["device"], "inode": root["inode"]})
    require(root_digest == proof["target"]["rootIdentitySha256"]
            and environment == proof["target"]["environmentSha256"],
            "Original captured physical identity changed")
    def current():
        return [read_file(root["root"], f["relativePath"], (root["device"], root["inode"]))
                for f in proof["files"]]
    files = current()
    require(files == current(), "Files changed during protected observation")
    def matches(phase):
        return all((actual["sha256"], actual["size"]) ==
                   (wanted[phase+"Sha256"], wanted[phase+"Size"])
                   for actual, wanted in zip(files, proof["files"]))
    outcome = "notApplied" if matches("before") else "applied" if matches("after") else "unknown"
    profile = http("GET", "hosts/" + config["hostId"] + "/collaboration-bridge")["bridge"]
    body = {**intent, "bridgeRevision": profile["revision"],
            "executorId": proof["executorId"], "descriptorDigest": proof["descriptorDigest"],
            "serviceBindingDigest": proof["serviceBindingDigest"],
            "channel": "stopped-executor-observation/v1",
            "outcome": outcome, "filesObserved": files}
    body["target"] = {**proof["target"], "actionDigest": digest(body),
                      "paths": [{"relativePath": f["relativePath"],
                                 "resolvedPath": str(Path(root["root"]) / f["relativePath"])}
                                for f in files]}
    saved(command, {"state": "pending", "intent": intent, "wire": body})
    try:
        result = http("POST", "collaboration/mutation-observations", body)
    except urllib.error.HTTPError as error:
        if error.code in (400, 403, 409):
            saved(command, {"state": "rejected", "intent": intent, "wire": body, "status": error.code})
        raise
    saved(command, {"state": "completed", "intent": intent, "wire": body, "result": result})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--permit-id", required=True, type=UUID)
    parser.add_argument("--permit-revision", required=True, type=int)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--note", required=True)
    args = parser.parse_args()
    require(args.permit_revision > 0 and 1 <= len(args.operation_id) <= 128
            and 1 <= len(args.note) <= 1000, "Bounded explicit original observation required")
    print(json.dumps(observe_permit(args.config, str(args.permit_id), args.permit_revision,
                                   args.operation_id, args.note)))


if __name__ == "__main__":
    main()
