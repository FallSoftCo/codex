"""Native discovery, protected observation and explicit review of held file edits."""
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

from .collaboration_bridge import require

READ_TOOL = "hollywood_mutation_read"
ADMIN_TOOLS = {"hollywood_mutation_observe", "hollywood_mutation_reconcile"}


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
        return await c.http("POST", "collaboration/delivery-edits/" + identity + "/reconcile",
                            {"operationId": operation + ":admin:mutation-reconcile",
                             "effectDisposition": "reviewed",
                             **{k: args[k] for k in
                                ("permitRevision", "observationDigest", "outcome", "note")}})
    require(name == "hollywood_mutation_observe"
            and c.role_context.value["hostAdministrationVerified"],
            "Verified local host administrator required for physical observation")
    # Installation paths belong to the selected host. No remote filesystem is inferred.
    authority = str(UUID(c.active["request"]["authority"]))
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
    return json.loads(stdout)
