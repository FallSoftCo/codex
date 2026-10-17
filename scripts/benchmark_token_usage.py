#!/usr/bin/env python3
"""Token usage helpers for model-in-the-loop benchmark runners."""

from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any


TOKEN_USAGE_KEYS = (
    "inputTokens",
    "cachedInputTokens",
    "nonCachedInputTokens",
    "outputTokens",
    "reasoningOutputTokens",
    "totalTokens",
    "uncachedPlusOutputTokens",
)
TRANSIENT_CODEX_EXEC_ERROR_PATTERNS = (
    "selected model is at capacity",
    "please try a different model",
)


def empty_token_usage() -> dict[str, int]:
    return {key: 0 for key in TOKEN_USAGE_KEYS}


def normalize_token_usage(value: dict[str, Any] | None) -> dict[str, int]:
    if not isinstance(value, dict):
        return empty_token_usage()

    input_tokens = _int_field(value, "inputTokens", "input_tokens")
    cached_input_tokens = _int_field(value, "cachedInputTokens", "cached_input_tokens")
    output_tokens = _int_field(value, "outputTokens", "output_tokens")
    reasoning_output_tokens = _int_field(
        value,
        "reasoningOutputTokens",
        "reasoning_output_tokens",
    )
    total_tokens = _int_field(value, "totalTokens", "total_tokens")
    if total_tokens == 0 and (input_tokens or output_tokens):
        total_tokens = input_tokens + output_tokens
    non_cached_input_tokens = max(input_tokens - cached_input_tokens, 0)
    return {
        "inputTokens": input_tokens,
        "cachedInputTokens": cached_input_tokens,
        "nonCachedInputTokens": non_cached_input_tokens,
        "outputTokens": output_tokens,
        "reasoningOutputTokens": reasoning_output_tokens,
        "totalTokens": total_tokens,
        "uncachedPlusOutputTokens": non_cached_input_tokens + output_tokens,
    }


def add_token_usage(
    left: dict[str, Any] | None, right: dict[str, Any] | None
) -> dict[str, int]:
    normalized_left = normalize_token_usage(left)
    normalized_right = normalize_token_usage(right)
    return {
        key: normalized_left[key] + normalized_right[key] for key in TOKEN_USAGE_KEYS
    }


def sum_token_usage(usages: list[dict[str, Any] | None]) -> dict[str, int]:
    total = empty_token_usage()
    for usage in usages:
        total = add_token_usage(total, usage)
    return total


def has_token_usage(value: dict[str, Any] | None) -> bool:
    usage = normalize_token_usage(value)
    return any(usage[key] > 0 for key in TOKEN_USAGE_KEYS)


def parse_codex_exec_jsonl_token_usage(stdout: str) -> dict[str, int]:
    usages: list[dict[str, Any]] = []
    for event in _jsonl_events(stdout):
        if event.get("type") == "turn.completed":
            usages.append(normalize_token_usage(event.get("usage")))
    return sum_token_usage(usages)


def run_codex_exec_with_retries(
    run_once: Callable[[], CompletedProcess[str]],
    *,
    max_attempts: int = 3,
    retry_delay_seconds: int = 60,
) -> tuple[CompletedProcess[str], list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    result = run_once()
    for attempt_index in range(1, max_attempts):
        if not is_transient_codex_exec_failure(result):
            return result, attempts
        attempts.append(
            {
                "attempt": attempt_index,
                "returncode": result.returncode,
                "stdoutTail": _tail_text(result.stdout),
                "stderrTail": _tail_text(result.stderr),
                "retryDelaySeconds": retry_delay_seconds,
            }
        )
        time.sleep(retry_delay_seconds)
        result = run_once()
    return result, attempts


def is_transient_codex_exec_failure(result: CompletedProcess[str]) -> bool:
    if result.returncode == 0:
        return False
    combined = f"{result.stdout}\n{result.stderr}".lower()
    return any(pattern in combined for pattern in TRANSIENT_CODEX_EXEC_ERROR_PATTERNS)


def summarize_codex_exec_collab_tools(stdout: str, stderr: str) -> dict[str, Any]:
    json_summary = _summarize_jsonl_collab_tools(stdout)
    if json_summary["toolCalls"]["total"] > 0:
        return json_summary

    combined = stdout + "\n" + stderr
    error_lines = [
        line
        for line in combined.splitlines()
        if "codex_core::tools::router: error=" in line
    ]
    return {
        "spawnAgentCalls": combined.count("collab: SpawnAgent"),
        "waitAgentCalls": combined.count("collab: Wait"),
        "sendInputCalls": combined.count("collab: SendInput"),
        "toolCalls": {
            "total": (
                combined.count("collab: SpawnAgent")
                + combined.count("collab: Wait")
                + combined.count("collab: SendInput")
            ),
            "byTool": {
                "spawn_agent": combined.count("collab: SpawnAgent"),
                "wait": combined.count("collab: Wait"),
                "send_input": combined.count("collab: SendInput"),
            },
        },
        "errorCalls": {
            "total": len(error_lines),
            "examples": error_lines[:10],
        },
    }


def snapshot_rollout_files(codex_home: Path) -> dict[Path, tuple[int, int]]:
    sessions = codex_home / "sessions"
    if not sessions.exists():
        return {}
    snapshot: dict[Path, tuple[int, int]] = {}
    for path in sessions.rglob("*.jsonl"):
        try:
            stat_result = path.stat()
        except FileNotFoundError:
            continue
        snapshot[path] = (stat_result.st_mtime_ns, stat_result.st_size)
    return snapshot


def changed_rollout_files(
    codex_home: Path,
    before: dict[Path, tuple[int, int]],
) -> list[Path]:
    sessions = codex_home / "sessions"
    if not sessions.exists():
        return []
    changed: list[Path] = []
    for path in sessions.rglob("*.jsonl"):
        try:
            stat_result = path.stat()
        except FileNotFoundError:
            continue
        fingerprint = (stat_result.st_mtime_ns, stat_result.st_size)
        if before.get(path) != fingerprint:
            changed.append(path)
    return sorted(changed)


def summarize_rollout_token_usage(paths: list[Path]) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for path in paths:
        usage = _rollout_file_token_usage(path)
        if not has_token_usage(usage):
            continue
        files.append(
            {
                "path": str(path),
                "tokenUsage": usage,
            }
        )
    return {
        "tokenUsage": sum_token_usage([item["tokenUsage"] for item in files]),
        "files": files,
        "fileCount": len(files),
    }


def summarize_app_server_token_usage(
    notifications: list[dict[str, Any]],
    tracked_threads: set[str],
) -> dict[str, Any]:
    latest_by_thread: dict[str, dict[str, Any]] = {}
    event_count = 0
    for message in notifications:
        if message.get("method") != "thread/tokenUsage/updated":
            continue
        params = message.get("params")
        if not isinstance(params, dict):
            continue
        thread_id = params.get("threadId")
        if not isinstance(thread_id, str):
            continue
        if tracked_threads and thread_id not in tracked_threads:
            continue
        token_usage = params.get("tokenUsage")
        if not isinstance(token_usage, dict):
            continue
        total = normalize_token_usage(token_usage.get("total"))
        latest_by_thread[thread_id] = {
            "turnId": params.get("turnId"),
            "total": total,
            "last": normalize_token_usage(token_usage.get("last")),
            "modelContextWindow": token_usage.get("modelContextWindow"),
        }
        event_count += 1

    total_usage = sum_token_usage(
        [thread_summary["total"] for thread_summary in latest_by_thread.values()]
    )
    return {
        "tokenUsage": total_usage,
        "eventCount": event_count,
        "threadCount": len(latest_by_thread),
        "byThread": latest_by_thread,
    }


def _rollout_file_token_usage(path: Path) -> dict[str, int]:
    latest_info: dict[str, Any] | None = None
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload = row.get("payload")
                if (
                    not isinstance(payload, dict)
                    or payload.get("type") != "token_count"
                ):
                    continue
                info = payload.get("info")
                if isinstance(info, dict):
                    latest_info = info
    except FileNotFoundError:
        return empty_token_usage()

    if latest_info is None:
        return empty_token_usage()
    return normalize_token_usage(latest_info.get("total_token_usage"))


def _summarize_jsonl_collab_tools(stdout: str) -> dict[str, Any]:
    tools_by_item: dict[str, dict[str, Any]] = {}
    for event in _jsonl_events(stdout):
        if event.get("type") not in {"item.started", "item.updated", "item.completed"}:
            continue
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "collab_tool_call":
            continue
        item_id = str(item.get("id", f"unknown-{len(tools_by_item)}"))
        tools_by_item[item_id] = item

    calls_by_tool: Counter[str] = Counter()
    errors_by_tool: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []
    for item in tools_by_item.values():
        tool = item.get("tool")
        if not isinstance(tool, str):
            continue
        calls_by_tool[tool] += 1
        status = str(item.get("status", "")).lower()
        agent_states = item.get("agents_states", {})
        failed_agent_states = (
            [
                agent_id
                for agent_id, state in agent_states.items()
                if isinstance(state, dict)
                and str(state.get("status", "")).lower() in {"errored", "not_found"}
            ]
            if isinstance(agent_states, dict)
            else []
        )
        if status == "failed" or failed_agent_states:
            errors_by_tool[tool] += 1
            if len(examples) < 10:
                examples.append(
                    {
                        "tool": tool,
                        "status": status,
                        "failedAgentStates": failed_agent_states,
                    }
                )

    return {
        "spawnAgentCalls": calls_by_tool.get("spawn_agent", 0),
        "waitAgentCalls": calls_by_tool.get("wait", 0),
        "sendInputCalls": calls_by_tool.get("send_input", 0),
        "toolCalls": {
            "total": sum(calls_by_tool.values()),
            "byTool": dict(calls_by_tool),
        },
        "errorCalls": {
            "total": sum(errors_by_tool.values()),
            "byTool": dict(errors_by_tool),
            "examples": examples,
        },
    }


def _jsonl_events(text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _tail_text(value: str, limit: int = 2000) -> str:
    if len(value) <= limit:
        return value
    return value[-limit:]


def _int_field(value: dict[str, Any], camel_name: str, snake_name: str) -> int:
    raw = value.get(camel_name, value.get(snake_name, 0))
    if isinstance(raw, bool):
        return int(raw)
    if isinstance(raw, int):
        return max(raw, 0)
    if isinstance(raw, float):
        return max(int(raw), 0)
    if isinstance(raw, str):
        try:
            return max(int(raw.replace(",", "")), 0)
        except ValueError:
            return 0
    return 0
