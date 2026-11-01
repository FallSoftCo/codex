"""Initial native authorization belongs to the durable Codex thread settings.

A thread/start response is not proof that an empty context's overrides survived
closing its provisioning process. Persist them through the supported native
settings API before declaring a new context ready. Ordinary resumes do not
reassert installation defaults or overwrite later owner restrictions.
"""

SANDBOX_TYPES = {
    "danger-full-access": "dangerFullAccess",
    "workspace-write": "workspaceWrite",
    "read-only": "readOnly",
}
APPROVAL_POLICIES = {"never", "untrusted", "on-request", "on-failure"}


def requested(config):
    sandbox = config.get("sandbox")
    approval = config.get("approvalPolicy", "never")
    if (
        sandbox not in SANDBOX_TYPES
        or not isinstance(approval, str)
        or approval not in APPROVAL_POLICIES
    ):
        raise ValueError(
            "Supported installation-owned initial native permission policy required"
        )
    return {"sandbox": sandbox, "approvalPolicy": approval}


def observed(response):
    value = {
        "sandbox": response.get("sandbox"),
        "approvalPolicy": response.get("approvalPolicy"),
    }
    if (
        not isinstance(value["sandbox"], dict)
        or not isinstance(value["sandbox"].get("type"), str)
        or not isinstance(value["approvalPolicy"], (str, dict))
    ):
        raise ValueError("Native effective permission metadata unavailable")
    return value


def verified(response, request):
    actual = observed(response)
    if (
        actual["sandbox"]["type"] != SANDBOX_TYPES[request["sandbox"]]
        or actual["approvalPolicy"] != request["approvalPolicy"]
    ):
        raise PermissionError(
            "Native effective policy differs from approved initial provisioning"
        )
    return actual


async def persist_new_thread(rpc, thread, response, config):
    actual = verified(response, requested(config))
    settings = {
        "threadId": thread,
        "approvalPolicy": actual["approvalPolicy"],
        "sandboxPolicy": actual["sandbox"],
    }
    # Creation-time config overrides are not durable thread preferences. Persist
    # only explicit initial choices here; ordinary resumes must preserve later
    # user changes instead of reasserting installation defaults.
    for key in ("model", "effort"):
        if key in config:
            if not isinstance(config[key], str) or not config[key].strip():
                raise ValueError("Explicit initial native model/effort must be nonempty")
            settings[key] = config[key]
    await rpc.call("thread/settings/update", settings)
    return actual
