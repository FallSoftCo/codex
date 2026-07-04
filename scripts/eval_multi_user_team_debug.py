#!/usr/bin/env python3
"""Evaluate multi-user Losangelex team behavior with live app-server agents."""

from __future__ import annotations

import argparse
import json
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eval_collaboration_first_debug import DEFAULT_OUT_ROOT as COLLAB_DEBUG_OUT_ROOT
from eval_collaboration_first_debug import fetch_room_messages
from eval_collaboration_first_debug import fresh_workspace
from eval_collaboration_first_debug import managed_debug_app_server
from eval_collaboration_first_debug import managed_hollywood_server
from eval_collaboration_first_debug import workspace_diff
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


DEFAULT_OUT_ROOT = COLLAB_DEBUG_OUT_ROOT.parent / "multi-user-team-debug"


@dataclass(frozen=True)
class UserAgent:
    role: str
    name: str
    prompt: str


@dataclass(frozen=True)
class MultiUserScenario:
    scenario_id: str
    description: str
    files: dict[str, str]
    user_agents: tuple[UserAgent, ...]
    peer_name: str
    peer_prompt: str


SCENARIOS = {
    "two_users_shared_notes": MultiUserScenario(
        scenario_id="two_users_shared_notes",
        description=(
            "Two user-facing agents receive separate user directives in one repo, "
            "with a shared notes file that requires non-overlapping coordination."
        ),
        files={
            "README.md": """# Multi User Team Debug App

Scratch project for evaluating multi-user Losangelex team behavior.
""",
            "client/dashboard.js": """export function dashboardCards() {
  return ["Latency", "Errors"];
}

export function reconnectBanner(state) {
  if (state === "retrying") {
    return "Trying again";
  }
  return "Ready";
}
""",
            "server/permissions.js": """export function canViewDashboard(role) {
  return role === "admin" || role === "operator";
}
""",
            "docs/team_notes.md": """# Team Notes

## Alice

- TODO

## Bob

- TODO
""",
        },
        user_agents=(
            UserAgent(
                role="alice",
                name="AliceAgent",
                prompt="""User Alice asks you to improve the dashboard reconnect experience.

Make a minimal client-side change in `client/dashboard.js`: add a `Reconnects`
card and change retrying copy to `Reconnecting`.

Also update only the Alice section of `docs/team_notes.md` with the files you
checked. Bob may be working server permissions in this same repo; coordinate in
Hollywood before touching shared notes and do not overwrite Bob's section.
""",
            ),
            UserAgent(
                role="bob",
                name="BobAgent",
                prompt="""User Bob asks you to add audit export permission support.

Make a minimal server-side change in `server/permissions.js`: add an exported
`canExportAudit(role)` helper that returns true only for `admin`.

Also update only the Bob section of `docs/team_notes.md` with the files you
checked. Alice may be working dashboard changes in this same repo; coordinate in
Hollywood before touching shared notes and do not overwrite Alice's section.
""",
            ),
        ),
        peer_name="QAPeer",
        peer_prompt="""You are an attached Losangelex QA peer for a multi-user debug evaluation.

Stay available in this Hollywood room. Do not edit files unless another session
asks. If you see conflicting edits, overlapping ownership, or an explicit
verification request, respond with a narrow finding and the exact files checked.
""",
    )
}


@dataclass(frozen=True)
class StartedAgent:
    name: str
    thread_id: str
    role: str


def wait_for_threads(
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
    scenario: MultiUserScenario,
    codex: Path,
    model: str,
    output_dir: Path,
    codex_home_source: Path,
    startup_timeout_seconds: int,
    turn_timeout_seconds: int,
) -> dict[str, Any]:
    run_id = uuid.uuid4().hex[:8]
    run_dir = output_dir / scenario.scenario_id / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    workspace = run_dir / "workspace"
    fresh_workspace(workspace, scenario.files)

    with (
        managed_hollywood_server(run_dir) as hollywood,
        managed_debug_app_server(
            codex=codex,
            output_dir=run_dir,
            codex_home_source=codex_home_source,
            candidate=True,
            hollywood_url=str(hollywood["url"]),
            start_timeout_seconds=startup_timeout_seconds,
        ) as app_server,
    ):
        room = f"repo/multi-user-team-debug-{scenario.scenario_id}-{run_id}"
        conn = JsonRpcWs(app_server.url, request_timeout=turn_timeout_seconds + 30)
        agents: list[StartedAgent] = []
        try:
            initialize(conn)
            for user_agent in scenario.user_agents:
                thread_id = start_agent(
                    conn,
                    workspace=str(workspace),
                    hollywood_url=str(hollywood["url"]),
                    room=room,
                    observed_rooms=[room],
                    wake_rooms=[room],
                    name=f"{user_agent.name}-{run_id}",
                    model=model,
                    model_provider=DEFAULT_EVAL_MODEL_PROVIDER,
                )
                agents.append(
                    StartedAgent(
                        name=user_agent.name,
                        thread_id=thread_id,
                        role=user_agent.role,
                    )
                )

            peer_id = start_agent(
                conn,
                workspace=str(workspace),
                hollywood_url=str(hollywood["url"]),
                room=room,
                observed_rooms=[room],
                wake_rooms=[room],
                name=f"{scenario.peer_name}-{run_id}",
                model=model,
                model_provider=DEFAULT_EVAL_MODEL_PROVIDER,
            )
            agents.append(
                StartedAgent(name=scenario.peer_name, thread_id=peer_id, role="peer")
            )

            tracked_threads = {agent.thread_id for agent in agents}
            conn.drain(3)
            send_turn(conn, peer_id, scenario.peer_prompt)
            wait_for_threads(conn, {peer_id}, timeout_seconds=turn_timeout_seconds)

            user_started_agents = [agent for agent in agents if agent.role != "peer"]
            for user_agent, agent in zip(
                scenario.user_agents,
                user_started_agents,
                strict=True,
            ):
                send_turn(conn, agent.thread_id, user_agent.prompt)

            wait_for_threads(
                conn,
                {agent.thread_id for agent in agents if agent.role != "peer"},
                timeout_seconds=turn_timeout_seconds,
            )
            conn.drain(20)
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
    file_contents = {
        relative: (workspace / relative).read_text(encoding="utf-8")
        for relative in (
            "client/dashboard.js",
            "server/permissions.js",
            "docs/team_notes.md",
        )
    }
    score = score_run(
        agents=agents,
        room_messages=room_messages,
        notification_summary=notification_summary,
        notifications=notifications,
        diff=diff,
        file_contents=file_contents,
    )
    result = {
        "scenarioId": scenario.scenario_id,
        "description": scenario.description,
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
        "fileContents": file_contents,
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
    agents: list[StartedAgent],
    room_messages: list[dict[str, Any]],
    notification_summary: dict[str, Any],
    notifications: list[dict[str, Any]],
    diff: str,
    file_contents: dict[str, str],
) -> dict[str, Any]:
    thread_roles = {agent.thread_id: agent.role for agent in agents}
    message_counts_by_role: Counter[str] = Counter()
    direct_messages = 0
    peer_responses = 0
    scope_mentions = 0
    required_direct_message_ids: set[int] = set()

    for message in room_messages:
        message_id = message.get("id")
        sender = str(message.get("sender_id") or message.get("senderId") or "")
        recipient = str(message.get("recipient_id") or message.get("recipientId") or "")
        body = str(message.get("body") or "")
        body_lower = body.lower()
        message_kind = str(
            message.get("message_kind") or message.get("messageKind") or ""
        )
        response_policy = str(
            message.get("response_policy") or message.get("responsePolicy") or ""
        )
        role = thread_roles.get(sender, "unknown")
        message_counts_by_role[role] += 1
        if recipient:
            direct_messages += 1
        if message_id is not None and (
            recipient
            or message_kind.lower() == "direct"
            or response_policy.lower() == "required"
        ):
            required_direct_message_ids.add(int(message_id))
        if role == "peer":
            peer_responses += 1
        if any(
            term in body_lower
            for term in (
                "client/dashboard.js",
                "server/permissions.js",
                "docs/team_notes.md",
                "alice",
                "bob",
                "scope",
                "own",
            )
        ):
            scope_mentions += 1

    turn_starts_by_role: Counter[str] = Counter()
    hollywood_wake_turns_by_role: Counter[str] = Counter()
    internal_hollywood_responses_by_role: Counter[str] = Counter()
    wake_message_ids_by_role: dict[str, list[int]] = {}
    for notification in notifications:
        method = notification.get("method")
        params = notification.get("params") or {}
        thread_id = str(params.get("threadId") or "")
        role = thread_roles.get(thread_id, "unknown")
        if method == "turn/started":
            turn = params.get("turn") or {}
            turn_id = str(turn.get("id") or "")
            turn_starts_by_role[role] += 1
            hollywood_message_id = hollywood_message_id_from_turn_id(turn_id)
            if hollywood_message_id is not None:
                hollywood_wake_turns_by_role[role] += 1
                wake_message_ids_by_role.setdefault(role, []).append(
                    hollywood_message_id
                )
        elif method == "item/completed":
            turn_id = str(params.get("turnId") or "")
            if not turn_id.startswith("hollywood-"):
                continue
            item = params.get("item") or {}
            item_type = item.get("type")
            if item_type == "userMessage":
                message_id = hollywood_message_id_from_user_message(item)
                if message_id is not None:
                    wake_message_ids_by_role.setdefault(role, []).append(message_id)
            elif item_type == "agentMessage" and str(item.get("text") or "").strip():
                internal_hollywood_responses_by_role[role] += 1

    delivered_wake_message_ids = {
        message_id
        for message_ids in wake_message_ids_by_role.values()
        for message_id in message_ids
    }
    required_direct_wakes_delivered = required_direct_message_ids.issubset(
        delivered_wake_message_ids
    )

    client = file_contents["client/dashboard.js"]
    server = file_contents["server/permissions.js"]
    notes = file_contents["docs/team_notes.md"]
    alice_done = "Reconnects" in client and "Reconnecting" in client
    bob_done = "canExportAudit" in server and 'role === "admin"' in server
    notes_have_alice = "## Alice" in notes and "client/dashboard.js" in notes
    notes_have_bob = "## Bob" in notes and "server/permissions.js" in notes
    conflict_markers = any(
        marker in "\n".join(file_contents.values())
        for marker in ("<<<<<<<", "=======", ">>>>>>>")
    )
    coordination_errors = notification_summary["coordinationToolSummary"]["errorCalls"][
        "total"
    ]
    user_roles = {agent.role for agent in agents if agent.role != "peer"}
    user_roles_with_messages = {
        role for role in user_roles if message_counts_by_role.get(role, 0) > 0
    }

    passed = (
        alice_done
        and bob_done
        and notes_have_alice
        and notes_have_bob
        and not conflict_markers
        and coordination_errors == 0
        and user_roles_with_messages == user_roles
        and required_direct_wakes_delivered
    )
    return {
        "passed": passed,
        "aliceTaskDone": alice_done,
        "bobTaskDone": bob_done,
        "sharedNotesHaveAlice": notes_have_alice,
        "sharedNotesHaveBob": notes_have_bob,
        "conflictMarkers": conflict_markers,
        "workspaceChanged": bool(diff.strip()),
        "messageCountsByRole": dict(message_counts_by_role),
        "directMessageCount": direct_messages,
        "requiredDirectMessageIds": sorted(required_direct_message_ids),
        "requiredDirectWakesDelivered": required_direct_wakes_delivered,
        "wakeMessageIdsByRole": wake_message_ids_by_role,
        "turnStartsByRole": dict(turn_starts_by_role),
        "hollywoodWakeTurnsByRole": dict(hollywood_wake_turns_by_role),
        "internalHollywoodResponsesByRole": dict(internal_hollywood_responses_by_role),
        "peerResponseCount": peer_responses,
        "scopeMentionCount": scope_mentions,
        "coordinationToolErrors": coordination_errors,
        "tokenUsage": notification_summary.get("tokenUsage", {}),
    }


def hollywood_message_id_from_turn_id(turn_id: str) -> int | None:
    prefix = "hollywood-"
    if not turn_id.startswith(prefix):
        return None
    try:
        return int(turn_id[len(prefix) :])
    except ValueError:
        return None


def hollywood_message_id_from_user_message(item: dict[str, Any]) -> int | None:
    content = item.get("content") or []
    text = "\n".join(str(part.get("text") or "") for part in content)
    start = text.find("<hollywood_message>")
    end = text.find("</hollywood_message>")
    if start == -1 or end == -1 or end <= start:
        return None
    payload = text[start + len("<hollywood_message>") : end].strip()
    try:
        value = json.loads(payload)
    except json.JSONDecodeError:
        return None
    message_id = value.get("message_id")
    if isinstance(message_id, int):
        return message_id
    return None


def write_report(output_dir: Path, results: list[dict[str, Any]]) -> None:
    lines = [
        "# Multi-User Team Debug Evaluation",
        "",
        f"Generated: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        "",
        "This evaluation uses isolated app-server processes, isolated CODEX_HOME directories, isolated Hollywood servers/databases, and scratch workspaces.",
        "",
        "## Summary",
        "",
        "| Scenario | Runs | Passed | User room messages | Peer responses | Tool errors |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    by_scenario: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        by_scenario.setdefault(result["scenarioId"], []).append(result)
    for scenario_id, scenario_results in sorted(by_scenario.items()):
        passed = sum(1 for result in scenario_results if result["score"]["passed"])
        user_messages = sum(
            sum(
                count
                for role, count in result["score"]["messageCountsByRole"].items()
                if role not in {"peer", "unknown"}
            )
            for result in scenario_results
        )
        peer_responses = sum(
            result["score"]["peerResponseCount"] for result in scenario_results
        )
        tool_errors = sum(
            result["score"]["coordinationToolErrors"] for result in scenario_results
        )
        lines.append(
            f"| {scenario_id} | {len(scenario_results)} | {passed} | {user_messages} | {peer_responses} | {tool_errors} |"
        )

    lines.extend(["", "## Runs", ""])
    for result in results:
        score = result["score"]
        lines.extend(
            [
                f"### {result['scenarioId']} / {result['runId']}",
                "",
                f"- Passed: `{score['passed']}`",
                f"- Alice task done: `{score['aliceTaskDone']}`",
                f"- Bob task done: `{score['bobTaskDone']}`",
                f"- Shared notes have Alice: `{score['sharedNotesHaveAlice']}`",
                f"- Shared notes have Bob: `{score['sharedNotesHaveBob']}`",
                f"- Conflict markers: `{score['conflictMarkers']}`",
                f"- Message counts by role: `{json.dumps(score['messageCountsByRole'], sort_keys=True)}`",
                f"- Direct messages: `{score['directMessageCount']}`",
                f"- Required direct wakes delivered: `{score['requiredDirectWakesDelivered']}`",
                f"- Wake message IDs by role: `{json.dumps(score['wakeMessageIdsByRole'], sort_keys=True)}`",
                f"- Hollywood wake turns by role: `{json.dumps(score['hollywoodWakeTurnsByRole'], sort_keys=True)}`",
                f"- Internal Hollywood responses by role: `{json.dumps(score['internalHollywoodResponsesByRole'], sort_keys=True)}`",
                f"- Peer responses: `{score['peerResponseCount']}`",
                f"- Coordination tool errors: `{score['coordinationToolErrors']}`",
                f"- Result: `{result['scenarioId']}/{result['runId']}/result.json`",
                "",
            ]
        )
    (output_dir / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-name", required=True)
    parser.add_argument("--scenario", action="append", choices=sorted(SCENARIOS))
    parser.add_argument("--runs-per-scenario", type=int, default=1)
    parser.add_argument("--codex", type=Path, default=DEFAULT_CODEX)
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument(
        "--codex-home-source", type=Path, default=Path.home() / ".codex"
    )
    parser.add_argument("--startup-timeout-seconds", type=int, default=60)
    parser.add_argument("--turn-timeout-seconds", type=int, default=240)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ensure_default_codex(args.codex)
    codex = args.codex
    output_dir = args.output_root / args.campaign_name
    output_dir.mkdir(parents=True, exist_ok=True)
    scenarios = [SCENARIOS[name] for name in (args.scenario or sorted(SCENARIOS))]

    results: list[dict[str, Any]] = []
    for scenario in scenarios:
        for _ in range(args.runs_per_scenario):
            result = run_single_eval(
                scenario=scenario,
                codex=codex,
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
                        "runId": result["runId"],
                        "scenarioId": result["scenarioId"],
                        "score": result["score"],
                    },
                    sort_keys=True,
                )
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
