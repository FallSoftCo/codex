"""Native discovery, protected observation and explicit review of held file edits."""

from .tool_execution import participation
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

from .collaboration_bridge import require, digest

READ_TOOL = "hollywood_mutation_read"
ADMIN_TOOLS = {"hollywood_mutation_observe", "hollywood_mutation_reconcile"}


def view(result):
    """Keep complete receipts private; inject one bounded status/manifest view."""
    receipt = result.get("receipt", result)
    permit = receipt["permit"]
    proof, source = permit["proof"], permit["source"]
    observation = permit.get("observation") or {}
    settlement = permit.get("settlement") or {}
    observed = {f["relativePath"]: f for f in observation.get("filesObserved", [])}
    value = {
        "schema": "lax-mutation-view/v1", "scope": "delivery",
        "permitId": permit["id"], "permitRevision": permit["revision"],
        "state": permit["state"], "effectiveState": result.get("effectiveState", permit["state"]),
        "mayApply": False, "newExecutionAdmitted": False,
        "receiptEventId": receipt.get("eventId"), "replayed": result.get("replayed", False),
        "source": {k: source[k] for k in ("agentId", "hostId", "requestId", "deliveryId", "callId")},
        "workspaceId": proof["workspaceId"], "patchSha256": proof["patchSha256"],
        "fileManifestSha256": digest(proof["files"]), "fileCount": len(proof["files"]),
        "files": [{**f, **({"observedSha256": observed[f["relativePath"]]["sha256"],
                           "observedSize": observed[f["relativePath"]]["size"]}
                          if f["relativePath"] in observed else {})}
                  for f in proof["files"]],
        "observation": {k: observation[k] for k in
                        ("outcome", "observedAt", "controllerId", "executorId")
                        if k in observation},
        "observationDigest": receipt.get("observationDigest") or
                             (digest(observation) if observation else None),
        "settlement": {k: settlement[k] for k in
                       ("outcome", "holds", "effectDisposition", "classification",
                        "observationDigest", "externalEffectsUndone", "reconciliationOnly")
                       if k in settlement},
        "originalOutcome": (settlement.get("originalSettlement") or settlement).get("outcome"),
    }
    # Large literal path sets remain in the full canonical receipt. This view
    # never truncates JSON or drops an accepted effect/receipt identity.
    if len(json.dumps(value).encode()) > 8192:
        value["files"] = []
        value["filesOmitted"] = True
    require(len(json.dumps(value).encode()) <= 8192, "Mutation view exceeds context bound")
    return value


def definitions(spec):
    text = {"type": "string"}
    revision = {"type": "integer", "minimum": 1}
    return [
        spec(READ_TOOL,
             "Read an original ordinary file-mutation permit and its held/stopped observation. Owner or administrator only; reading never applies or releases a mutation.",
             {"permitId": text}, ["permitId"]),
        spec("hollywood_mutation_observe",
             "Verified host administrator: independently inspect the stopped original executor and exact registered files. Records evidence only; a live/unknown executor refuses. No edit, replay or lock release.",
             {"permitId": text, "permitRevision": revision, "note": text},
             ["permitId", "permitRevision", "note"]),
        spec("hollywood_mutation_reconcile",
             "Administrator: explicitly review an original held ordinary mutation against its exact protected stopped observation. Applied requires all after-content, notApplied all before-content. Unknown/mixed remains held. Releases only original locks, preserves failed settlement, starts no work and does not undo effects.",
             {"permitId": text, "permitRevision": revision, "observationDigest": text,
              "outcome": {"type": "string", "enum": ["applied", "notApplied"]}, "note": text},
             ["permitId", "permitRevision", "observationDigest", "outcome", "note"]),
    ]


async def administer(c, name, args, operation):
    require(c.role_context.value["communicationAdministrator"], "Administrator required")
    identity = str(UUID(args["permitId"]))
    if name == "hollywood_mutation_reconcile":
        return view(await c.http("POST", "collaboration/delivery-edits/" + identity + "/reconcile",
                                 {"operationId": operation + ":admin:mutation-reconcile",
                                  "effectDisposition": "reviewed",
                                  **{k: args[k] for k in
                                     ("permitRevision", "observationDigest", "outcome", "note")}}))
    require(name == "hollywood_mutation_observe"
            and c.role_context.value["hostAdministrationVerified"],
            "Verified local host administrator required for physical observation")
    # Installation paths belong to the selected host. No remote filesystem is inferred.
    authority = str(UUID(participation(c)["request"]["authority"]))
    host = str(UUID(c.config["hostId"]))
    config = (Path("/var/lib/harness") / authority / "hosts" / host /
              "native-collaboration/bridge.json")
    process = await asyncio.create_subprocess_exec(
        "sudo", "-n", sys.executable, "-m", "lax_connector.mutation_recovery",
        "--config", str(config), "--permit-id", identity,
        "--permit-revision", str(args["permitRevision"]),
        "--operation-id", operation + ":observe", "--note", args["note"],
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, _ = await process.communicate()
    require(process.returncode == 0,
            "Protected original observation failed/unconfirmed; inspect the original permit/operation; never repeat a mutation")
    return view(json.loads(stdout))
