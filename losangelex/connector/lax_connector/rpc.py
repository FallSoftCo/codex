"""Bounded JSON-RPC transport over a private native app-server stdio connection."""

import asyncio
import json
import logging
import os
from pathlib import Path

LOGGER = logging.getLogger(__name__)


class RpcError(Exception):
    def __init__(self, message, *, code=None, not_sent=False):
        super().__init__(message)
        self.code = code
        self.not_sent = not_sent


class AppServer:
    def __init__(
        self,
        binary: str,
        home: Path,
        state: Path,
        on_event,
        on_request,
        on_submission=None,
        on_spawn=None,
        enterprise=False,
        collaboration_channel=None,
        isolated_process_group=False,
    ):
        self.binary, self.home, self.state = binary, home, state
        self.on_event, self.on_request = on_event, on_request
        self.on_submission = on_submission
        self.on_spawn = on_spawn
        self.enterprise = enterprise
        self.collaboration_channel = collaboration_channel
        self.isolated_process_group = isolated_process_group
        self.pending = {}
        self.requests = set()
        self.sequence = 0
        self.process = None
        self.reader = None

    async def start(self):
        if self.enterprise:
            from .native_package import inspect_package
            # The current execution UID must be able to launch every packaged asset.
            # Read-only recovery connections remain available for older native stores.
            self.package_preflight = await asyncio.to_thread(inspect_package, self.binary)
        self.home.mkdir(parents=True, exist_ok=True)
        self.state.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, CODEX_HOME=str(self.home))
        # A canonical worker never falls back to standalone shared SQLite or legacy ambient wakes.
        env.pop("LAX_CANONICAL_NATIVE_CHANNEL", None)
        env.pop("LAX_NATIVE_ENTERPRISE", None)
        if self.enterprise:
            env["LAX_NATIVE_ENTERPRISE"] = "1"
            if self.collaboration_channel is not None:
                from .service_observer import protected
                descriptor = protected(Path(self.collaboration_channel))
                if (set(descriptor) != {"schema", "socket", "ports"}
                        or descriptor["schema"] != "lax-native-collaboration-channel/v1"
                        or not isinstance(descriptor["ports"], list)):
                    raise RuntimeError("Protected native collaboration descriptor differs")
                env["LAX_CANONICAL_NATIVE_CHANNEL"] = str(self.collaboration_channel)

        # Pin the executable; inherited launcher overrides must not choose another build.
        for key in ("CODEX_CLI_PATH", "CODEX_EXECUTABLE", "CODEX_EXEC_SERVER_URL"):
            env.pop(key, None)
        # MCP configuration belongs to this explicit CODEX_HOME. Leave server
        # discovery and enablement to upstream without imposing a CLI table.
        # Canonical packaging already supports a headless entrypoint. Its CLI
        # accepts transport arguments directly; the full CLI needs its subcommand.
        from .native_package import runtime_command
        command = runtime_command(self.binary)
        with (self.state / "app-server.log").open("ab") as log:
            self.process = await asyncio.create_subprocess_exec(
                *command,
                "--listen",
                "stdio://",
                "-c",
                f"sqlite_home={json.dumps(str(self.state / 'sqlite'))}",
                "-c",
                f"log_dir={json.dumps(str(self.state / 'logs'))}",
                "-c",
                "check_for_update_on_startup=false",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=log,
                env=env,
                start_new_session=self.isolated_process_group,
                limit=16 * 1024 * 1024,
            )
        if self.on_spawn:
            await self.on_spawn(self)
        self.reader = asyncio.create_task(self._read())
        await self.call(
            "initialize",
            {
                "clientInfo": {"name": "lax-hollywood-connector", "version": "0.1.0"},
                "capabilities": {"experimentalApi": True},
            },
        )
        await self.write({"method": "initialized", "params": {}})

    async def write(self, message):
        if self.process is None or self.process.returncode is not None:
            raise RpcError("Codex runtime is unavailable", not_sent=True)
        self.process.stdin.write((json.dumps(message) + "\n").encode())
        await self.process.stdin.drain()

    async def call(self, method, params, *, timeout=60):
        self.sequence += 1
        request_id = self.sequence
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        try:
            await self.write({"id": request_id, "method": method, "params": params})
            return await asyncio.wait_for(future, timeout)
        finally:
            self.pending.pop(request_id, None)

    async def _request(self, message):
        params = {**message.get("params", {}), "_rpcRequestId": message["id"]}
        try:
            result = await self.on_request(message["method"], params)
        except Exception as exc:
            LOGGER.exception("App-server request handler failed: %s", message["method"])
            result = {
                "error": {
                    "code": -32603,
                    "message": f"Hollywood request failed: {type(exc).__name__}",
                }
            }
            outgoing = {"id": message["id"], **result}
        else:
            outgoing = {"id": message["id"], "result": result}
        written = False
        try:
            await self.write(outgoing)
            written = True
        finally:
            # Failure after the result write cannot justify a second JSON-RPC
            # response or replay of the human's approval/answer.
            if self.on_submission:
                await self.on_submission(
                    message["method"], params, written and "result" in outgoing
                )

    async def _read(self):
        try:
            while line := await self.process.stdout.readline():
                message = json.loads(line)
                if "method" in message:
                    if "id" in message:
                        task = asyncio.create_task(self._request(message))
                        self.requests.add(task)
                        task.add_done_callback(self.requests.discard)
                    else:
                        await self.on_event(
                            message["method"], message.get("params", {})
                        )
                elif (
                    future := self.pending.get(message.get("id"))
                ) and not future.done():
                    if "error" in message:
                        error = message["error"]
                        future.set_exception(
                            RpcError(str(error), code=error.get("code"))
                        )
                    else:
                        future.set_result(message.get("result", {}))
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(
                        RpcError("Codex connection lost; reconcile before retry")
                    )
            await self.on_event("hollywood/runtimeLost", {})

    async def close(self):
        if self.process and self.process.returncode is None:
            self.process.stdin.close()
            try:
                await asyncio.wait_for(self.process.wait(), 15)
            except asyncio.TimeoutError:
                self.process.terminate()
                await self.process.wait()
        if self.reader:
            await asyncio.gather(self.reader, return_exceptions=True)
        for task in self.requests:
            task.cancel()
        await asyncio.gather(*self.requests, return_exceptions=True)
