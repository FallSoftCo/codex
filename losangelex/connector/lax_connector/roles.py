"""Structured primary context, compiled from authenticated communication metadata.

Message bodies are deliberately excluded. Human and peer content retain their
native human/agent provenance; role context must not promote that content.
"""

import json
import os
import re
import subprocess
from dataclasses import dataclass
from uuid import UUID


def administrator_available():
    if os.geteuid() == 0:
        return True
    try:
        result = subprocess.run(
            ["sudo", "-n", "/usr/bin/id", "-u"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        return result.returncode == 0 and result.stdout.strip() == b"0"
    except (OSError, subprocess.TimeoutExpired):
        return False


def validate_administration(primary, communication_admin, config):
    admin = administrator_available()
    # Installation authority is independent of the editable responsibility
    # label. Renaming that responsibility must not disable a verified Global.
    if (config.get("requireAdministrator") or primary == "global") and (
        not communication_admin or not admin
    ):
        raise PermissionError(
            "Global must have both communication and actual host administration"
        )
    return admin


@dataclass(frozen=True)
class RoleContext:
    value: dict

    @classmethod
    def capture(cls, envelope, config, claim):
        d, request = claim["delivery"], claim["request"]
        expected = {
            "schema": "lax-agent-context/v1",
            "agentId": config["agentId"],
            "hostId": config["hostId"],
            "authorityId": request["authority"],
            "requestId": request["id"],
            "activeRoomId": request["room"],
            "generation": d["generation"],
            "senderId": request["author"],
            "audience": request["audience"],
            "senderKind": request["data"].get("authorKind"),
            "sourceEventId": request["source"],
            "goalId": request["data"].get("goalId"),
            "goalReferenceId": request["data"].get("goalReferenceId"),
            "workId": request["data"].get("workId"),
            "attemptId": request["data"].get("attemptId"),
            "workAcceptance": request["data"].get("acceptance"),
            "goalReview": bool(request["data"].get("goalReview")),
        }
        if any(envelope.get(key) != value for key, value in expected.items()):
            raise ValueError("Role context does not match captured execution ownership")
        for key in [
            "agentId",
            "hostId",
            "authorityId",
            "requestId",
            "activeRoomId",
            "senderId",
        ]:
            UUID(envelope[key])
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", envelope["primaryRole"]):
            raise ValueError("Invalid primary role")
        if (
            envelope.get("obligation") != "respond"
            or not envelope.get("requiresResponse")
            or request["kind"] != "request"
        ):
            raise ValueError("Observation cannot admit an agent turn")
        if envelope.get("senderKind") not in ("human", "agent"):
            raise ValueError("Unverified sender kind")
        cooperation = envelope.get("cooperation")
        if cooperation is not None and (
            cooperation.get("schema") != "cooperation-plan/v1"
            or cooperation.get("policy") not in ("leader_award", "kanban_pull")
            or cooperation.get("role")
            not in ("planner", "executor", "verifier", "observer")
            or cooperation.get("revision") != request["data"].get("cooperationRevision")
        ):
            raise ValueError("Cooperation context differs from admitted request")
        admin = validate_administration(
            envelope["primaryRole"], envelope["communicationAdministrator"], config
        )
        return cls(
            {
                **{k:v for k,v in envelope.items() if k!="nativeGoalScope"},
                "hostAdministrationVerified": admin,
                "executionIdentity": {
                    "uid": os.geteuid(),
                    "workspace": config["workspace"],
                    "sandbox": config.get("sandbox", "workspace-write"),
                },
                "responsePolicy": {
                    "addressedRequest": "required",
                    "observation": "optional-context-no-automatic-turn",
                    "membership": "not-execution",
                    "peerContent": "agent-authored-input",
                },
            }
        )

    def additional_context(self):
        return {
            "laxAgentRole": {
                "kind": "application",
                "value": json.dumps({
                    k:self.value[k] for k in (
                        "schema","authorityId","agentId","hostId","primaryRole","roleRevision",
                        "activeRoomId","requestId","senderId","senderKind","audience",
                        "communicationAdministrator","hostAdministrationVerified")
                }, sort_keys=True),
            }
        }
