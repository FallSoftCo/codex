#!/usr/bin/env python3
"""Run real Hollywood team app-build evaluations and score the resulting app."""

from __future__ import annotations

import argparse
import filecmp
import json
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
TMP_ROOT = REPO_ROOT / "tmp" / "app_build_eval"
TEAM = (
    ("tony", "planning, architecture, integration, release verification"),
    ("james", "frontend UI and polish"),
    ("chris", "state management, storage, review, helper implementation"),
    ("ray", "QA, browser behavior, and final test verification"),
)
CHALLENGES = {
    "habit_dashboard": REPO_ROOT / "evals" / "app_challenges" / "habit_dashboard_template",
    "incident_console": REPO_ROOT / "evals" / "app_challenges" / "incident_console_template",
    "expense_board": REPO_ROOT / "evals" / "app_challenges" / "expense_board_template",
}
POLICY_PROMPTS = {
    "room_message": {
        "shared": (
            "Coordinate informally like a normal team in Hollywood. Share discoveries in the room, "
            "pick lanes, avoid duplicate edits, and finish only when the app is actually done."
        ),
    },
    "leader_award": {
        "tony": (
            "You are the lead. Read the challenge, decompose it, assign exact lanes to teammates, "
            "and own final integration and completion."
        ),
        "shared": (
            "Tony is the lead for this run. Wait for his lane assignments before starting work, "
            "unless he explicitly asks for self-directed help."
        ),
    },
    "semantic_market": {
        "shared": (
            "Use market-style coordination. Read the challenge, announce or claim the exact lane you "
            "are strongest at, keep work saturated when there is a real open lane, and avoid overlap. "
            "Prefer exact file scope and concrete ownership over vague room chatter."
        ),
    },
    "hybrid": {
        "tony": (
            "Own dependency-sensitive sequencing and final integration. Do not bottleneck easy helper, "
            "UI, or QA lanes that teammates can self-select."
        ),
        "shared": (
            "Use a hybrid policy: let Tony coordinate dependencies and integration, but self-select "
            "clear UI, QA, and helper lanes when they are obviously available."
        ),
    },
    "market_with_finisher": {
        "ray": (
            "You are the finisher and quiescence owner. Let teammates self-select exact lanes, but once "
            "the test gate looks close to green you must take over final verification, ask for missing "
            "summaries, rerun `npm test -- --run`, and explicitly tell the team to stop when the app is done."
        ),
        "shared": (
            "Use market-style exact-lane coordination, but treat Ray as the final verifier and shutdown "
            "arbiter. When Ray declares the app done or says there is no actionable delta, go idle."
        ),
    },
    "leader_market": {
        "tony": (
            "Your job is decomposition, dependency ordering, and clarifying exact lanes. Do the initial split "
            "and update it when facts change, but do not monopolize execution once lanes are clear."
        ),
        "shared": (
            "Tony owns decomposition and dependency ordering. After he outlines the work graph, self-select "
            "the exact executable lane you are strongest at and keep the team saturated without overlapping."
        ),
    },
    "critic_executor": {
        "ray": (
            "You are the critic and verifier. Continuously read teammate updates, rerun tests after material "
            "changes, convert failures into concrete deltas, and only implement code yourself if progress stalls."
        ),
        "shared": (
            "Treat this as an executor/critic loop. Builders should implement exact lanes and post concise "
            "handoff notes; Ray should keep the test signal fresh and drive the next corrective delta."
        ),
    },
    "dual_command": {
        "tony": (
            "You own the work graph, dependency order, and final integration. Keep the next ready lanes explicit, "
            "reassign quickly when facts change, and make sure somebody always owns the highest-value open lane."
        ),
        "ray": (
            "You own verification, idle detection, and shutdown. Keep the test signal fresh, call out blocked or "
            "idle teammates, and explicitly close the room when the app is actually done."
        ),
        "shared": (
            "Use dual-command coordination. Tony controls planning and reassignment; Ray controls verification and "
            "quiescence. James and Chris should execute exact lanes, hand off concise summaries, and immediately take "
            "the next ready lane when either Tony or Ray identifies one."
        ),
    },
    "kanban_pull": {
        "shared": (
            "Run the team as a pull-based kanban system. Convert the broad goal into a visible backlog of small exact "
            "lanes, keep at most one active lane per agent, and when you go idle immediately pull the highest-priority "
            "ready unowned lane. Prefer small batches, clear state transitions, and fast handoffs over long private work."
        ),
    },
    "relay_foreman": {
        "tony": (
            "You are the rolling foreman. Keep a short queue of the next one or two ready lanes, feed idle teammates "
            "continuously, and replan immediately after each completion or blocker so nobody sits idle while real work exists."
        ),
        "shared": (
            "Use relay-style execution. Take one exact lane, finish or block it, post a concise handoff, and then "
            "immediately request or take the next ready lane Tony has posted."
        ),
    },
    "review_gated": {
        "ray": (
            "You are the mandatory reviewer and test gatekeeper. Builders should hand work to you for verification, "
            "and you should turn failures into exact follow-up lanes until the whole app passes cleanly."
        ),
        "shared": (
            "Use review-gated execution. Implementers claim exact lanes and hand them to Ray for validation before the "
            "team moves on. Do not call the app done until Ray confirms the test gate and Tony confirms integration."
        ),
    },
    "org_layered": {
        "tony": (
            "You are the governance layer. Maintain the shared work graph, keep the highest-value ready lanes explicit, "
            "assign exact scope, and reassign immediately when facts change. Avoid coding unless integration is blocked "
            "or the execution layer has no ready lane."
        ),
        "ray": (
            "You are the compliance layer. Keep the test signal fresh, convert failures into exact follow-up lanes, "
            "challenge ambiguous completion claims, and explicitly stand the team down once the app is green and no "
            "owned lane remains unresolved."
        ),
        "shared": (
            "Operate as a layered organization. Tony owns governance and lane allocation, James and Chris are the main "
            "execution layer, and Ray owns compliance and closure. Treat the room as a blackboard of state changes: "
            "post exact scope, status transitions, blockers, and handoffs, not open-ended discussion. Keep at most one "
            "active lane per agent and pull the next ready lane as soon as your current lane is done or blocked."
        ),
    },
    "gpgp_blackboard": {
        "tony": (
            "Seed the initial goal tree, expose the highest-worth ready lanes, and keep integration constraints visible, "
            "but do not micromanage every move once the shared constraints are clear."
        ),
        "ray": (
            "Continuously translate test and verification results into shared scheduling constraints. Publish only exact "
            "deltas that change what should be worked on next, and explicitly retract stale or redundant follow-up work."
        ),
        "shared": (
            "Use a GPGP/blackboard style. Treat coordination as posting and consuming shared scheduling constraints "
            "rather than chatting. Before starting work, read the current board state, then post one concise commitment "
            "with exact file scope, expected outcome, and any dependency it relies on. If another agent has posted an "
            "equivalent commitment, retract one of the redundant commitments and move to the next ready lane. Communicate "
            "only on state transitions, blockers, retractions, or materially new evidence. Prefer small exact commitments "
            "and opportunistic pull from the highest-priority ready work."
        ),
    },
    "quiescence_token": {
        "tony": (
            "Coordinate exact lanes as the lead, but once Ray initiates a quiescence round you must stop opening new work "
            "unless Ray cancels the round because there is still unresolved exact scope or a failing test."
        ),
        "ray": (
            "You own distributed termination detection for this run. When the app appears green or nearly green, start an "
            "explicit quiescence round: require each teammate to reply with either `IDLE-ACK` or `STILL-OWN <exact-scope>`. "
            "Do not declare done until the latest test pass still holds and every other agent has acknowledged idle with no "
            "unresolved owned lane. If any agent reports unresolved scope or a new failing test appears, cancel the round, "
            "publish the exact delta, and restart the round only after the fix lands."
        ),
        "shared": (
            "Use leader coordination for execution, but use an explicit quiescence protocol for shutdown. When Ray starts a "
            "quiescence round, stop exploratory work and answer precisely with either `IDLE-ACK` or `STILL-OWN <exact-scope>`. "
            "After `IDLE-ACK`, stay silent unless materially new work appears. Avoid casual completion chatter; the room should "
            "converge on one explicit quiescence decision."
        ),
    },
}


@dataclass
class AgentRun:
    role_name: str
    runtime_name: str
    specialty: str
    thread_id: str


def run_command(
    command: list[str],
    *,
    cwd: Path,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def prepare_workspace(challenge: str, policy: str) -> Path:
    template = CHALLENGES[challenge]
    workspace = TMP_ROOT / f"{challenge}-{policy}-{uuid.uuid4().hex[:8]}"
    shutil.copytree(template, workspace)
    return workspace


def install_workspace(workspace: Path) -> subprocess.CompletedProcess[str]:
    return run_command(["npm", "install"], cwd=workspace, timeout=240)


def run_tests(workspace: Path) -> subprocess.CompletedProcess[str]:
    return run_command(["npm", "test", "--", "--run"], cwd=workspace, timeout=120)


def changed_files(workspace: Path, challenge: str) -> list[str]:
    template = CHALLENGES[challenge]
    changed: list[str] = []
    for path in sorted(template.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(template)
        if "node_modules" in rel.parts:
            continue
        candidate = workspace / rel
        if not candidate.exists() or path.read_text(errors="ignore") != candidate.read_text(
            errors="ignore"
        ):
            changed.append(str(rel))
    return changed


def policy_prompt(policy: str, agent_name: str, specialty: str) -> str:
    policy_block = POLICY_PROMPTS[policy].get(agent_name) or POLICY_PROMPTS[policy]["shared"]
    roster = ", ".join(name for name, _ in TEAM)
    return (
        f"You are {agent_name}. Your strongest lane is {specialty}. "
        f"The team roster is: {roster}. "
        "Work in the current repository workspace. Read README.md first, then coordinate through "
        "Hollywood to finish the app. Run tests before claiming the app is done. "
        "Only declare completion when `npm test -- --run` passes in this workspace. "
        f"{policy_block}"
    )


def start_team(
    conn: JsonRpcWs,
    *,
    workspace: Path,
    room: str,
    run_suffix: str,
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


def evaluate_policy(
    *,
    policy: str,
    challenge: str,
    app_server_url: str,
    timeout_seconds: int,
    poll_seconds: int,
    post_pass_soak_seconds: int,
) -> dict[str, Any]:
    workspace = prepare_workspace(challenge, policy)
    install_result = install_workspace(workspace)
    baseline_test = run_tests(workspace)
    run_suffix = uuid.uuid4().hex[:6]
    room = f"repo/{challenge}-{policy}-{run_suffix}"

    conn = JsonRpcWs(app_server_url)
    started_at = time.time()
    passed_at: float | None = None
    test_history: list[dict[str, Any]] = []
    agents: list[AgentRun] = []
    try:
        initialize(conn)
        agents = start_team(conn, workspace=workspace, room=room, run_suffix=run_suffix)
        tracked_threads = {agent.thread_id for agent in agents}
        conn.drain(8)
        for agent in agents:
            prompt = (
                f"Your runtime Hollywood identity for this run is `{agent.runtime_name}`. "
                f"Your persistent role is `{agent.role_name}`. "
                + policy_prompt(policy, agent.role_name, agent.specialty)
            )
            send_turn(conn, agent.thread_id, prompt)

        deadline = started_at + timeout_seconds
        while time.time() < deadline:
            conn.drain(poll_seconds)
            test_result = run_tests(workspace)
            elapsed = round(time.time() - started_at, 1)
            test_history.append(
                {
                    "elapsedSeconds": elapsed,
                    "returncode": test_result.returncode,
                    "stdoutTail": "\n".join(test_result.stdout.splitlines()[-12:]),
                    "stderrTail": "\n".join(test_result.stderr.splitlines()[-12:]),
                }
            )
            if test_result.returncode == 0:
                passed_at = elapsed
                if post_pass_soak_seconds > 0:
                    conn.drain(post_pass_soak_seconds)
                break

        final_test = run_tests(workspace)
        thread_states = {
            agent.thread_id: read_thread_state(conn, agent.thread_id) for agent in agents
        }
        summary = summarize_notifications(conn.notifications, {agent.thread_id for agent in agents})
        completed = completed_threads(conn.notifications, {agent.thread_id for agent in agents})
        changed = changed_files(workspace, challenge)
        active_threads_after_run = sum(
            1
            for state in thread_states.values()
            if isinstance(state.get("status"), dict)
            and state["status"].get("type") == "active"
        )
        message_count = summary["notificationCounts"].get("thread/hollywood/message", 0)
        return {
            "policy": policy,
            "challenge": challenge,
            "room": room,
            "workspace": str(workspace),
            "install": {
                "returncode": install_result.returncode,
                "stdoutTail": "\n".join(install_result.stdout.splitlines()[-12:]),
                "stderrTail": "\n".join(install_result.stderr.splitlines()[-12:]),
            },
            "baselineTestReturncode": baseline_test.returncode,
            "passed": final_test.returncode == 0,
            "passedAtSeconds": passed_at,
            "changedFiles": changed,
            "changedFilesCount": len(changed),
            "activeThreadsAfterRun": active_threads_after_run,
            "messageCount": message_count,
            "finalTest": {
                "returncode": final_test.returncode,
                "stdoutTail": "\n".join(final_test.stdout.splitlines()[-20:]),
                "stderrTail": "\n".join(final_test.stderr.splitlines()[-20:]),
            },
            "testHistory": test_history,
            "agents": [
                {
                    "name": agent.runtime_name,
                    "roleName": agent.role_name,
                    "specialty": agent.specialty,
                    "threadId": agent.thread_id,
                }
                for agent in agents
            ],
            "completedThreads": sorted(completed),
            "threadStates": thread_states,
            "summary": summary,
        }
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--challenge", choices=sorted(CHALLENGES), default="habit_dashboard")
    parser.add_argument(
        "--policy",
        choices=sorted(POLICY_PROMPTS),
        action="append",
        help="Policies to run. Defaults to room_message, leader_award, semantic_market, hybrid.",
    )
    parser.add_argument("--timeout-seconds", type=int, default=360)
    parser.add_argument("--poll-seconds", type=int, default=45)
    parser.add_argument("--post-pass-soak-seconds", type=int, default=20)
    parser.add_argument("--app-server-url")
    parser.add_argument("--current-app-server", default=str(DEFAULT_CURRENT_APP_SERVER))
    args = parser.parse_args()

    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    app_server_url = args.app_server_url or load_app_server_url(Path(args.current_app_server))
    policies = args.policy or ["room_message", "leader_award", "semantic_market", "hybrid"]

    results = []
    for policy in policies:
        results.append(
            evaluate_policy(
                policy=policy,
                challenge=args.challenge,
                app_server_url=app_server_url,
                timeout_seconds=args.timeout_seconds,
                poll_seconds=args.poll_seconds,
                post_pass_soak_seconds=args.post_pass_soak_seconds,
            )
        )

    print(json.dumps({"appServerUrl": app_server_url, "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
