"""Role-scoped Hollywood work tools and independently hashed artifact evidence."""

import hashlib
import os
import stat
from pathlib import PurePosixPath
from uuid import UUID, uuid5

from .native_goals import bind, progress, workspace_id

READ_TOOLS = {"hollywood_goal_read", "hollywood_work_read", "hollywood_supervision"}
MUTATION_TOOLS = {
    "hollywood_goal_create",
    "hollywood_work_create",
    "hollywood_work_assign",
    "hollywood_work_report",
    "hollywood_work_review",
    "hollywood_work_cancel",
    "hollywood_goal_state",
}


def definitions(spec):
    text = {"type": "string"}
    revision = {"type": "integer", "minimum": 1}
    return [
        spec(
            "hollywood_goal_create",
            "Record an explicitly authorized room goal and acceptance criteria. reviewBudget is the finite number of material worker reviews authorized by this request; use zero without authorization. Creation does not assign work.",
            {
                "title": text,
                "objective": text,
                "acceptance": text,
                "reviewBudget": {"type": "integer", "minimum": 0, "maximum": 16},
            },
            ["title", "objective", "acceptance", "reviewBudget"],
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
            "Goal manager: add accountable work to the plan without execution. Prerequisites must belong to this goal and will require acceptance before admission.",
            {
                "goalId": text,
                "revision": revision,
                "roomId": text,
                "ownerId": text,
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
            "Report only this captured work assignment. For submitted work, complete its native goal only after meeting its criteria; supply relative artifact paths for independent connector hashing. A blocked report records a specific obstacle. This is not business acceptance.",
            {
                "workId": text,
                "revision": revision,
                "state": {"type": "string", "enum": ["submitted", "blocked"]},
                "note": text,
                "artifactPaths": {"type": "array", "items": text, "maxItems": 16},
            },
            ["workId", "revision", "state", "note", "artifactPaths"],
        ),
        spec(
            "hollywood_work_review",
            "Goal manager: accept or reject submitted work only after execution completes and you independently inspect the artifact evidence against its criteria. State what you verified.",
            {
                "workId": text,
                "revision": revision,
                "decision": {"type": "string", "enum": ["accepted", "rejected"]},
                "note": text,
            },
            ["workId", "revision", "decision", "note"],
        ),
        spec(
            "hollywood_work_cancel",
            "Goal manager: request cancellation of this work. A cancellation request never proves external effects stopped or were undone.",
            {"workId": text, "revision": revision, "note": text},
            ["workId", "revision", "note"],
        ),
        spec(
            "hollywood_goal_state",
            "Goal manager: change the canonical goal lifecycle with revision fencing. Acceptance requires all work accepted and a concrete review. Pause gates new admission; it does not interrupt active effects.",
            {
                "goalId": text,
                "revision": revision,
                "state": {
                    "type": "string",
                    "enum": ["active", "paused", "accepted", "cancelled"],
                },
                "note": text,
            },
            ["goalId", "revision", "state", "note"],
        ),
    ]


def artifacts(config, paths):
    from pathlib import Path

    root = Path(config["workspace"]).resolve(strict=True)
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
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fd = None
        try:
            for part in p.parts[:-1]:
                child = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
                )
                os.close(directory)
                directory = child
            fd = os.open(p.parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
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
            if (before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
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


async def invoke(c, name, args, operation):
    def identity(key):
        return str(UUID(args[key]))

    if name == "hollywood_goal_read":
        return await c.http("GET", "goals/" + identity("goalId"))
    if name == "hollywood_work_read":
        return await c.http("GET", "work/" + identity("workId"))
    if name == "hollywood_supervision":
        return await c.http(
            "GET",
            "supervision?after=" + str(args["after"]) + "&limit=" + str(args["limit"]),
        )
    if name == "hollywood_goal_create":
        payload = {
            **{
                key: args[key]
                for key in ("title", "objective", "acceptance", "reviewBudget")
            },
            "operationId": operation,
            "id": str(uuid5(UUID(c.config["agentId"]), operation)),
            "sourceEventId": c.active["request"]["id"],
        }
        receipt = await c.http(
            "POST", "rooms/" + c.active["request"]["room"] + "/goals", payload
        )
        # An existing primary coordination goal remains intact. A new canonical
        # goal does not silently replace it or create a shadow room context.
        if not c.goal_binding:
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
        return await c.http(
            "POST",
            "goals/" + identity("goalId") + "/state",
            {
                **{k: v for k, v in args.items() if k not in ("goalId", "operationId")},
                "operationId": operation,
            },
        )
    work = identity("workId")
    action = name.removeprefix("hollywood_work_")
    payload = {
        **{k: v for k, v in args.items() if k not in ("workId", "operationId")},
        "operationId": operation,
    }
    if action == "report":
        if c.active["request"]["data"].get("workId") != work or not c.goal_binding:
            raise PermissionError("Only the captured native work may be reported")
        native = await progress(c)
        if args["state"] == "submitted" and native["status"] != "complete":
            raise ValueError(
                "Native goal remains unfinished; complete it only after verifying its objective"
            )
        payload.pop("artifactPaths")
        try:
            evidence = artifacts(c.config, args["artifactPaths"])
        except OSError as error:
            raise ValueError(
                "Artifact is unavailable or outside the allowed file boundary"
            ) from error
        payload.update(
            claimId=c.active["delivery"]["claim_id"],
            generation=c.active["delivery"]["generation"],
            evidence=evidence,
        )
    return await c.http("POST", "work/" + work + "/" + action, payload)
