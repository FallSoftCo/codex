"""Read authenticated native-effect parentage, never infer it from conversation."""

from .continuation_context import encoded, identity, origin_reference, read, receipt, require


SCHEMA = "hollywood-native-delegation/v1"
FIELDS = {"schema", "childRequestId", "childDeliveryId", "conversationSourceEventId",
          "parent", "nativeCallId", "operationId", "proof"}
PARENT_FIELDS = {"authorityId", "agentId", "hostId", "deliveryId", "generation",
                 "claimId", "requestId", "contextId", "roleRevision"}


def positive(value):
    return type(value) is int and value > 0


def digest_id(value):
    return (isinstance(value, str) and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


def validate(value, child, actor, authority):
    dd, de = receipt(child)
    require(isinstance(value, dict) and len(encoded(value)) <= 32768
            and value.get("schema") == SCHEMA and set(value) == FIELDS,
            "NATIVE_DELEGATION_UNAVAILABLE")
    require(value.get("childRequestId") == de["id"]
            and value.get("childDeliveryId") == dd["id"]
            and value.get("conversationSourceEventId") == de["source"]
            and dd["authority"] == de["authority"] == authority
            and de["author"] == actor and de["data"].get("authorKind") == "agent"
            and de["data"].get("expectsReply") is True,
            "NATIVE_DELEGATION_CHILD_MISMATCH")
    parent = value.get("parent")
    require(isinstance(parent, dict) and set(parent) == PARENT_FIELDS,
            "NATIVE_DELEGATION_PARENT_MISSING")
    for key in ("authorityId", "agentId", "hostId", "deliveryId", "requestId"):
        identity(parent.get(key))
    require(parent["authorityId"] == authority and parent["agentId"] == actor
            and positive(parent.get("generation")) and positive(parent.get("roleRevision"))
            and digest_id(parent.get("contextId"))
            and isinstance(parent.get("claimId"), str) and 0 < len(parent["claimId"]) <= 256
            and all(isinstance(value.get(key), str) and 0 < len(value[key]) <= maximum
                    for key, maximum in (("nativeCallId", 256), ("operationId", 128))),
            "NATIVE_DELEGATION_PARENT_MISMATCH")
    proof = value.get("proof")
    require(isinstance(proof, dict) and set(proof) == {"nativeEffectId", "recordedBy"}
            and positive(proof.get("nativeEffectId"))
            and proof.get("recordedBy") in ("native_acceptance", "verified_original_transaction"),
            "NATIVE_DELEGATION_PROOF_MISSING")
    return parent


def historical_binding(provenance, canonical):
    """Match the admitted historical binding; no current executor is required."""
    pd, pe = receipt(canonical)
    expected = {"id": provenance["deliveryId"], "authority": provenance["authorityId"],
                "agent": provenance["agentId"], "host": provenance["hostId"],
                "event": provenance["requestId"], "generation": provenance["generation"],
                "claim_id": provenance["claimId"]}
    require(all(pd.get(k) == v for k, v in expected.items()),
            "NATIVE_DELEGATION_PARENT_CHANGED")
    identity(pd.get("native_thread"))
    binding = canonical.get("agentContextBinding")
    require(isinstance(binding, dict) and all(binding.get(k) == v for k, v in {
        "delivery": pd["id"], "generation": pd["generation"], "principal": pd["agent"],
        "context_id": provenance["contextId"], "role_revision": provenance["roleRevision"],
        "native_thread": pd.get("native_thread"),
    }.items()) and isinstance(pd.get("native_thread"), str),
        "NATIVE_DELEGATION_BINDING_CHANGED")
    require(not pd["cancellation_requested"] and pd["state"] not in
            ("cancel_requested", "cancelled", "unknown"), "PARENT_SCOPE_HELD")
    return pd, pe


async def parent_for(get, child, actor, authority):
    dd, de = receipt(child)
    path = "deliveries/" + dd["id"] + "/delegation"
    value = await read(get, path)
    parent = validate(value, child, actor, authority)
    canonical = await read(get, "deliveries/" + parent["deliveryId"])
    _, pe = historical_binding(parent, canonical)
    require(pe["seq"] < de["seq"], "LINEAGE_ORDER_MISMATCH")
    again = await read(get, path)
    require(value == again, "NATIVE_DELEGATION_CHANGED_DURING_READ")
    return {"provenance": value, "canonical": canonical,
            "reference": origin_reference(canonical)}
