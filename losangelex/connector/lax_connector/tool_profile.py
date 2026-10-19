"""Approved native writer tools, using the fork's existing MCP/config path."""
import hashlib
import json
import re
import stat
from pathlib import Path

from .native_policy import normalized

SCHEMA = "lax-native-tool-profile/v1"
BUILTINS = {"view_image", "web_search"}
SERVER = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,60}")


def decode(raw):
    if len(raw) > 65536:
        raise ValueError("Approved tool profile exceeds its bounded declaration")
    value = json.loads(raw)
    if (not isinstance(value, dict)
            or set(value) != {"schema", "builtins", "mcpServers", "allowedTools", "webSearchMode"}
            or value["schema"] != SCHEMA):
        raise ValueError("Explicit native writer tool profile required")
    builtins = value["builtins"]
    if (not isinstance(builtins, list) or any(not isinstance(t, str) or t not in BUILTINS for t in builtins)
            or len(builtins) != len(set(builtins))):
        raise ValueError("Unsupported native execution tool")
    servers = value["mcpServers"]
    if (not isinstance(servers, dict) or len(servers) > 16
            or any(not isinstance(name, str) or not SERVER.fullmatch(name) or not isinstance(config, dict)
                   for name, config in servers.items())):
        raise ValueError("Invalid approved MCP server declaration")
    namespaces = {"mcp__" + name.replace("-", "_") for name in servers}
    if len(namespaces) != len(servers):
        raise ValueError("Approved MCP server namespaces collide")
    selected = normalized({"allowedTools": value["allowedTools"]})
    if any(namespace == "functions" or not namespace for namespace, _ in selected):
        raise ValueError("External declarations require explicit non-core namespaces")
    # Managed account connectors already exist in the native runtime and need
    # no duplicate MCP server configuration. Their selected tools still require
    # exact namespace/name approval, just like explicitly configured providers.
    if servers and not selected:
        raise ValueError("Configured providers require explicit selected tools")
    if value["webSearchMode"] not in ("disabled", "cached", "live"):
        raise ValueError("Invalid declared native search mode")
    if ("web_search" in builtins) != (value["webSearchMode"] != "disabled"):
        raise ValueError("Search exposure and mode must agree")
    tools = [{"name": name, "namespace": namespace} for namespace, name in sorted(selected)]
    tools += [{"name": name} for name in sorted(builtins)]
    if selected:
        tools.append({"name": "tool_search"})
    overrides = {"mcp_servers": servers}
    if "web_search" in builtins:
        overrides["web_search"] = value["webSearchMode"]
    return {"value": value, "allowedTools": tools, "overrides": overrides,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "summary": {"schema": SCHEMA, "builtins": sorted(builtins),
                        "mcpServers": sorted(servers), "selectedTools": len(selected)}}


def read(path, expected=None):
    path = Path(path)
    info = path.lstat()
    if (not path.is_absolute() or not stat.S_ISREG(info.st_mode)
            or info.st_uid != 0 or info.st_mode & 0o022):
        raise PermissionError("Tool declaration must be an administrator-protected regular file")
    result = decode(path.read_bytes())
    if expected is not None and result["sha256"] != expected:
        raise PermissionError("Installed tool declaration changed; explicit upgrade required")
    return result


def for_context(config, purpose):
    if purpose != "writer" or not config.get("toolProfileFile"):
        return {"allowedTools": [], "overrides": {}, "summary": None}
    result = read(config["toolProfileFile"], config["toolProfileSha256"])
    return {key: result[key] for key in ("allowedTools", "overrides", "summary")}
