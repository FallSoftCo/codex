"""Project an observed native terminal state without promoting commentary."""


def terminal_body(status, items, publications=()):
    if status == "cancelled":
        return "Execution stopped."
    if status == "failed":
        return "Execution failed. Review the recorded activity before retrying."
    if status != "completed":
        raise ValueError("Only an observed native terminal state has a terminal reply")
    messages = [
        item for item in items
        if item.get("type") == "agentMessage" and item.get("text")
        and item.get("delivery") is None
    ]
    final = [item for item in messages if item.get("phase") == "final_answer"]
    unphased = [item for item in messages if item.get("phase") is None]
    if final or unphased:
        return (final or unphased)[-1]["text"]
    if publications:
        return "Execution ended; replies are recorded in this conversation."
    return "Execution ended without a final reply."
