"""Per-callback host reads from one canonical executor snapshot.

Contexts are isolated across concurrent callbacks. This reader cannot forward
arbitrary agent IDs, room reads or administrative writes through host authority.
"""
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from uuid import UUID


class HostCaptureReads:
    def __init__(self, transport, *, host_id, authority_id):
        self.transport = transport
        self.host_id = str(UUID(host_id))
        self.authority_id = str(UUID(authority_id))
        self.current = ContextVar("host_capture_execution", default=None)

    def fetch(self, executor):
        if executor["host"] != self.host_id or executor["authority"] != self.authority_id:
            raise PermissionError("Executor belongs to another host")
        identity = str(UUID(executor["id"]))
        result = self.transport("GET", "executors/" + identity + "?view=capture")
        actual = result["executor"]
        if any(actual[key] != executor[key] for key in (
                "id", "authority", "agent", "host", "delivery", "generation", "claim_id")):
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

    @contextmanager
    def bind_delivery(self, agent_id, delivery_id):
        agent_id, delivery_id = str(UUID(agent_id)), str(UUID(delivery_id))
        after, matches = None, []
        for _ in range(4):
            path = "hosts/" + self.host_id + "/executors?limit=256"
            if after:
                path += "&after=" + str(UUID(after))
            page = self.transport("GET", path)
            matches.extend(row for row in page["executors"]
                           if row["agent"] == agent_id and row["delivery"] == delivery_id)
            after = page["nextAfter"]
            if not after:
                break
        if after or len(matches) != 1:
            raise PermissionError("One exact local execution must own metadata capture")
        with self.bind(matches[0]):
            yield

    def request(self, method, path, payload=None):
        if method == "GET":
            if path.startswith("administration/commands/"):
                operation = path.removeprefix("administration/commands/")
                if not operation or len(operation) > 128 or "/" in operation:
                    raise PermissionError("Original command receipt identity required")
                return self.transport(method, path)
            return self.read(method, path, payload)
        bound = self.current.get()
        if method != "PUT" or bound is None or not isinstance(payload, dict):
            raise PermissionError("Administrative operation is outside host capture")
        work = bound[1].get("work")
        parts = path.split("/")
        if (not work or len(parts) != 4 or parts[0] != "physical-workspaces"
                or parts[2] != "grants" or parts[3] != work["id"]
                or set(payload) != {"operationId", "revision", "workspaceRevision",
                                    "workRevision", "state"}
                or payload["state"] != "active" or payload["workRevision"] != work["revision"]):
            raise PermissionError("Only the original Work resource grant is supported")
        str(UUID(parts[1]))
        # The canonical transaction independently fences host, agent access,
        # revocations, current execution and the original operation receipt.
        return self.transport(method, path, payload)

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


def guardian_scope(capture, owner, delivery_id):
    """Bind metadata only after the caller verifies its actual guardian peer."""
    reads = getattr(capture, "host_reads", None)
    return (reads.bind_delivery(owner["agentId"], delivery_id)
            if reads is not None else nullcontext())
