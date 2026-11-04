"""Bounded canonical placement metadata; no host execution imports.

This shared projection is used by every OS on the existing catalog edge.
It reads/validates values only and cannot start or resume native work.
"""
import json


def require(value, message):
    if not value:
        raise ValueError(message)


def bounded(value):
    require(len(json.dumps(value, ensure_ascii=True).encode("ascii")) <= 32768,
            "Resource metadata exceeds published bound; request a smaller page")
    require(value.get("mayApply") is False,
            "Resource metadata is never mutation admission")
    return value


def view(value, authority, agent, host=None):
    bounded(value)
    require(
        value.get("schema") == "hollywood-placement/v1"
        and (value.get("authorityId"), value.get("agentId")) == (authority, agent)
        and value.get("newExecutionAdmitted") is False
        and value.get("drainVerified") is False,
        "Placement inspection scope or non-admission evidence differs",
    )
    row = value["placement"]
    if value.get("state") == "not_enrolled":
        require(row is None and value.get("hostId") is None,
                "Unenrolled placement must have no host or revision")
        return value
    require(isinstance(row, dict), "Enrolled placement row required")
    require(
        str(row["authority"]) == authority
        and str(row["agent"]) == agent
        and str(row["host"]) == value["hostId"]
        and (host is None or value["hostId"] == host)
        and type(row["revision"]) is int
        and row["revision"] >= 1
        and type(row["enabled"]) is bool
        and value["state"] == ("enabled" if row["enabled"] else "paused"),
        "Placement revision/host/state differs",
    )
    return value

