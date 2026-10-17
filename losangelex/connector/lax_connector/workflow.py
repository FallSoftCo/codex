"""Role-scoped Hollywood work tools and independently hashed artifact evidence."""

import hashlib
import os
import stat
from pathlib import PurePosixPath
from uuid import UUID, uuid5

from .native_goals import bind, progress, sync_policy, workspace_id
from .errors import ToolValidationError, validate_workflow_note
from .artifact_routing import collect as collect_artifacts

from .resource_routing import READ_TOOLS as RESOURCE_READ_TOOLS
from .placement_control import READ_TOOL as PLACEMENT_READ_TOOL

READ_TOOLS = RESOURCE_READ_TOOLS | {
    "hollywood_mutation_read",
    PLACEMENT_READ_TOOL,
    "hollywood_portfolio",
    "hollywood_execution_read",
    "hollywood_briefing",
    "hollywood_decisions",
    "hollywood_work_attempts",
    "hollywood_goal_read",
    "hollywood_work_read",
    "hollywood_work_list",
    "hollywood_supervision",
    "hollywood_attention_read",
    "hollywood_attention_list",
}
MUTATION_TOOLS = {
    "hollywood_execution_cancel",
    "hollywood_decision_set",
    "hollywood_work_revise",
    "hollywood_work_recover",
    "hollywood_goal_create",
    "hollywood_cooperation_set",
    "hollywood_work_claim",
    "hollywood_work_create",
    "hollywood_work_assign",
    "hollywood_work_report",
    "hollywood_work_report_reconcile",
    "hollywood_work_review",
    "hollywood_work_cancel",
    "hollywood_goal_state",
}


def definitions(spec):
    text = {"type": "string"}
    note = {"type": "string", "minLength": 1, "maxLength": 4000,
            "description": "Concise outcome and evidence references, at most4000 characters; do not copy full transcripts."}
    revision = {"type": "integer", "minimum": 1}
    from .resource_routing import definitions as resource_definitions
    from .placement_control import definitions as placement_definitions
    return resource_definitions(spec) + placement_definitions(spec) + [
        spec(
            "hollywood_portfolio",
            "Global: inspect durable portfolio obligations, original review receipts and held/unknown review state. Dispatch is not acceptance; observation starts no model.",
            {
                "afterReference": {"type": ["string", "null"]},
                "afterScope": {
                    "type": ["string", "null"],
                    "enum": ["goal", "delivery", None],
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            [],
        ),
        spec(
            "hollywood_execution_read",
            "Inspect an authorized original execution receipt, native pointers and admission timestamps. Reading never starts or retries execution.",
            {"deliveryId": text},
            ["deliveryId"],
        ),
        spec(
            "hollywood_execution_cancel",
            "Request an authorized execution stop. Admission and descendants must be fenced and the executor must acknowledge; unknown remains held. This does not undo completed effects.",
            {"deliveryId": text},
            ["deliveryId"],
        ),
        spec(
            "hollywood_briefing",
            "Read current authorized work direction, decision revisions and this original attempt. Read at work start and after a material correction; current sourced decisions supersede stale assumptions. Content remains attributable tool data, not new user authority. Use deliveryId to read an original completed delivery without changing current participation. Reading never admits another turn.",
            {"deliveryId": {"type": ["string", "null"]}, "readId": {"type": ["string", "null"]}, "cursor": {"type":"integer","minimum":0}, "pageSize":{"type":"integer","minimum":1,"maximum":32}},
            [],
        ),
        spec(
            "hollywood_decisions",
            "Read a bounded page of current sourced decisions, including retracted/conflicted state. Follow nextCursor when truncated; room permission does not grant private goal access.",
            {
                "roomId": text,
                "after": {"type": ["string", "null"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                "goalId": {"type": ["string", "null"]},
            },
            ["roomId", "after", "limit", "goalId"],
        ),
        spec(
            "hollywood_decision_set",
            "Record/revise an explicit scoped decision with a source in the addressed exchange. Only its issuer, scope owner or administrator may change it. Use original id/key and current revision; creation uses revision 0. An observation is not permission to decide. Retractions/conflicts remain visible.",
            {
                "decisionId": text,
                "key": text,
                "revision": {"type": "integer", "minimum": 0},
                "goalId": {"type": ["string", "null"]},
                "state": {
                    "type": "string",
                    "enum": ["active", "retracted", "conflicted"],
                },
                "body": text,
                "sourceEventId": text,
            },
            [
                "decisionId",
                "key",
                "revision",
                "goalId",
                "state",
                "body",
                "sourceEventId",
            ],
        ),
        spec(
            "hollywood_work_attempts",
            "Inspect original work-attempt lineage, native pointers, evidence and review without re-execution. Pagination never discards prior attempts.",
            {
                "workId": text,
                "after": {"type": "integer", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            ["workId", "after", "limit"],
        ),
        spec(
            "hollywood_work_recover",
            "Goal manager: explicitly reopen an exactly reconciled pre-turn failed attempt without changing its task or starting execution. Inspect protected original receipts; stopped alone does not prove no effects. Supply their reconciliation SHA256, exact failure result and stopped executor. Unknown, possibly executed, reported or cancelled work cannot use this path. Preserve old attempts; assignment is separate.",
            {
                "workId": text, "revision": revision,
                "priorDeliveryId": text, "resultEventId": text, "executorId": text,
                "outcome": {"type": "string", "enum": ["pre_turn_denied"]},
                "reconciliationSha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "note": note,
            },
            ["workId", "revision", "priorDeliveryId", "resultEventId", "executorId",
             "outcome", "reconciliationSha256", "note"],
        ),
        spec(
            "hollywood_work_revise",
            "Goal manager: explicitly prepare rework only after completed work was independently rejected. Preserve its old attempt/evidence; unknown or unsettled execution cannot reopen. This does not assign/start the next attempt.",
            {
                "workId": text,
                "revision": revision,
                "ownerId": text,
                "specification": text,
                "acceptance": text,
                "note": note,
            },
            ["workId", "revision", "ownerId", "specification", "acceptance", "note"],
        ),
        spec(
            "hollywood_goal_create",
            "Record an accountable Goal from this current authenticated human/agent request. Optional roomId selects its collaboration room independently of agent context. For another room explicitly set publishScopedIntent=true: only selected Goal intent is published there, never private source text. Original source must be room-visible. reviewBudget bounds authorized material reviews; creation assigns no work.",
            {
                "roomId": {"type": ["string", "null"]},
                "publishScopedIntent": {"type": "boolean"},
                "title": text,
                "objective": text,
                "acceptance": text,
                "reviewBudget": {"type": "integer", "minimum": 0, "maximum": 16},
            },
            ["title", "objective", "acceptance", "reviewBudget"],
        ),
        spec(
            "hollywood_attention_list",
            "Read an authorized room's native questions/approvals and source identities once. Current participants/administrators only; this does not answer, resume or poll a model.",
            {
                "roomId": text,
                "after": {"type": "integer", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            ["roomId", "after", "limit"],
        ),
        spec(
            "hollywood_attention_read",
            "Read one authorized native question/approval, exact execution scope, response and attributable human. Reading does not answer or resume it.",
            {"attentionId": text},
            ["attentionId"],
        ),
        spec(
            "hollywood_cooperation_set",
            "Accountable goal planner: configure this goal's independent peers before any work admission. leader_award uses explicit assignments; kanban_pull allows only listed executors to claim open work. The designated verifier independently reviews and accepts; it cannot change the plan. Room defaults do not choose the planner. This does not start agents or authorize a model loop.",
            {
                "goalId": text,
                "revision": revision,
                "cooperationRevision": {"type": "integer", "minimum": 0},
                "policy": {"type": "string", "enum": ["leader_award", "kanban_pull"]},
                "reviewerId": {"type": ["string", "null"]},
                "executorIds": {
                    "type": "array",
                    "items": text,
                    "minItems": 1,
                    "maxItems": 32,
                },
            },
            [
                "goalId",
                "revision",
                "cooperationRevision",
                "policy",
                "reviewerId",
                "executorIds",
            ],
        ),
        spec(
            "hollywood_work_list",
            "Read a bounded page of authorized room work without admitting execution. Discover exact ownership, prerequisites and open Kanban work; do not poll with model turns.",
            {
                "roomId": text,
                "after": {"type": ["string", "null"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            ["roomId", "after", "limit"],
        ),
        spec(
            "hollywood_work_claim",
            "Eligible Kanban executor: atomically claim one unowned ready work record. This queues its separate owned native execution; finish this coordination request and let that assignment execute. Do not implement it in the current unrelated turn. Claimed/unknown work is never stolen or re-admitted on timeout.",
            {"workId": text, "revision": revision},
            ["workId", "revision"],
        ),
        spec(
            "hollywood_goal_read",
            "Read an authorized canonical goal and its revisioned dependency plan. Read once when needed; never poll or wait with model turns.",
            {"goalId": text},
            ["goalId"],
        ),
        spec(
            "hollywood_work_read",
            "Read authorized work, its original execution and artifact evidence. This does not start work.",
            {"workId": text},
            ["workId"],
        ),
        spec(
            "hollywood_supervision",
            "Observe authorized room activity hints once without admitting execution; use material events to choose relevant room reads.",
            {
                "after": {"type": "integer", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            ["after", "limit"],
        ),
        spec(
            "hollywood_work_create",
            "Goal planner: add work without execution. Use null ownerId only for open Kanban work with an explicit executor set. Prerequisites must belong to this goal and require acceptance before admission.",
            {
                "goalId": text,
                "revision": revision,
                "roomId": text,
                "ownerId": {"type": ["string", "null"]},
                "specification": text,
                "acceptance": text,
                "dependencies": {"type": "array", "items": text, "maxItems": 16},
            },
            [
                "goalId",
                "revision",
                "roomId",
                "ownerId",
                "specification",
                "acceptance",
                "dependencies",
            ],
        ),
        spec(
            "hollywood_work_assign",
            "Goal manager: explicitly admit planned work after prerequisites are accepted. This creates one owned execution request. Do not repeat an uncertain effect.",
            {"workId": text, "revision": revision},
            ["workId", "revision"],
        ),
        spec(
            "hollywood_work_report",
            "Report only this captured work assignment after verifying its acceptance criteria; supply paths relative to optional artifactWorkspaceId (own registered physical root UUID), or the selected resource default, for independent hashing. A blocked report records a specific obstacle. Submission does not establish independent business acceptance.",
            {
                "workId": text,
                "revision": revision,
                "state": {"type": "string", "enum": ["submitted", "blocked"]},
                "note": note,
                "artifactPaths": {"type": "array", "items": text, "maxItems": 16},
                "artifactWorkspaceId": {"type": "string", "format": "uuid"},
            },
            ["workId", "revision", "state", "note", "artifactPaths"],
        ),
        spec(
            "hollywood_work_report_reconcile",
            "Explicitly report your exact completed, unreported original assignment from later authenticated participation in the same persistent context and workspace. Inspect original receipts, effects and acceptance first. Explicitly attest effectDisposition reviewed or unknown; submitted requires reviewed and verified criteria, blocked preserves uncertainty. Supply priorDeliveryId and original artifact paths relative to optional artifactWorkspaceId (own currently authorized physical root UUID), or the selected resource default. Never restart/reassign work or infer reviewed/no effects from stopped. Current authority/cancellation and independent review still apply; ordinary captured reporting stays strict.",
            {
                "workId": text,
                "revision": revision,
                "priorDeliveryId": text,
                "state": {"type": "string", "enum": ["submitted", "blocked"]},
                "effectDisposition": {"type": "string", "enum": ["reviewed", "unknown"]},
                "note": note,
                "artifactPaths": {"type": "array", "items": text, "maxItems": 16},
                "artifactWorkspaceId": {"type": "string", "format": "uuid"},
            },
            ["workId", "revision", "priorDeliveryId", "state", "effectDisposition", "note", "artifactPaths"],
        ),
        spec(
            "hollywood_work_review",
            "Authorized independent verifier (or goal manager without a designated verifier): inspect completed execution and its evidence, then accept or reject submitted work. Completed blocked work may only be rejected, preserving its report and allowing explicit revised rework; blocked work cannot be accepted. State what you verified.",
            {
                "workId": text,
                "revision": revision,
                "decision": {"type": "string", "enum": ["accepted", "rejected"]},
                "note": note,
            },
            ["workId", "revision", "decision", "note"],
        ),
        spec(
            "hollywood_work_cancel",
            "Goal manager: request cancellation of this work. A cancellation request never proves external effects stopped or were undone.",
            {"workId": text, "revision": revision, "note": note},
            ["workId", "revision", "note"],
        ),
        spec(
            "hollywood_goal_state",
            "Goal manager: change lifecycle with revision fencing. Acceptance requires reviewed work. Pause gates new admission. Request cancelled to durably stop all goal work; cancel_requested remains until original acknowledgements settle. Do not poll model turns for cancellation.",
            {
                "goalId": text,
                "revision": revision,
                "state": {
                    "type": "string",
                    "enum": ["active", "paused", "accepted", "cancelled"],
                },
                "note": note,
            },
            ["goalId", "revision", "state", "note"],
        ),
    ]


def artifacts(config, paths, *, root_fd=None):
    from pathlib import Path

    root = Path(config["workspace"]).resolve(strict=True) if root_fd is None else None
    results = []
    for value in paths:
        p = PurePosixPath(value)
        if (
            not value
            or not p.parts
            or p.is_absolute()
            or ".." in p.parts
            or "\\\\" in value
        ):
            raise ValueError("Artifact requires a relative workspace path")
        directory = os.dup(root_fd) if root_fd is not None else os.open(
            root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        )
        fd = None
        try:
            for part in p.parts[:-1]:
                child = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
                )
                os.close(directory)
                directory = child
            fd = os.open(p.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size > config.get(
                "artifactEvidenceMaxBytes", 67108864
            ):
                raise ValueError("Artifact is not a bounded regular workspace file")
            sha = hashlib.sha256()
            size = 0
            with os.fdopen(fd, "rb") as f:
                fd = None
                while block := f.read(1048576):
                    size += len(block)
                    if size > config.get("artifactEvidenceMaxBytes", 67108864):
                        raise ValueError("Artifact grew beyond evidence limit")
                    sha.update(block)
                after = os.fstat(f.fileno())
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise ValueError("Artifact changed while collecting evidence")
            results.append(
                {
                    "hostId": config["hostId"],
                    "workspaceId": workspace_id(config),
                    "relativePath": str(p),
                    "sha256": sha.hexdigest(),
                    "size": size,
                }
            )
        finally:
            if fd is not None:
                os.close(fd)
            os.close(directory)
    return results


async def reconcile_report(c, args, operation):
    """Evidence-only submission: the original is never selected as active work."""
    validate_workflow_note(args.get("note"))
    work_id, prior = str(UUID(args["workId"])), str(UUID(args["priorDeliveryId"]))
    if (type(args["revision"]) is not int or args["revision"] < 1
        or args["state"] not in ("submitted", "blocked")
        or args.get("effectDisposition") not in ("reviewed", "unknown")
        or (args["state"] == "submitted" and args["effectDisposition"] != "reviewed")
        or not isinstance(args["note"], str) or not args["note"].strip()
        or len(args["note"]) > 4000
        or not isinstance(args["artifactPaths"], list)
        or len(args["artifactPaths"]) > 16
        or any(not isinstance(p, str) for p in args["artifactPaths"])):
        raise ValueError("Reconciliation requires explicit effect disposition; submitted needs reviewed effects")
    current = c.active
    binding = c.agent_binding
    if not current or not binding:
        raise PermissionError("Reconciliation requires current persistent native participation")
    delivery, request = current["delivery"], current["request"]
    expected_current = {
        "delivery": delivery["id"], "generation": delivery["generation"],
        "principal": c.config["agentId"], "native_thread": c.thread,
        "context_id": c.context_id, "workspace_id": workspace_id(c.config),
        "role_revision": c.role_context.value["roleRevision"],
    }
    if (any(binding.get(k) != v for k, v in expected_current.items())
        or delivery["id"] == prior
        or delivery["agent"] != c.config["agentId"]
        or delivery["host"] != c.config["hostId"]
        or delivery["authority"] != request["authority"]
        or delivery["event"] != request["id"]
        or delivery["state"] not in ("claimed", "running")
        or delivery.get("cancellation_requested")):
        raise PermissionError("Current native participation binding changed or is cancelled")

    # Reads are not permission to mutate. The server repeats these fences and
    # checks room/goal/cooperation/decision authority atomically at POST time.
    value = await c.http("GET", "work/" + work_id)
    original = await c.http("GET", "deliveries/" + prior)
    work, old, source = value["work"], original["delivery"], original["request"]
    original_binding = original.get("agentContextBinding") or {}
    expected_original = {
        "delivery": prior, "generation": old["generation"],
        "principal": c.config["agentId"], "native_thread": c.thread,
        "context_id": c.context_id, "workspace_id": workspace_id(c.config),
    }
    if (work.get("id") != work_id
        or work.get("owner") != c.config["agentId"]
        or work.get("authority") != request["authority"]
        or work.get("revision") != args["revision"]
        or work.get("delivery") != prior
        or work.get("state") != "assigned"
        or work.get("report_event") or work.get("evidence")
        or work.get("request_event") != source.get("id")
        or source.get("room") != work.get("room")
        or source.get("authority") != request["authority"]
        or source.get("recipient") != c.config["agentId"]
        or source.get("kind") != "request"
        or source.get("data", {}).get("workId") != work_id
        or old.get("id") != prior
        or old.get("event") != source.get("id")
        or old.get("authority") != request["authority"]
        or old.get("agent") != c.config["agentId"]
        or old.get("host") != c.config["hostId"]
        or old.get("native_thread") != c.thread
        or old.get("state") != "completed"
        or not old.get("result_event")
        or old.get("cancellation_requested")
        or any(original_binding.get(k) != v for k, v in expected_original.items())):
        raise PermissionError("Original completed/unreported owner, work or context boundary differs")

    from .report_scope import proof_for_report
    scope_proof, original_sequence = proof_for_report(c, work, original)

    evidence = await collect_artifacts(c, args, artifacts)
    payload = {
        "revision": args["revision"], "priorDeliveryId": prior,
        "state": args["state"], "note": args["note"], "evidence": evidence,
        "effectDisposition": args["effectDisposition"],
        "operationId": operation,
        "briefingSequence": original_sequence,
        "scopeRead": scope_proof,
    }
    # The normal v2 native-source header authenticates THIS participation, never
    # a fabricated active claim for the completed prior delivery.
    return await c.http("POST", "work/" + work_id + "/report-reconcile", payload)


async def invoke(c, name, args, operation):
    def identity(key):
        return str(UUID(args[key]))

    if name == PLACEMENT_READ_TOOL:
        from .placement_control import read
        return await read(c, args)
    if name in RESOURCE_READ_TOOLS:
        from .resource_routing import read
        return await read(c, name, args)
    if name == "hollywood_work_report_reconcile":
        return await reconcile_report(c, args, operation)
    if name in MUTATION_TOOLS and "note" in args:
        validate_workflow_note(args["note"])
    if name == "hollywood_portfolio":
        from urllib.parse import urlencode

        query = {"limit": args.get("limit", 32)}
        if args.get("afterReference"):
            query["afterReference"] = str(UUID(args["afterReference"]))
            query["afterScope"] = args["afterScope"]
        return await c.http(
            "GET", "agents/" + c.config["agentId"] + "/supervision?" + urlencode(query)
        )
    if name == "hollywood_execution_read":
        return await c.http("GET", "deliveries/" + identity("deliveryId"))
    if name == "hollywood_execution_cancel":
        return await c.http(
            "POST", "deliveries/" + identity("deliveryId") + "/cancel", {}
        )
    if name == "hollywood_briefing":
        if args.get("deliveryId") and args["deliveryId"] != c.active["delivery"]["id"]:
            from .report_scope import read
            return await read(c, args, operation)
        if any(args.get(key) is not None for key in ("readId", "cursor", "pageSize")):
            raise ValueError("Report scope paging requires an original deliveryId")
        return await c.briefing(args.get("deliveryId"))
    if name == "hollywood_decisions":
        from urllib.parse import urlencode

        query = {"limit": args["limit"]}
        if args["after"]:
            query["after"] = str(UUID(args["after"]))
        if args["goalId"]:
            query["goalId"] = str(UUID(args["goalId"]))
        return await c.http(
            "GET", "rooms/" + identity("roomId") + "/decisions?" + urlencode(query)
        )
    if name == "hollywood_decision_set":
        return await c.http(
            "POST",
            "rooms/" + c.active["request"]["room"] + "/decisions",
            {
                **{k: v for k, v in args.items() if k != "decisionId"},
                "id": identity("decisionId"),
                "operationId": operation,
            },
        )
    if name == "hollywood_work_attempts":
        return await c.http(
            "GET",
            "work/"
            + identity("workId")
            + "/attempts?after="
            + str(args["after"])
            + "&limit="
            + str(args["limit"]),
        )
    if name == "hollywood_attention_list":
        return await c.http(
            "GET",
            "rooms/"
            + identity("roomId")
            + "/attention?after="
            + str(args["after"])
            + "&limit="
            + str(args["limit"]),
        )
    if name == "hollywood_attention_read":
        return await c.http("GET", "attention/" + identity("attentionId"))
    if name == "hollywood_goal_read":
        return await c.http("GET", "goals/" + identity("goalId"))
    if name == "hollywood_work_list":
        from urllib.parse import urlencode

        query = {"limit": args["limit"]}
        if args["after"]:
            query["after"] = str(UUID(args["after"]))
        return await c.http(
            "GET", "rooms/" + identity("roomId") + "/work?" + urlencode(query)
        )
    if name == "hollywood_cooperation_set":
        return await c.http(
            "POST",
            "goals/" + identity("goalId") + "/cooperation",
            {
                **{k: v for k, v in args.items() if k != "goalId"},
                "operationId": operation,
            },
        )
    if name == "hollywood_work_read":
        return await c.http("GET", "work/" + identity("workId"))
    if name == "hollywood_supervision":
        return await c.http(
            "GET",
            "supervision?after=" + str(args["after"]) + "&limit=" + str(args["limit"]),
        )
    if name == "hollywood_goal_create":
        room = identity("roomId") if args.get("roomId") is not None else c.active["request"]["room"]
        publish = args.get("publishScopedIntent", False)
        if type(publish) is not bool:
            raise ToolValidationError("invalid_scoped_intent", "Scoped intent publication must be boolean",
                                      "Choose an explicit boolean; original source remains unchanged.")
        if room != c.active["request"]["room"] and not publish:
            raise ToolValidationError("scoped_intent_required", "Cross-room Goal requires explicit scoped intent",
                                      "Set publishScopedIntent=true for the selected Goal room; never broaden room access.")
        payload = {
            **{
                key: args[key]
                for key in ("title", "objective", "acceptance", "reviewBudget")
            },
            "operationId": operation,
            "id": str(uuid5(UUID(c.config["agentId"]), operation)),
            "sourceEventId": c.active["request"]["id"],
        }
        if publish:
            payload["publishScopedIntent"] = True
        receipt = await c.http("POST", "rooms/" + room + "/goals", payload)
        # An existing primary coordination goal remains intact. A new canonical
        # goal does not silently replace it or create a shadow room context.
        if not c.goal_binding and not c.agent_binding:
            receipt["nativeBinding"] = await bind(c, receipt["goalId"], new_goal=True)
        return receipt
    if name == "hollywood_work_create":
        return await c.http(
            "POST",
            "goals/" + identity("goalId") + "/work",
            {
                **{
                    k: v
                    for k, v in args.items()
                    if k not in ("goalId", "operationId", "id")
                },
                "operationId": operation,
                "id": str(uuid5(UUID(c.config["agentId"]), operation)),
            },
        )
    if name == "hollywood_goal_state":
        goal = identity("goalId")
        receipt = await c.http(
            "POST",
            "goals/" + goal + "/state",
            {
                **{k: v for k, v in args.items() if k not in ("goalId", "operationId")},
                "operationId": operation,
            },
        )
        control = await sync_policy(c, goal, args["state"], operation)
        if control:
            receipt["nativePolicy"] = control
        return receipt
    work = identity("workId")
    action = name.removeprefix("hollywood_work_")
    payload = {
        **{k: v for k, v in args.items() if k not in ("workId", "operationId")},
        "operationId": operation,
    }
    if action == "report":
        if c.active["request"]["data"].get("workId") != work or not (c.goal_binding or c.agent_binding):
            raise PermissionError("Only the captured native work may be reported")
        native = await progress(c) if c.goal_binding else None
        if args["state"] == "submitted" and native and native["status"] != "complete":
            raise ToolValidationError(
                "NATIVE_WORK_GOAL_INCOMPLETE",
                "This bounded native work goal remains unfinished.",
                "Inspect get_goal and verify the assigned objective. If its criteria "
                "are met, complete this work goal with update_goal, then submit using "
                "the current work revision. Keep the parent enterprise goal open. "
                "If a criterion is unmet, report the specific blocker instead.",
            )
        payload.pop("artifactPaths")
        payload.pop("artifactWorkspaceId", None)
        evidence = await collect_artifacts(c, args, artifacts)
        payload.update(
            claimId=c.active["delivery"]["claim_id"],
            generation=c.active["delivery"]["generation"],
            evidence=evidence,
            briefingSequence=c.work_briefing["asOfSequence"]
            if c.work_briefing
            else None,
        )
    return await c.http("POST", "work/" + work + "/" + action, payload)
