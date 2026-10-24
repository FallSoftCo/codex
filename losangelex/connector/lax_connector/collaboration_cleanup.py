"""Authority-reducing cleanup keeps its original physical namespace.

The native source remains the CURRENT admitted purpose. Original Work, ownership,
known effects and revisions are independently revalidated by Hollywood.
"""
from uuid import UUID

from .collaboration_bridge import require
from .service_observer import protected


def permitted(port, command):
    return ((port == "coordination" and command.get("action") == "release")
            or (port == "edit-plans" and command.get("action") in ("withdraw", "revoke")))


def root(bridge, record, port, command, environment):
    require(permitted(port, command), "Only explicit authority-reducing cleanup")
    if port == "coordination":
        locator = protected(bridge.state / "commands" /
                            ("claim-" + str(UUID(command["claimId"])) + ".json"))
        workspace, host = locator["workspaceId"], record["sourceBase"]["hostId"]
    else:
        snapshot = bridge.http("GET", "collaboration/edit-plans/" + str(UUID(command["planId"])))
        original = snapshot["plan"]
        require(str(original["id"]) == str(UUID(command["planId"])),
                "Original cleanup plan identity differs")
        if command["action"] == "withdraw":
            require(str(original["integrator_work"]) == str(UUID(command["workId"])),
                    "Only original integrator Work may withdraw its plan")
            workspace, host = str(original["workspace_id"]), str(original["host"])
        else:
            consents = [vote for vote in snapshot["consents"]
                        if str(vote["work"]) == str(UUID(command["workId"]))]
            require(len(consents) == 1, "Exact original participant consent required")
            workspace, host = str(consents[0]["workspace_id"]), str(consents[0]["host"])
    require(host == record["sourceBase"]["hostId"], "Cleanup needs its original execution host")
    roots = [item for item in record["resources"]
             if item["workspaceId"] == workspace and item["hostId"] == host
             and item["environmentId"] == environment]
    require(len(roots) == 1, "Original cleanup namespace is not an authorized captured local resource")
    # The caller retains inode, path, frame, grant, decision and backend checks.
    # No current-default substitution, grant widening or filesystem operation.
    return roots[0]
