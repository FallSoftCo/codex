"""Fail-closed native startup tool ceiling; no prompt-only substitute."""

import unicodedata


class NativeToolPolicyUnavailable(RuntimeError):
    pass


def normalized(value):
    if not isinstance(value, dict) or set(value) != {"allowedTools"}:
        raise ValueError("nativeToolPolicy requires only allowedTools")
    tools = value["allowedTools"]
    if not isinstance(tools, list) or len(tools) > 512:
        raise ValueError("Native tool allowlist must contain at most 512 names")
    result = set()
    for tool in tools:
        if (
            not isinstance(tool, dict)
            or set(tool) - {"name", "namespace"}
            or "name" not in tool
        ):
            raise ValueError("Native tool name requires name and optional namespace")
        name, namespace = tool["name"], tool.get("namespace")
        if (
            not isinstance(name, str)
            or not name
            or len(name) > 128
            or any(c.isspace() or unicodedata.category(c) == "Cc" for c in name)
        ):
            raise ValueError("Invalid native tool name")
        if namespace is not None and (
            not isinstance(namespace, str)
            or len(namespace) > 128
            or any(c.isspace() or unicodedata.category(c) == "Cc" for c in namespace)
        ):
            raise ValueError("Invalid native tool namespace")
        result.add((namespace or "functions", name))
    return result


def verify(required, response):
    if required is None:
        return response.get("toolPolicy")
    expected = normalized(required)
    actual = response.get("toolPolicy")
    if actual is None:
        raise NativeToolPolicyUnavailable(
            "Native runtime did not return an effective tool ceiling"
        )
    try:
        effective = normalized(actual)
    except ValueError as error:
        raise NativeToolPolicyUnavailable(
            "Native runtime returned an invalid tool ceiling"
        ) from error
    if not effective <= expected:
        raise NativeToolPolicyUnavailable(
            "Native runtime tool ceiling exceeds the requested policy"
        )
    return actual
