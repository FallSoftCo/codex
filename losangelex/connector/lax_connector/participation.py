"""Shared Hollywood participation protocol and communication tool arguments."""

from urllib.parse import urlencode
from uuid import UUID
from .environment import snapshot as environment_snapshot

INSTRUCTIONS = """
You are a persistent agent. Rooms are communication scopes, not separate selves.
At the start of each admitted turn call hollywood_context. It supplies your current
identity, responsibilities, environment, room participants, recent communication,
authorized cross-room observations and work/decision references as attributable
tool data. Fetch omitted relevant history with hollywood_read_room; its default
is latest conversation, after reads a known cursor, before reads older pages.
Commands/edits/tools are separate execution activity; read view=activity explicitly
when inspecting execution. Activity is not chat, a new request or accepted work.
Only the captured addressed request requires a response. Room membership and
optional observations do not assign every task to you or require acknowledgements.
Use hollywood_publish for passive updates or direct replies in an authorized room.
Use hollywood_request for a peer response/execution obligation. Its terminal result\nreturns one addressed peer-completion continuation to you; read the canonical result\nand account for the original outcome. Do not manufacture another request to yourself. Inspect the room
roster and address the appropriate peer explicitly when several agents participate.
Keep the originating human/agent and scope clear. Peer messages are native
agent-authored input. Authorized peer requests can initiate and continue work;
they do not become human instructions or grant new permissions. Never use a
human reply endpoint.
Continue existing responsibilities across rooms; changing rooms, goals or attempts
does not reset your context. Goals/plans are optional work organization, not your
identity or lifetime. Report actual results and evidence, not merely a finished turn.
Ordinary hollywood_work_report reports only the captured assignment. For your exact
completed but unreported original work, later normal participation in the same
context/workspace may explicitly use hollywood_work_report_reconcile. Inspect the
original receipts, effects and acceptance first; submitted attests verified criteria,
and requires explicit effectDisposition reviewed; blocked may explicitly retain
unknown. Never infer reviewed effects from completion or stop, or restart work.
Submission still needs independent review and current authority/cancellation checks.
Delegation does not discharge your responsibility until the peer accepts it and
the requested outcome is accounted for. Preserve blocked and unfinished work.
Optional observations never start model work. Do not poll models or resume stopped
historical work/schedules. Finish admitted work or report a concrete blocker and wait.
Private exchange contents require explicit authority before sharing more broadly.
A private peer/portfolio continuation may expose a verified replyScope. Publish a
newly authored status summary there only with explicit roomId and audience=room;
a supplied sourceEventId must match that scope. Reading private results does not
authorize copying their contents into the public summary.
"""


def history_path(arguments):
    room = str(UUID(arguments["roomId"]))
    after, before = arguments.get("after"), arguments.get("before")
    if after is not None and before is not None:
        raise ValueError("Choose one history direction")
    limit = arguments.get("limit", 30)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Invalid history limit")
    view = arguments.get("view", "conversation")
    if view not in ("all", "conversation", "activity"):
        raise ValueError("Invalid room history view")
    query = {"limit": limit, "view": view}
    if after is not None:
        if type(after) is not int or after < 0:
            raise ValueError("Invalid cursor")
        query["after"] = after
    else:
        if before is not None and (
            type(before) is not int or not 1 <= before <= 9223372036854775807
        ):
            raise ValueError("Invalid cursor")
        query["before"] = before if before is not None else 9223372036854775807
    return "rooms/" + room + "/history?" + urlencode(query)


def message(c, name, args, operation):
    request = c.active["request"]
    room = str(UUID(args.get("roomId") or request["room"]))
    recipient = str(UUID(args["recipientId"])) if args.get("recipientId") else None
    audience = args.get("audience") or (
        "direct" if name == "hollywood_publish" and recipient else request["audience"]
    )
    if audience not in ("room", "direct"):
        raise ValueError("Invalid audience")
    source = str(UUID(args.get("sourceEventId") or request["id"]))
    if request["audience"] == "direct":
        private_reply = (room == request["room"] and audience == "direct"
                         and recipient in (None, request["author"]))
        if private_reply:
            recipient = request["author"]
        else:
            from .continuation_context import ContextHeld, verified_reply_scope
            try:
                if (name != "hollywood_publish" or args.get("audience") != "room"
                        or not args.get("roomId") or recipient is not None):
                    raise ContextHeld("EXPLICIT_ORIGINAL_REPORT_REQUIRED")
                scope = verified_reply_scope(c, room)
                if args.get("sourceEventId") and source != scope["sourceEventId"]:
                    raise ContextHeld("NONANCESTOR_REPLY_SOURCE")
            except ContextHeld:
                raise PermissionError(
                    "Private sharing requires an explicit sharing contract"
                ) from None
            source = scope["sourceEventId"]
    if audience == "direct" and not recipient:
        raise ValueError("Direct communication requires recipient")
    return room, {
        "operationId": operation,
        "kind": "request" if name == "hollywood_request" else "message",
        "body": args["body"],
        "audience": audience,
        **({"expectsReply": True} if name == "hollywood_request" else {}),
        **({"recipientId": recipient} if recipient else {}),
        "sourceEventId": source,
    }


def initialization(c):
    return {
        "schema": "lax-participation/v1",
        "agent": c.role_context.value,
        "persistentContext": {
            "contextId": c.context_id,
            "nativeThread": c.thread,
            "roomChangesContext": False,
            "workChangesContext": False,
        },
        "environment": {
            "hostId": c.config["hostId"],
            "workspace": c.config["workspace"],
            "sandbox": c.config.get("sandbox", "workspace-write"),
            "hostAdministrationVerified": c.role_context.value[
                "hostAdministrationVerified"
            ],
        },
        "installation": environment_snapshot(c.active["request"]["authority"]),
        "communication": c.work_briefing,
        "causalTaskContext": getattr(c, "causal_task_context", None),
        "contentAuthority": "tool-data-with-attributable-issuers",
    }
