"""Native goal identity binding; metadata reconciliation never starts a turn."""

import hashlib
import json
from uuid import UUID, uuid4, uuid5


class NativeAdmissionUnavailable(RuntimeError):
    pass


class NativeGoalHeld(RuntimeError):
    pass


async def external_admission(rpc, external_lifecycle=False):
    required = {"goal_external_admission"}
    if external_lifecycle:
        required.add("goal_external_lifecycle")
    available = set()
    cursor = None
    while True:
        page = await rpc.call(
            "experimentalFeature/list",
            {"limit": 100, **({"cursor": cursor} if cursor else {})},
        )
        available.update(f["name"] for f in page["data"])
        cursor = page.get("nextCursor")
        if not cursor:
            break
    if required - available:
        raise NativeAdmissionUnavailable(
            "Native goal control unavailable; no context loaded: "
            + ", ".join(sorted(required - available))
        )
    enablement = {"goal_external_admission": True}
    if "goal_external_lifecycle" in available:
        enablement["goal_external_lifecycle"] = external_lifecycle
    await rpc.call("experimentalFeature/enablement/set", {"enablement": enablement})


def role_scope(connector):
    value = connector.role_context.value
    return value.get("nativeGoalScope") == "role" and not value.get("workId")


async def bind_role(c):
    """Attach one externally owned responsibility; never adopt an old work goal."""
    from .journal import saved

    policy = c.role_context.value
    role = {
        key: policy[key]
        for key in (
            "authorityId",
            "agentId",
            "primaryRole",
            "roleRevision",
            "rolePurpose",
            "homeRoomId",
        )
    }
    role_digest = hashlib.sha256(json.dumps(role, sort_keys=True).encode()).hexdigest()
    snapshot = await c.rpc.call("thread/goal/get", {"threadId": c.thread})
    if "goalId" not in snapshot:
        raise NativeGoalHeld("Native role goal fencing is unavailable")
    path = c.state / ("native-goal-" + c.context_id + ".json")
    binding = json.loads(path.read_text()) if path.exists() else None
    if binding:
        if (
            binding.get("bindingKind") != "role"
            or binding.get("roleDigest") != role_digest
            or binding["nativeThread"] != c.thread
        ):
            raise NativeGoalHeld(
                "Existing native objective needs explicit role reconciliation"
            )
        if binding.get("nativeGoalId"):
            if binding["nativeGoalId"] != snapshot["goalId"]:
                raise NativeGoalHeld("Original role goal was cleared or replaced")
        elif (
            not snapshot["goal"]
            or snapshot["goal"]["objective"] != binding["objective"]
        ):
            raise NativeGoalHeld("Original role goal creation remains unconfirmed")
        else:
            binding = {**binding, "nativeGoalId": snapshot["goalId"], "state": "bound"}
            saved(path, binding)
    else:
        if snapshot["goal"]:
            raise NativeGoalHeld(
                "Existing native objective cannot silently become a role"
            )
        objective = (
            "Ongoing Hollywood responsibility for agent "
            + policy["agentId"]
            + "; instance "
            + str(uuid4())
            + chr(10)
            + "Primary: "
            + policy["primaryRole"]
            + chr(10)
            + "Responsibility: "
            + policy["rolePurpose"]
            + chr(10)
            + "This responsibility spans separately accepted business goals. "
            "Completing, cancelling or failing one delivery does not finish this role. "
            "Hollywood admits every turn; remain idle between addressed requests or authorized material reviews."
        )
        if len(objective) > 4000:
            objective = (
                "Ongoing Hollywood responsibility for agent " + policy["agentId"]
                + "; instance " + str(uuid4()) + chr(10)
                + "Authority: " + policy["authorityId"] + chr(10)
                + "Primary: " + policy["primaryRole"] + chr(10)
                + "Exact captured role contract SHA-256: " + role_digest + chr(10)
                + "Follow the complete authoritative role purpose in the captured "
                "LAX role context. This responsibility spans separately accepted "
                "business goals; completing one delivery does not finish the role. "
                "Hollywood admits every turn. Remain idle between addressed "
                "requests and authorized material reviews."
            )
        binding = {
            "state": "create-intent",
            "bindingKind": "role",
            "roleDigest": role_digest,
            "roleRevision": policy["roleRevision"],
            "nativeThread": c.thread,
            "contextId": c.context_id,
            "nativeGoalId": None,
            "objective": objective,
            "goalId": None,
            "workId": None,
        }
        saved(path, binding)
        result = await c.rpc.call(
            "thread/goal/set",
            {
                "threadId": c.thread,
                "expectedGoalId": None,
                "origin": "automatic",
                "objective": objective,
                "status": "active",
            },
        )
        if not result.get("goalId") or result["goal"]["objective"] != objective:
            raise NativeGoalHeld("Original role goal creation is unconfirmed")
        binding = {**binding, "nativeGoalId": result["goalId"], "state": "bound"}
        saved(path, binding)
        snapshot = result
    if (
        not snapshot.get("goal")
        or snapshot["goal"]["objective"] != binding["objective"]
    ):
        raise NativeGoalHeld("Original role responsibility changed")
    if snapshot["goal"]["status"] != "active":
        raise NativeGoalHeld(
            "Stopped role responsibility requires explicit operator control"
        )
    payload = {
        "claimId": c.active["delivery"]["claim_id"],
        "generation": c.active["delivery"]["generation"],
        "goalId": None,
        "workId": None,
        "bindingKind": "role",
        "roleRevision": policy["roleRevision"],
        "nativeThread": c.thread,
        "nativeGoalId": binding["nativeGoalId"],
        "contextId": c.context_id,
        "workspaceId": workspace_id(c.config),
        "objectiveDigest": hashlib.sha256(binding["objective"].encode()).hexdigest(),
    }
    intent = c.state / ("goal-link-" + c.active["delivery"]["id"] + ".json")
    saved(intent, {"state": "intent", "payload": payload})
    receipt = await c.http(
        "POST",
        "connector/deliveries/" + c.active["delivery"]["id"] + "/goal-binding",
        payload,
    )
    saved(intent, {"state": "accepted", "payload": payload, "receipt": receipt})
    c.goal_binding = binding
    return {
        key: binding[key]
        for key in (
            "bindingKind",
            "nativeThread",
            "nativeGoalId",
            "contextId",
            "roleRevision",
        )
    }


def workspace_id(config):
    return (
        str(UUID(config["workspaceId"]))
        if config.get("workspaceId")
        else str(uuid5(UUID(config["hostId"]), config["workspace"]))
    )


async def bind(connector, goal_id, work_id=None, new_goal=False):
    from .journal import saved

    c = connector
    snapshot = await c.rpc.call("thread/goal/get", {"threadId": c.thread})
    if "goalId" not in snapshot:
        raise NativeGoalHeld("Native goal instance/fencing API unavailable")
    path = c.state / ("native-goal-" + c.context_id + ".json")
    binding = json.loads(path.read_text()) if path.exists() else None
    expected = None
    if binding:
        if binding["nativeThread"] != c.thread:
            raise NativeGoalHeld("Native goal context changed")
        if binding.get("nativeGoalId"):
            if snapshot["goalId"] != binding["nativeGoalId"]:
                raise NativeGoalHeld("Original native goal was cleared or replaced")
            if new_goal and not work_id and snapshot["goal"]["status"] == "complete":
                archive = c.state / (
                    "native-goal-history-"
                    + hashlib.sha256(binding["nativeGoalId"].encode()).hexdigest()
                    + ".json"
                )
                if archive.exists() and json.loads(archive.read_text()) != binding:
                    raise NativeGoalHeld(
                        "Original goal history requires reconciliation"
                    )
                saved(archive, binding)
                expected = binding["nativeGoalId"]
                binding = None
        else:
            if (
                not snapshot["goal"]
                or snapshot["goal"]["objective"] != binding["objective"]
                or snapshot["goalId"] == binding.get("expectedGoalId")
            ):
                raise NativeGoalHeld("Original goal creation remains unconfirmed")
            binding = {**binding, "nativeGoalId": snapshot["goalId"], "state": "bound"}
            saved(path, binding)
    if not binding:
        if snapshot["goal"] and expected is None:
            raise NativeGoalHeld("Existing native goal needs explicit adoption")
        # Native goals have a 4,000-character ceiling. Hollywood messages and
        # acceptance are separate, larger authoritative records; duplicating them
        # here can reject ordinary enterprise assignments before the first turn.
        # Bind exact references and digests, retaining the complete original
        # request in the admitted turn, journal and Hollywood work briefing.
        request = c.active["request"]
        specification = {
            "requestId": request["id"],
            "body": request["body"],
            "acceptance": c.role_context.value.get("workAcceptance"),
        }
        contract_digest = hashlib.sha256(
            json.dumps(specification, sort_keys=True).encode()
        ).hexdigest()
        objective = (
            ("Hollywood work " + work_id if work_id else
             "Hollywood coordination request " + request["id"])
            + "; binding " + str(uuid4()) + chr(10)
            + "Authority: " + request["authority"] + chr(10)
            + "Hollywood goal: " + goal_id + chr(10)
            + "Source request: " + request["id"] + chr(10)
            + "Exact request/acceptance contract SHA-256: " + contract_digest + chr(10)
            + "Perform the complete original admitted request and its authoritative "
            "Hollywood work acceptance, available in the turn and hollywood_briefing. "
            "Do not substitute this reference for reading that contract. "
            "Complete this bounded native objective only after satisfying those "
            "criteria and submitting verifiable work evidence. Do not complete "
            "the parent enterprise goal or ongoing agent responsibility."
        )
        binding = {
            "state": "create-intent",
            "nativeThread": c.thread,
            "goalId": goal_id,
            "workId": work_id,
            "objective": objective,
            "contextId": c.context_id,
            "nativeGoalId": None,
            "expectedGoalId": expected,
        }
        saved(path, binding)
        result = await c.rpc.call(
            "thread/goal/set",
            {
                "threadId": c.thread,
                "expectedGoalId": expected,
                "origin": "automatic",
                "objective": objective,
                "status": "active",
            },
        )
        if not result.get("goalId") or result["goal"]["objective"] != objective:
            raise NativeGoalHeld("Original goal creation is unconfirmed")
        binding = {**binding, "nativeGoalId": result["goalId"], "state": "bound"}
        saved(path, binding)
        snapshot = result
    if binding["goalId"] != goal_id:
        raise NativeGoalHeld(
            "Another unfinished coordination goal owns this native instance"
        )
    if work_id and binding["workId"] != work_id:
        raise NativeGoalHeld("Another work assignment owns this native goal")
    if (work_id or c.active["request"]["data"].get("goalReview")) and snapshot["goal"][
        "status"
    ] != "active":
        raise NativeGoalHeld(
            "Stopped/completed goal requires explicit lifecycle reconciliation"
        )
    payload = {
        "claimId": c.active["delivery"]["claim_id"],
        "generation": c.active["delivery"]["generation"],
        "goalId": goal_id,
        "workId": work_id,
        "nativeThread": c.thread,
        "nativeGoalId": binding["nativeGoalId"],
        "contextId": c.context_id,
        "workspaceId": workspace_id(c.config),
        "objectiveDigest": hashlib.sha256(
            snapshot["goal"]["objective"].encode()
        ).hexdigest(),
    }
    intent = c.state / ("goal-link-" + c.active["delivery"]["id"] + ".json")
    saved(intent, {"state": "intent", "payload": payload})
    receipt = await c.http(
        "POST",
        "connector/deliveries/" + c.active["delivery"]["id"] + "/goal-binding",
        payload,
    )
    saved(intent, {"state": "accepted", "payload": payload, "receipt": receipt})
    c.goal_binding = {**binding, "goalId": goal_id, "workId": work_id}
    return {
        "nativeThread": c.thread,
        "nativeGoalId": binding["nativeGoalId"],
        "contextId": c.context_id,
        "goalId": goal_id,
        "workId": work_id,
    }


async def progress(connector):
    c = connector
    if not c.goal_binding:
        return None
    snapshot = await c.rpc.call("thread/goal/get", {"threadId": c.thread})
    if snapshot.get("goalId") != c.goal_binding["nativeGoalId"] or not snapshot.get(
        "goal"
    ):
        raise RuntimeError("Native goal instance changed during admitted work")
    expected_digest = c.goal_binding.get("objectiveDigest")
    if not expected_digest and c.goal_binding.get("objective"):
        expected_digest = hashlib.sha256(
            c.goal_binding["objective"].encode()
        ).hexdigest()
    if (
        expected_digest
        and hashlib.sha256(snapshot["goal"]["objective"].encode()).hexdigest()
        != expected_digest
    ):
        raise NativeGoalHeld("Native goal objective changed during bound work")
    return {
        "goalId": snapshot["goalId"],
        **{
            key: snapshot["goal"][key]
            for key in ("status", "tokensUsed", "timeUsedSeconds", "tokenBudget")
        },
    }


async def restore(connector, record):
    """Recover the server's original binding without creating/adopting a goal."""
    c = connector
    agent_binding = c.active.get("agentContextBinding")
    if agent_binding:
        if (agent_binding["native_thread"],agent_binding["context_id"],agent_binding["workspace_id"]) != (
            record.get("nativeThread"),record.get("contextId"),workspace_id(c.config)
        ):
            raise NativeGoalHeld("Original agent execution context changed")
        c.context_id = agent_binding["context_id"]
        c.agent_binding = agent_binding
        c.goal_binding = None
        return None
    binding = c.active.get("nativeGoalBinding")
    if not binding:
        if c.active["request"]["data"].get("goalId"):
            raise NativeGoalHeld("Accepted work has no confirmed native goal binding")
        return None
    if (
        binding["native_thread"] != record.get("nativeThread")
        or binding["context_id"] != record.get("contextId")
        or binding["workspace_id"] != workspace_id(c.config)
        or binding["delivery"] != c.active["delivery"]["id"]
        or binding["generation"] != c.active["delivery"]["generation"]
    ):
        raise NativeGoalHeld("Recovery binding differs from original native ownership")
    snapshot = await c.rpc.call("thread/goal/get", {"threadId": c.thread})
    if (
        snapshot.get("goalId") != binding["native_goal_id"]
        or not snapshot.get("goal")
        or hashlib.sha256(snapshot["goal"]["objective"].encode()).hexdigest()
        != binding["objective_digest"]
    ):
        raise NativeGoalHeld("Original native goal was cleared, replaced or changed")
    c.context_id = binding["context_id"]
    c.goal_binding = {
        "nativeThread": c.thread,
        "contextId": c.context_id,
        "nativeGoalId": binding["native_goal_id"],
        "goalId": binding["goal"],
        "workId": binding["work"],
        "objectiveDigest": binding["objective_digest"],
        "bindingKind": binding.get("binding_kind", "coordination"),
        "roleRevision": binding.get("role_revision"),
    }
    return c.goal_binding


async def settle(connector, status):
    """Pause unfinished goals after a terminal stop/failure; never admit execution."""
    from .journal import saved

    c = connector
    if (
        not c.goal_binding
        or c.goal_binding.get("bindingKind") == "role"
        or status not in ("cancelled", "failed")
    ):
        return None
    before = await progress(c)
    intent = {
        "deliveryId": c.active["delivery"]["id"],
        "generation": c.active["delivery"]["generation"],
        "nativeThread": c.thread,
        "nativeGoalId": c.goal_binding["nativeGoalId"],
        "executionState": status,
        "desiredStatus": "paused",
    }
    path = c.state / ("goal-lifecycle-" + intent["deliveryId"] + ".json")
    if path.exists():
        prior = json.loads(path.read_text())
        if prior["intent"] != intent:
            raise NativeGoalHeld("Native lifecycle intent changed ownership")
    saved(path, {"state": "intent", "intent": intent, "before": before})
    if before["status"] not in ("paused", "complete"):
        try:
            await c.rpc.call(
                "thread/goal/set",
                {
                    "threadId": c.thread,
                    "expectedGoalId": intent["nativeGoalId"],
                    "status": "paused",
                },
            )
        except Exception:
            # Reconcile only metadata for the original instance, never a native turn.
            after = await progress(c)
            if after["status"] != "paused":
                raise NativeGoalHeld("Original goal pause is unconfirmed")
    after = await progress(c)
    if after["status"] not in ("paused", "complete"):
        raise NativeGoalHeld("Stopped execution retains an active native goal")
    result = {
        "state": "confirmed",
        "intent": intent,
        "before": before,
        "after": after,
        "modelTurnsStarted": 0,
        "externalEffectsUndone": False,
    }
    saved(path, result)
    return after


async def sync_policy(connector, goal_id, state, operation):
    if getattr(connector,"purpose_scope",None):
        return None  # Canonical Hollywood goals do not replace purpose identities.
    """An explicit goal control changes only its existing matching native binding."""
    from .journal import saved

    c = connector
    if (
        not c.goal_binding
        or c.goal_binding.get("bindingKind") == "role"
        or c.goal_binding["goalId"] != goal_id
        or state == "accepted"
    ):
        return None
    desired = "active" if state == "active" else "paused"
    before = await progress(c)
    if desired == "active" and before["status"] == "complete":
        raise NativeGoalHeld(
            "Completed native objective needs explicit new-instance reconciliation"
        )
    intent = {
        "operationId": operation,
        "canonicalGoalId": goal_id,
        "requestedCanonicalState": state,
        "deliveryId": c.active["delivery"]["id"],
        "nativeThread": c.thread,
        "nativeGoalId": c.goal_binding["nativeGoalId"],
        "desiredStatus": desired,
    }
    path = c.state / (
        "goal-policy-" + hashlib.sha256(operation.encode()).hexdigest() + ".json"
    )
    if path.exists() and json.loads(path.read_text())["intent"] != intent:
        raise NativeGoalHeld("Original native policy operation changed")
    saved(path, {"state": "intent", "intent": intent, "before": before})
    if before["status"] not in (desired, "complete"):
        try:
            await c.rpc.call(
                "thread/goal/set",
                {
                    "threadId": c.thread,
                    "expectedGoalId": intent["nativeGoalId"],
                    "status": desired,
                },
            )
        except Exception:
            observed = await progress(c)
            if observed["status"] != desired:
                raise NativeGoalHeld("Original native goal control remains unconfirmed")
    after = await progress(c)
    if after["status"] not in (desired, "complete"):
        raise NativeGoalHeld(
            "Native goal policy differs from its confirmed business control"
        )
    result = {
        "state": "confirmed",
        "intent": intent,
        "after": after,
        "modelTurnsStarted": 0,
        "activeExecutionStopped": False,
        "externalEffectsUndone": False,
    }
    saved(path, result)
    return result
