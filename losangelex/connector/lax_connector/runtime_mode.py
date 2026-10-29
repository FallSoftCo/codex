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
