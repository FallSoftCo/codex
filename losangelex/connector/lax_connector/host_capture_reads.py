"""Per-callback host reads from one canonical executor snapshot.

Contexts are isolated across concurrent callbacks. This reader cannot forward
arbitrary agent IDs, room reads or administrative writes through host authority.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID


class HostCaptureReads:
    def __init__(self, transport):
        self.transport = transport
        self.current = ContextVar("host_capture_execution", default=None)

    def fetch(self, executor):
        identity = str(UUID(executor["id"]))
        result = self.transport("GET", "executors/" + identity + "?view=capture")
        actual = result["executor"]
        if any(actual[key] != executor[key] for key in (
                "id", "agent", "host", "delivery", "generation", "claim_id")):
            raise PermissionError("Host execution identity changed")
        proof = result["capture"]
        if (proof.get("schema") != "hollywood-host-execution-capture/v1"
                or proof.get("admitsExecution") is not False
                or proof["snapshot"]["delivery"]["id"] != executor["delivery"]
                or proof["role"]["principal"] != executor["agent"]):
            raise PermissionError("Canonical host capture differs from original execution")
        return proof

    @contextmanager
    def bind(self, executor):
        token = self.current.set((executor, self.fetch(executor)))
        try:
            yield
        finally:
            self.current.reset(token)

    def read(self, method, path, payload=None):
        if method != "GET" or payload is not None:
            raise PermissionError("Host capture does not authorize administrative writes")
        # Independent executor recovery already has canonical host authorization.
        if path.startswith("executors/"):
            identity = str(UUID(path.removeprefix("executors/")))
            return self.transport("GET", "executors/" + identity)
        bound = self.current.get()
        if bound is None:
            raise PermissionError("An original native callback must own host capture reads")
        executor, proof = bound
        delivery_path = "deliveries/" + executor["delivery"]
        if path == delivery_path:
            # Native admission may still be persisting its running receipt.
            # Refresh this same execution; never look up another agent's state.
            proof = self.fetch(executor)
            self.current.set((executor, proof))
            return proof["snapshot"]
        if path == "agents/" + executor["agent"] + "/role":
            return proof["role"]
        work, goal = proof.get("work"), proof.get("goal")
        if work and path == "work/" + work["id"]:
            return {"work": work}
        if goal and path == "goals/" + goal["id"]:
            return {"goal": goal}
        raise PermissionError("Read is outside the original host execution")
