"""Agent-bound client for the native host daemon's existing Unix WebSocket.

The native server owns process lifetime, thread storage and request routing. This
client owns one agent/thread subscription and never launches or stops a server.
All clients of a host profile are trusted local clients of the same account.
"""
import asyncio
import errno
import json
import os
import stat
from pathlib import Path
from uuid import UUID
from aiohttp import ClientSession, UnixConnector, WSMsgType, ClientConnectorError
from .rpc import AppServer, RpcError


def host_manifest(config):
    selection = config.get("nativeServer")
    if not isinstance(selection, dict) or set(selection) != {"manifest"}:
        raise ValueError("Explicit native host manifest required")
    file = Path(selection["manifest"])
    if not file.is_absolute():
        raise ValueError("Native host manifest must be absolute")
    from .runtime_files import private_file
    private_file(file, administrator_allowed=True)
    value = json.loads(file.read_text())
    return validate_host_manifest(config,value)


def validate_host_manifest(config,value):
    """Validate a protected declaration or a derived, pinned release candidate."""
    if (value.get("schema") != "lax-native-host/v1"
            or value.get("runtimeMode") != "room-conversation"
            or value.get("authorityId") != str(UUID(config["authorityId"]))
            or value.get("hostId") != str(UUID(config["hostId"]))):
        raise ValueError("Native host authority, execution host or mode differs")
    for key in ("binary", "codexHome", "state", "socket"):
        if not isinstance(value.get(key), str) or not Path(value[key]).is_absolute():
            raise ValueError("Native host paths must be absolute")
    if (not os.path.samefile(value["binary"], config["binary"])
            or Path(value["codexHome"]).resolve() != Path(config["codexHome"]).resolve()):
        raise ValueError("Shared native profile/package adoption must be explicit")
    return value


class SharedAppServer(AppServer):
    shared = True

    def __init__(self, config, on_event, on_request, on_submission=None):
        value = host_manifest(config)
        super().__init__(value["binary"], Path(value["codexHome"]), Path(value["state"]),
                         on_event, on_request, on_submission=on_submission,
                         enterprise=True, runtime_mode="room-conversation")
        self.manifest = value
        self.socket_path = Path(value["socket"])
        self.thread_id = config.get("nativeThreadId")
        self.session = None
        self.websocket = None
        self.closing = False
        self.diagnostics = Path(config["state"]) / "shared-native-connection.json"

    @property
    def has_started(self):
        return self.reader is not None

    @property
    def is_connected(self):
        return (self.websocket is not None and not self.websocket.closed
                and self.reader is not None and not self.reader.done())

    def bind_thread(self, thread_id):
        if not isinstance(thread_id, str) or not thread_id:
            raise ValueError("Native thread identity required")
        if self.thread_id and self.thread_id != thread_id:
            raise ValueError("A shared connection cannot change its agent thread")
        self.thread_id = thread_id

    async def start(self):
        if self.has_started:
            raise RpcError("Original shared connection must be reconciled, not implicitly replaced")
        # Type=simple means exec has started, not that native has bound its IPC.
        # Wait only for local transport readiness; never submit/retry a model turn.
        deadline = asyncio.get_running_loop().time() + 5
        while True:
            try:
                info = self.socket_path.stat()
                break
            except FileNotFoundError:
                if asyncio.get_running_loop().time() >= deadline:
                    raise RpcError("Native host socket did not become ready", not_sent=True) from None
                await asyncio.sleep(.05)
        if os.name == "nt":
            from .windows_ipc import WindowsUnixConnector
            connector = WindowsUnixConnector(self.socket_path, self.manifest["binary"])
        else:
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise PermissionError("Native host socket must be private to the enrolled service user")
            connector = UnixConnector(path=str(self.socket_path))
        self.session = ClientSession(connector=connector)
        try:
            while True:
                try:
                    self.websocket = await self.session.ws_connect("http://localhost/", max_msg_size=16 * 1024 * 1024)
                    break
                except ClientConnectorError as error:
                    if error.os_error.errno not in (errno.ENOENT, errno.ECONNREFUSED):raise
                    if asyncio.get_running_loop().time() >= deadline:
                        raise RpcError("Native IPC listener did not become ready", not_sent=True) from error
                    await asyncio.sleep(.05)
            self.reader = asyncio.create_task(self._read())
            initialized = await self.call("initialize", {
                "clientInfo": {"name": "lax-host-agent", "version": "0.1.0"},
                "capabilities": {"experimentalApi": True},
            })
            self.lax_capabilities = frozenset(initialized.get("laxCapabilities", []))
            await self.write({"method": "initialized", "params": {}})
        except BaseException:
            await self.close()
            raise

    async def write(self, message):
        if self.websocket is None or self.websocket.closed:
            raise RpcError("Shared native connection unavailable; no private-server fallback", not_sent=True)
        try:
            await self.websocket.send_json(message)
        except (OSError, ConnectionError, RuntimeError) as error:
            raise RpcError("Native write uncertain; reconcile original operation before continuing") from error

    async def call(self, method, params, *, timeout=60):
        target = params.get("threadId")
        if target:
            if self.thread_id is None and method == "thread/resume":
                self.bind_thread(target)
            elif target != self.thread_id:
                raise ValueError("RPC belongs to a different agent thread")
        if method == "thread/start" and self.thread_id:
            raise ValueError("An existing agent cannot start a replacement thread")
        value = await super().call(method, params, timeout=timeout)
        if method in ("thread/start", "thread/resume"):
            self.bind_thread(value["thread"]["id"])
        return value

    def event_thread(self, message):
        params = message.get("params", {})
        return params.get("threadId") or (params.get("thread", {}) or {}).get("id")

    async def _read(self):
        try:
            async for frame in self.websocket:
                if frame.type == WSMsgType.TEXT:
                    message = json.loads(frame.data)
                    if "method" in message:
                        target = self.event_thread(message)
                        if "id" in message:
                            if target != self.thread_id or not target:
                                # Never answer a foreign agent's approval/tool callback.
                                raise RpcError("Native callback ownership mismatch")
                            task = asyncio.create_task(self._request(message))
                            self.requests.add(task)
                            task.add_done_callback(self.requests.discard)
                        elif target == self.thread_id and target:
                            await self.on_event(message["method"], message.get("params", {}))
                    elif (future := self.pending.get(message.get("id"))) and not future.done():
                        if "error" in message:
                            error = message["error"]
                            future.set_exception(RpcError(str(error), code=error.get("code"), detail=error))
                        else:
                            future.set_result(message.get("result", {}))
                elif frame.type == WSMsgType.ERROR:
                    raise RpcError("Shared native WebSocket failed")
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(RpcError("Shared native connection lost; original delivery may be unknown"))
            if not self.closing:
                from .journal import saved
                saved(self.diagnostics, {"state": "disconnected", "threadId": self.thread_id,
                                        "serverStopped": False, "privateProcessFallback": False})
                await self.on_event("hollywood/runtimeLost", {"threadId": self.thread_id})

    async def wait_closed(self):
        if self.reader:
            await self.reader

    async def close(self):
        self.closing = True
        if self.websocket:
            await self.websocket.close()
        if self.reader:
            await asyncio.gather(self.reader, return_exceptions=True)
        for task in list(self.requests):
            task.cancel()
        await asyncio.gather(*list(self.requests), return_exceptions=True)
        if self.session:
            await self.session.close()
        # No native shutdown, process signal or another agent's unsubscribe.


def native_client(config, on_event, on_request, **options):
    if config.get("nativeServer") is not None:
        if options.get("on_spawn") or options.get("collaboration_channel"):
            raise ValueError("Shared conversational clients cannot own a protected executor process")
        return SharedAppServer(config, on_event, on_request, options.get("on_submission"))
    return AppServer(config["binary"], Path(config["codexHome"]), Path(config["state"]) / "native",
                     on_event, on_request, enterprise=True, runtime_mode="room-conversation", **options)
