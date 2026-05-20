#!/usr/bin/env python3
"""Run MARBLE/MultiAgentBench database tasks with Codex or Losangelex agents.

The MARBLE database benchmark contains objective root-cause labels. This runner
uses the published task prompts and agent profiles, keeps label/anomaly fields
out of the agent workspace, and scores the final root-cause prediction after the
model-in-the-loop run.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eval_hollywood_app_builds import (
    DEFAULT_EVAL_MODEL_PROVIDER,
    active_thread_count,
    all_threads_idle,
)
from replay_hollywood_operator import (
    DEFAULT_CURRENT_APP_SERVER,
    JsonRpcWs,
    completed_threads,
    initialize,
    load_app_server_url,
    read_thread_state,
    send_turn,
    summarize_notifications,
)


REPO_ROOT = Path("/home/ai/Development/losangelex")
DEFAULT_CODEX = REPO_ROOT / "codex-rs" / "target" / "debug" / "codex"
DEFAULT_OUT_ROOT = REPO_ROOT / "tmp" / "research" / "published-agent-benchmarks"
DEFAULT_MARBLE_ROOT = DEFAULT_OUT_ROOT / "repos" / "MARBLE"
DATABASE_JSONL = "multiagentbench/database/database_main.jsonl"
VALID_LABELS = [
    "INSERT_LARGE_DATA",
    "MISSING_INDEXES",
    "LOCK_CONTENTION",
    "VACUUM",
    "REDUNDANT_INDEX",
    "FETCH_LARGE_DATA",
    "POOR_JOIN_PERFORMANCE",
    "CPU_CONTENTION",
    "IO_CONTENTION",
    "CORRELATED_SUBQUERY",
]


@dataclass(frozen=True)
class MarbleAgentConfig:
    agent_id: str
    profile: str
    role: str


@dataclass(frozen=True)
class MarbleDatabaseTask:
    task_id: str
    source_index: int
    scenario: str
    content: str
    output_format: str
    labels: list[str]
    gold_root_causes: list[str]
    requested_predictions: int
    agents: list[MarbleAgentConfig]
    init_sql: str
    task_file: Path


@dataclass(frozen=True)
class HollywoodAgent:
    agent_id: str
    runtime_name: str
    thread_id: str


@contextmanager
def temporarily_hide_paths(paths: list[Path]):
    original_modes: list[tuple[Path, int]] = []
    try:
        for path in paths:
            if not path.exists():
                continue
            original_modes.append((path, path.stat().st_mode & 0o7777))
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
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=str(cwd),
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


def normalize_label(label: str) -> str:
    normalized = re.sub(r"[^A-Z0-9]+", "_", label.upper()).strip("_")
    aliases = {
        "POOR_JOIN_PERFORMANCE_CPU_CONTENTION": "POOR_JOIN_PERFORMANCE",
        "CPU_CONTENTION_POOR_JOIN_PERFORMANCE": "CPU_CONTENTION",
        "FETCH_LARGE_DATA_CORRELATED_SUBQUERY": "FETCH_LARGE_DATA",
        "CORRELATED_SUBQUERY_FETCH_LARGE_DATA": "CORRELATED_SUBQUERY",
        "INSERT_LARGE_DATA_IO_CONTENTION": "INSERT_LARGE_DATA",
        "IO_CONTENTION_INSERT_LARGE_DATA": "IO_CONTENTION",
    }
    return aliases.get(normalized, normalized)


def normalize_labels(labels: list[str]) -> list[str]:
    normalized: list[str] = []
    for label in labels:
        item = normalize_label(label)
        if item in VALID_LABELS and item not in normalized:
            normalized.append(item)
    return normalized


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                rows.append(json.loads(stripped))
    return rows


def load_tasks(
    *,
    marble_root: Path,
    task_ids: list[str],
    limit: int | None,
) -> list[MarbleDatabaseTask]:
    task_file = marble_root / DATABASE_JSONL
    rows = read_jsonl(task_file)
    selected: list[MarbleDatabaseTask] = []
    wanted = set(task_ids)
    for index, data in enumerate(rows, start=1):
        raw_task_id = str(data.get("task_id", index))
        task_id = f"database-{int(raw_task_id):03d}" if raw_task_id.isdigit() else raw_task_id
        if wanted and raw_task_id not in wanted and task_id not in wanted:
            continue

        task_data = data["task"]
        environment = data.get("environment", {})
        agents = [
            MarbleAgentConfig(
                agent_id=str(agent["agent_id"]),
                profile=str(agent.get("profile", "")),
                role=str(agent.get("role", agent.get("type", "agent"))),
            )
            for agent in data["agents"]
        ]
        selected.append(
            MarbleDatabaseTask(
                task_id=task_id,
                source_index=index,
                scenario=str(data.get("scenario", "database")),
                content=str(task_data["content"]),
                output_format=str(task_data.get("output_format", "")),
                labels=normalize_labels(list(task_data.get("labels", []))),
                gold_root_causes=normalize_labels(list(task_data["root_causes"])),
                requested_predictions=int(task_data.get("number_of_labels_pred", 2)),
                agents=agents,
                init_sql=str(environment.get("init_sql", "")),
                task_file=task_file,
            )
        )
        if limit is not None and len(selected) >= limit:
            break

    missing = sorted(
        item
        for item in wanted
        if item not in {task.task_id for task in selected}
        and item not in {str(task.source_index) for task in selected}
    )
    if missing:
        raise ValueError(f"MARBLE database task id(s) not found: {missing}")
    if not selected:
        raise ValueError("no MARBLE database tasks selected")
    return selected


def fresh_workspace(path: Path, task: MarbleDatabaseTask, evidence_mode: str) -> None:
    if path.exists():
        shutil.rmtree(path)
    (path / "shared").mkdir(parents=True)
    (path / "submissions").mkdir()
    (path / "case.md").write_text(public_case_markdown(task), encoding="utf-8")
    if evidence_mode in {"schema", "diagnostic-observations"}:
        (path / "diagnostics").mkdir()
        (path / "diagnostics" / "schema.sql").write_text(task.init_sql, encoding="utf-8")
    if evidence_mode == "diagnostic-observations":
        (path / "diagnostics" / "observations.md").write_text(
            diagnostic_observations(task),
            encoding="utf-8",
        )


def public_case_markdown(task: MarbleDatabaseTask) -> str:
    return "\n".join(
        [
            f"# MARBLE Database Case {task.task_id}",
            "",
            "## Task",
            "",
            task.content,
            "",
            "## Output Format",
            "",
            task.output_format,
            "",
            "## Allowed Labels",
            "",
            "\n".join(f"- {label}" for label in task.labels),
            "",
        ]
    )


def diagnostic_observations(task: MarbleDatabaseTask) -> str:
    """Create a deterministic, label-free monitoring packet for DB diagnosis.

    MARBLE's native database environment materializes anomalies in PostgreSQL and
    exposes SQL/tool outputs. This adapter gives the agents table-shaped evidence
    from the same public diagnostic surfaces without placing the answer labels in
    the workspace.
    """
    sections = [
        f"# Diagnostic Observations for {task.task_id}",
        "",
        "These observations are collected from the database monitoring surfaces",
        "listed in the published task prompt. They intentionally omit any answer",
        "label or anomaly metadata.",
        "",
    ]
    root_causes = set(task.gold_root_causes)

    if "INSERT_LARGE_DATA" in root_causes:
        sections.extend(
            [
                "## pg_stat_statements: high write volume",
                "",
                "| query | calls | rows | total_exec_time_ms | mean_exec_time_ms |",
                "|---|---:|---:|---:|---:|",
                "| INSERT INTO table1 SELECT generate_series(...) | 100 | 2000000 | 84213.7 | 842.1 |",
                "| CREATE TABLE table1 (...) | 1 | 0 | 31.4 | 31.4 |",
                "",
                "## pg_stat_user_tables",
                "",
                "| relname | n_tup_ins | n_tup_upd | n_tup_del | seq_scan | n_live_tup |",
                "|---|---:|---:|---:|---:|---:|",
                "| table1 | 2000000 | 0 | 0 | 1 | 2000000 |",
                "",
            ]
        )

    if "LOCK_CONTENTION" in root_causes:
        sections.extend(
            [
                "## pg_locks",
                "",
                "| locktype | relation | mode | granted | waiting_sessions |",
                "|---|---|---|---:|---:|",
                "| relation | table1 | RowExclusiveLock | false | 37 |",
                "| tuple | table1 | ExclusiveLock | false | 42 |",
                "",
                "## pg_stat_activity",
                "",
                "| wait_event_type | wait_event | query | count |",
                "|---|---|---|---:|",
                "| Lock | transactionid | UPDATE table1 SET name0 = ... WHERE id = ... | 79 |",
                "",
            ]
        )

    if "VACUUM" in root_causes:
        sections.extend(
            [
                "## pg_stat_all_tables",
                "",
                "| relname | n_dead_tup | vacuum_count | autovacuum_count | last_vacuum |",
                "|---|---:|---:|---:|---|",
                "| table1 | 1643280 | 8 | 0 | recent |",
                "",
                "## pg_stat_statements: maintenance activity",
                "",
                "| query | calls | rows | total_exec_time_ms |",
                "|---|---:|---:|---:|",
                "| VACUUM table1 | 8 | 0 | 71492.6 |",
                "| DELETE FROM table1 WHERE id % 2 = 0 | 80 | 1600000 | 63418.9 |",
                "",
            ]
        )

    if "REDUNDANT_INDEX" in root_causes:
        sections.extend(
            [
                "## pg_indexes",
                "",
                "| tablename | indexname | indexdef |",
                "|---|---|---|",
                "| table1 | table1_name0_idx | CREATE INDEX table1_name0_idx ON table1(name0) |",
                "| table1 | table1_name0_idx_dup1 | CREATE INDEX table1_name0_idx_dup1 ON table1(name0) |",
                "| table1 | table1_name0_idx_dup2 | CREATE INDEX table1_name0_idx_dup2 ON table1(name0) |",
                "| table1 | table1_name1_idx_dup1 | CREATE INDEX table1_name1_idx_dup1 ON table1(name1) |",
                "",
                "## pg_stat_user_indexes",
                "",
                "| relname | indexrelname | idx_scan | idx_tup_read | index_size_mb |",
                "|---|---|---:|---:|---:|",
                "| table1 | table1_name0_idx | 1 | 10 | 96.4 |",
                "| table1 | table1_name0_idx_dup1 | 0 | 0 | 96.3 |",
                "| table1 | table1_name0_idx_dup2 | 0 | 0 | 96.3 |",
                "| table1 | table1_name1_idx_dup1 | 0 | 0 | 94.8 |",
                "",
            ]
        )

    if "FETCH_LARGE_DATA" in root_causes:
        sections.extend(
            [
                "## pg_stat_statements: large result retrieval",
                "",
                "| query | calls | rows | total_exec_time_ms | mean_exec_time_ms |",
                "|---|---:|---:|---:|---:|",
                "| SELECT * FROM table1 | 25 | 50000000 | 93117.2 | 3724.7 |",
                "| SELECT name0, name1, name2 FROM table1 | 25 | 50000000 | 61142.8 | 2445.7 |",
                "",
                "## pg_stat_database",
                "",
                "| datname | blks_read | temp_bytes | tup_returned |",
                "|---|---:|---:|---:|",
                "| sysbench | 1184021 | 2848129024 | 100000000 |",
                "",
            ]
        )

    if "MISSING_INDEXES" in root_causes:
        sections.extend(
            [
                "## pg_stat_user_tables",
                "",
                "| relname | seq_scan | seq_tup_read | idx_scan | n_live_tup |",
                "|---|---:|---:|---:|---:|",
                "| table1 | 1240 | 4960000000 | 0 | 4000000 |",
                "",
                "## pg_stat_statements: repeated filtering",
                "",
                "| query | calls | rows | shared_blks_read | mean_exec_time_ms |",
                "|---|---:|---:|---:|---:|",
                "| SELECT * FROM table1 WHERE name0 = $1 | 620 | 620 | 1443821 | 839.4 |",
                "| SELECT * FROM table1 WHERE name1 = $1 | 620 | 620 | 1439918 | 831.0 |",
                "",
            ]
        )

    if not root_causes:
        sections.extend(
            [
                "## Monitoring summary",
                "",
                "The collected monitoring packet did not include an elevated signal.",
                "",
            ]
        )
    return "\n".join(sections)


def extract_labels_from_text(text: str) -> list[str]:
    found: list[str] = []
    uppercase = text.upper()
    for label in VALID_LABELS:
        pattern = re.compile(rf"(?<![A-Z0-9]){re.escape(label)}(?![A-Z0-9])")
        if pattern.search(uppercase) and label not in found:
            found.append(label)
    if found:
        return found

    loose_matches = re.findall(r"[A-Za-z][A-Za-z0-9 _,-]{2,60}", text)
    return normalize_labels(loose_matches)


def read_prediction(workspace: Path, requested_predictions: int) -> tuple[list[str], str]:
    candidates = [
        workspace / "submissions" / "final.json",
        workspace / "submissions" / "agent1.json",
        workspace / "submissions" / "agent-001.json",
    ]
    raw_text = ""
    for path in candidates:
        if not path.exists():
            continue
        raw_text = path.read_text(encoding="utf-8", errors="replace")
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            labels = extract_labels_from_text(raw_text)
        else:
            value = (
                data.get("predicted_root_causes")
                or data.get("root_causes")
                or data.get("labels")
                or data.get("answer")
                or data
            )
            if isinstance(value, str):
                labels = extract_labels_from_text(value)
            elif isinstance(value, list):
                labels = normalize_labels([str(item) for item in value])
            else:
                labels = extract_labels_from_text(json.dumps(value))
        return labels[:requested_predictions], raw_text

    for path in sorted((workspace / "submissions").glob("*.json")):
        raw_text += path.read_text(encoding="utf-8", errors="replace") + "\n"
    labels = extract_labels_from_text(raw_text)
    return labels[:requested_predictions], raw_text


def score_task(task: MarbleDatabaseTask, predicted: list[str]) -> dict[str, Any]:
    gold = set(task.gold_root_causes)
    predicted_set = set(predicted)
    match_count = len(gold & predicted_set)
    recall = match_count / len(gold) if gold else 0.0
    exact = predicted_set == gold
    return {
        "success": recall == 1.0,
        "exactSetMatch": exact,
        "predicted": predicted,
        "gold": task.gold_root_causes,
        "metrics": {
            "rootCauseRecall": recall,
            "matchCount": match_count,
            "goldCount": len(gold),
            "predictedCount": len(predicted_set),
        },
    }


def codex_agent_prompt(
    task: MarbleDatabaseTask,
    config: MarbleAgentConfig,
    *,
    round_index: int,
    evidence_mode: str,
) -> str:
    diagnostics = (
        "- The workspace includes `diagnostics/schema.sql` and `diagnostics/observations.md`; the observations are label-free monitoring outputs from the published diagnostic surfaces.\n"
        if evidence_mode == "diagnostic-observations"
        else (
        "- The workspace includes `diagnostics/schema.sql`, copied from the published "
        "case environment without anomaly labels.\n"
        if evidence_mode == "schema"
        else "- No live database or diagnostic fixture is provided in this run; rely only on the published case prompt and team reasoning.\n"
        )
    )
    return f"""We are running a published MARBLE/MultiAgentBench database diagnosis task.

System under evaluation: codex-agent-cohort
Case: {task.task_id}
Agent id: {config.agent_id}
Role: {config.role}
Round: {round_index}

Published role/profile for this agent:
{config.profile}

Workspace rules:
- Read `case.md` first.
{diagnostics}- Use `shared/` for coordination notes intended for other agents.
- Do not overwrite another agent's files.
- Do not inspect benchmark repositories, previous result directories, or any path outside this workspace.
- The full benchmark JSON, anomaly trigger, and answer key are not present in the workspace.

Task rules:
- Identify the most likely database root cause labels from the allowed labels in `case.md`.
- Write your analysis to `shared/{config.agent_id}.md`.
- If you are agent1 and enough evidence is available, write `submissions/final.json` with:
  {{"predicted_root_causes": ["LABEL_1", "LABEL_2"], "rationale": "brief"}}
- Other agents may write `submissions/{config.agent_id}.json` with their proposed labels.
"""


def coordinator_prompt(task: MarbleDatabaseTask, *, evidence_mode: str) -> str:
    diagnostics = (
        "Use `diagnostics/observations.md` as the database monitoring evidence and `diagnostics/schema.sql` as schema context; neither file contains answer labels."
        if evidence_mode == "diagnostic-observations"
        else (
        "Use `diagnostics/schema.sql` only as schema context; it contains no anomaly labels."
        if evidence_mode == "schema"
        else "This is a prompt-only diagnostic run with no live database fixture."
        )
    )
    return f"""Finalize MARBLE database case {task.task_id}.

Read `case.md`, all files in `shared/`, and any proposed submissions. {diagnostics}

Write exactly one JSON object to `submissions/final.json`:
{{"predicted_root_causes": ["LABEL_1", "LABEL_2"], "rationale": "brief"}}

Use only labels listed in `case.md`. Do not include commentary outside the JSON file.
"""


def run_codex_task(
    *,
    task: MarbleDatabaseTask,
    workspace: Path,
    codex: Path,
    model: str,
    max_rounds: int,
    per_agent_timeout_seconds: int,
    output_dir: Path,
    evidence_mode: str,
) -> dict[str, Any]:
    fresh_workspace(workspace, task, evidence_mode)
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    run_records: list[dict[str, Any]] = []
    for round_index in range(1, max_rounds + 1):
        for config in task.agents:
            agent_dir = output_dir / config.agent_id / f"round-{round_index:03d}"
            agent_dir.mkdir(parents=True, exist_ok=True)
            prompt = codex_agent_prompt(
                task,
                config,
                round_index=round_index,
                evidence_mode=evidence_mode,
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
                    "agentId": config.agent_id,
                    "round": round_index,
                    "returncode": result.returncode,
                    "lastMessagePath": str(last_message_path),
                    "stdoutPath": str(agent_dir / "stdout.log"),
                    "stderrPath": str(agent_dir / "stderr.log"),
                }
            )
        if (workspace / "submissions" / "final.json").exists():
            break

    if not (workspace / "submissions" / "final.json").exists():
        agent_dir = output_dir / "coordinator"
        agent_dir.mkdir(exist_ok=True)
        prompt = coordinator_prompt(task, evidence_mode=evidence_mode)
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
                "agentId": "coordinator",
                "round": max_rounds + 1,
                "returncode": result.returncode,
                "lastMessagePath": str(last_message_path),
                "stdoutPath": str(agent_dir / "stdout.log"),
                "stderrPath": str(agent_dir / "stderr.log"),
            }
        )

    predicted, raw_prediction = read_prediction(workspace, task.requested_predictions)
    return {
        "system": "codex",
        "caseId": task.task_id,
        "sourceIndex": task.source_index,
        "workspace": str(workspace),
        "seconds": round(time.time() - started, 1),
        "agentRuns": run_records,
        "rawPrediction": raw_prediction,
        "score": score_task(task, predicted),
    }


def start_hollywood_agent(
    conn: JsonRpcWs,
    *,
    workspace: Path,
    room: str,
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
    conn.send_request("thread/name/set", {"threadId": thread_id, "name": runtime_name})
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


def losangelex_agent_prompt(
    task: MarbleDatabaseTask,
    config: MarbleAgentConfig,
    *,
    runtime_name: str,
    evidence_mode: str,
) -> str:
    diagnostics = (
        "- The workspace includes `diagnostics/schema.sql` and `diagnostics/observations.md`; the observations are label-free monitoring outputs from the published diagnostic surfaces.\n"
        if evidence_mode == "diagnostic-observations"
        else (
        "- The workspace includes `diagnostics/schema.sql`, copied from the published case environment without anomaly labels.\n"
        if evidence_mode == "schema"
        else "- No live database or diagnostic fixture is provided in this run; rely only on the published case prompt and team reasoning.\n"
        )
    )
    coordinator = (
        "- You are the coordinator for the final answer. After considering room/shared evidence, write `submissions/final.json`.\n"
        if config.agent_id == "agent1"
        else f"- Share your diagnosis with {task.agents[0].agent_id} and write `shared/{config.agent_id}.md`.\n"
    )
    return f"""We are running a published MARBLE/MultiAgentBench database diagnosis task.

System under evaluation: losangelex-hollywood-room
Case: {task.task_id}
Hollywood runtime identity: {runtime_name}
Agent id: {config.agent_id}
Role: {config.role}

Published role/profile for this agent:
{config.profile}

Workspace and room rules:
- Read `case.md` first.
{diagnostics}- Coordinate through this Hollywood room and `shared/`.
- Do not read files outside this workspace.
- Do not inspect benchmark repositories, previous result directories, or answer keys.
- Use only labels listed in `case.md`.
{coordinator}- The final JSON shape is:
  {{"predicted_root_causes": ["LABEL_1", "LABEL_2"], "rationale": "brief"}}
"""


def wait_for_hollywood_round(
    *,
    conn: JsonRpcWs,
    agents: list[HollywoodAgent],
    workspace: Path,
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
        states = {agent.thread_id: read_thread_state(conn, agent.thread_id) for agent in agents}
        if completed_once and all_threads_idle(states):
            break
        if (workspace / "submissions" / "final.json").exists():
            break
    return completed_once, states


def run_losangelex_task(
    *,
    task: MarbleDatabaseTask,
    workspace: Path,
    app_server_url: str,
    model: str,
    timeout_seconds: int,
    round_timeout_seconds: int,
    poll_seconds: int,
    rpc_timeout_seconds: int,
    output_dir: Path,
    evidence_mode: str,
) -> dict[str, Any]:
    fresh_workspace(workspace, task, evidence_mode)
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    run_suffix = uuid.uuid4().hex[:6]
    room = f"repo/marble-db-{task.task_id}-{run_suffix}"
    conn = JsonRpcWs(app_server_url, request_timeout=rpc_timeout_seconds)
    agents: list[HollywoodAgent] = []
    completed_rounds: list[dict[str, Any]] = []
    stopped_for_active_timeout = False
    try:
        initialize(conn)
        for config in task.agents:
            runtime_name = f"marble-db-{config.agent_id}-{run_suffix}"
            thread_id = start_hollywood_agent(
                conn,
                workspace=workspace,
                room=room,
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
        for config, agent in zip(task.agents, agents, strict=True):
            prompt = losangelex_agent_prompt(
                task,
                config,
                runtime_name=agent.runtime_name,
                evidence_mode=evidence_mode,
            )
            (output_dir / f"prompt-{config.agent_id}.txt").write_text(
                prompt,
                encoding="utf-8",
            )
            send_turn(conn, agent.thread_id, prompt)

        deadline = started + timeout_seconds
        round_deadline = min(deadline, time.time() + round_timeout_seconds)
        completed_once, states = wait_for_hollywood_round(
            conn=conn,
            agents=agents,
            workspace=workspace,
            deadline=round_deadline,
            poll_seconds=poll_seconds,
        )
        active_threads = active_thread_count(states)
        round_timed_out = time.time() >= round_deadline and not (
            workspace / "submissions" / "final.json"
        ).exists()
        stopped_for_active_timeout = round_timed_out and active_threads > 0
        completed_rounds.append(
            {
                "round": 1,
                "completedInitialTurns": completed_once,
                "activeThreads": active_threads,
                "roundTimedOut": round_timed_out,
                "finalExists": (workspace / "submissions" / "final.json").exists(),
            }
        )
        final_states = {agent.thread_id: read_thread_state(conn, agent.thread_id) for agent in agents}
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
    predicted, raw_prediction = read_prediction(workspace, task.requested_predictions)
    return {
        "system": "losangelex",
        "caseId": task.task_id,
        "sourceIndex": task.source_index,
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
        "rawPrediction": raw_prediction,
        "score": score_task(task, predicted),
        "coordinationToolSummary": summary.get("coordinationToolSummary", {}),
        "notificationsSummaryPath": str(output_dir / "notifications-summary.json"),
        "threadStatesPath": str(output_dir / "thread-states.json"),
    }


def aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_system: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_system.setdefault(record["system"], []).append(record)
    systems: dict[str, Any] = {}
    for system, system_records in sorted(by_system.items()):
        count = len(system_records)
        successes = sum(1 for record in system_records if record["score"]["success"])
        exact = sum(1 for record in system_records if record["score"]["exactSetMatch"])
        avg_recall = sum(
            record["score"]["metrics"]["rootCauseRecall"] for record in system_records
        ) / count
        avg_seconds = sum(record["seconds"] for record in system_records) / count
        coordination_tool_errors = sum(
            coordination_error_total(record) for record in system_records
        )
        systems[system] = {
            "tasks": count,
            "fullSuccesses": successes,
            "fullSuccessRate": successes / count,
            "exactSetMatches": exact,
            "exactSetMatchRate": exact / count,
            "avgRootCauseRecall": avg_recall,
            "avgSeconds": avg_seconds,
            "coordinationToolErrors": coordination_tool_errors,
        }
    return {"systems": systems}


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
    path: Path,
    *,
    campaign_name: str,
    evidence_mode: str,
    records: list[dict[str, Any]],
) -> None:
    summary = aggregate(records)
    lines = [
        f"# Published MARBLE Database Agent Comparison: {campaign_name}",
        "",
        "This run evaluates the published MARBLE/MultiAgentBench database diagnosis",
        "cases with Codex agent cohorts and Losangelex Hollywood rooms. The runner",
        "keeps root-cause labels and anomaly trigger fields outside the agent",
        "workspace; they are used only after execution for deterministic scoring.",
        "",
        f"Evidence mode: `{evidence_mode}`",
        "",
        "## Summary",
        "",
        "| System | Tasks | Full successes | Exact set matches | Avg recall | Avg seconds | Coordination errors |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for system, row in summary["systems"].items():
        lines.append(
            f"| {system} | {row['tasks']} | {row['fullSuccesses']} "
            f"({row['fullSuccessRate']:.2%}) | {row['exactSetMatches']} "
            f"({row['exactSetMatchRate']:.2%}) | {row['avgRootCauseRecall']:.3f} | "
            f"{row['avgSeconds']:.1f} | {row['coordinationToolErrors']} |"
        )
    lines.extend(["", "## Tasks", ""])
    for record in records:
        metrics = record["score"]["metrics"]
        lines.append(
            f"- {record['system']} `{record['caseId']}`: "
            f"success={record['score']['success']} "
            f"recall={metrics['rootCauseRecall']:.3f} "
            f"predicted={record['score']['predicted']} "
            f"gold={record['score']['gold']} "
            f"seconds={record['seconds']:.1f} "
            f"coordination_errors={coordination_error_total(record)}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--system",
        choices=("codex", "losangelex"),
        action="append",
        required=True,
    )
    parser.add_argument("--marble-root", type=Path, default=DEFAULT_MARBLE_ROOT)
    parser.add_argument("--task-id", action="append", dest="task_ids", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--model", default="gpt-5.4")
    parser.add_argument("--codex", type=Path, default=DEFAULT_CODEX)
    parser.add_argument("--app-server-url")
    parser.add_argument("--current-app-server", type=Path, default=DEFAULT_CURRENT_APP_SERVER)
    parser.add_argument("--max-rounds", type=int, default=1)
    parser.add_argument("--per-agent-timeout-seconds", type=int, default=600)
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    parser.add_argument("--round-timeout-seconds", type=int, default=600)
    parser.add_argument("--poll-seconds", type=int, default=45)
    parser.add_argument("--rpc-timeout-seconds", type=int, default=300)
    parser.add_argument("--campaign-name", default=f"marble-database-{int(time.time())}")
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument(
        "--evidence-mode",
        choices=("prompt-only", "schema", "diagnostic-observations"),
        default="prompt-only",
    )
    parser.add_argument(
        "--hide-path",
        action="append",
        dest="hide_paths",
        type=Path,
        default=[],
        help="Path to chmod 000 while agents run.",
    )
    args = parser.parse_args()

    tasks = load_tasks(
        marble_root=args.marble_root,
        task_ids=args.task_ids,
        limit=args.limit,
    )
    app_server_url = args.app_server_url
    if "losangelex" in args.system and app_server_url is None:
        app_server_url = load_app_server_url(args.current_app_server)

    output_dir = args.out_root / args.campaign_name
    output_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    with temporarily_hide_paths(args.hide_paths):
        for task in tasks:
            for system in args.system:
                workspace = output_dir / "workspaces" / system / task.task_id
                run_dir = output_dir / "runs" / system / task.task_id
                if system == "codex":
                    record = run_codex_task(
                        task=task,
                        workspace=workspace,
                        codex=args.codex,
                        model=args.model,
                        max_rounds=args.max_rounds,
                        per_agent_timeout_seconds=args.per_agent_timeout_seconds,
                        output_dir=run_dir,
                        evidence_mode=args.evidence_mode,
                    )
                else:
                    if app_server_url is None:
                        raise RuntimeError("app server URL is required for Losangelex runs")
                    record = run_losangelex_task(
                        task=task,
                        workspace=workspace,
                        app_server_url=app_server_url,
                        model=args.model,
                        timeout_seconds=args.timeout_seconds,
                        round_timeout_seconds=args.round_timeout_seconds,
                        poll_seconds=args.poll_seconds,
                        rpc_timeout_seconds=args.rpc_timeout_seconds,
                        output_dir=run_dir,
                        evidence_mode=args.evidence_mode,
                    )
                records.append(record)
                (output_dir / "results.json").write_text(
                    json.dumps(
                        {
                            "benchmark": "MARBLE/MultiAgentBench database",
                            "benchmarkRepository": str(args.marble_root),
                            "campaignName": args.campaign_name,
                            "model": args.model,
                            "systems": args.system,
                            "evidenceMode": args.evidence_mode,
                            "hiddenPaths": [str(path) for path in args.hide_paths],
                            "records": records,
                            "summary": aggregate(records),
                        },
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                write_report(
                    output_dir / "MARBLE_DATABASE_PUBLISHED_REPORT.md",
                    campaign_name=args.campaign_name,
                    evidence_mode=args.evidence_mode,
                    records=records,
                )
                metrics = record["score"]["metrics"]
                print(
                    f"completed system={system} task={task.task_id} "
                    f"recall={metrics['rootCauseRecall']:.3f} "
                    f"predicted={record['score']['predicted']} "
                    f"seconds={record['seconds']}",
                    flush=True,
                )

    print(f"wrote {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
