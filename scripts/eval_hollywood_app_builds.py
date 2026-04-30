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
import urllib.error
import urllib.request
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
DEFAULT_HOLLYWOOD_URL = "http://127.0.0.1:8765"
DEFAULT_EVAL_MODEL = "gpt-5.4"
DEFAULT_EVAL_MODEL_PROVIDER = "openai"
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
RUNTIME_ROOM_POLICIES = {"leader_award", "kanban_pull", "dual_command_lease", "auto"}
ROOM_CONTRACT_VERSION = "losangelex-room/v2"
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
            "and own final integration and completion. When the app is already green and another "
            "previously awarded lane is no longer necessary, record `coordination_act cancel` with "
            "a concrete reason so the obsolete lane is retired durably. Before you reclaim or "
            "reassign a critical-path file, verify its current existence and exact workspace-relative "
            "path in the live workspace. If a critical file is missing, make that explicit and recreate "
            "the file at the workspace root instead of retrying stale patch context or absolute paths."
        ),
        "shared": (
            "Tony is the lead for this run. Wait for his lane assignments before starting work, "
            "unless he explicitly asks for self-directed help. Before editing a claimed file, verify "
            "the file still exists in the live workspace and use workspace-relative paths with "
            "`apply_patch`; if the expected file is actually missing, stop retrying the same patch and "
            "either recreate the file at the intended workspace path or hand the lane back."
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
            "reassign quickly when facts change, and make sure somebody always owns the highest-value open lane. "
            "Implementation ownership is your control surface: publish the initial lane map before builders claim code, "
            "and do not reclaim an active implementation lane unless the current owner explicitly yields, reports blocked, "
            "or Ray presents fresh test evidence that proves the lane is idle or wrong."
        ),
        "james": (
            "You are an executor under Tony's plan. Do not self-claim implementation files before Tony posts the first "
            "lane map. After that, take only an exact lane Tony has opened or confirmed for you, keep strictly to that "
            "scope, and hand back a concise completion note instead of freelancing into neighboring files."
        ),
        "chris": (
            "You are an executor under Tony's plan. Do not self-claim implementation files before Tony posts the first "
            "lane map. After that, take only an exact lane Tony has opened or confirmed for you, keep strictly to that "
            "scope, and if you become free ask Tony for the next lane instead of speculating on ownership."
        ),
        "ray": (
            "You own verification, idle detection, and shutdown. Keep the test signal fresh, call out blocked or "
            "idle teammates, and explicitly close the room when the app is actually done. Stay verification-only unless "
            "Tony explicitly assigns you an implementation lane; do not claim product code on your own."
        ),
        "shared": (
            "Use dual-command coordination. Tony controls planning and reassignment; Ray controls verification and "
            "quiescence. James and Chris should execute exact lanes, hand off concise summaries, and immediately take "
            "the next ready lane when Tony identifies one. Ray should publish verification deltas and closure signals, "
            "not implementation claims, unless Tony explicitly hands off a code lane."
        ),
    },
    "dual_command_lease": {
        "tony": (
            "You own the work graph, dependency order, and final integration. Publish the initial lane map before builders "
            "claim code. Treat an executor's explicit progress heartbeat as a lease on that lane: do not reassign an "
            "implementation file while the current owner is still heartbeating concrete progress or answering status checks. "
            "Only reassign after the owner explicitly yields, reports blocked, or misses repeated heartbeat requests and Ray "
            "confirms there is still no testable handback."
        ),
        "james": (
            "You are an executor under Tony's plan. Do not self-claim implementation files before Tony posts the first lane map. "
            "Once you own a lane, post concise progress heartbeats when Tony or Ray checks status, even if the visible shared diff "
            "is not ready yet. Keep to exact assigned scope and hand back a concrete completion note when the lane is testable."
        ),
        "chris": (
            "You are an executor under Tony's plan. Do not self-claim implementation files before Tony posts the first lane map. "
            "Once you own a lane, post concise progress heartbeats when Tony or Ray checks status, even if the visible shared diff "
            "is not ready yet. Keep to exact assigned scope and hand back a concrete completion note when the lane is testable."
        ),
        "ray": (
            "You own verification, idle detection, and shutdown. Stay verification-only unless Tony explicitly assigns code. "
            "Treat a recent owner heartbeat as active ownership, not idle work. Recommend reassignment only when the owner has "
            "missed repeated heartbeat checks or explicitly yielded, and keep the test signal fresh once a handback exists."
        ),
        "shared": (
            "Use dual-command coordination with lane leases. Tony controls planning and reassignment; Ray controls verification "
            "and shutdown; James and Chris execute exact lanes. Active owners must answer status checks with a short progress "
            "heartbeat before anyone treats the lane as stalled. Reassign only after a missed lease heartbeat or an explicit yield."
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
SUPPORTED_POLICIES = sorted(set(POLICY_PROMPTS) | RUNTIME_ROOM_POLICIES)


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


def active_thread_count(thread_states: dict[str, dict[str, Any]]) -> int:
    return sum(
        1
        for state in thread_states.values()
        if isinstance(state.get("status"), dict)
        and state["status"].get("type") == "active"
    )


def all_threads_idle(thread_states: dict[str, dict[str, Any]]) -> bool:
    return active_thread_count(thread_states) == 0


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
    roster = ", ".join(name for name, _ in TEAM)
    if policy == "auto":
        auto_block = (
            "The room starts in a discovery phase. Reduce the broad goal into exact claimable lanes "
            "before anyone claims broad implementation scope, then follow the active room coordination "
            "policy and later phase changes."
        )
        if agent_name == "tony":
            auto_block += (
                " As the initial lead, publish the first lane map or investigation lanes before "
                "taking product-code ownership yourself; only keep implementation scope you cannot "
                "split cleanly, and say why."
            )
        else:
            auto_block += (
                " During discovery, do not claim broad product scope on your own; wait for an exact "
                "lane or an explicit investigation request."
            )
        return (
            f"You are {agent_name}. Your strongest lane is {specialty}. "
            f"The team roster is: {roster}. "
            "Work in the current repository workspace. Read README.md first, then coordinate through "
            "Hollywood to finish the app. Follow the active room coordination policy and your Hollywood "
            "synthetic coordination briefs; do not invent a private policy. Run tests before claiming the "
            "app is done. Only declare completion when `npm test -- --run` passes in this workspace. "
            f"{auto_block}"
        )
    if policy in RUNTIME_ROOM_POLICIES:
        return (
            f"You are {agent_name}. Your strongest lane is {specialty}. "
            f"The team roster is: {roster}. "
            "Work in the current repository workspace. Read README.md first, then coordinate through "
            "Hollywood to finish the app. Follow the active room coordination policy and your Hollywood "
            "synthetic coordination briefs; do not invent a private policy. Run tests before claiming the "
            "app is done. Only declare completion when `npm test -- --run` passes in this workspace."
        )
    policy_block = POLICY_PROMPTS[policy].get(agent_name) or POLICY_PROMPTS[policy]["shared"]
    return (
        f"You are {agent_name}. Your strongest lane is {specialty}. "
        f"The team roster is: {roster}. "
        "Work in the current repository workspace. Read README.md first, then coordinate through "
        "Hollywood to finish the app. Run tests before claiming the app is done. "
        "Only declare completion when `npm test -- --run` passes in this workspace. "
        f"{policy_block}"
    )


def apply_room_policy_state(
    *,
    hollywood_url: str,
    room: str,
    policy: str,
    agents: list[AgentRun],
    phase: str | None = None,
    epoch: int = 1,
) -> dict[str, Any] | None:
    if policy not in RUNTIME_ROOM_POLICIES:
        return None

    thread_by_role = {agent.role_name: agent.thread_id for agent in agents}
    current_phase = phase or ("discovery" if policy == "auto" else "execution")
    payload: dict[str, Any] = {
        "room": room,
        "contract_version": ROOM_CONTRACT_VERSION,
        "coordination_policy": policy,
        "coordination_phase": current_phase,
        "coordination_epoch": epoch,
        "bump_state_version": True,
    }
    if policy in {"leader_award", "dual_command_lease", "auto"}:
        payload["leader_session_id"] = thread_by_role["tony"]
        payload["verifier_session_id"] = thread_by_role["ray"]

    request = urllib.request.Request(
        f"{hollywood_url.rstrip('/')}/hollywood/v1/rooms",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(
            f"failed to update Hollywood room policy state for {room}: {exc} {detail}".strip()
        ) from exc


def estimate_failed_test_count(test_result: subprocess.CompletedProcess[str]) -> int | None:
    if test_result.returncode == 0:
        return 0

    combined = "\n".join(
        part for part in (test_result.stdout, test_result.stderr) if part
    ).lower()
    patterns = (
        r"(\d+)\s+failed",
        r"failures?:\s*(\d+)",
        r"failed\s*\((\d+)\)",
    )
    for pattern in patterns:
        import re

        match = re.search(pattern, combined)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                continue
    return None


def infer_auto_phase(
    *,
    elapsed_seconds: float,
    latest_test: subprocess.CompletedProcess[str],
) -> str:
    if latest_test.returncode == 0:
        return "closure"

    failed_count = estimate_failed_test_count(latest_test)
    if failed_count is not None and failed_count <= 1:
        return "stabilization"
    if elapsed_seconds >= 45:
        return "execution"
    return "discovery"


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
            model=DEFAULT_EVAL_MODEL,
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


def evaluate_policy(
    *,
    policy: str,
    challenge: str,
    app_server_url: str,
    hollywood_url: str,
    timeout_seconds: int,
    poll_seconds: int,
    post_pass_soak_seconds: int,
    max_quiescence_wait_seconds: int | None = None,
) -> dict[str, Any]:
    workspace = prepare_workspace(challenge, policy)
    install_result = install_workspace(workspace)
    baseline_test = run_tests(workspace)
    run_suffix = uuid.uuid4().hex[:6]
    room = f"repo/{challenge}-{policy}-{run_suffix}"

    conn = JsonRpcWs(app_server_url)
    started_at = time.time()
    passed_at: float | None = None
    quiesced_at: float | None = None
    test_history: list[dict[str, Any]] = []
    agents: list[AgentRun] = []
    try:
        initialize(conn)
        agents = start_team(conn, workspace=workspace, room=room, run_suffix=run_suffix)
        current_phase = "discovery" if policy == "auto" else "execution"
        current_epoch = 1
        room_policy_state = apply_room_policy_state(
            hollywood_url=hollywood_url,
            room=room,
            policy=policy,
            agents=agents,
            phase=current_phase,
            epoch=current_epoch,
        )
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
            if policy == "auto":
                desired_phase = infer_auto_phase(
                    elapsed_seconds=elapsed,
                    latest_test=test_result,
                )
                if desired_phase != current_phase:
                    current_phase = desired_phase
                    current_epoch += 1
                    room_policy_state = apply_room_policy_state(
                        hollywood_url=hollywood_url,
                        room=room,
                        policy=policy,
                        agents=agents,
                        phase=current_phase,
                        epoch=current_epoch,
                    )
            if test_result.returncode == 0:
                passed_at = elapsed
                quiescence_wait_seconds = (
                    post_pass_soak_seconds
                    if max_quiescence_wait_seconds is None
                    else max_quiescence_wait_seconds
                )
                if quiescence_wait_seconds > 0:
                    quiescence_deadline = time.time() + quiescence_wait_seconds
                    while time.time() < quiescence_deadline:
                        remaining = max(0.05, quiescence_deadline - time.time())
                        conn.drain(min(5.0, remaining))
                        candidate_thread_states = {
                            agent.thread_id: read_thread_state(conn, agent.thread_id)
                            for agent in agents
                        }
                        if all_threads_idle(candidate_thread_states):
                            quiesced_at = round(time.time() - started_at, 1)
                            break
                break

        final_test = run_tests(workspace)
        thread_states = {
            agent.thread_id: read_thread_state(conn, agent.thread_id) for agent in agents
        }
        summary = summarize_notifications(conn.notifications, {agent.thread_id for agent in agents})
        completed = completed_threads(conn.notifications, {agent.thread_id for agent in agents})
        changed = changed_files(workspace, challenge)
        active_threads_after_run = active_thread_count(thread_states)
        message_count = summary["notificationCounts"].get("thread/hollywood/message", 0)
        return {
            "policy": policy,
            "challenge": challenge,
            "room": room,
            "workspace": str(workspace),
            "roomPolicyState": room_policy_state,
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
            "allThreadsIdleAfterRun": active_threads_after_run == 0,
            "quiescedAtSeconds": quiesced_at,
            "eventuallyQuiesced": quiesced_at is not None,
            "quiescenceLagSeconds": (
                round(quiesced_at - passed_at, 1)
                if quiesced_at is not None and passed_at is not None
                else None
            ),
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
        choices=SUPPORTED_POLICIES,
        action="append",
        help="Policies to run. Defaults to room_message, leader_award, semantic_market, hybrid.",
    )
    parser.add_argument("--timeout-seconds", type=int, default=360)
    parser.add_argument("--poll-seconds", type=int, default=45)
    parser.add_argument("--post-pass-soak-seconds", type=int, default=20)
    parser.add_argument("--max-quiescence-wait-seconds", type=int)
    parser.add_argument("--app-server-url")
    parser.add_argument("--hollywood-url", default=DEFAULT_HOLLYWOOD_URL)
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
                hollywood_url=args.hollywood_url,
                timeout_seconds=args.timeout_seconds,
                poll_seconds=args.poll_seconds,
                post_pass_soak_seconds=args.post_pass_soak_seconds,
                max_quiescence_wait_seconds=args.max_quiescence_wait_seconds,
            )
        )

    print(json.dumps({"appServerUrl": app_server_url, "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
