#!/usr/bin/env python3
"""Evaluate debug collaboration-first Losangelex behavior with live app-server agents."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
import uuid
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchmark_app_server import AppServerStartupError
from benchmark_app_server import BenchmarkAppServer
from benchmark_app_server import free_loopback_port
from benchmark_app_server import log_tail
from benchmark_app_server import prepare_minimal_codex_home
from benchmark_app_server import terminate_process
from benchmark_app_server import wait_for_ready
from eval_hollywood_app_builds import DEFAULT_EVAL_MODEL_PROVIDER
from losangelex_codex_bin import DEFAULT_CODEX
from losangelex_codex_bin import ensure_default_codex
from replay_hollywood_operator import JsonRpcWs
from replay_hollywood_operator import completed_threads
from replay_hollywood_operator import initialize
from replay_hollywood_operator import read_thread_state
from replay_hollywood_operator import send_turn
from replay_hollywood_operator import start_agent
from replay_hollywood_operator import summarize_notifications


REPO_ROOT = Path("/home/ai/Development/losangelex")
HOLLYWOOD_SCRIPT = Path("/home/ai/Development/hollywood/hollywood.py")
DEFAULT_OUT_ROOT = REPO_ROOT / "tmp/research/collaboration-first-debug"
COLLABORATION_FIRST_ENV_VAR = "LOSANGELEX_COLLABORATION_FIRST_DEBUG"


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    description: str
    respondent_name: str
    peer_names: tuple[str, ...]
    files: dict[str, str]
    respondent_prompt: str
    peer_prompt: str
    expect_collaboration: bool


SCENARIOS = {
    "splittable_reconnect": Scenario(
        scenario_id="splittable_reconnect",
        description="Cross-surface reconnect work with useful implementation and verification lanes.",
        respondent_name="Responder",
        peer_names=("ClientPeer", "VerifierPeer"),
        expect_collaboration=True,
        files={
            "README.md": """# Debug Eval App

This scratch project is used by a Losangelex collaboration evaluation.
""",
            "client/live_client.js": """export function reconnectDelay(attempt) {
  const capped = Math.min(attempt, 4);
  return 250 * capped;
}

export function statusCopy(state) {
  if (state === "reconnecting") {
    return "Trying again";
  }
  return "Connected";
}
""",
            "server/turn_handler.js": """export function shouldAcceptTurn({ connected, pendingTurn }) {
  if (!connected) {
    return false;
  }
  return pendingTurn !== "blocked";
}

export function reconnectNotice() {
  return "waiting for connection";
}
""",
            "tests/reconnect_notes.md": """# Reconnect Notes

- Client retry copy should be clear during reconnect.
- Server turn acceptance should reject disconnected turns.
- Verification should mention the files checked.
""",
        },
        peer_prompt="""You are an attached Losangelex peer in a debug collaboration evaluation.

Stay available in this Hollywood room. Do not start implementation on your own.
If another session asks for help, accept only one narrow lane that fits the request,
announce the exact files you will inspect or edit, avoid overlapping claims, and
send a concise completion or blocker update when done.
""",
        respondent_prompt="""Fix the reconnect jitter issue in this scratch repo.

The work may touch client retry behavior, server reconnect wording, and verification notes.
Keep changes minimal and inspect the repo before editing. Complete the work as you normally would.
""",
    ),
    "tiny_readme": Scenario(
        scenario_id="tiny_readme",
        description="Tiny local README edit where peer collaboration is unnecessary churn.",
        respondent_name="Responder",
        peer_names=("IdlePeer",),
        expect_collaboration=False,
        files={
            "README.md": """# Debug Eval App

This scratch project is used by a Losangelex collaboration evaluation.
""",
        },
        peer_prompt="""You are an attached Losangelex peer in a debug collaboration evaluation.

Stay available in this Hollywood room. Do not start implementation on your own.
If another session asks for help, accept only one narrow lane that fits the request,
announce the exact files you will inspect or edit, avoid overlapping claims, and
send a concise completion or blocker update when done.
""",
        respondent_prompt="""In this scratch repo, change the README heading from
`Debug Eval App` to `Debug Eval Scratch App`. Keep the edit local and minimal.
""",
    ),
}


@dataclass(frozen=True)
class StartedAgent:
    name: str
    thread_id: str
    role: str


@contextmanager
def managed_hollywood_server(output_dir: Path):
    if not HOLLYWOOD_SCRIPT.exists():
        raise RuntimeError(f"missing Hollywood server script: {HOLLYWOOD_SCRIPT}")
    port = free_loopback_port()
    url = f"http://127.0.0.1:{port}"
    db_path = output_dir / "hollywood.db"
    log_path = output_dir / "hollywood.log"
    log_handle = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            "python3",
            str(HOLLYWOOD_SCRIPT),
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--db",
            str(db_path),
        ],
        cwd=str(output_dir),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        wait_for_hollywood_ready(url, timeout_seconds=15)
        yield {
            "url": url,
            "dbPath": str(db_path),
            "logPath": str(log_path),
            "pid": process.pid,
        }
    finally:
        terminate_process(process)
        log_handle.close()


def wait_for_hollywood_ready(url: str, *, timeout_seconds: int) -> None:
    deadline = time.time() + timeout_seconds
    health_url = url.rstrip("/") + "/hollywood/v1/health"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=1.0) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.25)
    raise TimeoutError(f"{health_url} was not ready after {timeout_seconds}s")


@contextmanager
def managed_debug_app_server(
    *,
    codex: Path,
    output_dir: Path,
    codex_home_source: Path,
    candidate: bool,
    hollywood_url: str,
    start_timeout_seconds: int,
):
    codex_home = output_dir / "codex-home"
    prepare_minimal_codex_home(
        codex_home=codex_home,
        source_home=codex_home_source,
        output_dir=output_dir,
    )
    url = f"ws://127.0.0.1:{free_loopback_port()}"
    log_path = output_dir / "app-server.log"
    env = os.environ.copy()
    env["CODEX_HOME"] = str(codex_home)
    env["HOLLYWOOD_URL"] = hollywood_url
    if candidate:
        env[COLLABORATION_FIRST_ENV_VAR] = "1"
    else:
        env.pop(COLLABORATION_FIRST_ENV_VAR, None)
    log_handle = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [str(codex.resolve()), "app-server", "--listen", url],
        cwd=str(output_dir),
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        wait_for_ready(url, start_timeout_seconds)
    except Exception as exc:
        terminate_process(process)
        log_handle.close()
        raise AppServerStartupError(
            f"managed debug app-server failed to start: {exc}\n{log_tail(log_path)}"
        ) from exc

    try:
        yield BenchmarkAppServer(
            url=url,
            managed=True,
            codex_home=codex_home,
            log_path=log_path,
            pid=process.pid,
            source="collaboration-first-debug-candidate" if candidate else "baseline",
        )
    finally:
        terminate_process(process)
        log_handle.close()


def fresh_workspace(workspace: Path, files: dict[str, str]) -> None:
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    for relative, contents in files.items():
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
    subprocess.run(["git", "add", "."], cwd=workspace, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "initial scratch fixture"],
        cwd=workspace,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Eval",
            "GIT_AUTHOR_EMAIL": "eval@example.com",
            "GIT_COMMITTER_NAME": "Eval",
            "GIT_COMMITTER_EMAIL": "eval@example.com",
        },
        check=True,
    )


def workspace_diff(workspace: Path) -> str:
    result = subprocess.run(
        ["git", "diff", "--", "."],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout


def fetch_room_messages(hollywood_url: str, room: str) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode(
        {
            "room": room,
            "after_id": "0",
            "limit": "1000",
            "include_own": "1",
        }
    )
    url = f"{hollywood_url.rstrip('/')}/hollywood/v1/messages?{query}"
    with urllib.request.urlopen(url, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    messages = payload.get("messages", [])
    if not isinstance(messages, list):
        return []
    return [message for message in messages if isinstance(message, dict)]


def wait_for_tracked_turns(
    conn: JsonRpcWs,
    tracked_threads: set[str],
    *,
    timeout_seconds: float,
) -> None:
    deadline = time.time() + timeout_seconds
    conn.drain_until(
        lambda: (
            completed_threads(conn.notifications, tracked_threads) >= tracked_threads
        ),
        deadline,
    )


def run_single_eval(
    *,
    scenario: Scenario,
    system: str,
    codex: Path,
    model: str,
    output_dir: Path,
    codex_home_source: Path,
    startup_timeout_seconds: int,
    turn_timeout_seconds: int,
) -> dict[str, Any]:
    candidate = system == "candidate"
    run_id = uuid.uuid4().hex[:8]
    run_dir = output_dir / system / scenario.scenario_id / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    workspace = run_dir / "workspace"
    fresh_workspace(workspace, scenario.files)

    with (
        managed_hollywood_server(run_dir) as hollywood,
        managed_debug_app_server(
            codex=codex,
            output_dir=run_dir,
            codex_home_source=codex_home_source,
            candidate=candidate,
            hollywood_url=str(hollywood["url"]),
            start_timeout_seconds=startup_timeout_seconds,
        ) as app_server,
    ):
        room = f"repo/collab-debug-{scenario.scenario_id}-{run_id}"
        conn = JsonRpcWs(app_server.url, request_timeout=turn_timeout_seconds + 30)
        agents: list[StartedAgent] = []
        try:
            initialize(conn)
            respondent_id = start_agent(
                conn,
                workspace=str(workspace),
                hollywood_url=str(hollywood["url"]),
                room=room,
                observed_rooms=[room],
                wake_rooms=[room],
                name=f"{scenario.respondent_name}-{run_id}",
                model=model,
                model_provider=DEFAULT_EVAL_MODEL_PROVIDER,
            )
            agents.append(
                StartedAgent(
                    name=scenario.respondent_name,
                    thread_id=respondent_id,
                    role="respondent",
                )
            )
            for peer_name in scenario.peer_names:
                thread_id = start_agent(
                    conn,
                    workspace=str(workspace),
                    hollywood_url=str(hollywood["url"]),
                    room=room,
                    observed_rooms=[room],
                    wake_rooms=[room],
                    name=f"{peer_name}-{run_id}",
                    model=model,
                    model_provider=DEFAULT_EVAL_MODEL_PROVIDER,
                )
                agents.append(
                    StartedAgent(name=peer_name, thread_id=thread_id, role="peer")
                )

            tracked_threads = {agent.thread_id for agent in agents}
            conn.drain(3)
            for agent in agents:
                if agent.role == "peer":
                    send_turn(conn, agent.thread_id, scenario.peer_prompt)
            wait_for_tracked_turns(
                conn,
                {agent.thread_id for agent in agents if agent.role == "peer"},
                timeout_seconds=turn_timeout_seconds,
            )

            prompt_path = run_dir / "respondent-prompt.txt"
            prompt_path.write_text(scenario.respondent_prompt, encoding="utf-8")
            send_turn(conn, respondent_id, scenario.respondent_prompt)
            wait_for_tracked_turns(
                conn,
                tracked_threads,
                timeout_seconds=turn_timeout_seconds,
            )
            conn.drain(10)
            thread_states = {
                agent.thread_id: read_thread_state(conn, agent.thread_id)
                for agent in agents
            }
            notification_summary = summarize_notifications(
                conn.notifications,
                tracked_threads,
            )
            notifications = list(conn.notifications)
        finally:
            conn.close()

        room_messages = fetch_room_messages(str(hollywood["url"]), room)

    diff = workspace_diff(workspace)
    score = score_run(
        scenario=scenario,
        agents=agents,
        room_messages=room_messages,
        notification_summary=notification_summary,
        diff=diff,
    )
    result = {
        "system": system,
        "scenarioId": scenario.scenario_id,
        "description": scenario.description,
        "candidateEnv": candidate,
        "model": model,
        "runId": run_id,
        "workspace": str(workspace),
        "room": room,
        "appServer": app_server.metadata(),
        "hollywood": hollywood,
        "agents": [
            {"name": agent.name, "threadId": agent.thread_id, "role": agent.role}
            for agent in agents
        ],
        "threadStates": thread_states,
        "notificationSummary": notification_summary,
        "notificationsPath": "notifications.json",
        "roomMessages": room_messages,
        "workspaceDiff": diff,
        "score": score,
    }
    (run_dir / "result.json").write_text(
        json.dumps(result, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_dir / "workspace.diff").write_text(diff, encoding="utf-8")
    (run_dir / "room-messages.json").write_text(
        json.dumps(room_messages, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_dir / "notification-summary.json").write_text(
        json.dumps(notification_summary, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_dir / "notifications.json").write_text(
        json.dumps(notifications, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def score_run(
    *,
    scenario: Scenario,
    agents: list[StartedAgent],
    room_messages: list[dict[str, Any]],
    notification_summary: dict[str, Any],
    diff: str,
) -> dict[str, Any]:
    thread_roles = {agent.thread_id: agent.role for agent in agents}
    thread_names = {agent.thread_id: agent.name for agent in agents}
    message_counts_by_role: Counter[str] = Counter()
    request_count = 0
    peer_response_count = 0
    peer_names_lower = [agent.name.lower() for agent in agents if agent.role == "peer"]
    request_terms = (
        "can you",
        "could you",
        "please",
        "take",
        "help",
        "lane",
    )
    collaboration_decision_terms = (
        "collaborat",
        "peer",
        "split",
        "solo",
        "small",
        "local",
        "unsplittable",
    )
    collaboration_decision_count = 0

    for message in room_messages:
        sender = str(message.get("sender_id") or message.get("senderId") or "")
        recipient = str(message.get("recipient_id") or message.get("recipientId") or "")
        body = str(message.get("body") or "")
        body_lower = body.lower()
        response_policy = str(
            message.get("response_policy") or message.get("responsePolicy") or ""
        ).lower()
        role = thread_roles.get(sender, "unknown")
        message_counts_by_role[role] += 1
        if role == "respondent":
            mentions_peer = any(peer in body_lower for peer in peer_names_lower)
            has_request_term = any(term in body_lower for term in request_terms)
            requests_response = response_policy == "required"
            if recipient or mentions_peer or requests_response or has_request_term:
                request_count += 1
            if any(term in body_lower for term in collaboration_decision_terms):
                collaboration_decision_count += 1
        elif role == "peer":
            peer_response_count += 1

    tool_calls = (
        notification_summary.get("coordinationToolSummary", {})
        .get("toolCalls", {})
        .get("byTool", {})
    )
    tool_errors = (
        notification_summary.get("coordinationToolSummary", {})
        .get("errorCalls", {})
        .get("total", 0)
    )
    hollywood_send_calls = int(tool_calls.get("hollywood_send", 0))
    passed = (
        request_count > 0 and peer_response_count > 0
        if scenario.expect_collaboration
        else request_count == 0 and peer_response_count == 0
    )
    if tool_errors:
        passed = False
    return {
        "passed": passed,
        "expectedCollaboration": scenario.expect_collaboration,
        "roomMessageCount": len(room_messages),
        "messageCountsByRole": dict(message_counts_by_role),
        "peerRequestCount": request_count,
        "peerResponseCount": peer_response_count,
        "collaborationDecisionMessageCount": collaboration_decision_count,
        "hollywoodSendCalls": hollywood_send_calls,
        "coordinationToolErrors": tool_errors,
        "workspaceChanged": bool(diff.strip()),
        "threadNames": thread_names,
    }


def write_report(output_dir: Path, results: list[dict[str, Any]]) -> None:
    by_system: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        by_system.setdefault(str(result["system"]), []).append(result)

    lines = [
        "# Collaboration-First Debug Evaluation",
        "",
        f"Generated: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        "",
        "This debug evaluation uses isolated app-server processes, isolated CODEX_HOME directories, isolated Hollywood servers/databases, and scratch workspaces.",
        "",
        "## Summary",
        "",
        "| System | Runs | Passed | Peer requests | Peer responses | Hollywood sends | Tool errors |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for system, system_results in sorted(by_system.items()):
        passed = sum(1 for result in system_results if result["score"]["passed"])
        peer_requests = sum(
            result["score"]["peerRequestCount"] for result in system_results
        )
        peer_responses = sum(
            result["score"]["peerResponseCount"] for result in system_results
        )
        sends = sum(result["score"]["hollywoodSendCalls"] for result in system_results)
        errors = sum(
            result["score"]["coordinationToolErrors"] for result in system_results
        )
        lines.append(
            f"| {system} | {len(system_results)} | {passed} | {peer_requests} | {peer_responses} | {sends} | {errors} |"
        )

    lines.extend(["", "## Runs", ""])
    for result in results:
        score = result["score"]
        lines.extend(
            [
                f"### {result['system']} / {result['scenarioId']} / {result['runId']}",
                "",
                f"- Passed: `{score['passed']}`",
                f"- Expected collaboration: `{score['expectedCollaboration']}`",
                f"- Peer requests: `{score['peerRequestCount']}`",
                f"- Peer responses: `{score['peerResponseCount']}`",
                f"- Hollywood send calls: `{score['hollywoodSendCalls']}`",
                f"- Coordination tool errors: `{score['coordinationToolErrors']}`",
                f"- Workspace changed: `{score['workspaceChanged']}`",
                f"- Result: `{result['system']}/{result['scenarioId']}/{result['runId']}/result.json`",
                "",
            ]
        )

    (output_dir / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex", type=Path, default=DEFAULT_CODEX)
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument(
        "--campaign-name",
        default=f"collaboration-first-debug-{time.strftime('%Y-%m-%d-%H%M%S')}",
    )
    parser.add_argument(
        "--system",
        action="append",
        choices=("baseline", "candidate"),
        help="System(s) to run. Defaults to baseline and candidate.",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        choices=sorted(SCENARIOS),
        help="Scenario(s) to run. Defaults to all.",
    )
    parser.add_argument("--runs-per-scenario", type=int, default=1)
    parser.add_argument(
        "--codex-home-source", type=Path, default=Path.home() / ".codex"
    )
    parser.add_argument("--startup-timeout-seconds", type=int, default=45)
    parser.add_argument("--turn-timeout-seconds", type=int, default=240)
    args = parser.parse_args()

    ensure_default_codex(args.codex)
    systems = args.system or ["baseline", "candidate"]
    scenarios = [SCENARIOS[name] for name in (args.scenario or sorted(SCENARIOS))]
    output_dir = args.out_root / args.campaign_name
    output_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for scenario in scenarios:
        for system in systems:
            for _ in range(args.runs_per_scenario):
                result = run_single_eval(
                    scenario=scenario,
                    system=system,
                    codex=args.codex,
                    model=args.model,
                    output_dir=output_dir,
                    codex_home_source=args.codex_home_source,
                    startup_timeout_seconds=args.startup_timeout_seconds,
                    turn_timeout_seconds=args.turn_timeout_seconds,
                )
                results.append(result)
                print(
                    json.dumps(
                        {
                            "system": result["system"],
                            "scenarioId": result["scenarioId"],
                            "runId": result["runId"],
                            "score": result["score"],
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )

    (output_dir / "results.json").write_text(
        json.dumps(results, indent=2) + "\n",
        encoding="utf-8",
    )
    write_report(output_dir, results)
    print(f"wrote {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
