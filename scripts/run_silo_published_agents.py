#!/usr/bin/env python3
"""Run published SILO-BENCH tasks with Codex agents or Losangelex rooms.

This runner keeps SILO-BENCH's deterministic task files and scoring target, but
switches the agent substrate under test:

- codex: independent Codex CLI agents coordinating through a shared workspace.
- losangelex: native Hollywood/app-server agents coordinating through a room.

The runner intentionally does not place the full task JSON or expected answer in
the agent workspace before execution. Each agent receives only its private shard
prompt from the published benchmark instance.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchmark_app_server import add_benchmark_app_server_args
from benchmark_app_server import benchmark_app_server
from benchmark_app_server import prepare_minimal_codex_home
from eval_hollywood_app_builds import (
    DEFAULT_EVAL_MODEL_PROVIDER,
    active_thread_count,
    all_threads_idle,
)
from replay_hollywood_operator import (
    JsonRpcWs,
    completed_threads,
    initialize,
    read_thread_state,
    send_turn,
    summarize_notifications,
)


REPO_ROOT = Path("/home/ai/Development/losangelex")
DEFAULT_CODEX = REPO_ROOT / "codex-rs" / "target" / "debug" / "codex"
DEFAULT_OUT_ROOT = REPO_ROOT / "tmp" / "research" / "published-agent-benchmarks"
DEFAULT_SILO_ROOT = DEFAULT_OUT_ROOT / "repos" / "acl26-silo-bench"
DEFAULT_HOLLYWOOD_URL = "http://127.0.0.1:8765"


@dataclass(frozen=True)
class SiloAgentConfig:
    agent_id: int
    user_prompt: str
    profile: str | None = None


@dataclass(frozen=True)
class SiloTask:
    case_id: str
    case_name: str
    task_file: Path
    level: str
    agent_configs: list[SiloAgentConfig]
    expected_output: dict[str, Any]
    task_description: str


@dataclass(frozen=True)
class HollywoodAgent:
    agent_id: int
    runtime_name: str
    thread_id: str


@contextmanager
def temporarily_hide_paths(paths: list[Path]):
    """Temporarily remove all permissions from directories loaded by the harness.

    Codex/Losangelex agents are allowed to inspect their workspaces, but published
    benchmark files and previous result artifacts can contain answer keys. The
    runner loads selected task data before entering this context and restores
    original modes after the model-in-the-loop run.
    """
    original_modes: list[tuple[Path, int]] = []
    try:
        for path in paths:
            if not path.exists():
                continue
            stat_result = path.stat()
            original_modes.append((path, stat_result.st_mode & 0o7777))
            path.chmod(0)
        yield
    finally:
        for path, mode in reversed(original_modes):
            try:
                path.chmod(mode)
            except FileNotFoundError:
                pass


def run_command(
    command: list[str],
    *,
    cwd: Path,
    timeout: int,
    input_text: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=str(cwd),
            env=env,
            text=True,
            input=input_text,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return subprocess.CompletedProcess(
            command,
            124,
            stdout,
            stderr + f"\nTimed out after {timeout} seconds.\n",
        )


def load_task(path: Path) -> SiloTask:
    data = json.loads(path.read_text(encoding="utf-8"))
    agent_configs = [
        SiloAgentConfig(
            agent_id=int(agent["agent_id"]),
            user_prompt=str(agent["user_prompt"]),
            profile=agent.get("profile"),
        )
        for agent in data["agent_configs"]
    ]
    case_id = str(data["case_id"])
    level = case_id.split("-", maxsplit=1)[0]
    expected = data["expected_output"]
    if not isinstance(expected, dict) or "per_agent_values" not in expected:
        raise ValueError(f"{path} has unsupported expected_output shape")
    return SiloTask(
        case_id=case_id,
        case_name=str(data["case_name"]),
        task_file=path,
        level=level,
        agent_configs=agent_configs,
        expected_output=expected,
        task_description=str(data.get("task_description", data["case_name"])),
    )


def discover_tasks(
    *,
    silo_root: Path,
    task_ids: list[str],
    levels: list[str],
    agent_counts: list[int],
    limit: int | None,
) -> list[SiloTask]:
    task_dir = silo_root / "benchmarks"
    paths = sorted(task_dir.glob("*.json"))
    selected: list[SiloTask] = []
    wanted = set(task_ids)
    for path in paths:
        if wanted and path.stem not in wanted:
            continue
        if levels and not any(path.stem.startswith(f"{level}-") for level in levels):
            continue
        if agent_counts and not any(
            path.stem.endswith(f"_n{count}") for count in agent_counts
        ):
            continue
        try:
            task = load_task(path)
        except KeyError as exc:
            if wanted:
                raise ValueError(f"{path} is not a supported multi-agent task") from exc
            continue
        if wanted and task.case_id not in wanted and path.stem not in wanted:
            continue
        if levels and task.level not in levels:
            continue
        if agent_counts and len(task.agent_configs) not in agent_counts:
            continue
        selected.append(task)
        if limit is not None and len(selected) >= limit:
            break
    missing = sorted(
        item
        for item in wanted
        if item not in {task.task_file.stem for task in selected}
        and item not in {task.case_id for task in selected}
    )
    if missing:
        raise ValueError(f"SILO-BENCH task id(s) not found: {missing}")
    if not selected:
        raise ValueError("no SILO-BENCH tasks selected")
    return selected


def default_hidden_paths(silo_root: Path) -> list[Path]:
    return [silo_root]


def previous_result_hidden_paths(
    out_root: Path, current_output_dir: Path
) -> list[Path]:
    if not out_root.exists():
        return []
    current = current_output_dir.resolve()
    hidden: list[Path] = []
    for child in out_root.iterdir():
        if not child.is_dir() or child.name == "repos":
            continue
        if child.resolve() == current:
            continue
        hidden.append(child)
    return hidden


def effective_hidden_paths(
    *,
    explicit_paths: list[Path],
    silo_root: Path,
    include_defaults: bool,
) -> list[Path]:
    paths = list(explicit_paths)
    if include_defaults:
        paths.extend(default_hidden_paths(silo_root))
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.resolve() if path.exists() else path)
        if key not in seen:
            seen.add(key)
            deduped.append(path)
    return deduped


def fresh_workspace(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    (path / "shared").mkdir(parents=True)
    (path / "submissions").mkdir()


def _normalize_value(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        try:
            return int(stripped)
        except (TypeError, ValueError):
            pass
        try:
            return float(stripped)
        except (TypeError, ValueError):
            pass
        if stripped.startswith(("[", "{")):
            try:
                return _normalize_value(json.loads(stripped))
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        return stripped
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _normalize_value(item) for key, item in value.items()}
    return value


def _numeric_values_close(
    actual: Any, expected: Any, *, tolerance: float = 0.01
) -> bool:
    actual_norm = _normalize_value(actual)
    expected_norm = _normalize_value(expected)
    if isinstance(actual_norm, (int, float)) and isinstance(
        expected_norm, (int, float)
    ):
        return abs(actual_norm - expected_norm) <= tolerance
    if isinstance(actual_norm, list) and isinstance(expected_norm, list):
        return len(actual_norm) == len(expected_norm) and all(
            _numeric_values_close(left, right, tolerance=tolerance)
            for left, right in zip(actual_norm, expected_norm)
        )
    if isinstance(actual_norm, dict) and isinstance(expected_norm, dict):
        return actual_norm.keys() == expected_norm.keys() and all(
            _numeric_values_close(
                actual_norm[key],
                expected_norm[key],
                tolerance=tolerance,
            )
            for key in expected_norm
        )
    return actual_norm == expected_norm


def _numeric_partial_score(
    actual: Any, expected: Any, *, tolerance: float = 0.01
) -> float:
    actual_norm = _normalize_value(actual)
    expected_norm = _normalize_value(expected)
    if isinstance(actual_norm, list) and isinstance(expected_norm, list):
        if not expected_norm:
            return 1.0 if not actual_norm else 0.0
        if not isinstance(actual_norm, list):
            return 0.0
        pair_count = min(len(actual_norm), len(expected_norm))
        if pair_count == 0:
            return 0.0
        matched = sum(
            _numeric_partial_score(left, right, tolerance=tolerance)
            for left, right in zip(actual_norm, expected_norm)
        )
        return matched / len(expected_norm)
    if isinstance(actual_norm, dict) and isinstance(expected_norm, dict):
        if not expected_norm:
            return 1.0 if not actual_norm else 0.0
        matched = sum(
            _numeric_partial_score(
                actual_norm.get(key),
                expected_norm[key],
                tolerance=tolerance,
            )
            for key in expected_norm
        )
        return matched / len(expected_norm)
    return (
        1.0
        if _numeric_values_close(actual_norm, expected_norm, tolerance=tolerance)
        else 0.0
    )


def compute_numeric_tolerance_metrics(
    submissions: list[dict[str, Any]],
    expected_values: list[Any],
    *,
    tolerance: float = 0.01,
) -> dict[str, float]:
    count = len(expected_values)
    if count == 0:
        return {
            "S_numeric_tolerance_success_rate": 0.0,
            "P_numeric_tolerance_partial_correctness": 0.0,
        }
    submitted = {
        int(item["agent_id"]): _normalize_value(item["answer"])
        for item in submissions
        if item.get("exists")
    }
    exactish = 0
    partial_total = 0.0
    for agent_id, expected in enumerate(expected_values):
        if agent_id not in submitted:
            continue
        actual = submitted[agent_id]
        if _numeric_values_close(actual, expected, tolerance=tolerance):
            exactish += 1
        partial_total += _numeric_partial_score(
            actual,
            expected,
            tolerance=tolerance,
        )
    return {
        "S_numeric_tolerance_success_rate": exactish / count,
        "P_numeric_tolerance_partial_correctness": partial_total / count,
    }


def _canonical_sequence_key(value: Any) -> str:
    return json.dumps(_normalize_value(value), sort_keys=True, separators=(",", ":"))


def _lis_length(values: list[Any]) -> int:
    if not values:
        return 0
    from bisect import bisect_left

    tails: list[Any] = []
    for value in values:
        position = bisect_left(tails, value)
        if position == len(tails):
            tails.append(value)
        else:
            tails[position] = value
    return len(tails)


def read_submissions(workspace: Path, agent_count: int) -> list[dict[str, Any]]:
    submissions: list[dict[str, Any]] = []
    for agent_id in range(agent_count):
        path = workspace / "submissions" / f"agent-{agent_id:03d}.json"
        answer = None
        parse_error = None
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    answer = payload.get("answer")
                else:
                    answer = payload
            except json.JSONDecodeError as exc:
                parse_error = str(exc)
                answer = path.read_text(encoding="utf-8").strip()
        submissions.append(
            {
                "agent_id": agent_id,
                "answer": answer,
                "path": str(path),
                "exists": path.exists(),
                "parse_error": parse_error,
            }
        )
    return submissions


def score_task(task: SiloTask, submissions: list[dict[str, Any]]) -> dict[str, Any]:
    expected_values = task.expected_output["per_agent_values"]
    correct = 0
    records: list[dict[str, Any]] = []
    for submission in submissions:
        agent_id = int(submission["agent_id"])
        expected = (
            expected_values[agent_id] if agent_id < len(expected_values) else None
        )
        actual_norm = _normalize_value(submission["answer"])
        expected_norm = _normalize_value(expected)
        is_correct = actual_norm == expected_norm
        if is_correct:
            correct += 1
        records.append(
            {
                "agent_id": agent_id,
                "answer": submission["answer"],
                "expected": expected,
                "correct": is_correct,
                "exists": submission["exists"],
                "parse_error": submission["parse_error"],
            }
        )

    agent_count = len(expected_values)
    success_rate = correct / agent_count if agent_count else 0.0
    partial = compute_partial_correctness(
        level=task.level,
        submissions=submissions,
        expected_values=expected_values,
    )
    numeric_tolerance_metrics = compute_numeric_tolerance_metrics(
        submissions,
        expected_values,
    )
    return {
        "caseId": task.case_id,
        "caseName": task.case_name,
        "level": task.level,
        "agentCount": agent_count,
        "success": success_rate == 1.0,
        "metrics": {
            "S_success_rate": success_rate,
            "P_partial_correctness": partial,
            **numeric_tolerance_metrics,
        },
        "submissions": records,
    }


def compute_partial_correctness(
    *,
    level: str,
    submissions: list[dict[str, Any]],
    expected_values: list[Any],
    tolerance: float = 0.01,
) -> float:
    count = len(expected_values)
    if count == 0:
        return 0.0
    submitted = {
        int(item["agent_id"]): _normalize_value(item["answer"]) for item in submissions
    }

    if level == "I":
        scores = []
        for agent_id, expected_raw in enumerate(expected_values):
            actual = submitted.get(agent_id)
            expected = _normalize_value(expected_raw)
            if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
                if expected == 0:
                    scores.append(1.0 if actual == 0 else 0.0)
                elif abs(actual - expected) <= tolerance * abs(expected):
                    scores.append(1.0)
                else:
                    scores.append(0.0)
            else:
                scores.append(1.0 if actual == expected else 0.0)
        return sum(scores) / count

    if level == "II":
        total = 0.0
        for agent_id, expected_raw in enumerate(expected_values):
            actual = submitted.get(agent_id)
            expected = _normalize_value(expected_raw)
            if isinstance(actual, list) and isinstance(expected, list):
                if not expected:
                    total += 1.0 if not actual else 0.0
                else:
                    matches = sum(
                        1 for left, right in zip(actual, expected) if left == right
                    )
                    total += matches / len(expected)
            else:
                total += 1.0 if actual == expected else 0.0
        return total / count

    if level == "III":
        total = 0.0
        for agent_id, expected_raw in enumerate(expected_values):
            actual = submitted.get(agent_id)
            expected = _normalize_value(expected_raw)
            if isinstance(actual, list) and isinstance(expected, list):
                if not expected:
                    total += 1.0 if not actual else 0.0
                elif actual == expected:
                    total += 1.0
                else:
                    positions_by_value = {
                        _canonical_sequence_key(value): index
                        for index, value in enumerate(expected)
                    }
                    positions = [
                        positions_by_value[_canonical_sequence_key(value)]
                        for value in actual
                        if _canonical_sequence_key(value) in positions_by_value
                    ]
                    total += _lis_length(positions) / len(expected)
            else:
                total += 1.0 if actual == expected else 0.0
        return total / count

    return 0.0


def codex_prompt(task: SiloTask, config: SiloAgentConfig, *, round_index: int) -> str:
    return f"""We are running a published SILO-BENCH distributed coordination task.

System under evaluation: codex-agent-cohort
Case: {task.case_id} ({task.case_name})
Agent id: {config.agent_id}
Total agents: {len(task.agent_configs)}
Round: {round_index}

Private benchmark prompt for this agent:
{config.user_prompt}

Rules:
- You may read and write only inside this workspace.
- The full benchmark task JSON and answer key are not present in the workspace.
- Use `shared/` for coordination notes intended for other agents.
- Do not overwrite another agent's files.
- Do not inspect benchmark repositories, previous result directories, or any path
  outside this workspace. A run that uses an answer key is invalid.
- If you know your final answer, write exactly one JSON object to
  `submissions/agent-{config.agent_id:03d}.json` with this shape:
  {{"agent_id": {config.agent_id}, "answer": <your answer>}}
- If you do not know the answer yet, update `shared/agent-{config.agent_id:03d}.md`
  with your local fact, what you learned from teammates, and what you still need.
- Do not put commentary in the submission JSON file.
"""


def codex_subagent_worker_prompt(task: SiloTask, config: SiloAgentConfig) -> str:
    profile = (
        f"\nPublished role/profile for this agent:\n{config.profile}\n"
        if config.profile
        else ""
    )
    return f"""You are Codex subagent for a published SILO-BENCH distributed coordination task.

System under evaluation: codex-subagents
Case: {task.case_id} ({task.case_name})
Agent id: {config.agent_id}
Total agents: {len(task.agent_configs)}
{profile}
Private benchmark prompt for this agent:
{config.user_prompt}

Rules:
- Do not spawn any subagents. You are a worker, not an orchestrator.
- You may read and write only inside this workspace.
- The full benchmark task JSON and answer key are not present in the workspace.
- Use `shared/` for coordination notes intended for other agents.
- Do not overwrite another agent's files.
- Do not inspect benchmark repositories, previous result directories, or any path
  outside this workspace. A run that uses an answer key is invalid.
- Always write `shared/agent-{config.agent_id:03d}.md` with the local facts you
  computed from your private prompt.
- If you know your final answer, write exactly one JSON object to
  `submissions/agent-{config.agent_id:03d}.json` with this shape:
  {{"agent_id": {config.agent_id}, "answer": <your answer>}}
- If you do not know the answer yet, update `shared/agent-{config.agent_id:03d}.md`
  with your local fact, what you learned from teammates, and what you still need.
- Your final chat response is ignored by the scorer unless the required files
  exist, so do not substitute chat output for the files.
- Do not put commentary in the submission JSON file.

When your submission or shared note is written, finish. Do not wait for other
agents and do not delegate.
"""


def codex_subagent_parent_prompt(task: SiloTask) -> str:
    worker_sections = "\n\n".join(
        f"### Worker agent-{config.agent_id:03d}\n{codex_subagent_worker_prompt(task, config)}"
        for config in task.agent_configs
    )
    return f"""We are running a published SILO-BENCH distributed coordination task.

System under evaluation: codex-subagents
Case: {task.case_id} ({task.case_name})
Total agents: {len(task.agent_configs)}

This is the Codex-subagents orchestration baseline. You must use real Codex
subagents for the workers, not serial solo execution.

Important validity note:
- The worker prompts below contain private shards so you can pass each shard to
  the corresponding spawned worker. Do not solve the task in the parent from
  those shards.
- The parent's job is to spawn workers, wait for them, read worker-produced
  files/results, and aggregate those worker facts into the required submission
  files when the workers did not already write them.

Parent orchestration rules:
- Spawn exactly one Codex subagent for each worker prompt below.
- For each `spawn_agent` call, set `fork_turns` to exactly `none`.
- Do not include `agent_type`, `model`, `reasoning_effort`, `service_tier`, or
  `fork_context` in any `spawn_agent` call.
- Spawn the workers before inspecting the workspace so their work can run in parallel.
- Do not use Hollywood or Losangelex tools.
- Do not run `codex`, `codex exec`, or any other shell fallback to simulate subagents.
- Tell each worker exactly the corresponding prompt below.
- Wait for all spawned workers to finish. When calling `wait_agent`, use
  `timeout_ms` of at least `10000`; prefer `600000`.
- Never call `wait_agent` with small timeout values such as `1`, `5`, `1000`,
  or `5000`.
- If any `spawn_agent` call fails, do not complete the task yourself. Return
  `SPAWN_FAILED` with the error.
- If a spawned worker starts but later fails or times out, record that fact and
  continue with available worker files.
- After workers finish, read `shared/agent-*.md`, existing
  `submissions/agent-*.json`, and the worker completion messages.
- If the worker-produced facts are sufficient to determine the task answer,
  write or repair missing `submissions/agent-*.json` files for every original
  agent using only those worker-produced facts. Do not use the private shard text
  directly for the answer.
- If the worker-produced facts are insufficient, leave missing submissions
  missing and report the failure.
- Return a concise final message naming completed and missing submissions.

Worker prompts:

{worker_sections}
"""


def codex_subagent_tool_summary(stdout: str, stderr: str) -> dict[str, Any]:
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
        "errorCalls": {
            "total": len(error_lines),
            "examples": error_lines[:10],
        },
    }


def codex_subagent_artifact_summary(
    workspace: Path, agent_count: int
) -> dict[str, Any]:
    submissions_dir = workspace / "submissions"
    shared_dir = workspace / "shared"
    expected = [f"agent-{agent_id:03d}" for agent_id in range(agent_count)]
    submissions_present = [
        agent_name
        for agent_name in expected
        if (submissions_dir / f"{agent_name}.json").exists()
    ]
    shared_present = [
        agent_name
        for agent_name in expected
        if (shared_dir / f"{agent_name}.md").exists()
    ]
    return {
        "expectedAgents": expected,
        "submissionsPresent": submissions_present,
        "sharedPresent": shared_present,
        "missingSubmissions": [
            agent_name
            for agent_name in expected
            if agent_name not in submissions_present
        ],
        "missingShared": [
            agent_name for agent_name in expected if agent_name not in shared_present
        ],
    }


def write_codex_subagents_config(codex_home: Path) -> None:
    codex_home.mkdir(parents=True, exist_ok=True)
    (codex_home / "config.toml").write_text(
        "\n".join(
            [
                "[features.multi_agent_v2]",
                "enabled = true",
                "max_concurrent_threads_per_session = 128",
                "default_wait_timeout_ms = 600000",
                "hide_spawn_agent_metadata = true",
                "",
                f'[projects."{REPO_ROOT}"]',
                'trust_level = "trusted"',
                "",
            ]
        ),
        encoding="utf-8",
    )


def run_codex_task(
    *,
    task: SiloTask,
    workspace: Path,
    codex: Path,
    model: str,
    max_rounds: int,
    per_agent_timeout_seconds: int,
    output_dir: Path,
) -> dict[str, Any]:
    fresh_workspace(workspace)
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    run_records: list[dict[str, Any]] = []
    for round_index in range(1, max_rounds + 1):
        for config in task.agent_configs:
            submission_path = (
                workspace / "submissions" / f"agent-{config.agent_id:03d}.json"
            )
            if submission_path.exists():
                continue
            agent_dir = (
                output_dir / f"agent-{config.agent_id:03d}" / f"round-{round_index:03d}"
            )
            agent_dir.mkdir(parents=True, exist_ok=True)
            prompt = codex_prompt(task, config, round_index=round_index)
            (agent_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
            last_message_path = agent_dir / "last-message.txt"
            result = run_command(
                [
                    str(codex),
                    "-C",
                    str(workspace),
                    "--sandbox",
                    "workspace-write",
                    "--ask-for-approval",
                    "never",
                    "exec",
                    "--ephemeral",
                    "--ignore-user-config",
                    "--skip-git-repo-check",
                    "-m",
                    model,
                    "-o",
                    str(last_message_path),
                    "-",
                ],
                cwd=workspace,
                timeout=per_agent_timeout_seconds,
                input_text=prompt,
            )
            (agent_dir / "stdout.log").write_text(result.stdout, encoding="utf-8")
            (agent_dir / "stderr.log").write_text(result.stderr, encoding="utf-8")
            run_records.append(
                {
                    "agentId": config.agent_id,
                    "round": round_index,
                    "returncode": result.returncode,
                    "lastMessagePath": str(last_message_path),
                    "stdoutPath": str(agent_dir / "stdout.log"),
                    "stderrPath": str(agent_dir / "stderr.log"),
                    "submissionExists": submission_path.exists(),
                }
            )
        if all(
            (workspace / "submissions" / f"agent-{config.agent_id:03d}.json").exists()
            for config in task.agent_configs
        ):
            break

    submissions = read_submissions(workspace, len(task.agent_configs))
    score = score_task(task, submissions)
    return {
        "system": "codex",
        "caseId": task.case_id,
        "taskFile": task.task_file.name,
        "workspace": str(workspace),
        "seconds": round(time.time() - started, 1),
        "roundsExecuted": max((record["round"] for record in run_records), default=0),
        "agentRuns": run_records,
        "score": score,
    }


def run_codex_subagents_task(
    *,
    task: SiloTask,
    workspace: Path,
    codex: Path,
    model: str,
    timeout_seconds: int,
    output_dir: Path,
    codex_home: Path,
) -> dict[str, Any]:
    fresh_workspace(workspace)
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    prompt = codex_subagent_parent_prompt(task)
    (output_dir / "parent-prompt.txt").write_text(prompt, encoding="utf-8")
    last_message_path = output_dir / "parent-last-message.txt"
    env = os.environ.copy()
    env["CODEX_HOME"] = str(codex_home)
    result = run_command(
        [
            str(codex),
            "-C",
            str(workspace),
            "--sandbox",
            "workspace-write",
            "--ask-for-approval",
            "never",
            "exec",
            "--skip-git-repo-check",
            "-m",
            model,
            "-o",
            str(last_message_path),
            "-",
        ],
        cwd=workspace,
        timeout=timeout_seconds,
        input_text=prompt,
        env=env,
    )
    (output_dir / "parent-stdout.log").write_text(result.stdout, encoding="utf-8")
    (output_dir / "parent-stderr.log").write_text(result.stderr, encoding="utf-8")

    submissions = read_submissions(workspace, len(task.agent_configs))
    score = score_task(task, submissions)
    return {
        "system": "codex-subagents",
        "caseId": task.case_id,
        "taskFile": task.task_file.name,
        "workspace": str(workspace),
        "seconds": round(time.time() - started, 1),
        "parentRun": {
            "returncode": result.returncode,
            "lastMessagePath": str(last_message_path),
            "stdoutPath": str(output_dir / "parent-stdout.log"),
            "stderrPath": str(output_dir / "parent-stderr.log"),
        },
        "score": score,
        "coordinationToolSummary": codex_subagent_tool_summary(
            result.stdout, result.stderr
        ),
        "codexSubagentArtifacts": codex_subagent_artifact_summary(
            workspace,
            len(task.agent_configs),
        ),
        "baselineValidityNote": (
            "The parent prompt contains worker private shards so the model can call "
            "spawn_agent with the corresponding prompts. This is a true Codex-subagent "
            "orchestration baseline, not a strict parent-blind private-shard runtime. "
            "The parent may aggregate worker-produced facts into standardized "
            "submission files."
        ),
    }


def codex_full_context_prompt(task: SiloTask, *, round_index: int) -> str:
    private_prompts = "\n\n".join(
        [
            f"## Agent {config.agent_id}\n\n{config.user_prompt}"
            for config in task.agent_configs
        ]
    )
    submissions = "\n".join(
        [
            f"- `submissions/agent-{config.agent_id:03d}.json`: "
            f'{{"agent_id": {config.agent_id}, "answer": <answer_for_agent_{config.agent_id}>}}'
            for config in task.agent_configs
        ]
    )
    return f"""We are running a published SILO-BENCH full-context oracle baseline.

System under evaluation: codex-full-context
Case: {task.case_id} ({task.case_name})
Total agents in original task: {len(task.agent_configs)}
Round: {round_index}

You receive every private benchmark shard that would normally be distributed
across the original agents. The expected answer key is not present.

{private_prompts}

Rules:
- You may read and write only inside this workspace.
- The full benchmark task JSON and answer key are not present in the workspace.
- Do not inspect benchmark repositories, previous result directories, or any path
  outside this workspace. A run that uses an answer key is invalid.
- Write one JSON object per original agent:
{submissions}
- Do not put commentary in the submission JSON files.
"""


def codex_full_context_continue_prompt(task: SiloTask, *, round_index: int) -> str:
    missing = "\n".join(
        [
            f"- `submissions/agent-{config.agent_id:03d}.json`"
            for config in task.agent_configs
        ]
    )
    return f"""Continue the published SILO-BENCH full-context case {task.case_id}, round {round_index}.

Read the current workspace state and write any missing submission files.
The expected answer key is not present. Required files:
{missing}
"""


def run_codex_full_context_task(
    *,
    task: SiloTask,
    workspace: Path,
    codex: Path,
    model: str,
    max_rounds: int,
    per_agent_timeout_seconds: int,
    output_dir: Path,
) -> dict[str, Any]:
    fresh_workspace(workspace)
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    run_records: list[dict[str, Any]] = []
    for round_index in range(1, max_rounds + 1):
        if all(
            (workspace / "submissions" / f"agent-{config.agent_id:03d}.json").exists()
            for config in task.agent_configs
        ):
            break
        agent_dir = output_dir / f"round-{round_index:03d}"
        agent_dir.mkdir(parents=True, exist_ok=True)
        prompt = (
            codex_full_context_prompt(task, round_index=round_index)
            if round_index == 1
            else codex_full_context_continue_prompt(task, round_index=round_index)
        )
        (agent_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
        last_message_path = agent_dir / "last-message.txt"
        result = run_command(
            [
                str(codex),
                "-C",
                str(workspace),
                "--sandbox",
                "workspace-write",
                "--ask-for-approval",
                "never",
                "exec",
                "--ephemeral",
                "--ignore-user-config",
                "--skip-git-repo-check",
                "-m",
                model,
                "-o",
                str(last_message_path),
                "-",
            ],
            cwd=workspace,
            timeout=per_agent_timeout_seconds,
            input_text=prompt,
        )
        (agent_dir / "stdout.log").write_text(result.stdout, encoding="utf-8")
        (agent_dir / "stderr.log").write_text(result.stderr, encoding="utf-8")
        run_records.append(
            {
                "agentId": "full-context",
                "round": round_index,
                "returncode": result.returncode,
                "lastMessagePath": str(last_message_path),
                "stdoutPath": str(agent_dir / "stdout.log"),
                "stderrPath": str(agent_dir / "stderr.log"),
            }
        )

    submissions = read_submissions(workspace, len(task.agent_configs))
    score = score_task(task, submissions)
    return {
        "system": "codex-full-context",
        "caseId": task.case_id,
        "taskFile": task.task_file.name,
        "workspace": str(workspace),
        "seconds": round(time.time() - started, 1),
        "roundsExecuted": max((record["round"] for record in run_records), default=0),
        "agentRuns": run_records,
        "score": score,
    }


def start_hollywood_agent(
    conn: JsonRpcWs,
    *,
    workspace: Path,
    room: str,
    agent_id: int,
    runtime_name: str,
    model: str,
) -> str:
    response = conn.send_request(
        "thread/start",
        {
            "cwd": str(workspace),
            "approvalPolicy": "never",
            "sandbox": "workspace-write",
            "persistExtendedHistory": True,
            "model": model,
            "modelProvider": DEFAULT_EVAL_MODEL_PROVIDER,
        },
    )
    thread_id = response["thread"]["id"]
    conn.send_request(
        "thread/name/set",
        {
            "threadId": thread_id,
            "name": runtime_name,
        },
    )
    conn.send_request(
        "thread/hollywood/attach",
        {
            "threadId": thread_id,
            "room": room,
            "observedRooms": [room],
            "wakeRooms": [room],
            "attention": {
                "mode": "focused",
                "includeAtAll": True,
                "includeAtRoom": True,
            },
        },
    )
    return thread_id


def losangelex_prompt(
    task: SiloTask,
    config: SiloAgentConfig,
    *,
    runtime_name: str,
    round_index: int,
) -> str:
    profile = (
        f"\nPublished role/profile for this agent:\n{config.profile}\n"
        if config.profile
        else ""
    )
    return f"""We are running a published SILO-BENCH distributed coordination task.

System under evaluation: losangelex-hollywood-room
Case: {task.case_id} ({task.case_name})
Hollywood runtime identity: {runtime_name}
Agent id: {config.agent_id}
Total agents: {len(task.agent_configs)}
Round: {round_index}
{profile}
Private benchmark prompt for this agent:
{config.user_prompt}

Losangelex/Hollywood rules:
- Treat your private prompt as your only private data shard.
- Coordinate with the other agents through this Hollywood room and, if useful, `shared/`.
- Do not read files outside this workspace.
- Do not inspect benchmark repositories, previous result directories, or any path
  outside this workspace. A run that uses an answer key is invalid.
- Do not overwrite another agent's files.
- If you know your final answer, write exactly one JSON object to
  `submissions/agent-{config.agent_id:03d}.json` with this shape:
  {{"agent_id": {config.agent_id}, "answer": <your answer>}}
- If you do not know the answer yet, post the local fact you can contribute, ask for
  the missing facts, and update `shared/agent-{config.agent_id:03d}.md`.
- Do not put commentary in the submission JSON file.
"""


def continue_losangelex_prompt(
    task: SiloTask,
    config: SiloAgentConfig,
    *,
    round_index: int,
) -> str:
    return f"""Continue the published SILO-BENCH case {task.case_id}, round {round_index}.

Your private task prompt remains:
{config.user_prompt}

Read the current room/shared workspace state, coordinate only as needed, and write
`submissions/agent-{config.agent_id:03d}.json` once you know your answer.
"""


def wait_for_hollywood_round(
    *,
    conn: JsonRpcWs,
    agents: list[HollywoodAgent],
    deadline: float,
    poll_seconds: int,
) -> tuple[bool, dict[str, dict[str, Any]]]:
    tracked_threads = {agent.thread_id for agent in agents}
    completed_once = False
    states: dict[str, dict[str, Any]] = {}
    while time.time() < deadline:
        conn.drain(min(poll_seconds, max(0.1, deadline - time.time())))
        completed_once = (
            completed_threads(conn.notifications, tracked_threads) >= tracked_threads
        )
        states = {
            agent.thread_id: read_thread_state(conn, agent.thread_id)
            for agent in agents
        }
        if completed_once and all_threads_idle(states):
            break
    return completed_once, states


def run_losangelex_task(
    *,
    task: SiloTask,
    workspace: Path,
    app_server_url: str,
    model: str,
    max_rounds: int,
    timeout_seconds: int,
    round_timeout_seconds: int,
    poll_seconds: int,
    rpc_timeout_seconds: int,
    output_dir: Path,
) -> dict[str, Any]:
    fresh_workspace(workspace)
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    run_suffix = uuid.uuid4().hex[:6]
    room = f"repo/silo-{task.case_id}-n{len(task.agent_configs)}-{run_suffix}"
    conn = JsonRpcWs(app_server_url, request_timeout=rpc_timeout_seconds)
    agents: list[HollywoodAgent] = []
    completed_rounds: list[dict[str, Any]] = []
    stopped_for_active_timeout = False
    try:
        initialize(conn)
        for config in task.agent_configs:
            runtime_name = f"silo-agent-{config.agent_id:03d}-{run_suffix}"
            thread_id = start_hollywood_agent(
                conn,
                workspace=workspace,
                room=room,
                agent_id=config.agent_id,
                runtime_name=runtime_name,
                model=model,
            )
            agents.append(
                HollywoodAgent(
                    agent_id=config.agent_id,
                    runtime_name=runtime_name,
                    thread_id=thread_id,
                )
            )
        conn.drain(5)
        deadline = started + timeout_seconds
        for round_index in range(1, max_rounds + 1):
            for config, agent in zip(task.agent_configs, agents, strict=True):
                submission_path = (
                    workspace / "submissions" / f"agent-{config.agent_id:03d}.json"
                )
                if submission_path.exists():
                    continue
                if round_index == 1:
                    prompt = losangelex_prompt(
                        task,
                        config,
                        runtime_name=agent.runtime_name,
                        round_index=round_index,
                    )
                else:
                    prompt = continue_losangelex_prompt(
                        task,
                        config,
                        round_index=round_index,
                    )
                (
                    output_dir
                    / f"prompt-agent-{config.agent_id:03d}-round-{round_index:03d}.txt"
                ).write_text(
                    prompt,
                    encoding="utf-8",
                )
                send_turn(conn, agent.thread_id, prompt)
            round_deadline = min(deadline, time.time() + round_timeout_seconds)
            completed_once, states = wait_for_hollywood_round(
                conn=conn,
                agents=agents,
                deadline=round_deadline,
                poll_seconds=poll_seconds,
            )
            submitted = [
                config.agent_id
                for config in task.agent_configs
                if (
                    workspace / "submissions" / f"agent-{config.agent_id:03d}.json"
                ).exists()
            ]
            active_threads = active_thread_count(states)
            round_timed_out = time.time() >= round_deadline and len(submitted) < len(
                task.agent_configs
            )
            completed_rounds.append(
                {
                    "round": round_index,
                    "completedInitialTurns": completed_once,
                    "activeThreads": active_threads,
                    "roundTimedOut": round_timed_out,
                    "submitted": submitted,
                }
            )
            if all(
                (
                    workspace / "submissions" / f"agent-{config.agent_id:03d}.json"
                ).exists()
                for config in task.agent_configs
            ):
                break
            if round_timed_out and active_threads > 0:
                stopped_for_active_timeout = True
                break
            if time.time() >= deadline:
                break
        final_states = {
            agent.thread_id: read_thread_state(conn, agent.thread_id)
            for agent in agents
        }
        summary = summarize_notifications(
            conn.notifications,
            {agent.thread_id for agent in agents},
        )
    finally:
        conn.close()

    (output_dir / "thread-states.json").write_text(
        json.dumps(final_states, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "notifications-summary.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    submissions = read_submissions(workspace, len(task.agent_configs))
    score = score_task(task, submissions)
    return {
        "system": "losangelex",
        "caseId": task.case_id,
        "taskFile": task.task_file.name,
        "workspace": str(workspace),
        "room": room,
        "seconds": round(time.time() - started, 1),
        "rounds": completed_rounds,
        "stoppedForActiveTimeout": stopped_for_active_timeout,
        "agents": [
            {
                "agentId": agent.agent_id,
                "runtimeName": agent.runtime_name,
                "threadId": agent.thread_id,
            }
            for agent in agents
        ],
        "score": score,
        "coordinationToolSummary": summary.get("coordinationToolSummary", {}),
        "notificationsSummaryPath": str(output_dir / "notifications-summary.json"),
        "threadStatesPath": str(output_dir / "thread-states.json"),
    }


def aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    def summarize(record_group: list[dict[str, Any]]) -> dict[str, Any]:
        count = len(record_group)
        successes = sum(1 for record in record_group if record["score"]["success"])
        avg_success_rate = (
            sum(record["score"]["metrics"]["S_success_rate"] for record in record_group)
            / count
        )
        avg_partial = (
            sum(
                record["score"]["metrics"]["P_partial_correctness"]
                for record in record_group
            )
            / count
        )
        avg_numeric_tolerance_success_rate = (
            sum(
                record["score"]["metrics"].get(
                    "S_numeric_tolerance_success_rate",
                    record["score"]["metrics"]["S_success_rate"],
                )
                for record in record_group
            )
            / count
        )
        avg_numeric_tolerance_partial = (
            sum(
                record["score"]["metrics"].get(
                    "P_numeric_tolerance_partial_correctness",
                    record["score"]["metrics"]["P_partial_correctness"],
                )
                for record in record_group
            )
            / count
        )
        avg_seconds = sum(record["seconds"] for record in record_group) / count
        coordination_tool_errors = sum(
            coordination_error_total(record) for record in record_group
        )
        return {
            "tasks": count,
            "fullSuccesses": successes,
            "fullSuccessRate": successes / count,
            "avgAgentSuccessRate": avg_success_rate,
            "avgPartialCorrectness": avg_partial,
            "avgNumericToleranceSuccessRate": avg_numeric_tolerance_success_rate,
            "avgNumericTolerancePartialCorrectness": avg_numeric_tolerance_partial,
            "avgSeconds": avg_seconds,
            "coordinationToolErrors": coordination_tool_errors,
        }

    by_system: dict[str, list[dict[str, Any]]] = {}
    by_level_system: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for record in records:
        by_system.setdefault(record["system"], []).append(record)
        level = str(record["score"].get("level", "unknown"))
        by_level_system.setdefault(level, {}).setdefault(record["system"], []).append(
            record
        )
    systems: dict[str, Any] = {}
    for system, system_records in sorted(by_system.items()):
        systems[system] = summarize(system_records)
    levels: dict[str, Any] = {}
    for level, level_records_by_system in sorted(by_level_system.items()):
        levels[level] = {
            "systems": {
                system: summarize(level_records)
                for system, level_records in sorted(level_records_by_system.items())
            }
        }
    return {"systems": systems, "levels": levels}


def coordination_error_total(record: dict[str, Any]) -> int:
    summary = record.get("coordinationToolSummary", {})
    if not isinstance(summary, dict):
        return 0
    error_calls = summary.get("errorCalls", {})
    if not isinstance(error_calls, dict):
        return 0
    total = error_calls.get("total", 0)
    return int(total) if isinstance(total, (int, float)) else 0


def write_report(
    path: Path, *, campaign_name: str, records: list[dict[str, Any]]
) -> None:
    summary = aggregate(records)
    lines = [
        f"# Published SILO-BENCH Agent Comparison: {campaign_name}",
        "",
        "This run evaluates the same published SILO-BENCH task files with Codex",
        "agent cohorts and Losangelex Hollywood rooms. Each agent received only its",
        "private benchmark shard prompt; the expected answers were used only after",
        "execution for deterministic scoring.",
        "",
        "## Summary",
        "",
        "| System | Tasks | Full successes | Avg S | Avg P | Avg S_tol | Avg P_tol | Avg seconds | Coordination errors |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for system, row in summary["systems"].items():
        lines.append(
            f"| {system} | {row['tasks']} | {row['fullSuccesses']} "
            f"({row['fullSuccessRate']:.2%}) | {row['avgAgentSuccessRate']:.3f} | "
            f"{row['avgPartialCorrectness']:.3f} | "
            f"{row['avgNumericToleranceSuccessRate']:.3f} | "
            f"{row['avgNumericTolerancePartialCorrectness']:.3f} | "
            f"{row['avgSeconds']:.1f} | "
            f"{row['coordinationToolErrors']} |"
        )
    lines.extend(
        [
            "",
            "## By Level",
            "",
            "| Level | System | Tasks | Full successes | Avg S | Avg P | Avg S_tol | Avg P_tol | Avg seconds | Coordination errors |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for level, level_summary in summary["levels"].items():
        for system, row in level_summary["systems"].items():
            lines.append(
                f"| {level} | {system} | {row['tasks']} | {row['fullSuccesses']} "
                f"({row['fullSuccessRate']:.2%}) | {row['avgAgentSuccessRate']:.3f} | "
                f"{row['avgPartialCorrectness']:.3f} | "
                f"{row['avgNumericToleranceSuccessRate']:.3f} | "
                f"{row['avgNumericTolerancePartialCorrectness']:.3f} | "
                f"{row['avgSeconds']:.1f} | "
                f"{row['coordinationToolErrors']} |"
            )
    lines.extend(["", "## Tasks", ""])
    for record in records:
        metrics = record["score"]["metrics"]
        lines.append(
            f"- {record['system']} `{record['taskFile']}`: "
            f"success={record['score']['success']} "
            f"S={metrics['S_success_rate']:.3f} "
            f"P={metrics['P_partial_correctness']:.3f} "
            f"S_tol={metrics.get('S_numeric_tolerance_success_rate', metrics['S_success_rate']):.3f} "
            f"P_tol={metrics.get('P_numeric_tolerance_partial_correctness', metrics['P_partial_correctness']):.3f} "
            f"seconds={record['seconds']:.1f} "
            f"coordination_errors={coordination_error_total(record)}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--system",
        choices=("codex", "codex-subagents", "codex-full-context", "losangelex"),
        action="append",
        required=True,
    )
    parser.add_argument("--silo-root", type=Path, default=DEFAULT_SILO_ROOT)
    parser.add_argument("--task-id", action="append", dest="task_ids", default=[])
    parser.add_argument("--level", action="append", dest="levels", default=[])
    parser.add_argument(
        "--agent-count",
        action="append",
        dest="agent_counts",
        type=int,
        default=[],
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--model", default="gpt-5.4")
    parser.add_argument("--codex", type=Path, default=DEFAULT_CODEX)
    add_benchmark_app_server_args(parser)
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--per-agent-timeout-seconds", type=int, default=600)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--round-timeout-seconds", type=int, default=300)
    parser.add_argument("--poll-seconds", type=int, default=45)
    parser.add_argument("--rpc-timeout-seconds", type=int, default=300)
    parser.add_argument("--campaign-name", default=f"silo-{int(time.time())}")
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument(
        "--hide-path",
        action="append",
        dest="hide_paths",
        type=Path,
        default=[],
        help=(
            "Path to chmod 000 while agents run. Use this for benchmark repos "
            "and previous result roots that contain answer keys."
        ),
    )
    parser.add_argument(
        "--no-default-hide-paths",
        action="store_true",
        help="Do not hide the published benchmark repository during agent execution.",
    )
    args = parser.parse_args()

    tasks = discover_tasks(
        silo_root=args.silo_root,
        task_ids=args.task_ids,
        levels=args.levels,
        agent_counts=args.agent_counts,
        limit=args.limit,
    )
    output_dir = args.out_root / args.campaign_name
    output_dir.mkdir(parents=True, exist_ok=True)
    codex_subagents_home = None
    if "codex-subagents" in args.system:
        codex_subagents_home = (output_dir / "codex-subagents-home").resolve()
        prepare_minimal_codex_home(
            codex_home=codex_subagents_home,
            source_home=args.codex_home_source,
            output_dir=output_dir,
        )
        write_codex_subagents_config(codex_subagents_home)
    records: list[dict[str, Any]] = []
    hidden_paths = effective_hidden_paths(
        explicit_paths=args.hide_paths,
        silo_root=args.silo_root,
        include_defaults=not args.no_default_hide_paths,
    )
    if not args.no_default_hide_paths:
        hidden_paths = effective_hidden_paths(
            explicit_paths=[
                *hidden_paths,
                *previous_result_hidden_paths(args.out_root, output_dir),
            ],
            silo_root=args.silo_root,
            include_defaults=False,
        )
    with (
        benchmark_app_server(
            required="losangelex" in args.system,
            app_server_url=args.app_server_url,
            reuse_current_app_server=args.reuse_current_app_server,
            current_app_server=args.current_app_server,
            codex=args.codex,
            output_dir=output_dir,
            benchmark_codex_home=args.benchmark_codex_home,
            codex_home_source=args.codex_home_source,
            start_timeout_seconds=args.app_server_start_timeout_seconds,
        ) as app_server,
        temporarily_hide_paths(hidden_paths),
    ):
        app_server_url = app_server.url if app_server is not None else None
        app_server_metadata = app_server.metadata() if app_server is not None else None
        for task in tasks:
            for system in args.system:
                workspace = output_dir / "workspaces" / system / task.task_file.stem
                run_dir = output_dir / "runs" / system / task.task_file.stem
                if system == "codex":
                    record = run_codex_task(
                        task=task,
                        workspace=workspace,
                        codex=args.codex,
                        model=args.model,
                        max_rounds=args.max_rounds,
                        per_agent_timeout_seconds=args.per_agent_timeout_seconds,
                        output_dir=run_dir,
                    )
                elif system == "codex-subagents":
                    if codex_subagents_home is None:
                        raise RuntimeError(
                            "codex-subagents CODEX_HOME was not prepared"
                        )
                    record = run_codex_subagents_task(
                        task=task,
                        workspace=workspace,
                        codex=args.codex,
                        model=args.model,
                        timeout_seconds=args.timeout_seconds,
                        output_dir=run_dir,
                        codex_home=codex_subagents_home,
                    )
                elif system == "codex-full-context":
                    record = run_codex_full_context_task(
                        task=task,
                        workspace=workspace,
                        codex=args.codex,
                        model=args.model,
                        max_rounds=args.max_rounds,
                        per_agent_timeout_seconds=args.per_agent_timeout_seconds,
                        output_dir=run_dir,
                    )
                else:
                    if app_server_url is None:
                        raise RuntimeError(
                            "app server URL is required for Losangelex runs"
                        )
                    record = run_losangelex_task(
                        task=task,
                        workspace=workspace,
                        app_server_url=app_server_url,
                        model=args.model,
                        max_rounds=args.max_rounds,
                        timeout_seconds=args.timeout_seconds,
                        round_timeout_seconds=args.round_timeout_seconds,
                        poll_seconds=args.poll_seconds,
                        rpc_timeout_seconds=args.rpc_timeout_seconds,
                        output_dir=run_dir,
                    )
                records.append(record)
                (output_dir / "results.json").write_text(
                    json.dumps(
                        {
                            "benchmark": "SILO-BENCH",
                            "benchmarkRepository": str(args.silo_root),
                            "campaignName": args.campaign_name,
                            "model": args.model,
                            "systems": args.system,
                            "hiddenPaths": [str(path) for path in hidden_paths],
                            "defaultHiddenPathsEnabled": not args.no_default_hide_paths,
                            "appServer": app_server_metadata,
                            "codexSubagentsHome": (
                                str(codex_subagents_home)
                                if codex_subagents_home is not None
                                else None
                            ),
                            "records": records,
                            "summary": aggregate(records),
                        },
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                write_report(
                    output_dir / "SILO_PUBLISHED_REPORT.md",
                    campaign_name=args.campaign_name,
                    records=records,
                )
                metrics = record["score"]["metrics"]
                print(
                    f"completed system={system} task={task.task_file.stem} "
                    f"S={metrics['S_success_rate']:.3f} "
                    f"P={metrics['P_partial_correctness']:.3f} "
                    f"seconds={record['seconds']}",
                    flush=True,
                )

    print(f"wrote {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
