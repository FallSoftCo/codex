#!/usr/bin/env python3
"""Generate SWE-bench predictions with Codex or a Losangelex Hollywood team."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from datasets import load_dataset

from eval_hollywood_app_builds import (
    DEFAULT_EVAL_MODEL_PROVIDER,
    TEAM,
    AgentRun,
    active_thread_count,
    all_threads_idle,
    apply_room_policy_state,
)
from replay_hollywood_operator import (
    DEFAULT_CURRENT_APP_SERVER,
    JsonRpcWs,
    completed_threads,
    initialize,
    load_app_server_url,
    read_thread_state,
    send_turn,
    start_agent,
    summarize_notifications,
)


REPO_ROOT = Path("/home/ai/Development/losangelex")
DEFAULT_CODEX = REPO_ROOT / "codex-rs" / "target" / "debug" / "codex"
DEFAULT_OUT_ROOT = REPO_ROOT / "tmp" / "research" / "swebench-published"
DEFAULT_HOLLYWOOD_URL = "http://127.0.0.1:8765"
DEFAULT_DATASET = "SWE-bench/SWE-bench_Lite"


@dataclass(frozen=True)
class Instance:
    repo: str
    instance_id: str
    base_commit: str
    problem_statement: str
    hints_text: str
    version: str
    fail_to_pass: list[str]
    pass_to_pass: list[str]


def run_command(
    command: list[str],
    *,
    cwd: Path,
    timeout: int,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        input=input_text,
        capture_output=True,
        timeout=timeout,
        check=False,
        env=env,
    )


def load_instances(
    *,
    dataset_name: str,
    split: str,
    instance_ids: list[str],
    limit: int | None,
) -> list[Instance]:
    dataset = load_dataset(dataset_name, split=split)
    wanted = set(instance_ids)
    rows: list[Instance] = []
    for row in dataset:
        if wanted and row["instance_id"] not in wanted:
            continue
        rows.append(
            Instance(
                repo=row["repo"],
                instance_id=row["instance_id"],
                base_commit=row["base_commit"],
                problem_statement=row["problem_statement"],
                hints_text=row.get("hints_text", ""),
                version=str(row.get("version", "")),
                fail_to_pass=parse_swebench_list(row.get("FAIL_TO_PASS", [])),
                pass_to_pass=parse_swebench_list(row.get("PASS_TO_PASS", [])),
            )
        )
        if limit is not None and len(rows) >= limit:
            break
    missing = sorted(wanted - {row.instance_id for row in rows})
    if missing:
        raise ValueError(
            f"instance id(s) not found in {dataset_name}/{split}: {missing}"
        )
    if not rows:
        raise ValueError("no SWE-bench instances selected")
    return rows


def parse_swebench_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [value] if value else []
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
        return [str(parsed)]
    return []


def prepare_workspace(instance: Instance, workspace: Path) -> dict[str, Any]:
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.parent.mkdir(parents=True, exist_ok=True)
    clone = run_command(
        ["git", "clone", f"https://github.com/{instance.repo}.git", str(workspace)],
        cwd=workspace.parent,
        timeout=900,
    )
    if clone.returncode != 0:
        raise RuntimeError(f"git clone failed for {instance.repo}:\n{clone.stderr}")
    checkout = run_command(
        ["git", "checkout", instance.base_commit],
        cwd=workspace,
        timeout=120,
    )
    if checkout.returncode != 0:
        raise RuntimeError(
            f"git checkout failed for {instance.instance_id}:\n{checkout.stderr}"
        )
    run_command(
        ["git", "config", "user.email", "swebench@losangelex.local"],
        cwd=workspace,
        timeout=30,
    )
    run_command(
        ["git", "config", "user.name", "SWE-bench Runner"],
        cwd=workspace,
        timeout=30,
    )
    return {
        "cloneReturncode": clone.returncode,
        "checkoutReturncode": checkout.returncode,
        "cloneStdoutTail": "\n".join(clone.stdout.splitlines()[-12:]),
        "cloneStderrTail": "\n".join(clone.stderr.splitlines()[-12:]),
        "checkoutStdoutTail": "\n".join(checkout.stdout.splitlines()[-12:]),
        "checkoutStderrTail": "\n".join(checkout.stderr.splitlines()[-12:]),
    }


def swebench_prompt(instance: Instance, *, system_name: str) -> str:
    tests = (
        "\n".join(f"- {test}" for test in instance.fail_to_pass[:12])
        or "- Not provided"
    )
    hints = instance.hints_text.strip() or "No hints provided."
    return f"""We are running a published SWE-bench task.

System under evaluation: {system_name}
Instance: {instance.instance_id}
Repository: {instance.repo}
Version: {instance.version}
Base commit: {instance.base_commit}

Problem statement:
{instance.problem_statement}

Hints from the benchmark instance:
{hints}

Fail-to-pass tests named by the benchmark:
{tests}

Constraints:
- Work only in this repository checkout.
- Do not look up or use the gold patch.
- Produce the best production-code fix you can, leaving the final patch in the working tree.
- Do not edit test files, benchmark files, or generated lockfiles. SWE-bench supplies its own
  held-out tests during scoring.
- Prefer targeted tests when practical, but do not spend the whole run on environment setup.
- Do not commit the changes.
"""


def collect_patch(workspace: Path) -> str:
    diff = run_command(["git", "diff", "--binary"], cwd=workspace, timeout=120)
    if diff.returncode != 0:
        raise RuntimeError(f"git diff failed:\n{diff.stderr}")
    return diff.stdout


def git_status(workspace: Path) -> str:
    status = run_command(["git", "status", "--short"], cwd=workspace, timeout=60)
    return status.stdout


def run_codex_prediction(
    *,
    instance: Instance,
    workspace: Path,
    codex: Path,
    model: str,
    timeout_seconds: int,
    output_dir: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    prompt = swebench_prompt(instance, system_name="codex-single-agent")
    prompt_path = output_dir / "prompt.txt"
    last_message_path = output_dir / "last-message.txt"
    stdout_path = output_dir / "stdout.log"
    stderr_path = output_dir / "stderr.log"
    prompt_path.write_text(prompt, encoding="utf-8")

    started = time.time()
    result = run_command(
        [
            str(codex),
            "-C",
            str(workspace),
            "--sandbox",
            "danger-full-access",
            "--ask-for-approval",
            "never",
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "-m",
            model,
            "-o",
            str(last_message_path),
            "-",
        ],
        cwd=workspace,
        timeout=timeout_seconds,
        env=None,
        input_text=prompt,
    )
    stdout_path.write_text(result.stdout, encoding="utf-8")
    stderr_path.write_text(result.stderr, encoding="utf-8")
    patch = collect_patch(workspace)
    return {
        "system": "codex",
        "instance_id": instance.instance_id,
        "workspace": str(workspace),
        "seconds": round(time.time() - started, 1),
        "returncode": result.returncode,
        "patchChars": len(patch),
        "status": git_status(workspace),
        "stdoutPath": str(stdout_path),
        "stderrPath": str(stderr_path),
        "lastMessagePath": str(last_message_path),
        "prediction": {
            "instance_id": instance.instance_id,
            "model_name_or_path": f"codex-single-agent/{model}",
            "model_patch": patch,
        },
    }


def start_team(
    conn: JsonRpcWs,
    *,
    workspace: Path,
    room: str,
    run_suffix: str,
    model: str,
) -> list[AgentRun]:
    agents: list[AgentRun] = []
    for name, specialty in TEAM:
        runtime_name = f"{name}-{run_suffix}"
        thread_id = start_agent(
            conn,
            workspace=str(workspace),
            room=room,
            observed_rooms=[room],
            wake_rooms=[room],
            name=runtime_name,
            model=model,
            model_provider=DEFAULT_EVAL_MODEL_PROVIDER,
        )
        agents.append(
            AgentRun(
                role_name=name,
                runtime_name=runtime_name,
                specialty=specialty,
                thread_id=thread_id,
            )
        )
    return agents


def losangelex_role_prompt(
    instance: Instance,
    *,
    runtime_name: str,
    role_name: str,
    specialty: str,
    policy: str,
) -> str:
    base = swebench_prompt(instance, system_name=f"losangelex-hollywood-team/{policy}")
    roster = ", ".join(name for name, _ in TEAM)
    if role_name == "tony":
        role_block = (
            "You are the lead. Decompose the issue into exact lanes, keep ownership clear, "
            "and own final integration. Avoid duplicating teammates' work."
        )
    elif role_name == "ray":
        role_block = (
            "You are the verifier. Keep test signal fresh when practical, convert failures into "
            "specific follow-up lanes, and call shutdown when the patch is ready."
        )
    else:
        role_block = (
            "You are an executor. Claim one exact lane that matches your specialty, implement it, "
            "and hand back concise status without taking neighboring scope."
        )
    return f"""{base}

Hollywood runtime identity: {runtime_name}
Persistent role: {role_name}
Specialty: {specialty}
Team roster: {roster}
Coordination policy: {policy}

Losangelex/Hollywood instructions:
- Coordinate through the room before overlapping on files.
- Keep claims to exact file or behavior lanes.
- If another agent owns equivalent scope, switch to review, tests, or a clearly unowned lane.
- Leave the final SWE-bench patch in the shared working tree.

Role-specific instruction:
{role_block}
"""


def run_losangelex_prediction(
    *,
    instance: Instance,
    workspace: Path,
    app_server_url: str,
    hollywood_url: str,
    model: str,
    policy: str,
    timeout_seconds: int,
    poll_seconds: int,
    rpc_timeout_seconds: int,
    output_dir: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    run_suffix = uuid.uuid4().hex[:6]
    room = f"repo/swebench-{instance.instance_id}-{policy}-{run_suffix}"
    conn = JsonRpcWs(app_server_url, request_timeout=rpc_timeout_seconds)
    started = time.time()
    agents: list[AgentRun] = []
    try:
        initialize(conn)
        agents = start_team(
            conn,
            workspace=workspace,
            room=room,
            run_suffix=run_suffix,
            model=model,
        )
        room_policy_state = apply_room_policy_state(
            hollywood_url=hollywood_url,
            room=room,
            policy=policy,
            agents=agents,
            phase="execution",
            epoch=1,
        )
        tracked_threads = {agent.thread_id for agent in agents}
        conn.drain(8)
        for agent in agents:
            prompt = losangelex_role_prompt(
                instance,
                runtime_name=agent.runtime_name,
                role_name=agent.role_name,
                specialty=agent.specialty,
                policy=policy,
            )
            (output_dir / f"prompt-{agent.role_name}.txt").write_text(
                prompt,
                encoding="utf-8",
            )
            send_turn(conn, agent.thread_id, prompt)

        deadline = started + timeout_seconds
        completed_once = False
        thread_states: dict[str, dict[str, Any]] = {}
        while time.time() < deadline:
            conn.drain(min(poll_seconds, max(0.1, deadline - time.time())))
            completed_once = (
                completed_threads(conn.notifications, tracked_threads)
                >= tracked_threads
            )
            thread_states = {
                agent.thread_id: read_thread_state(conn, agent.thread_id)
                for agent in agents
            }
            if completed_once and all_threads_idle(thread_states):
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

    patch = collect_patch(workspace)
    notifications_path = output_dir / "notifications-summary.json"
    notifications_path.write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    states_path = output_dir / "thread-states.json"
    states_path.write_text(json.dumps(final_states, indent=2) + "\n", encoding="utf-8")
    return {
        "system": "losangelex",
        "instance_id": instance.instance_id,
        "workspace": str(workspace),
        "room": room,
        "roomPolicyState": room_policy_state,
        "seconds": round(time.time() - started, 1),
        "completedInitialTurns": completed_once,
        "activeThreadsAfterRun": active_thread_count(final_states),
        "patchChars": len(patch),
        "status": git_status(workspace),
        "coordinationToolSummary": summary.get("coordinationToolSummary", {}),
        "notificationsSummaryPath": str(notifications_path),
        "threadStatesPath": str(states_path),
        "agents": [
            {
                "roleName": agent.role_name,
                "runtimeName": agent.runtime_name,
                "threadId": agent.thread_id,
                "specialty": agent.specialty,
            }
            for agent in agents
        ],
        "prediction": {
            "instance_id": instance.instance_id,
            "model_name_or_path": f"losangelex-hollywood-team-{policy}/{model}",
            "model_patch": patch,
        },
    }


def write_predictions(path: Path, predictions: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for prediction in predictions:
            handle.write(json.dumps(prediction) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-name", default=DEFAULT_DATASET)
    parser.add_argument("--split", default="test")
    parser.add_argument("--instance-id", action="append", dest="instance_ids")
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--system",
        choices=("codex", "losangelex"),
        action="append",
        required=True,
    )
    parser.add_argument("--model", default="gpt-5.4")
    parser.add_argument("--codex", type=Path, default=DEFAULT_CODEX)
    parser.add_argument("--app-server-url")
    parser.add_argument(
        "--current-app-server", type=Path, default=DEFAULT_CURRENT_APP_SERVER
    )
    parser.add_argument("--hollywood-url", default=DEFAULT_HOLLYWOOD_URL)
    parser.add_argument("--policy", default="dual_command_lease")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--rpc-timeout-seconds", type=int, default=300)
    parser.add_argument("--campaign-name", default=f"swebench-{int(time.time())}")
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    args = parser.parse_args()

    instances = load_instances(
        dataset_name=args.dataset_name,
        split=args.split,
        instance_ids=args.instance_ids or [],
        limit=args.limit,
    )
    app_server_url = args.app_server_url
    if "losangelex" in args.system and app_server_url is None:
        app_server_url = load_app_server_url(args.current_app_server)

    output_dir = args.out_root / args.campaign_name
    output_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    predictions_by_system: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for instance in instances:
        for system in args.system:
            workspace = output_dir / "workspaces" / system / instance.instance_id
            preparation = prepare_workspace(instance, workspace)
            run_dir = output_dir / "runs" / system / instance.instance_id
            if system == "codex":
                record = run_codex_prediction(
                    instance=instance,
                    workspace=workspace,
                    codex=args.codex,
                    model=args.model,
                    timeout_seconds=args.timeout_seconds,
                    output_dir=run_dir,
                )
            else:
                if app_server_url is None:
                    raise RuntimeError("app server URL is required for Losangelex runs")
                record = run_losangelex_prediction(
                    instance=instance,
                    workspace=workspace,
                    app_server_url=app_server_url,
                    hollywood_url=args.hollywood_url,
                    model=args.model,
                    policy=args.policy,
                    timeout_seconds=args.timeout_seconds,
                    poll_seconds=args.poll_seconds,
                    rpc_timeout_seconds=args.rpc_timeout_seconds,
                    output_dir=run_dir,
                )
            record["preparation"] = preparation
            records.append(record)
            predictions_by_system[system].append(record["prediction"])
            write_predictions(
                output_dir / f"predictions-{system}.jsonl",
                predictions_by_system[system],
            )
            (output_dir / "results.json").write_text(
                json.dumps(
                    {
                        "datasetName": args.dataset_name,
                        "split": args.split,
                        "model": args.model,
                        "systems": args.system,
                        "policy": args.policy,
                        "appServerUrl": app_server_url,
                        "hollywoodUrl": args.hollywood_url,
                        "records": records,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            print(
                "completed "
                f"system={system} instance={instance.instance_id} "
                f"patch_chars={record['patchChars']} seconds={record['seconds']}",
                flush=True,
            )

    for system, predictions in predictions_by_system.items():
        write_predictions(output_dir / f"predictions-{system}.jsonl", predictions)
    print(f"wrote {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
