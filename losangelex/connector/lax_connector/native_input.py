"""Translate an authenticated Hollywood delivery into the native LAX input API.

This module consumes the original server event. It neither rewrites its author
nor constructs a function-call output to stand in for peer communication.
"""

from uuid import UUID


def submission(agent_id, active, thread_id, model, effort, additional_context):
    request, delivery = active["request"], active["delivery"]
    recipient = str(UUID(agent_id))
    if str(UUID(delivery["agent"])) != recipient:
        raise ValueError("Hollywood delivery belongs to another agent")
    if str(UUID(request["recipient"])) != recipient:
        raise ValueError("Hollywood event and delivery recipients differ")
    author = str(UUID(request["author"]))
    event = str(UUID(request["id"]))
    authority = str(UUID(request["authority"]))
    if str(UUID(delivery["event"])) != event:
        raise ValueError("Hollywood delivery and source event differ")
    if str(UUID(delivery["authority"])) != authority:
        raise ValueError("Hollywood delivery and source authority differ")
    kind = request["data"].get("authorKind")
    if kind == "human":
        return "turn/start", {
            "threadId": thread_id,
            "model": model,
            "effort": effort,
            "input": [{"type": "text", "text": request["body"]}],
            "clientUserMessageId": "hollywood-v3-" + event,
            "additionalContext": additional_context,
        }
    if kind != "agent":
        raise ValueError("Unsupported Hollywood author kind for conversational input")
    # The server rejects arbitrary self-requests, but admits bounded, sourced
    # work-review events for the owner. Preserve that canonical author too.
    return "hollywood/agentMessage", {
        "threadId": thread_id,
        "authorityId": authority,
        "roomId": str(UUID(request["room"])),
        "eventId": event,
        "authorId": author,
        "recipientId": recipient,
        "body": request["body"],
        "audience": request["audience"],
        "kind": request["kind"],
        "sourceEventId": str(UUID(request["source"])) if request.get("source") else None,
        "expectsReply": request["data"].get("expectsReply", False),
    }
