#!/usr/bin/env python3
"""Start app-server-hosted Losangelex peer sessions for Hollywood teamwork."""

import argparse
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

try:
    import websocket
except ImportError as exc:  # pragma: no cover - environment diagnostic
    raise SystemExit(
        "losangelex team requires the Python package `websocket-client`."
    ) from exc


DEFAULT_CURRENT_APP_SERVER = Path.home() / ".codex/losangelex/current-app-server.json"
DEFAULT_HOLLYWOOD_URL = "http://127.0.0.1:8765"


class JsonRpcWs:
    def __init__(self, url: str, request_timeout: float = 120) -> None:
        self.ws = websocket.create_connection(
            url,
            suppress_origin=True,
            timeout=request_timeout,
        )
        self.request_timeout = request_timeout
        self.next_id = 1
        self.notifications: list[dict[str, Any]] = []

    def close(self) -> None:
        self.ws.close()

    def send_notification(
        self, method: str, params: dict[str, Any] | None = None
    ) -> None:
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self.ws.send(json.dumps(message))

    def send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self.next_id
        self.next_id += 1
        self.ws.send(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
                }
            )
        )
        while True:
            message = self._recv_json(timeout=self.request_timeout)
            if "id" in message and message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError(
                        f"{method} failed: {json.dumps(message['error'], ensure_ascii=True)}"
                    )
                return message["result"]
            self.notifications.append(message)

    def drain(self, seconds: float) -> list[dict[str, Any]]:
        deadline = time.time() + seconds
        return self.drain_until(lambda: False, deadline)

    def drain_until(
        self, predicate: Callable[[], bool], deadline: float
    ) -> list[dict[str, Any]]:
        drained: list[dict[str, Any]] = []
        while time.time() < deadline:
            if predicate():
                break
            remaining = max(0.05, min(1.0, deadline - time.time()))
            try:
                message = self._recv_json(timeout=remaining)
            except TimeoutError:
                continue
            self.notifications.append(message)
            drained.append(message)
        return drained

    def _recv_json(self, timeout: float) -> dict[str, Any]:
        self.ws.settimeout(timeout)
        try:
            raw = self.ws.recv()
        except websocket.WebSocketTimeoutException as exc:
            raise TimeoutError from exc
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)


def parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def load_app_server_url(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(
            f"app-server state file not found: {path}; start Losangelex once or pass --app-server-url"
        ) from exc
    url = data.get("websocket_url")
    if not isinstance(url, str) or not url:
        raise SystemExit(f"{path} does not contain websocket_url")
    return url


def parse_agent_spec(value: str) -> dict[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("agent must use NAME=TASK")
    name, task = value.split("=", 1)
    name = name.strip()
    task = task.strip()
    if not name or not task:
        raise argparse.ArgumentTypeError("agent name and task must both be non-empty")
    return {"name": name, "task": task}


def load_agents(args: argparse.Namespace) -> list[dict[str, str]]:
    agents: list[dict[str, str]] = list(args.agent or [])
    if args.agents_json:
        data = json.loads(Path(args.agents_json).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for name, task in data.items():
                if not isinstance(name, str) or not isinstance(task, str):
                    raise SystemExit("--agents-json object values must be string tasks")
                agents.append({"name": name, "task": task})
        elif isinstance(data, list):
            for index, item in enumerate(data, start=1):
                if not isinstance(item, dict):
                    raise SystemExit(f"--agents-json item {index} must be an object")
                name = item.get("name")
                task = item.get("task")
                if not isinstance(name, str) or not isinstance(task, str):
                    raise SystemExit(
                        f"--agents-json item {index} must include string name and task"
                    )
                agents.append({"name": name, "task": task})
        else:
            raise SystemExit("--agents-json must be an object or array")
    if not agents:
        raise SystemExit("provide at least one --agent NAME=TASK or --agents-json file")
    return agents


def initialize(conn: JsonRpcWs) -> None:
    conn.send_request(
        "initialize",
        {
            "clientInfo": {
                "name": "losangelex-team",
                "title": "Losangelex Team Launcher",
                "version": "0.1",
            },
            "capabilities": {
                "experimentalApi": True,
            },
        },
    )
    conn.send_notification("initialized", {})


def start_agent(
    conn: JsonRpcWs,
    *,
    workspace: str,
    hollywood_url: str,
    room: str,
    observed_rooms: list[str],
    wake_rooms: list[str],
    attention_mode: str,
    name: str,
    model: str | None,
    model_provider: str | None,
) -> str:
    params: dict[str, Any] = {
        "cwd": workspace,
        "approvalPolicy": "never",
        "sandbox": "danger-full-access",
        "serviceName": "losangelex-team",
    }
    if model is not None:
        params["model"] = model
    if model_provider is not None:
        params["modelProvider"] = model_provider

    response = conn.send_request("thread/start", params)
    thread_id = response["thread"]["id"]
    conn.send_request(
        "thread/name/set",
        {
            "threadId": thread_id,
            "name": name,
        },
    )
    conn.send_request(
        "thread/hollywood/attach",
        {
            "threadId": thread_id,
            "url": hollywood_url,
            "room": room,
            "observedRooms": observed_rooms,
            "wakeRooms": wake_rooms,
            "attention": {
                "mode": attention_mode,
                "includeAtAll": True,
                "includeAtRoom": True,
            },
        },
    )
    return thread_id


def send_turn(conn: JsonRpcWs, thread_id: str, text: str) -> None:
    conn.send_request(
        "turn/start",
        {
            "threadId": thread_id,
            "input": [
                {
                    "type": "text",
                    "text": text,
                }
            ],
        },
    )


def completed_threads(
    notifications: list[dict[str, Any]], tracked_threads: set[str]
) -> set[str]:
    completed: set[str] = set()
    for message in notifications:
        if message.get("method") != "turn/completed":
            continue
        params = message.get("params")
        if not isinstance(params, dict):
            continue
        thread_id = params.get("threadId")
        if isinstance(thread_id, str) and thread_id in tracked_threads:
            completed.add(thread_id)
    return completed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Start app-server-hosted Losangelex peer sessions and assign initial tasks.",
    )
    parser.add_argument("--app-server-url")
    parser.add_argument(
        "--app-server-state",
        type=Path,
        default=DEFAULT_CURRENT_APP_SERVER,
        help="current-app-server.json to read when --app-server-url is omitted",
    )
    parser.add_argument("--workspace", default=os.getcwd())
    parser.add_argument(
        "--hollywood-url", default=os.getenv("HOLLYWOOD_URL", DEFAULT_HOLLYWOOD_URL)
    )
    parser.add_argument("--room", default=os.getenv("HOLLYWOOD_ROOM", "main"))
    parser.add_argument(
        "--observed-rooms", default=os.getenv("HOLLYWOOD_OBSERVED_ROOMS", "")
    )
    parser.add_argument("--observed-room", action="append", default=[])
    parser.add_argument("--wake-rooms", default=os.getenv("HOLLYWOOD_WAKE_ROOMS", ""))
    parser.add_argument("--wake-room", action="append", default=[])
    parser.add_argument(
        "--attention-mode",
        choices=["focused", "ambient", "broad"],
        default=os.getenv("HOLLYWOOD_ATTENTION_MODE", "focused"),
    )
    parser.add_argument("--model")
    parser.add_argument("--model-provider")
    parser.add_argument("--agent", action="append", type=parse_agent_spec)
    parser.add_argument("--agents-json")
    parser.add_argument("--no-start-turns", action="store_true")
    parser.add_argument("--startup-wait-seconds", type=float, default=0.0)
    parser.add_argument("--turn-soak-seconds", type=float, default=2.0)
    parser.add_argument("--wait-turns", action="store_true")
    parser.add_argument("--turn-timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--summary-json", type=Path)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    agents = load_agents(args)

    app_server_url = args.app_server_url or load_app_server_url(args.app_server_state)
    observed_rooms = [*parse_csv(args.observed_rooms), *args.observed_room]
    wake_rooms = [*parse_csv(args.wake_rooms), *args.wake_room]

    conn = JsonRpcWs(app_server_url)
    launched: list[dict[str, Any]] = []
    try:
        initialize(conn)
        for agent in agents:
            thread_id = start_agent(
                conn,
                workspace=args.workspace,
                hollywood_url=args.hollywood_url,
                room=args.room,
                observed_rooms=observed_rooms,
                wake_rooms=wake_rooms,
                attention_mode=args.attention_mode,
                name=agent["name"],
                model=args.model,
                model_provider=args.model_provider,
            )
            launched.append(
                {
                    "name": agent["name"],
                    "threadId": thread_id,
                    "task": agent["task"],
                }
            )

        tracked_threads = {item["threadId"] for item in launched}
        if args.startup_wait_seconds > 0:
            conn.drain(args.startup_wait_seconds)

        if not args.no_start_turns:
            for agent in launched:
                send_turn(conn, agent["threadId"], agent["task"])
            if args.wait_turns:
                deadline = time.time() + args.turn_timeout_seconds
                conn.drain_until(
                    lambda: (
                        completed_threads(conn.notifications, tracked_threads)
                        >= tracked_threads
                    ),
                    deadline,
                )
            elif args.turn_soak_seconds > 0:
                conn.drain(args.turn_soak_seconds)
    finally:
        conn.close()

    summary = {
        "appServerUrl": app_server_url,
        "workspace": args.workspace,
        "hollywood": {
            "url": args.hollywood_url,
            "room": args.room,
            "observedRooms": observed_rooms,
            "wakeRooms": wake_rooms,
            "attentionMode": args.attention_mode,
        },
        "agents": launched,
    }
    text = json.dumps(summary, indent=2, sort_keys=True)
    if args.summary_json:
        args.summary_json.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
