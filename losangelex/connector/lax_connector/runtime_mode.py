"""Select the existing single-context connector without converting histories.

Purpose-separated installations retain their explicit entrypoint and state.
This check runs before any connector lock, queue admission or native process.
"""


def require_single_context(config):
    mode = config.get("runtimeMode", "single-context")
    if mode != "single-context":
        raise ValueError("This connector requires runtimeMode single-context")
    if any(key in config for key in ("homes", "tokens", "installedPurposeRuntime")):
        raise ValueError(
            "Purpose-separated configuration requires its original runtime; "
            "explicit history adoption is required before single-context execution"
        )
    return mode


def require_worker_context(config):
    """Explicit worker installation modes; never adopt a purpose history."""
    if config.get("runtimeMode", "single-context") != "room-conversation":
        return require_single_context(config)
    if any(key in config for key in ("homes", "tokens", "installedPurposeRuntime")):
        raise ValueError("Conversational provisioning cannot adopt purpose contexts")
    if not isinstance(config.get("nativeName"), str) or not config["nativeName"].strip():
        raise ValueError("Meaningful resident agent name required")
    if not isinstance(config.get("purpose"), str) or not config["purpose"].strip():
        raise ValueError("Explicit resident agent responsibility required")
    rooms=config.get("rooms")
    if not isinstance(rooms,list) or not rooms:
        raise ValueError("Explicit initial room receive boundaries required")
    from uuid import UUID
    seen=set()
    for room in rooms:
        if not isinstance(room,dict) or set(room)!={"roomId","after"}:
            raise ValueError("Room identity and exact initial cursor required")
        identity=str(UUID(room["roomId"]))
        if identity in seen or type(room["after"]) is not int or not 0<=room["after"]<=9007199254740991:
            raise ValueError("Invalid or duplicate room receive boundary")
        seen.add(identity)
    return "room-conversation"
