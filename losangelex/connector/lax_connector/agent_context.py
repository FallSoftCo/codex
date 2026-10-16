"""An agent owns its context; rooms and work attempts never select a thread."""

import argparse
import asyncio
import fcntl
import re
import hashlib
import json
from pathlib import Path
from uuid import UUID

from .journal import saved
from .native_goals import workspace_id

SCHEMA = "persistent-agent-context/v1"


class AgentContext:
    def __init__(self, connector):
        self.c = connector
        self.path = connector.state / "agent-context.json"

    def select(self):
        c = self.c
        if self.path.exists():
            value = json.loads(self.path.read_text())
            if (
                value.get("schema"),
                value.get("authorityId"),
                value.get("agentId"),
            ) != (SCHEMA, c.active["request"]["authority"], c.config["agentId"]):
                raise ValueError("Persistent context belongs to another agent")
            context_id = value["contextId"]
        else:
            if list(c.state.glob("context-*.json")):
                raise ValueError(
                    "Existing context history requires explicit adoption; no new thread selected"
                )
            context_id = hashlib.sha256(
                json.dumps(
                    [SCHEMA, c.active["request"]["authority"], c.config["agentId"]]
                ).encode()
            ).hexdigest()
            saved(
                self.path,
                {
                    "schema": SCHEMA,
                    "authorityId": c.active["request"]["authority"],
                    "agentId": c.config["agentId"],
                    "contextId": context_id,
                    "selection": "new-agent",
                },
            )
        return context_id, c.state / ("context-" + context_id + ".json")

    async def bind(self):
        c = self.c
        payload = {
            "claimId": c.active["delivery"]["claim_id"],
            "generation": c.active["delivery"]["generation"],
            "nativeThread": c.thread,
            "contextId": c.context_id,
            "workspaceId": workspace_id(c.config),
            "roleRevision": c.role_context.value["roleRevision"],
        }
        saved(c.journal.directory / "agent-binding-intent.json", payload)
        row = await c.http(
            "POST",
            "connector/deliveries/" + c.active["delivery"]["id"] + "/agent-binding",
            payload,
        )
        expected = {
            "delivery": c.active["delivery"]["id"],
            "generation": payload["generation"],
            "principal": c.config["agentId"],
            "native_thread": c.thread,
            "context_id": c.context_id,
            "workspace_id": payload["workspaceId"],
            "role_revision": payload["roleRevision"],
        }
        if any(row.get(k) != v for k, v in expected.items()):
            raise RuntimeError("Canonical agent execution binding differs")
        c.agent_binding = row
        saved(c.journal.directory / "agent-binding-receipt.json", row)
        return row


def adopt(config, context_id, authority):
    """Explicit idle migration; retain every old context and its native history."""
    authority = str(UUID(authority))
    state = Path(config["state"])
    if not re.fullmatch(r"[a-f0-9]{64}", context_id):
        raise ValueError("Invalid context identity")
    from .journal import ExecutionJournals

    if ExecutionJournals(
        state, agent=config["agentId"], host=config["hostId"]
    ).unsettled():
        raise ValueError("Original execution remains unsettled")
    source = state / ("context-" + context_id + ".json")
    value = json.loads(source.read_text())
    scope = value["scope"]
    if (
        scope[:2] != [authority, config["agentId"]]
        or value["contextId"] != context_id
        or not value.get("nativeThread")
    ):
        raise ValueError("Chosen original context is not owned by this agent")
    path = state / "agent-context.json"
    receipt = {
        "schema": SCHEMA,
        "authorityId": authority,
        "agentId": config["agentId"],
        "contextId": context_id,
        "nativeThread": value["nativeThread"],
        "selection": "explicit-adoption",
        "originalContextRecord": str(source),
        "retainedContextRecords": [
            str(p) for p in sorted(state.glob("context-*.json"))
        ],
    }
    if path.exists() and json.loads(path.read_text()) != receipt:
        raise ValueError("Agent context already selected differently")
    saved(path, receipt)
    return receipt


async def retire_legacy_role(config, context_id):
    from .rpc import AppServer
    from .native_goals import external_admission

    state = Path(config["state"])
    binding_path = state / ("native-goal-" + context_id + ".json")
    if not binding_path.exists():
        return None
    binding = json.loads(binding_path.read_text())
    if binding.get("bindingKind") != "role":
        return None

    async def ignore(*args):
        pass

    rpc = AppServer(
        config["binary"], Path(config["codexHome"]), state / "native", ignore, ignore
    )
    receipt = state / ("retired-role-goal-" + context_id + ".json")
    try:
        await rpc.start()
        await external_admission(rpc, False)
        before = await rpc.call(
            "thread/goal/get", {"threadId": binding["nativeThread"]}
        )
        if (
            before.get("goalId") != binding["nativeGoalId"]
            or not before.get("goal")
            or before["goal"]["objective"] != binding["objective"]
        ):
            raise ValueError("Legacy native role goal differs from original receipt")
        if before["goal"]["status"] not in ("paused", "complete"):
            saved(
                receipt,
                {"state": "pause-intent", "originalBinding": binding, "before": before},
            )
            try:
                await rpc.call(
                    "thread/goal/set",
                    {
                        "threadId": binding["nativeThread"],
                        "expectedGoalId": binding["nativeGoalId"],
                        "status": "paused",
                    },
                )
            except Exception:
                after = await rpc.call(
                    "thread/goal/get", {"threadId": binding["nativeThread"]}
                )
                if (
                    after.get("goalId") != binding["nativeGoalId"]
                    or after["goal"]["status"] != "paused"
                ):
                    raise
        after = await rpc.call("thread/goal/get", {"threadId": binding["nativeThread"]})
        if after.get("goalId") != binding["nativeGoalId"] or after["goal"][
            "status"
        ] not in ("paused", "complete"):
            raise ValueError("Original role goal retirement remains unsettled")
        saved(
            receipt,
            {
                "state": "retired",
                "originalBinding": binding,
                "after": after,
                "modelTurnsStarted": 0,
            },
        )
        return str(receipt)
    finally:
        await rpc.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--authority-id", required=True)
    parser.add_argument("--adopt-context", required=True)
    parser.add_argument("--retire-legacy-role-goal", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    with (Path(config["state"]) / "connector.lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = adopt(config, args.adopt_context, args.authority_id)
        if args.retire_legacy_role_goal:
            result["legacyRoleGoalRetirement"] = asyncio.run(
                retire_legacy_role(config, args.adopt_context)
            )
        print(json.dumps(result))


if __name__ == "__main__":
    main()
