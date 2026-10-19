"""An accepted immutable native turn scope; not a claim of executor liveness."""
from dataclasses import dataclass
from types import MappingProxyType
from uuid import UUID


@dataclass(frozen=True)
class ExecutionScope:
    wire: object

    @classmethod
    def accepted(cls, receipt, *, agent, thread, turn, materials):
        values = receipt.get("executionScopes", [])
        if len(values) != 1:
            raise RuntimeError("Writer needs one accepted original execution scope")
        value = dict(values[0])
        if value.get("schema") not in ("lax-execution-scope/v1","lax-execution-scope/v2"):
            raise RuntimeError("Unsupported accepted execution scope")
        if value["schema"]=="lax-execution-scope/v2":
            UUID(value["executorId"])
        expected = {"agentId": agent,
                    "purpose": "writer", "nativeThread": thread, "nativeTurn": turn}
        if any(value.get(k) != v for k, v in expected.items()):
            raise RuntimeError("Accepted execution scope belongs to another native owner")
        if [value.get("materialId")] != list(materials):
            raise RuntimeError("Accepted execution scope changed original work")
        for key in ("authorityId", "agentId", "hostId", "contextId", "materialId", "sourceRequestId", "deliveryId"):
            UUID(value[key])
        if type(value["generation"]) is not int or value["generation"] < 1 or not value["claimId"]:
            raise RuntimeError("Accepted execution scope has no original claim")
        return cls(MappingProxyType(value))

    def as_dict(self):
        return dict(self.wire)
