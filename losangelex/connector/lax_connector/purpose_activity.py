"""Attribute delayed native activity to its accepted origin, never the current turn."""
import hashlib
import json
from uuid import UUID

from .activity import Activity
from .execution_scope import ExecutionScope
from .journal import saved


class PurposeActivity(Activity):
    def __init__(self, runner):
        super().__init__(
            state=runner.state, scope=lambda: runner.execution_scope,
            send=runner.send_activity, secrets=tuple(runner.config["tokens"].values()))
        self.runner = runner

    def record(self, method, params):
        runner = self.runner
        if params.get("threadId") != runner.thread:
            return
        if method in ("item/started", "item/completed"):
            if params.get("item", {}).get("type") not in (
                    "commandExecution", "fileChange", "planUpdate", "mcpToolCall"):
                return
        elif method != "turn/plan/updated":
            return
        try:
            turn = str(UUID(params["turnId"]))
            scope = runner.execution_scope
            if scope is None or scope.as_dict()["nativeTurn"] != turn:
                path = runner.state / ("execution-" + turn + ".json")
                if path.stat().st_size > 65536:
                    raise ValueError("Accepted activity scope receipt exceeds bound")
                receipt = json.loads(path.read_text())
                scopes = receipt.get("executionScopes", [])
                if len(scopes) != 1:
                    raise ValueError("Original activity needs one accepted execution scope")
                scope = ExecutionScope.accepted(
                    receipt, agent=runner.config["agentId"], thread=runner.thread,
                    turn=turn, materials=[scopes[0]["materialId"]])
            if scope.as_dict()["contextId"] != runner.config["contextIds"]["writer"]:
                raise ValueError("Original activity belongs to another purpose context")
            super().record(method, params, captured_scope=scope)
        except Exception as error:
            # Observations grant no execution authority. Retain an unpublishable
            # event privately; never relabel it or tear down the model transport.
            notification = {"method": method, "params": params}
            identity = hashlib.sha256(
                json.dumps(notification, sort_keys=True).encode()).hexdigest()
            directory = runner.state / "activity-gaps"
            directory.mkdir(mode=0o700, exist_ok=True)
            path = directory / (identity + ".json")
            if not path.exists():
                saved(path, {
                    "notification": notification, "error": type(error).__name__,
                    "state": "unpublished", "executionReplayed": False})
            runner.trace("activity_observation_gap", {
                "nativeTurn": params.get("turnId"), "journal": str(path),
                "error": type(error).__name__, "executionReplayed": False})
