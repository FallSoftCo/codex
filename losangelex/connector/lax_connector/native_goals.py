"""Native goal identity binding; metadata reconciliation never starts a turn."""

import hashlib
import json
from uuid import UUID, uuid4, uuid5


class NativeAdmissionUnavailable(RuntimeError):
    pass


class NativeGoalHeld(RuntimeError):
    pass


async def external_admission(rpc):
    cursor = None
    while True:
        page = await rpc.call(
            "experimentalFeature/list",
            {"limit": 100, **({"cursor": cursor} if cursor else {})},
        )
        if any(f["name"] == "goal_external_admission" for f in page["data"]):
            await rpc.call(
                "experimentalFeature/enablement/set",
                {"enablement": {"goal_external_admission": True}},
            )
            return
        cursor = page.get("nextCursor")
        if not cursor:
            raise NativeAdmissionUnavailable(
                "Native external goal admission is unavailable; no context loaded"
            )


def workspace_id(config):
    return (
        str(UUID(config["workspaceId"]))
        if config.get("workspaceId")
        else str(uuid5(UUID(config["hostId"]), config["workspace"]))
    )


async def bind(connector, goal_id, work_id=None, new_goal=False):
    from .connector import saved

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
        objective = (
            "Hollywood work " + work_id
            if work_id
            else "Hollywood coordination request " + c.active["request"]["id"]
        )
        objective += "; binding " + str(uuid4()) + chr(10) + c.active["request"]["body"]
        if work_id and c.role_context.value.get("workAcceptance"):
            objective += (
                chr(10) + "Acceptance: " + c.role_context.value["workAcceptance"]
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
    return {
        "goalId": snapshot["goalId"],
        **{
            key: snapshot["goal"][key]
            for key in ("status", "tokensUsed", "timeUsedSeconds", "tokenBudget")
        },
    }
