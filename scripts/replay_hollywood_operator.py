#!/usr/bin/env python3
"""Run a user-simulated Hollywood operator replay against a live app-server."""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import websocket


DEFAULT_CURRENT_APP_SERVER = Path.home() / ".codex/losangelex/current-app-server.json"
COORDINATION_TOOL_NAMES = {
    "coordination_act",
    "hollywood_read",
    "hollywood_send",
    "hollywood_status",
    "hollywood_team_member_update",
    "hollywood_team_status",
    "hollywood_team_up",
}
COORDINATION_ERROR_PATTERNS = (
    ("unknownLiveAgent", ("unknown live hollywood agent",)),
    ("invalidAgent", ("invalid live hollywood agent", "invalid agent")),
    (
        "malformedToolCall",
        (
            "arguments must",
            "failed to parse",
            "incompatible payload",
            "invalid arguments",
            "malformed",
            "missing arguments",
        ),
    ),
)


@dataclass
class AgentRun:
    name: str
    task: str
    thread_id: str


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


def load_scenario(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("scenario must be a JSON object")
    agents = data.get("agents")
    if not isinstance(agents, list) or not agents:
        raise ValueError("scenario.agents must be a non-empty array")
    for index, agent in enumerate(agents, start=1):
        if not isinstance(agent, dict):
            raise ValueError(f"scenario.agents[{index}] must be an object")
        if not isinstance(agent.get("name"), str) or not agent["name"]:
            raise ValueError(
                f"scenario.agents[{index}].name must be a non-empty string"
            )
        if not isinstance(agent.get("task"), str) or not agent["task"]:
            raise ValueError(
                f"scenario.agents[{index}].task must be a non-empty string"
            )
    return data


def load_app_server_url(path: Path) -> str:
    data = json.loads(path.read_text())
    url = data.get("websocket_url")
    if not isinstance(url, str) or not url:
        raise ValueError(f"{path} does not contain websocket_url")
    return url


def initialize(conn: JsonRpcWs) -> None:
    conn.send_request(
        "initialize",
        {
            "clientInfo": {
                "name": "hollywood-operator-replay",
                "title": "Hollywood Operator Replay",
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
    room: str,
    observed_rooms: list[str],
    wake_rooms: list[str],
    name: str,
    model: str | None = None,
    model_provider: str | None = None,
) -> str:
    params: dict[str, Any] = {
        "cwd": workspace,
        "approvalPolicy": "never",
        "sandbox": "danger-full-access",
        "persistExtendedHistory": True,
    }
    if model is not None:
        params["model"] = model
    if model_provider is not None:
        params["modelProvider"] = model_provider
    response = conn.send_request(
        "thread/start",
        params,
    )
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
            "room": room,
            "observedRooms": observed_rooms,
            "wakeRooms": wake_rooms,
            "attention": {
                "mode": "focused",
                "includeAtAll": True,
                "includeAtRoom": True,
            },
        },
    )
    return thread_id


def read_thread_state(conn: JsonRpcWs, thread_id: str) -> dict[str, Any]:
    response = conn.send_request(
        "thread/read",
        {
            "threadId": thread_id,
            "includeTurns": False,
        },
    )
    thread = response["thread"]
    return {
        "id": thread["id"],
        "name": thread.get("name"),
        "status": thread.get("status"),
        "updatedAt": thread.get("updatedAt"),
        "hollywood": thread.get("hollywood"),
    }


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


def summarize_notifications(
    notifications: list[dict[str, Any]], tracked_threads: set[str]
) -> dict[str, Any]:
    method_counts: Counter[str] = Counter()
    turn_started: Counter[str] = Counter()
    turn_completed: Counter[str] = Counter()
    hollywood_messages: list[dict[str, Any]] = []
    by_thread: dict[str, list[str]] = defaultdict(list)

    for message in notifications:
        method = message.get("method")
        if not isinstance(method, str):
            continue
        method_counts[method] += 1
        params = message.get("params", {})
        if method == "turn/started":
            thread_id = params.get("threadId")
            if thread_id in tracked_threads:
                turn_started[thread_id] += 1
        elif method == "turn/completed":
            thread_id = params.get("threadId")
            if thread_id in tracked_threads:
                turn_completed[thread_id] += 1
                output = params.get("lastAgentMessage")
                if isinstance(output, str):
                    by_thread[thread_id].append(output)
        elif method == "thread/hollywood/message":
            message_payload = params.get("message")
            if isinstance(message_payload, dict):
                hollywood_messages.append(
                    {
                        "threadId": params.get("threadId"),
                        "senderId": message_payload.get("senderId"),
                        "body": message_payload.get("body"),
                        "messageKind": message_payload.get("messageKind"),
                    }
                )

    return {
        "notificationCounts": dict(method_counts),
        "turnStartedByThread": dict(turn_started),
        "turnCompletedByThread": dict(turn_completed),
        "lastAgentMessagesByThread": dict(by_thread),
        "hollywoodMessages": hollywood_messages,
        "coordinationToolSummary": summarize_coordination_tools(
            notifications,
            tracked_threads,
        ),
    }


def summarize_coordination_tools(
    notifications: list[dict[str, Any]], tracked_threads: set[str]
) -> dict[str, Any]:
    calls_by_tool: Counter[str] = Counter()
    errors_by_tool: Counter[str] = Counter()
    errors_by_thread: Counter[str] = Counter()
    errors_by_category: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []

    for message in notifications:
        if message.get("method") != "item/completed":
            continue
        params = message.get("params", {})
        thread_id = params.get("threadId")
        if tracked_threads and thread_id not in tracked_threads:
            continue
        item = params.get("item")
        if not isinstance(item, dict):
            continue
        tool = item.get("tool")
        if not isinstance(tool, str) or tool not in COORDINATION_TOOL_NAMES:
            continue

        calls_by_tool[tool] += 1
        status = str(item.get("status", "")).lower()
        success = item.get("success")
        output_text = _coordination_tool_output_text(item)
        category = _coordination_error_category(output_text)
        failed = success is False or status == "failed" or category is not None
        if not failed:
            continue

        category = category or "otherFailure"
        errors_by_tool[tool] += 1
        if isinstance(thread_id, str):
            errors_by_thread[thread_id] += 1
        errors_by_category[category] += 1
        if len(examples) < 10:
            examples.append(
                {
                    "threadId": thread_id,
                    "tool": tool,
                    "category": category,
                    "message": _truncate_for_summary(output_text),
                }
            )

    return {
        "toolCalls": {
            "total": sum(calls_by_tool.values()),
            "byTool": dict(calls_by_tool),
        },
        "errorCalls": {
            "total": sum(errors_by_tool.values()),
            "byTool": dict(errors_by_tool),
            "byThread": dict(errors_by_thread),
            "byCategory": dict(errors_by_category),
        },
        "examples": examples,
    }


def _coordination_tool_output_text(item: dict[str, Any]) -> str:
    text_parts = []
    for key in ("error", "result", "contentItems", "content_items"):
        text_parts.extend(_iter_strings(item.get(key)))
    return "\n".join(text_parts)


def _iter_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        strings: list[str] = []
        for item in value:
            strings.extend(_iter_strings(item))
        return strings
    if isinstance(value, dict):
        strings: list[str] = []
        if isinstance(value.get("text"), str):
            strings.append(value["text"])
        for key, item in value.items():
            if key in {"text", "type"}:
                continue
            strings.extend(_iter_strings(item))
        return strings
    return []


def _coordination_error_category(text: str) -> str | None:
    lowered = text.lower()
    for category, patterns in COORDINATION_ERROR_PATTERNS:
        if any(pattern in lowered for pattern in patterns):
            return category
    return None


def _truncate_for_summary(text: str, limit: int = 500) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def completed_threads(
    notifications: list[dict[str, Any]], tracked_threads: set[str]
) -> set[str]:
    completed: set[str] = set()
    for message in notifications:
        if message.get("method") != "turn/completed":
            continue
        params = message.get("params", {})
        thread_id = params.get("threadId")
        if thread_id in tracked_threads:
            completed.add(thread_id)
    return completed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario-file", required=True)
    parser.add_argument("--app-server-url")
    parser.add_argument("--current-app-server", default=str(DEFAULT_CURRENT_APP_SERVER))
    args = parser.parse_args()

    scenario = load_scenario(Path(args.scenario_file))
    app_server_url = args.app_server_url or load_app_server_url(
        Path(args.current_app_server)
    )
    workspace = str(scenario["workspace"])
    base_room = str(scenario["room"])
    room = base_room
    if bool(scenario.get("autoUniqueRoom", False)):
        room = f"{base_room}-{uuid.uuid4().hex[:8]}"
    observed_rooms = [
        room if configured_room == base_room else configured_room
        for configured_room in list(scenario.get("observedRooms", []))
    ]
    wake_rooms = [
        room if configured_room == base_room else configured_room
        for configured_room in list(scenario.get("wakeRooms", []))
    ]
    startup_wait_seconds = float(scenario.get("startupWaitSeconds", 10))
    wait_for_startup_completions = bool(
        scenario.get("waitForStartupCompletions", False)
    )
    startup_completion_timeout_seconds = float(
        scenario.get("startupCompletionTimeoutSeconds", startup_wait_seconds)
    )
    soak_seconds = float(scenario.get("soakSeconds", 20))
    wait_for_turn_completions = bool(scenario.get("waitForTurnCompletions", False))
    turn_completion_timeout_seconds = float(
        scenario.get("turnCompletionTimeoutSeconds", soak_seconds)
    )

    conn = JsonRpcWs(app_server_url)
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        initialize(conn)
        agents: list[AgentRun] = []
        for agent in scenario["agents"]:
            thread_id = start_agent(
                conn,
                workspace=workspace,
                room=room,
                observed_rooms=observed_rooms,
                wake_rooms=wake_rooms,
                name=agent["name"],
            )
            agents.append(AgentRun(agent["name"], agent["task"], thread_id))

        tracked_threads = {agent.thread_id for agent in agents}
        if wait_for_startup_completions:
            deadline = time.time() + startup_completion_timeout_seconds
            conn.drain_until(
                lambda: (
                    completed_threads(conn.notifications, tracked_threads)
                    >= tracked_threads
                ),
                deadline,
            )
        elif startup_wait_seconds > 0:
            conn.drain(startup_wait_seconds)

        for agent in agents:
            send_turn(conn, agent.thread_id, agent.task)

        if wait_for_turn_completions:
            deadline = time.time() + turn_completion_timeout_seconds
            conn.drain_until(
                lambda: (
                    completed_threads(conn.notifications, tracked_threads)
                    >= tracked_threads
                ),
                deadline,
            )
        else:
            conn.drain(soak_seconds)

        summary = summarize_notifications(conn.notifications, tracked_threads)
        thread_states = {
            agent.thread_id: read_thread_state(conn, agent.thread_id)
            for agent in agents
        }
        result = {
            "appServerUrl": app_server_url,
            "workspace": workspace,
            "room": room,
            "startedAt": started_at,
            "startupWaitSeconds": startup_wait_seconds,
            "waitForStartupCompletions": wait_for_startup_completions,
            "startupCompletionTimeoutSeconds": startup_completion_timeout_seconds,
            "soakSeconds": soak_seconds,
            "waitForTurnCompletions": wait_for_turn_completions,
            "turnCompletionTimeoutSeconds": turn_completion_timeout_seconds,
            "agents": [
                {
                    "name": agent.name,
                    "threadId": agent.thread_id,
                    "task": agent.task,
                }
                for agent in agents
            ],
            "threadStates": thread_states,
            "summary": summary,
        }
        print(json.dumps(result, indent=2))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
