"""Real installed app-server MCP discovery in disposable homes; no model turn.

Run explicitly with MCP_RPC_BINARY and a new MCP_RPC_EVIDENCE directory. The
caller supplies a clean environment and an isolated network namespace. This
script neither loads account auth nor creates/resumes a native thread.
"""

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

from lax_connector.journal import saved
from lax_connector.rpc import AppServer


ALLOWED_METHODS = {"initialize", "initialized", "mcpServerStatus/list"}
BASE_CONFIG = '''model = "owned-proof-no-turn"
model_provider = "owned-proof"
approval_policy = "never"
sandbox_mode = "read-only"
[model_providers.owned-proof]
name = "Owned proof; no provider calls allowed"
base_url = "http://127.0.0.1:9/v1"
wire_api = "responses"
requires_openai_auth = false
[analytics]
enabled = false
[feedback]
enabled = false
[otel]
exporter = "none"
metrics_exporter = "none"
[features]
enable_mcp_apps = false
[plugins._default]
enabled = false
'''


def sha(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            value.update(block)
    return value.hexdigest()


class ObservedAppServer(AppServer):
    async def write(self, message):
        if "method" in message:
            assert message["method"] in ALLOWED_METHODS, "Thread/model/tool request forbidden"
        self.proof["outgoing"].append(message)
        return await super().write(message)


async def profile(root, binary, fixture, name, *, configured, enterprise):
    home, state = root / (name + "-home"), root / (name + "-state")
    home.mkdir(mode=0o700)
    state.mkdir(mode=0o700)
    fixture_log = root / (name + "-mcp.jsonl")
    config = BASE_CONFIG
    if configured:
        config += '\n[mcp_servers.owned_fixture]\ncommand = ' + json.dumps(sys.executable)
        config += '\nargs = ' + json.dumps([str(fixture), str(fixture_log)])
        config += '\nenabled = true\nstartup_timeout_sec = 10\n'
    config_path = home / "config.toml"
    config_path.write_text(config)
    config_hash = sha(config_path)
    proof = {"home": str(home), "state": str(state), "enterprise": enterprise,
             "outgoing": [], "events": [], "serverRequests": [], "configSha256Before": config_hash}

    async def event(method, params):
        proof["events"].append({"method": method, "params": params})

    async def request(method, params):
        proof["serverRequests"].append({"method": method, "params": params})
        raise AssertionError("No model/tool/approval request is authorized")

    async def spawned(rpc):
        process = Path("/proc") / str(rpc.process.pid)
        proof["pid"] = rpc.process.pid
        executable = process / "exe"
        info = executable.stat()
        proof["nativeExecutable"] = {"device": info.st_dev, "inode": info.st_ino,
            "size": info.st_size, "sha256": sha(executable)}
        proof["command"] = process.joinpath("cmdline").read_bytes().decode().split("\0")[:-1]
        env = dict(item.split("=", 1) for item in process.joinpath("environ").read_bytes().decode().split("\0") if item)
        proof["startupEnvironment"] = {key: env.get(key) for key in (
            "CODEX_HOME", "LAX_NATIVE_ENTERPRISE", "LAX_CANONICAL_NATIVE_CHANNEL",
            "CODEX_CLI_PATH", "CODEX_EXECUTABLE", "CODEX_EXEC_SERVER_URL")}
        assert env["CODEX_HOME"] == str(home)
        assert env.get("LAX_NATIVE_ENTERPRISE") == ("1" if enterprise else None)
        assert "LAX_CANONICAL_NATIVE_CHANNEL" not in env
        assert all(key not in env for key in ("CODEX_CLI_PATH", "CODEX_EXECUTABLE", "CODEX_EXEC_SERVER_URL"))

    rpc = ObservedAppServer(binary, home, state, event, request, on_spawn=spawned, enterprise=enterprise)
    rpc.proof = proof
    try:
        await asyncio.wait_for(rpc.start(), 30)
        proof["status"] = await rpc.call("mcpServerStatus/list", {"detail": "full", "limit": 8}, timeout=20)
    finally:
        await rpc.close()
        proof["exitCode"] = rpc.process.returncode if rpc.process else None
        proof["packagePreflight"] = getattr(rpc, "package_preflight", None)
        proof["configSha256After"] = sha(config_path)
        proof["fixtureMessages"] = [json.loads(line) for line in fixture_log.read_text().splitlines()] if fixture_log.exists() else []
        proof["authFiles"] = [str(path.relative_to(home)) for path in home.rglob("auth.json")]
        saved(root / (name + "-proof.json"), proof)
    assert proof["configSha256After"] == config_hash
    assert not proof["serverRequests"] and not proof["authFiles"]
    assert proof["exitCode"] == 0
    assert not Path("/proc", str(proof["pid"])).exists()
    for item in proof["fixtureMessages"]:
        if item.get("event") == "started":
            assert not Path("/proc", str(item["pid"])).exists(), "Owned MCP child did not exit"
    return proof


async def main():
    root = Path(os.environ["MCP_RPC_EVIDENCE"])
    root.mkdir(mode=0o700)
    binary = os.environ["MCP_RPC_BINARY"]
    fixture = Path(__file__).parent / "fixtures/owned_stdio_mcp.py"
    configured = await profile(root, binary, fixture, "configured", configured=True, enterprise=True)
    empty = await profile(root, binary, fixture, "empty", configured=False, enterprise=False)
    rows = configured["status"]["data"]
    assert len(rows) == 1 and rows[0]["name"] == "owned_fixture", configured["status"]
    assert list(rows[0]["tools"]) == ["owned_profile_probe"], rows[0]
    assert rows[0]["serverCapabilities"]["extensions"] == {"owned-proof": {}}
    assert empty["status"] == {"data": [], "nextCursor": None}
    assert not empty["fixtureMessages"]
    methods = [value.get("method") for value in configured["fixtureMessages"]]
    assert "initialize" in methods and "notifications/initialized" in methods and "tools/list" in methods
    assert not any(value == "tools/call" for value in methods)
    for item in configured["fixtureMessages"]:
        if item.get("event") == "started":
            assert item["uid"] == os.geteuid()
    assert not list(root.rglob("sessions/**/*.jsonl")), "Discovery must not create native threads"
    result = {"passed": True, "uid": os.geteuid(), "binary": binary,
        "configuredServerInitialized": True, "configuredToolAdvertised": True,
        "separateEmptyProfileHasNoServers": True, "explicitHomesAndConfigPreserved": True,
        "enterpriseStartupPreserved": True, "nativeThreadsCreated": 0, "modelTurnsSubmitted": 0,
        "mcpToolsInvoked": 0, "providerCallsAuthorized": 0, "productionChanged": False}
    saved(root / "result.json", result)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
