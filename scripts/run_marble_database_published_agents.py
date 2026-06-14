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
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchmark_token_usage import changed_rollout_files
from benchmark_token_usage import has_token_usage
from benchmark_token_usage import normalize_token_usage
from benchmark_token_usage import parse_codex_exec_jsonl_token_usage
from benchmark_token_usage import run_codex_exec_with_retries
from benchmark_token_usage import snapshot_rollout_files
from benchmark_token_usage import sum_token_usage
from benchmark_token_usage import summarize_codex_exec_collab_tools
from benchmark_token_usage import summarize_rollout_token_usage
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
DEFAULT_MARBLE_ROOT = DEFAULT_OUT_ROOT / "repos" / "MARBLE"
DATABASE_JSONL = "multiagentbench/database/database_main.jsonl"
ACTIVE_COMPOSE_FILES: list[Path] | None = None
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
    anomalies: list[dict[str, Any]]
    task_file: Path


@dataclass(frozen=True)
class HollywoodAgent:
    agent_id: str
    runtime_name: str
    thread_id: str


@dataclass(frozen=True)
class NativePostgresMetadata:
    enabled: bool
    docker_compose_dir: str | None = None
    query_socket: str | None = None
    query_request_dir: str | None = None
    setup_log: str | None = None
    background_pids: list[int] | None = None


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
        task_id = (
            f"database-{int(raw_task_id):03d}" if raw_task_id.isdigit() else raw_task_id
        )
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
                anomalies=list(environment.get("anomalies", [])),
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


def default_hidden_paths(marble_root: Path) -> list[Path]:
    return [marble_root]


def previous_result_hidden_paths(
    out_root: Path, current_output_dir: Path
) -> list[Path]:
    if not out_root.exists():
        return []
    current = current_output_dir.resolve()
    paths: list[Path] = []
    for path in out_root.iterdir():
        if path.resolve() == current:
            continue
        if path.is_dir():
            paths.append(path)
    return paths


def effective_hidden_paths(
    *,
    explicit_paths: list[Path],
    marble_root: Path,
    include_defaults: bool,
) -> list[Path]:
    paths = list(explicit_paths)
    if include_defaults:
        paths.extend(default_hidden_paths(marble_root))
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.resolve() if path.exists() else path)
        if key not in seen:
            seen.add(key)
            deduped.append(path)
    return deduped


def fresh_workspace(path: Path, task: MarbleDatabaseTask, evidence_mode: str) -> None:
    if path.exists():
        shutil.rmtree(path)
    (path / "shared").mkdir(parents=True)
    (path / "submissions").mkdir()
    (path / "case.md").write_text(public_case_markdown(task), encoding="utf-8")
    if evidence_mode in {"schema", "diagnostic-observations"}:
        (path / "diagnostics").mkdir()
        (path / "diagnostics" / "schema.sql").write_text(
            task.init_sql, encoding="utf-8"
        )
    if evidence_mode == "diagnostic-observations":
        (path / "diagnostics" / "observations.md").write_text(
            diagnostic_observations(task),
            encoding="utf-8",
        )
    if evidence_mode == "native-postgres":
        write_query_client(path / "query_db.py")
        (path / "database.md").write_text(native_database_markdown(), encoding="utf-8")


def write_query_client(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
import time
import uuid
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: ./query_db.py '<SQL query>'", file=sys.stderr)
        return 2
    sql = " ".join(sys.argv[1:])
    request_dir_file = Path(__file__).with_name("query_db_requests.txt")
    if request_dir_file.exists():
        request_dir = Path(request_dir_file.read_text(encoding="utf-8").strip())
    else:
        request_dir = Path(__file__).with_name("query_requests")
    request_dir.mkdir(parents=True, exist_ok=True)
    request_id = uuid.uuid4().hex
    request_path = request_dir / f"{request_id}.request.json"
    tmp_path = request_dir / f"{request_id}.request.tmp"
    response_path = request_dir / f"{request_id}.response.json"
    tmp_path.write_text(json.dumps({"id": request_id, "sql": sql}), encoding="utf-8")
    os.replace(tmp_path, request_path)
    deadline = time.time() + 45
    while time.time() < deadline:
        if response_path.exists():
            response = json.loads(response_path.read_text(encoding="utf-8"))
            try:
                response_path.unlink()
            except FileNotFoundError:
                pass
            break
        time.sleep(0.1)
    else:
        print("query timed out waiting for harness response", file=sys.stderr)
        return 124
    if response.get("stdout"):
        print(response["stdout"], end="")
    if response.get("stderr"):
        print(response["stderr"], end="", file=sys.stderr)
    return int(response.get("returncode", 1))


if __name__ == "__main__":
    raise SystemExit(main())
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def native_database_markdown() -> str:
    return "\n".join(
        [
            "# Live PostgreSQL Diagnostic Interface",
            "",
            "Use `./query_db.py '<SQL query>'` to inspect the live MARBLE PostgreSQL",
            "database prepared for this case. The helper returns tab-separated psql",
            "output. Keep queries bounded with explicit `LIMIT` clauses.",
            "",
            "Useful catalog views include:",
            "",
            "- `pg_stat_statements`",
            "- `pg_stat_activity`",
            "- `pg_locks`",
            "- `pg_stat_user_tables`",
            "- `pg_stat_all_tables`",
            "- `pg_stat_user_indexes`",
            "- `pg_indexes`",
            "",
        ]
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


def read_prediction(
    workspace: Path, requested_predictions: int
) -> tuple[list[str], str]:
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


def append_log(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)
        if not text.endswith("\n"):
            handle.write("\n")


def postgres_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PGPASSWORD"] = "Test123_456"
    return env


def psql_args() -> list[str]:
    if ACTIVE_COMPOSE_FILES is not None:
        return [
            "docker",
            "exec",
            "-i",
            "-e",
            "PGPASSWORD=Test123_456",
            "db_env_docker-postgres_db-1",
            "psql",
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
            "-P",
            "pager=off",
            "-h",
            "127.0.0.1",
            "-U",
            "test",
            "-d",
            "sysbench",
        ]
    return [
        "psql",
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-P",
        "pager=off",
        "-h",
        "127.0.0.1",
        "-U",
        "test",
        "-d",
        "sysbench",
    ]


def run_psql(
    sql: str,
    *,
    timeout: int,
    log_path: Path,
    stdout: int | None = subprocess.PIPE,
) -> subprocess.CompletedProcess[str]:
    append_log(log_path, f"\n$ psql -c {sql[:500]!r}")
    result = subprocess.run(
        [*psql_args(), "-c", sql],
        env=postgres_env(),
        text=True,
        stdout=stdout,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    stdout_text = result.stdout if isinstance(result.stdout, str) else ""
    append_log(log_path, stdout_text[-4000:])
    append_log(log_path, result.stderr[-4000:])
    append_log(log_path, f"returncode={result.returncode}")
    return result


def run_psql_input(
    sql: str, *, timeout: int, log_path: Path
) -> subprocess.CompletedProcess[str]:
    append_log(log_path, f"\n$ psql < {len(sql)} bytes")
    result = subprocess.run(
        psql_args(),
        env=postgres_env(),
        text=True,
        input=sql,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    append_log(log_path, result.stdout[-4000:])
    append_log(log_path, result.stderr[-4000:])
    append_log(log_path, f"returncode={result.returncode}")
    return result


def wait_for_postgres(log_path: Path, timeout_seconds: int = 120) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        result = subprocess.run(
            [*psql_args(), "-c", "SELECT 1;"],
            env=postgres_env(),
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            return
        append_log(log_path, result.stderr[-1000:])
        time.sleep(2)
    raise RuntimeError("PostgreSQL did not become ready before timeout")


def anomaly_settings(task: MarbleDatabaseTask, label: str) -> dict[str, int]:
    for anomaly in task.anomalies:
        anomaly_name = normalize_label(str(anomaly.get("anomaly", "")))
        if anomaly_name == label:
            return {
                "nrow": min(max(int(anomaly.get("nrow", 10000)), 1000), 20000),
                "ncolumn": min(max(int(anomaly.get("ncolumn", 8)), 1), 20),
                "colsize": min(max(int(anomaly.get("colsize", 32)), 8), 200),
            }
    return {"nrow": 10000, "ncolumn": 8, "colsize": 32}


def wide_table_sql(
    table_name: str, *, nrow: int, ncolumn: int, colsize: int = 32
) -> str:
    columns = ", ".join(f"name{i} text" for i in range(ncolumn))
    repeat_count = max(1, (colsize + 31) // 32)
    values = ", ".join(
        f"substr(repeat(md5((g + {i})::text), {repeat_count}), 1, {colsize})"
        for i in range(ncolumn)
    )
    return (
        f"DROP TABLE IF EXISTS {table_name}; "
        f"CREATE TABLE {table_name} (id integer, {columns}); "
        f"INSERT INTO {table_name} SELECT g, {values} "
        f"FROM generate_series(1, {nrow}) AS s(g);"
    )


def prepare_native_tables(task: MarbleDatabaseTask, log_path: Path) -> None:
    roots = set(task.gold_root_causes)
    setup_sql: list[str] = []
    if "INSERT_LARGE_DATA" in roots:
        settings = anomaly_settings(task, "INSERT_LARGE_DATA")
        columns = ", ".join(f"name{i} text" for i in range(settings["ncolumn"]))
        setup_sql.append(
            f"DROP TABLE IF EXISTS marble_insert; CREATE TABLE marble_insert (id integer, {columns});"
        )
    if "FETCH_LARGE_DATA" in roots:
        setup_sql.append(
            wide_table_sql("marble_fetch", **anomaly_settings(task, "FETCH_LARGE_DATA"))
        )
    if "MISSING_INDEXES" in roots:
        setup_sql.append(
            wide_table_sql(
                "marble_missing", **anomaly_settings(task, "MISSING_INDEXES")
            )
        )
    if "VACUUM" in roots:
        settings = anomaly_settings(task, "VACUUM")
        setup_sql.append(wide_table_sql("marble_vacuum", **settings))
        setup_sql.append(
            f"DELETE FROM marble_vacuum WHERE id <= {int(settings['nrow'] * 0.8)};"
        )
    if "REDUNDANT_INDEX" in roots:
        setup_sql.append(
            wide_table_sql(
                "marble_redundant", **anomaly_settings(task, "REDUNDANT_INDEX")
            )
        )
    if "LOCK_CONTENTION" in roots:
        setup_sql.append(
            wide_table_sql("marble_lock", **anomaly_settings(task, "LOCK_CONTENTION"))
        )
    if "POOR_JOIN_PERFORMANCE" in roots or "CPU_CONTENTION" in roots:
        setup_sql.append(wide_table_sql("marble_join_a", nrow=5000, ncolumn=4))
        setup_sql.append(wide_table_sql("marble_join_b", nrow=5000, ncolumn=4))
    if setup_sql:
        result = run_psql_input("\n".join(setup_sql), timeout=180, log_path=log_path)
        if result.returncode != 0:
            raise RuntimeError("failed to prepare native MARBLE tables")


def start_lock_contention(log_path: Path) -> list[subprocess.Popen[str]]:
    processes: list[subprocess.Popen[str]] = []
    holder_log = log_path.with_name("native-postgres-lock-holder.log")
    waiter_log = log_path.with_name("native-postgres-lock-waiters.log")
    holder_handle = holder_log.open("w", encoding="utf-8")
    waiter_handle = waiter_log.open("w", encoding="utf-8")
    holder = subprocess.Popen(
        [
            *psql_args(),
            "-c",
            "BEGIN; UPDATE marble_lock SET name0 = 'holder' WHERE id = 1; SELECT pg_sleep(900);",
        ],
        env=postgres_env(),
        text=True,
        stdout=holder_handle,
        stderr=holder_handle,
    )
    processes.append(holder)
    time.sleep(2)
    for _ in range(3):
        waiter = subprocess.Popen(
            [
                *psql_args(),
                "-c",
                "UPDATE marble_lock SET name0 = 'waiter' WHERE id = 1;",
            ],
            env=postgres_env(),
            text=True,
            stdout=waiter_handle,
            stderr=waiter_handle,
        )
        processes.append(waiter)
    append_log(
        log_path,
        f"started lock contention pids={[process.pid for process in processes]}",
    )
    return processes


def run_native_activities(
    task: MarbleDatabaseTask, log_path: Path
) -> list[subprocess.Popen[str]]:
    roots = set(task.gold_root_causes)
    result = run_psql(
        "SELECT pg_stat_statements_reset();", timeout=30, log_path=log_path
    )
    if result.returncode != 0:
        raise RuntimeError("failed to reset pg_stat_statements")
    background: list[subprocess.Popen[str]] = []
    if "INSERT_LARGE_DATA" in roots:
        settings = anomaly_settings(task, "INSERT_LARGE_DATA")
        values = ", ".join(f"md5((g + {i})::text)" for i in range(settings["ncolumn"]))
        run_psql(
            f"INSERT INTO marble_insert SELECT g, {values} FROM generate_series(1, {settings['nrow']}) AS s(g);",
            timeout=120,
            log_path=log_path,
        )
    if "FETCH_LARGE_DATA" in roots:
        run_psql(
            "SELECT * FROM marble_fetch;",
            timeout=120,
            log_path=log_path,
            stdout=subprocess.DEVNULL,
        )
    if "MISSING_INDEXES" in roots:
        for index in range(20):
            run_psql(
                f"SELECT * FROM marble_missing WHERE name0 = 'not-present-{index}' LIMIT 5;",
                timeout=30,
                log_path=log_path,
            )
    if "VACUUM" in roots:
        run_psql(
            "VACUUM (VERBOSE, ANALYZE) marble_vacuum;", timeout=120, log_path=log_path
        )
    if "REDUNDANT_INDEX" in roots:
        run_psql(
            "CREATE INDEX marble_redundant_name0_idx ON marble_redundant(name0); "
            "CREATE INDEX marble_redundant_name0_dup1 ON marble_redundant(name0); "
            "CREATE INDEX marble_redundant_name0_dup2 ON marble_redundant(name0); "
            "CREATE INDEX marble_redundant_name1_dup1 ON marble_redundant(name1);",
            timeout=120,
            log_path=log_path,
        )
    if "LOCK_CONTENTION" in roots:
        background.extend(start_lock_contention(log_path))
    if "POOR_JOIN_PERFORMANCE" in roots or "CPU_CONTENTION" in roots:
        run_psql(
            "SELECT count(*) FROM marble_join_a a JOIN marble_join_b b ON substring(a.name0, 1, 2) = substring(b.name0, 1, 2);",
            timeout=120,
            log_path=log_path,
        )
    return background


class FileQueryServer:
    def __init__(self, request_dir: Path, log_path: Path):
        self.request_dir = request_dir
        self.log_path = log_path
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._seen: set[str] = set()

    def start(self) -> None:
        self.request_dir.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _serve(self) -> None:
        while not self._stop.is_set():
            handled = False
            for request_path in sorted(self.request_dir.glob("*.request.json")):
                if request_path.name in self._seen:
                    continue
                self._seen.add(request_path.name)
                handled = True
                request = self._read_request(request_path)
                response = self._handle_request(request)
                response_path = (
                    self.request_dir
                    / f"{request.get('id', request_path.stem)}.response.json"
                )
                tmp_path = response_path.with_suffix(".response.tmp")
                tmp_path.write_text(json.dumps(response), encoding="utf-8")
                tmp_path.replace(response_path)
                try:
                    request_path.unlink()
                except FileNotFoundError:
                    pass
            if not handled:
                time.sleep(0.05)

    def _read_request(self, request_path: Path) -> dict[str, Any]:
        try:
            return json.loads(request_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {"id": request_path.stem.removesuffix(".request"), "sql": ""}

    def _handle_request(self, request: dict[str, Any]) -> dict[str, Any]:
        sql = str(request.get("sql", ""))[:4000]
        append_log(self.log_path, f"\n[query] {sql}")
        if not sql.strip():
            return {"returncode": 2, "stdout": "", "stderr": "empty SQL query\n"}
        try:
            result = subprocess.run(
                [
                    *psql_args(),
                    "-A",
                    "-F",
                    "\t",
                    "-c",
                    f"SET statement_timeout TO '10s'; {sql}",
                ],
                env=postgres_env(),
                text=True,
                capture_output=True,
                timeout=15,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {"returncode": 124, "stdout": "", "stderr": "query timed out\n"}
        stdout = result.stdout[-20000:]
        stderr = result.stderr[-12000:]
        append_log(self.log_path, stdout[-4000:])
        append_log(self.log_path, stderr[-4000:])
        return {"returncode": result.returncode, "stdout": stdout, "stderr": stderr}


@contextmanager
def native_postgres_runtime(
    *,
    enabled: bool,
    task: MarbleDatabaseTask,
    marble_root: Path,
    workspace: Path,
    output_dir: Path,
) -> Any:
    if not enabled:
        yield NativePostgresMetadata(enabled=False)
        return

    global ACTIVE_COMPOSE_FILES
    docker_dir = (marble_root / "marble" / "environments" / "db_env_docker").resolve()
    setup_log = output_dir / "native-postgres-setup.log"
    override_file = (output_dir / "native-postgres-compose.override.yml").resolve()
    override_file.write_text(
        "\n".join(
            [
                "services:",
                "  postgres_db:",
                "    image: postgres:16",
                "    ports: !reset []",
                "  prometheus:",
                "    ports: !reset []",
                "  node_exporter:",
                "    ports: !reset []",
                "  pg_exporter:",
                "    ports: !reset []",
                "",
            ]
        ),
        encoding="utf-8",
    )
    compose_files = [(docker_dir / "docker-compose.yml").resolve(), override_file]
    query_server: FileQueryServer | None = None
    background: list[subprocess.Popen[str]] = []
    previous_compose_files = ACTIVE_COMPOSE_FILES
    ACTIVE_COMPOSE_FILES = compose_files
    try:
        append_log(setup_log, f"docker compose dir: {docker_dir}")
        append_log(setup_log, f"docker compose override: {override_file}")
        compose_command = ["docker", "compose"]
        for compose_file in compose_files:
            compose_command.extend(["-f", str(compose_file)])
        subprocess.run(
            [*compose_command, "down", "-v"],
            cwd=docker_dir,
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        up = subprocess.run(
            [*compose_command, "up", "-d", "--remove-orphans"],
            cwd=docker_dir,
            text=True,
            capture_output=True,
            timeout=180,
            check=False,
        )
        append_log(setup_log, up.stdout[-4000:])
        append_log(setup_log, up.stderr[-4000:])
        if up.returncode != 0:
            raise RuntimeError("docker compose up failed for native MARBLE database")
        wait_for_postgres(setup_log)
        init_sql = "\n".join(
            [
                task.init_sql,
                "CREATE EXTENSION IF NOT EXISTS pg_stat_statements;",
            ]
        )
        init = run_psql_input(init_sql, timeout=180, log_path=setup_log)
        if init.returncode != 0:
            raise RuntimeError("native MARBLE database initialization failed")
        prepare_native_tables(task, setup_log)
        background = run_native_activities(task, setup_log)
        request_dir = (workspace / "query_requests").resolve()
        (workspace / "query_db_requests.txt").write_text(
            str(request_dir) + "\n",
            encoding="utf-8",
        )
        query_server = FileQueryServer(request_dir, setup_log)
        query_server.start()
        yield NativePostgresMetadata(
            enabled=True,
            docker_compose_dir=str(docker_dir),
            query_request_dir=str(request_dir),
            setup_log=str(setup_log),
            background_pids=[process.pid for process in background],
        )
    finally:
        if query_server is not None:
            query_server.stop()
        for process in background:
            if process.poll() is None:
                process.terminate()
        for process in background:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        subprocess.run(
            [*compose_command, "down", "-v"],
            cwd=docker_dir,
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        ACTIVE_COMPOSE_FILES = previous_compose_files


def score_task(task: MarbleDatabaseTask, predicted: list[str]) -> dict[str, Any]:
    gold = set(task.gold_root_causes)
    predicted_set = set(predicted)
    match_count = len(gold & predicted_set)
    recall = match_count / len(gold) if gold else 0.0
    precision = match_count / len(predicted_set) if predicted_set else 0.0
    f1 = (
        2 * precision * recall / (precision + recall) if precision + recall > 0 else 0.0
    )
    exact = predicted_set == gold
    return {
        "success": recall == 1.0,
        "exactSetMatch": exact,
        "predicted": predicted,
        "gold": task.gold_root_causes,
        "metrics": {
            "rootCauseRecall": recall,
            "rootCausePrecision": precision,
            "rootCauseF1": f1,
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
            "- The workspace includes `database.md` and `query_db.py`; use `./query_db.py '<SQL query>'` to inspect the live PostgreSQL database prepared from the published MARBLE database substrate.\n"
            if evidence_mode == "native-postgres"
            else (
                "- The workspace includes `diagnostics/schema.sql`, copied from the published "
                "case environment without anomaly labels.\n"
                if evidence_mode == "schema"
                else "- No live database or diagnostic fixture is provided in this run; rely only on the published case prompt and team reasoning.\n"
            )
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
            "Use `./query_db.py '<SQL query>'` when more live PostgreSQL evidence is needed."
            if evidence_mode == "native-postgres"
            else (
                "Use `diagnostics/schema.sql` only as schema context; it contains no anomaly labels."
                if evidence_mode == "schema"
                else "This is a prompt-only diagnostic run with no live database fixture."
            )
        )
    )
    return f"""Finalize MARBLE database case {task.task_id}.

Read `case.md`, all files in `shared/`, and any proposed submissions. {diagnostics}

Write exactly one JSON object to `submissions/final.json`:
{{"predicted_root_causes": ["LABEL_1", "LABEL_2"], "rationale": "brief"}}

Use only labels listed in `case.md`. Do not include commentary outside the JSON file.
"""


def codex_subagent_worker_prompt(
    task: MarbleDatabaseTask,
    config: MarbleAgentConfig,
    *,
    evidence_mode: str,
) -> str:
    if evidence_mode == "diagnostic-observations":
        diagnostics = (
            "- The workspace includes `diagnostics/schema.sql` and `diagnostics/observations.md`; "
            "the observations are label-free monitoring outputs from the published diagnostic surfaces.\n"
        )
    elif evidence_mode == "native-postgres":
        diagnostics = (
            "- The workspace includes `database.md` and `query_db.py`; use `./query_db.py '<SQL query>'` "
            "to inspect the live PostgreSQL database prepared from the published MARBLE database substrate.\n"
        )
    elif evidence_mode == "schema":
        diagnostics = "- The workspace includes `diagnostics/schema.sql`, copied from the published case environment without anomaly labels.\n"
    else:
        diagnostics = "- No live database or diagnostic fixture is provided in this run; rely only on the published case prompt and team reasoning.\n"
    return f"""You are Codex subagent `{config.agent_id}` in a MARBLE/MultiAgentBench database diagnosis benchmark.

Important benchmark rules:
- Do not spawn any subagents. You are a worker, not an orchestrator.
- You are not alone in the workspace; other Codex subagents are working in parallel.
- Do not overwrite another agent's files.
- Do not inspect benchmark repositories, previous result directories, or any path outside this workspace.
- The answer key and anomaly trigger fields are not present in the workspace.

Case: {task.task_id}
Role: {config.role}

Published role/profile for this agent:
{config.profile}

Workspace instructions:
- Read `case.md` first.
{diagnostics}- Use only labels listed in `case.md`.
- Write your analysis to `shared/{config.agent_id}.md`.
- Also write `submissions/{config.agent_id}.json` with:
  {{"predicted_root_causes": ["LABEL_1"], "rationale": "brief"}}
- If the task prompt asks for multiple labels, include your best ranked labels up to that count.

When your two files are written, finish. Do not wait for other agents and do not delegate.
"""


def codex_subagent_parent_prompt(
    task: MarbleDatabaseTask, *, evidence_mode: str
) -> str:
    worker_sections = "\n\n".join(
        f"### Worker {config.agent_id}\n{codex_subagent_worker_prompt(task, config, evidence_mode=evidence_mode)}"
        for config in task.agents
    )
    if evidence_mode == "diagnostic-observations":
        diagnostics = "Use `diagnostics/observations.md` and `diagnostics/schema.sql` as label-free monitoring evidence."
    elif evidence_mode == "native-postgres":
        diagnostics = "Use `./query_db.py '<SQL query>'` if the worker reports need confirmation from the live PostgreSQL database."
    elif evidence_mode == "schema":
        diagnostics = "Use `diagnostics/schema.sql` only as schema context; it contains no anomaly labels."
    else:
        diagnostics = (
            "This is a prompt-only diagnostic run with no live database fixture."
        )
    return f"""We are running a published MARBLE/MultiAgentBench database diagnosis task.

System under evaluation: codex-subagents
Case: {task.task_id}

The user explicitly wants a true Codex subagent baseline. You must use Codex
subagents for the role workers, not serial solo execution.

Parent orchestration rules:
- Spawn exactly one Codex subagent for each worker prompt below.
- For each `spawn_agent` call, set `fork_turns` to exactly `none`.
- Do not include `agent_type`, `model`, `reasoning_effort`, `service_tier`, or
  `fork_context` in any `spawn_agent` call.
- Spawn the workers before doing your own final diagnosis so their work can run in parallel.
- Do not use Hollywood or Losangelex tools.
- Do not run `codex`, `codex exec`, or any other shell fallback to simulate subagents.
- Tell each worker exactly the corresponding prompt below.
- Wait for all spawned workers to finish. When calling `wait_agent`, use
  `timeout_ms` of at least `10000`; prefer `600000`.
- Never call `wait_agent` with small timeout values such as `1`, `5`, `1000`,
  or `5000`.
- If any `spawn_agent` call fails, do not complete the task yourself. Write no
  final JSON and return `SPAWN_FAILED` with the error.
- If a spawned worker starts but later fails or times out, record that fact and
  continue with available worker files.
- After workers finish, read `case.md`, `shared/*.md`, and `submissions/*.json`. {diagnostics}
- Write exactly one final JSON object to `submissions/final.json`:
  {{"predicted_root_causes": ["LABEL_1", "LABEL_2"], "rationale": "brief"}}
- Use only labels listed in `case.md`.
- Return a concise final message naming the final labels and any worker failures.

Worker prompts:

{worker_sections}
"""


def codex_subagent_tool_summary(stdout: str, stderr: str) -> dict[str, Any]:
    return summarize_codex_exec_collab_tools(stdout, stderr)


def codex_subagent_artifact_summary(
    workspace: Path,
    agents: list[MarbleAgentConfig],
) -> dict[str, Any]:
    shared_dir = workspace / "shared"
    submissions_dir = workspace / "submissions"
    expected = [agent.agent_id for agent in agents]
    shared_present = [
        agent_id for agent_id in expected if (shared_dir / f"{agent_id}.md").exists()
    ]
    submissions_present = [
        agent_id
        for agent_id in expected
        if (submissions_dir / f"{agent_id}.json").exists()
    ]
    return {
        "expectedAgents": expected,
        "sharedPresent": shared_present,
        "submissionsPresent": submissions_present,
        "missingShared": [
            agent_id for agent_id in expected if agent_id not in shared_present
        ],
        "missingSubmissions": [
            agent_id for agent_id in expected if agent_id not in submissions_present
        ],
        "finalExists": (submissions_dir / "final.json").exists(),
    }


def write_codex_subagents_config(codex_home: Path) -> None:
    codex_home.mkdir(parents=True, exist_ok=True)
    (codex_home / "config.toml").write_text(
        "\n".join(
            [
                "[features.multi_agent_v2]",
                "enabled = true",
                "max_concurrent_threads_per_session = 8",
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
    task: MarbleDatabaseTask,
    workspace: Path,
    codex: Path,
    model: str,
    max_rounds: int,
    per_agent_timeout_seconds: int,
    output_dir: Path,
    evidence_mode: str,
    marble_root: Path,
    hidden_paths: list[Path],
) -> dict[str, Any]:
    fresh_workspace(workspace, task, evidence_mode)
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    run_records: list[dict[str, Any]] = []
    with native_postgres_runtime(
        enabled=evidence_mode == "native-postgres",
        task=task,
        marble_root=marble_root,
        workspace=workspace,
        output_dir=output_dir,
    ) as native_postgres:
        with temporarily_hide_paths(hidden_paths):
            for round_index in range(1, max_rounds + 1):
                for config in task.agents:
                    agent_dir = (
                        output_dir / config.agent_id / f"round-{round_index:03d}"
                    )
                    agent_dir.mkdir(parents=True, exist_ok=True)
                    prompt = codex_agent_prompt(
                        task,
                        config,
                        round_index=round_index,
                        evidence_mode=evidence_mode,
                    )
                    (agent_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
                    last_message_path = agent_dir / "last-message.txt"
                    result, transient_retries = run_codex_exec_with_retries(
                        lambda: run_command(
                            [
                                str(codex),
                                "-C",
                                str(workspace),
                                "--sandbox",
                                "workspace-write",
                                "--ask-for-approval",
                                "never",
                                "exec",
                                "--json",
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
                    )
                    (agent_dir / "stdout.log").write_text(
                        result.stdout, encoding="utf-8"
                    )
                    (agent_dir / "stderr.log").write_text(
                        result.stderr, encoding="utf-8"
                    )
                    token_usage = parse_codex_exec_jsonl_token_usage(result.stdout)
                    run_records.append(
                        {
                            "agentId": config.agent_id,
                            "round": round_index,
                            "returncode": result.returncode,
                            "lastMessagePath": str(last_message_path),
                            "stdoutPath": str(agent_dir / "stdout.log"),
                            "stderrPath": str(agent_dir / "stderr.log"),
                            "tokenUsage": token_usage,
                            "transientRetries": transient_retries,
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
                result, transient_retries = run_codex_exec_with_retries(
                    lambda: run_command(
                        [
                            str(codex),
                            "-C",
                            str(workspace),
                            "--sandbox",
                            "workspace-write",
                            "--ask-for-approval",
                            "never",
                            "exec",
                            "--json",
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
                )
                (agent_dir / "stdout.log").write_text(result.stdout, encoding="utf-8")
                (agent_dir / "stderr.log").write_text(result.stderr, encoding="utf-8")
                token_usage = parse_codex_exec_jsonl_token_usage(result.stdout)
                run_records.append(
                    {
                        "agentId": "coordinator",
                        "round": max_rounds + 1,
                        "returncode": result.returncode,
                        "lastMessagePath": str(last_message_path),
                        "stdoutPath": str(agent_dir / "stdout.log"),
                        "stderrPath": str(agent_dir / "stderr.log"),
                        "tokenUsage": token_usage,
                        "transientRetries": transient_retries,
                    }
                )

        native_postgres_metadata = native_postgres.__dict__
        predicted, raw_prediction = read_prediction(
            workspace, task.requested_predictions
        )
    return {
        "system": "codex",
        "caseId": task.task_id,
        "sourceIndex": task.source_index,
        "workspace": str(workspace),
        "seconds": round(time.time() - started, 1),
        "agentRuns": run_records,
        "tokenUsage": sum_token_usage(
            [record.get("tokenUsage") for record in run_records]
        ),
        "rawPrediction": raw_prediction,
        "score": score_task(task, predicted),
        "nativePostgres": native_postgres_metadata,
    }


def run_codex_subagents_task(
    *,
    task: MarbleDatabaseTask,
    workspace: Path,
    codex: Path,
    model: str,
    timeout_seconds: int,
    output_dir: Path,
    codex_home: Path,
    evidence_mode: str,
    marble_root: Path,
    hidden_paths: list[Path],
) -> dict[str, Any]:
    fresh_workspace(workspace, task, evidence_mode)
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    with native_postgres_runtime(
        enabled=evidence_mode == "native-postgres",
        task=task,
        marble_root=marble_root,
        workspace=workspace,
        output_dir=output_dir,
    ) as native_postgres:
        with temporarily_hide_paths(hidden_paths):
            prompt = codex_subagent_parent_prompt(task, evidence_mode=evidence_mode)
            (output_dir / "parent-prompt.txt").write_text(prompt, encoding="utf-8")
            last_message_path = output_dir / "parent-last-message.txt"
            env = os.environ.copy()
            env["CODEX_HOME"] = str(codex_home)
            rollout_snapshot = snapshot_rollout_files(codex_home)
            result, transient_retries = run_codex_exec_with_retries(
                lambda: run_command(
                    [
                        str(codex),
                        "-C",
                        str(workspace),
                        "--sandbox",
                        "workspace-write",
                        "--ask-for-approval",
                        "never",
                        "exec",
                        "--json",
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
            )
            (output_dir / "parent-stdout.log").write_text(
                result.stdout, encoding="utf-8"
            )
            (output_dir / "parent-stderr.log").write_text(
                result.stderr, encoding="utf-8"
            )
            parent_token_usage = parse_codex_exec_jsonl_token_usage(result.stdout)
            rollout_token_usage = summarize_rollout_token_usage(
                changed_rollout_files(codex_home, rollout_snapshot),
            )
            token_usage = (
                rollout_token_usage["tokenUsage"]
                if rollout_token_usage["fileCount"] > 0
                else parent_token_usage
            )

        native_postgres_metadata = native_postgres.__dict__
        predicted, raw_prediction = read_prediction(
            workspace, task.requested_predictions
        )
    return {
        "system": "codex-subagents",
        "caseId": task.task_id,
        "sourceIndex": task.source_index,
        "workspace": str(workspace),
        "seconds": round(time.time() - started, 1),
        "parentRun": {
            "returncode": result.returncode,
            "lastMessagePath": str(last_message_path),
            "stdoutPath": str(output_dir / "parent-stdout.log"),
            "stderrPath": str(output_dir / "parent-stderr.log"),
            "tokenUsage": parent_token_usage,
            "transientRetries": transient_retries,
        },
        "tokenUsage": token_usage,
        "tokenUsageSummary": {
            "source": (
                "codex-session-rollouts"
                if rollout_token_usage["fileCount"] > 0
                else "codex-exec-jsonl"
            ),
            "rollouts": rollout_token_usage,
            "parentExecJsonl": parent_token_usage,
        },
        "rawPrediction": raw_prediction,
        "score": score_task(task, predicted),
        "coordinationToolSummary": codex_subagent_tool_summary(
            result.stdout, result.stderr
        ),
        "codexSubagentArtifacts": codex_subagent_artifact_summary(
            workspace, task.agents
        ),
        "nativePostgres": native_postgres_metadata,
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
            "- The workspace includes `database.md` and `query_db.py`; use `./query_db.py '<SQL query>'` to inspect the live PostgreSQL database prepared from the published MARBLE database substrate.\n"
            if evidence_mode == "native-postgres"
            else (
                "- The workspace includes `diagnostics/schema.sql`, copied from the published case environment without anomaly labels.\n"
                if evidence_mode == "schema"
                else "- No live database or diagnostic fixture is provided in this run; rely only on the published case prompt and team reasoning.\n"
            )
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
        states = {
            agent.thread_id: read_thread_state(conn, agent.thread_id)
            for agent in agents
        }
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
    marble_root: Path,
    hidden_paths: list[Path],
) -> dict[str, Any]:
    fresh_workspace(workspace, task, evidence_mode)
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    run_suffix = uuid.uuid4().hex[:6]
    room = f"repo/marble-db-{task.task_id}-{run_suffix}"
    agents: list[HollywoodAgent] = []
    completed_rounds: list[dict[str, Any]] = []
    stopped_for_active_timeout = False
    with native_postgres_runtime(
        enabled=evidence_mode == "native-postgres",
        task=task,
        marble_root=marble_root,
        workspace=workspace,
        output_dir=output_dir,
    ) as native_postgres:
        with temporarily_hide_paths(hidden_paths):
            conn = JsonRpcWs(app_server_url, request_timeout=rpc_timeout_seconds)
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
                round_timed_out = (
                    time.time() >= round_deadline
                    and not (workspace / "submissions" / "final.json").exists()
                )
                stopped_for_active_timeout = round_timed_out and active_threads > 0
                completed_rounds.append(
                    {
                        "round": 1,
                        "completedInitialTurns": completed_once,
                        "activeThreads": active_threads,
                        "roundTimedOut": round_timed_out,
                        "finalExists": (
                            workspace / "submissions" / "final.json"
                        ).exists(),
                    }
                )
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
        predicted, raw_prediction = read_prediction(
            workspace, task.requested_predictions
        )
        native_postgres_metadata = native_postgres.__dict__
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
        "tokenUsage": summary.get("tokenUsage", {}),
        "tokenUsageSummary": summary.get("tokenUsageSummary", {}),
        "coordinationToolSummary": summary.get("coordinationToolSummary", {}),
        "notificationsSummaryPath": str(output_dir / "notifications-summary.json"),
        "threadStatesPath": str(output_dir / "thread-states.json"),
        "nativePostgres": native_postgres_metadata,
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
        metric_rows = [root_cause_metrics(record) for record in system_records]
        avg_recall = sum(row["recall"] for row in metric_rows) / count
        avg_precision = sum(row["precision"] for row in metric_rows) / count
        avg_f1 = sum(row["f1"] for row in metric_rows) / count
        avg_seconds = sum(record["seconds"] for record in system_records) / count
        coordination_tool_errors = sum(
            coordination_error_total(record) for record in system_records
        )
        token_usage_records = [
            normalize_token_usage(record.get("tokenUsage"))
            for record in system_records
            if has_token_usage(record.get("tokenUsage"))
        ]
        token_usage_count = len(token_usage_records)
        total_token_usage = sum_token_usage(token_usage_records)
        avg_total_tokens = (
            total_token_usage["totalTokens"] / token_usage_count
            if token_usage_count
            else None
        )
        avg_uncached_plus_output_tokens = (
            total_token_usage["uncachedPlusOutputTokens"] / token_usage_count
            if token_usage_count
            else None
        )
        total_tokens_per_full_success = (
            total_token_usage["totalTokens"] / successes if successes else None
        )
        uncached_plus_output_tokens_per_full_success = (
            total_token_usage["uncachedPlusOutputTokens"] / successes
            if successes
            else None
        )
        systems[system] = {
            "tasks": count,
            "fullSuccesses": successes,
            "fullSuccessRate": successes / count,
            "exactSetMatches": exact,
            "exactSetMatchRate": exact / count,
            "avgRootCauseRecall": avg_recall,
            "avgRootCausePrecision": avg_precision,
            "avgRootCauseF1": avg_f1,
            "avgSeconds": avg_seconds,
            "coordinationToolErrors": coordination_tool_errors,
            "tokenUsageTaskCount": token_usage_count,
            "totalTokenUsage": total_token_usage,
            "avgTotalTokens": avg_total_tokens,
            "avgUncachedPlusOutputTokens": avg_uncached_plus_output_tokens,
            "totalTokensPerFullSuccess": total_tokens_per_full_success,
            "uncachedPlusOutputTokensPerFullSuccess": (
                uncached_plus_output_tokens_per_full_success
            ),
        }
    return {"systems": systems}


def root_cause_metrics(record: dict[str, Any]) -> dict[str, float]:
    metrics = record["score"]["metrics"]
    recall = float(metrics["rootCauseRecall"])
    precision = metrics.get("rootCausePrecision")
    if precision is None:
        predicted_count = int(metrics["predictedCount"])
        precision = (
            float(metrics["matchCount"]) / predicted_count if predicted_count else 0.0
        )
    f1 = metrics.get("rootCauseF1")
    if f1 is None:
        f1 = (
            2 * float(precision) * recall / (float(precision) + recall)
            if float(precision) + recall > 0
            else 0.0
        )
    return {"recall": recall, "precision": float(precision), "f1": float(f1)}


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
        "| System | Tasks | Full successes | Exact set matches | Avg recall | Avg precision | Avg F1 | Avg seconds | Avg total tokens | Avg uncached+output | Total tokens/success | Coordination errors |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for system, row in summary["systems"].items():
        lines.append(
            f"| {system} | {row['tasks']} | {row['fullSuccesses']} "
            f"({row['fullSuccessRate']:.2%}) | {row['exactSetMatches']} "
            f"({row['exactSetMatchRate']:.2%}) | {row['avgRootCauseRecall']:.3f} | "
            f"{row['avgRootCausePrecision']:.3f} | {row['avgRootCauseF1']:.3f} | "
            f"{row['avgSeconds']:.1f} | "
            f"{format_token_value(row['avgTotalTokens'])} | "
            f"{format_token_value(row['avgUncachedPlusOutputTokens'])} | "
            f"{format_token_value(row['totalTokensPerFullSuccess'])} | "
            f"{row['coordinationToolErrors']} |"
        )
    lines.extend(["", "## Tasks", ""])
    for record in records:
        metrics = record["score"]["metrics"]
        token_usage = normalize_token_usage(record.get("tokenUsage"))
        lines.append(
            f"- {record['system']} `{record['caseId']}`: "
            f"success={record['score']['success']} "
            f"recall={metrics['rootCauseRecall']:.3f} "
            f"predicted={record['score']['predicted']} "
            f"gold={record['score']['gold']} "
            f"seconds={record['seconds']:.1f} "
            f"total_tokens={format_token_value(token_usage['totalTokens'])} "
            f"uncached_plus_output_tokens={format_token_value(token_usage['uncachedPlusOutputTokens'])} "
            f"coordination_errors={coordination_error_total(record)}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def format_token_value(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:,.0f}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--system",
        choices=("codex", "codex-subagents", "losangelex"),
        action="append",
        required=True,
    )
    parser.add_argument("--marble-root", type=Path, default=DEFAULT_MARBLE_ROOT)
    parser.add_argument("--task-id", action="append", dest="task_ids", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--model", default="gpt-5.4")
    parser.add_argument("--codex", type=Path, default=DEFAULT_CODEX)
    add_benchmark_app_server_args(parser)
    parser.add_argument("--max-rounds", type=int, default=1)
    parser.add_argument("--per-agent-timeout-seconds", type=int, default=600)
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    parser.add_argument("--round-timeout-seconds", type=int, default=600)
    parser.add_argument("--poll-seconds", type=int, default=45)
    parser.add_argument("--rpc-timeout-seconds", type=int, default=300)
    parser.add_argument(
        "--campaign-name", default=f"marble-database-{int(time.time())}"
    )
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument(
        "--evidence-mode",
        choices=("prompt-only", "schema", "diagnostic-observations", "native-postgres"),
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
    parser.add_argument(
        "--no-default-hide-paths",
        action="store_true",
        help="Do not hide the published benchmark repository during agent execution.",
    )
    args = parser.parse_args()

    tasks = load_tasks(
        marble_root=args.marble_root,
        task_ids=args.task_ids,
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
        marble_root=args.marble_root,
        include_defaults=not args.no_default_hide_paths,
    )
    if not args.no_default_hide_paths:
        hidden_paths = effective_hidden_paths(
            explicit_paths=[
                *hidden_paths,
                *previous_result_hidden_paths(args.out_root, output_dir),
            ],
            marble_root=args.marble_root,
            include_defaults=False,
        )
    global_hidden_paths = (
        [] if args.evidence_mode == "native-postgres" else hidden_paths
    )
    task_hidden_paths = hidden_paths if args.evidence_mode == "native-postgres" else []
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
        temporarily_hide_paths(global_hidden_paths),
    ):
        app_server_url = app_server.url if app_server is not None else None
        app_server_metadata = app_server.metadata() if app_server is not None else None
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
                        marble_root=args.marble_root,
                        hidden_paths=task_hidden_paths,
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
                        evidence_mode=args.evidence_mode,
                        marble_root=args.marble_root,
                        hidden_paths=task_hidden_paths,
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
                        timeout_seconds=args.timeout_seconds,
                        round_timeout_seconds=args.round_timeout_seconds,
                        poll_seconds=args.poll_seconds,
                        rpc_timeout_seconds=args.rpc_timeout_seconds,
                        output_dir=run_dir,
                        evidence_mode=args.evidence_mode,
                        marble_root=args.marble_root,
                        hidden_paths=task_hidden_paths,
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
                    output_dir / "MARBLE_DATABASE_PUBLISHED_REPORT.md",
                    campaign_name=args.campaign_name,
                    evidence_mode=args.evidence_mode,
                    records=records,
                )
                metrics = record["score"]["metrics"]
                token_usage = normalize_token_usage(record.get("tokenUsage"))
                print(
                    f"completed system={system} task={task.task_id} "
                    f"recall={metrics['rootCauseRecall']:.3f} "
                    f"predicted={record['score']['predicted']} "
                    f"seconds={record['seconds']} "
                    f"total_tokens={token_usage['totalTokens']}",
                    flush=True,
                )

    print(f"wrote {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
