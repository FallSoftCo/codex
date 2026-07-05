#!/usr/bin/env python3
"""Evaluate multi-user Losangelex team behavior with live app-server agents."""

from __future__ import annotations

import argparse
import json
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from dataclasses import field
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
    send_user_turns_sequentially: bool = False
    require_direct_wake: bool = False
    required_note_terms: tuple[str, ...] = ()
    required_file_terms: dict[str, tuple[str, ...]] = field(default_factory=dict)
    required_room_terms: tuple[str, ...] = ()
    required_wake_roles: tuple[str, ...] = ()
    require_peer_response: bool = False
    max_direct_messages: int | None = None


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
        required_file_terms={
            "client/dashboard.js": ("Reconnects", "Reconnecting"),
            "server/permissions.js": ("canExportAudit", 'role === "admin"'),
            "docs/team_notes.md": (
                "## Alice",
                "client/dashboard.js",
                "## Bob",
                "server/permissions.js",
            ),
        },
    ),
    "direct_dependency_after_peer_idle": MultiUserScenario(
        scenario_id="direct_dependency_after_peer_idle",
        description=(
            "Bob completes a server lane and becomes idle; Alice must use a "
            "required Hollywood direct message to wake Bob for the exact helper "
            "name before finishing her client lane and shared notes."
        ),
        files={
            "README.md": """# Direct Dependency Team Debug App

Scratch project for evaluating direct Hollywood wake behavior between user-facing Losangelex agents.
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
                role="bob",
                name="BobAgent",
                prompt="""User Bob asks you to add audit export permission support first.

Make a minimal server-side change in `server/permissions.js`: add an exported
`canExportAudit(role)` helper that returns true only for `admin`.

Also update only the Bob section of `docs/team_notes.md` with the files you
checked and the exact helper name you added. Alice may later ask you a direct
Hollywood question about this helper; if she does, answer her directly and
concisely.
""",
            ),
            UserAgent(
                role="alice",
                name="AliceAgent",
                prompt="""User Alice asks you to improve the dashboard reconnect experience, but this task depends on Bob's completed server lane.

Before making your final shared-notes update, send a Hollywood direct message to
`BobAgent` with `response_policy` set to `required`, asking Bob to confirm the
exact audit export helper name he added. Wait for Bob's Hollywood response and
use that response as your source of truth; do not infer the helper name from
silence.

Then make a minimal client-side change in `client/dashboard.js`: add a
`Reconnects` card and change retrying copy to `Reconnecting`.

Also update only the Alice section of `docs/team_notes.md` with the files you
checked and Bob's confirmed helper name. Do not overwrite Bob's section.
""",
            ),
        ),
        peer_name="QAPeer",
        peer_prompt="""You are an attached Losangelex QA peer for a direct-dependency debug evaluation.

Stay available in this Hollywood room. Do not edit files unless another session
asks. If Alice asks Bob directly, do not answer for Bob; only Bob should answer
the helper-name question.
""",
        send_user_turns_sequentially=True,
        require_direct_wake=True,
        required_note_terms=("canExportAudit",),
        required_file_terms={
            "client/dashboard.js": ("Reconnects", "Reconnecting"),
            "server/permissions.js": ("canExportAudit", 'role === "admin"'),
            "docs/team_notes.md": (
                "## Alice",
                "client/dashboard.js",
                "canExportAudit",
                "## Bob",
                "server/permissions.js",
            ),
        },
        required_wake_roles=("bob",),
        max_direct_messages=4,
    ),
    "three_users_shared_notes": MultiUserScenario(
        scenario_id="three_users_shared_notes",
        description=(
            "Three user-facing agents edit separate files while all three must "
            "coordinate around one shared notes artifact."
        ),
        files={
            "README.md": """# Three User Team Debug App

Scratch project for evaluating simultaneous multi-user Losangelex collaboration.
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
            "ops/runbook.md": """# Ops Runbook

- Audit export policy: pending.
""",
            "docs/team_notes.md": """# Team Notes

## Alice

- TODO

## Bob

- TODO

## Casey

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
checked. Bob and Casey may be working in this same repo; coordinate in
Hollywood before touching shared notes and do not overwrite their sections.
""",
            ),
            UserAgent(
                role="bob",
                name="BobAgent",
                prompt="""User Bob asks you to add audit export permission support.

Make a minimal server-side change in `server/permissions.js`: add an exported
`canExportAudit(role)` helper that returns true only for `admin`.

Also update only the Bob section of `docs/team_notes.md` with the files you
checked. Alice and Casey may be working in this same repo; coordinate in
Hollywood before touching shared notes and do not overwrite their sections.
""",
            ),
            UserAgent(
                role="casey",
                name="CaseyAgent",
                prompt="""User Casey asks you to document the audit export operating rule.

Make a minimal docs change in `ops/runbook.md`: replace the pending audit export
policy with `Audit exports require admin approval.`

Also update only the Casey section of `docs/team_notes.md` with the files you
checked. Alice and Bob may be working in this same repo; coordinate in Hollywood
before touching shared notes and do not overwrite their sections.
""",
            ),
        ),
        peer_name="QAPeer",
        peer_prompt="""You are an attached Losangelex QA peer for a three-user debug evaluation.

Stay available in this Hollywood room. Do not edit files unless another session
asks. If you see conflicting edits, overlapping ownership, or an explicit
verification request, respond with a narrow finding and the exact files checked.
""",
        required_file_terms={
            "client/dashboard.js": ("Reconnects", "Reconnecting"),
            "server/permissions.js": ("canExportAudit", 'role === "admin"'),
            "ops/runbook.md": ("Audit exports require admin approval.",),
            "docs/team_notes.md": (
                "## Alice",
                "client/dashboard.js",
                "## Bob",
                "server/permissions.js",
                "## Casey",
                "ops/runbook.md",
            ),
        },
    ),
    "third_agent_verification_after_dependency": MultiUserScenario(
        scenario_id="third_agent_verification_after_dependency",
        description=(
            "Bob finishes a lane, Alice depends on Bob, then Alice must wake "
            "an idle QA peer with a required direct verification request before "
            "marking the shared work complete."
        ),
        files={
            "README.md": """# Third Agent Verification Team Debug App

Scratch project for evaluating required Hollywood wake behavior across two peers.
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
                role="bob",
                name="BobAgent",
                prompt="""User Bob asks you to add audit export permission support first.

Make a minimal server-side change in `server/permissions.js`: add an exported
`canExportAudit(role)` helper that returns true only for `admin`.

Also update only the Bob section of `docs/team_notes.md` with the files you
checked and the exact helper name you added. Alice may later ask you a direct
Hollywood question about this helper; if she does, answer her directly and
concisely.
""",
            ),
            UserAgent(
                role="alice",
                name="AliceAgent",
                prompt="""User Alice asks you to improve the dashboard reconnect experience and get independent verification before marking the work complete.

First send a Hollywood direct message to `BobAgent` with `response_policy` set
to `required`, asking Bob to confirm the exact audit export helper name he
added. Wait for Bob's Hollywood response and use that response as your source of
truth; do not infer the helper name from silence.

Then make a minimal client-side change in `client/dashboard.js`: add a
`Reconnects` card and change retrying copy to `Reconnecting`.

Update only the Alice section of `docs/team_notes.md` with the files you checked
and Bob's confirmed helper name. Do not overwrite Bob's section.

Before your final answer, send a second Hollywood direct message to `QAPeer`
with `response_policy` set to `required`, asking QA to verify
`client/dashboard.js`, `server/permissions.js`, and `docs/team_notes.md`.
Wait for QAPeer's Hollywood response before marking the task done.
""",
            ),
        ),
        peer_name="QAPeer",
        peer_prompt="""You are an attached Losangelex QA peer for a third-agent verification debug evaluation.

Stay available in this Hollywood room. Do not edit files unless another session
asks. If Alice sends you a direct required verification request, inspect
`client/dashboard.js`, `server/permissions.js`, and `docs/team_notes.md`, then
reply in Hollywood with the exact files checked and whether the Alice and Bob
sections are both preserved.
""",
        send_user_turns_sequentially=True,
        require_direct_wake=True,
        required_note_terms=("canExportAudit",),
        required_file_terms={
            "client/dashboard.js": ("Reconnects", "Reconnecting"),
            "server/permissions.js": ("canExportAudit", 'role === "admin"'),
            "docs/team_notes.md": (
                "## Alice",
                "client/dashboard.js",
                "canExportAudit",
                "## Bob",
                "server/permissions.js",
            ),
        },
        required_room_terms=(
            "client/dashboard.js",
            "server/permissions.js",
            "docs/team_notes.md",
        ),
        required_wake_roles=("bob", "peer"),
        require_peer_response=True,
        max_direct_messages=6,
    ),
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
    started_at = time.time()
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
            if scenario.send_user_turns_sequentially:
                for user_agent, agent in zip(
                    scenario.user_agents,
                    user_started_agents,
                    strict=True,
                ):
                    send_turn(conn, agent.thread_id, user_agent.prompt)
                    wait_for_threads(
                        conn,
                        {agent.thread_id},
                        timeout_seconds=turn_timeout_seconds,
                    )
                    conn.drain(5)
            else:
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
        for relative in scenario.files
    }
    score = score_run(
        scenario=scenario,
        agents=agents,
        room_messages=room_messages,
        notification_summary=notification_summary,
        notifications=notifications,
        diff=diff,
        file_contents=file_contents,
    )
    ended_at = time.time()
    result = {
        "scenarioId": scenario.scenario_id,
        "description": scenario.description,
        "model": model,
        "runId": run_id,
        "startedAt": started_at,
        "endedAt": ended_at,
        "wallSeconds": round(ended_at - started_at, 3),
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
    scenario: MultiUserScenario,
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
    pending_required_direct_by_pair: dict[tuple[str, str], int] = {}
    duplicate_pending_required_direct_ids: list[int] = []

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
        sender_key = hollywood_identity_key(sender, agents, thread_roles)
        recipient_key = hollywood_identity_key(recipient, agents, thread_roles)
        if recipient:
            direct_messages += 1
        if (
            message_id is not None
            and recipient
            and response_policy.lower() == "required"
        ):
            required_message_id = int(message_id)
            required_direct_message_ids.add(required_message_id)
            pending_key = (sender_key, recipient_key)
            if pending_key in pending_required_direct_by_pair:
                duplicate_pending_required_direct_ids.append(required_message_id)
            else:
                pending_required_direct_by_pair[pending_key] = required_message_id
        elif recipient:
            pending_required_direct_by_pair.pop((recipient_key, sender_key), None)
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
    required_wake_roles_met = all(
        bool(wake_message_ids_by_role.get(role))
        for role in scenario.required_wake_roles
    )

    client = file_contents["client/dashboard.js"]
    server = file_contents["server/permissions.js"]
    notes = file_contents["docs/team_notes.md"]
    alice_done = "Reconnects" in client and "Reconnecting" in client
    bob_done = "canExportAudit" in server and 'role === "admin"' in server
    notes_have_alice = "## Alice" in notes and "client/dashboard.js" in notes
    notes_have_bob = "## Bob" in notes and "server/permissions.js" in notes
    required_note_terms_present = all(
        term in notes for term in scenario.required_note_terms
    )
    required_file_terms_present_by_file = {
        relative: all(term in file_contents.get(relative, "") for term in terms)
        for relative, terms in scenario.required_file_terms.items()
    }
    required_file_terms_present = all(required_file_terms_present_by_file.values())
    room_message_text = "\n".join(
        str(message.get("body") or "") for message in room_messages
    )
    room_message_text_lower = room_message_text.lower()
    required_room_terms_present_by_term = {
        term: term.lower() in room_message_text_lower
        for term in scenario.required_room_terms
    }
    required_room_terms_present = all(required_room_terms_present_by_term.values())
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

    direct_wake_requirement_met = required_direct_wakes_delivered and (
        not scenario.require_direct_wake
        or (
            direct_messages > 0
            and bool(required_direct_message_ids)
            and sum(hollywood_wake_turns_by_role.values()) > 0
            and required_wake_roles_met
        )
    )
    peer_response_requirement_met = (
        not scenario.require_peer_response or peer_responses > 0
    )
    direct_message_limit_met = (
        scenario.max_direct_messages is None
        or direct_messages <= scenario.max_direct_messages
    )
    duplicate_pending_required_directs = bool(duplicate_pending_required_direct_ids)
    passed = (
        alice_done
        and bob_done
        and notes_have_alice
        and notes_have_bob
        and required_note_terms_present
        and required_file_terms_present
        and required_room_terms_present
        and not conflict_markers
        and coordination_errors == 0
        and user_roles_with_messages == user_roles
        and direct_wake_requirement_met
        and peer_response_requirement_met
        and direct_message_limit_met
        and not duplicate_pending_required_directs
    )
    return {
        "passed": passed,
        "aliceTaskDone": alice_done,
        "bobTaskDone": bob_done,
        "sharedNotesHaveAlice": notes_have_alice,
        "sharedNotesHaveBob": notes_have_bob,
        "requiredNoteTermsPresent": required_note_terms_present,
        "requiredFileTermsPresent": required_file_terms_present,
        "requiredFileTermsPresentByFile": required_file_terms_present_by_file,
        "requiredRoomTermsPresent": required_room_terms_present,
        "requiredRoomTermsPresentByTerm": required_room_terms_present_by_term,
        "conflictMarkers": conflict_markers,
        "workspaceChanged": bool(diff.strip()),
        "messageCountsByRole": dict(message_counts_by_role),
        "directMessageCount": direct_messages,
        "maxDirectMessages": scenario.max_direct_messages,
        "directMessageLimitMet": direct_message_limit_met,
        "requiredDirectMessageIds": sorted(required_direct_message_ids),
        "duplicatePendingRequiredDirectIds": duplicate_pending_required_direct_ids,
        "duplicatePendingRequiredDirects": duplicate_pending_required_directs,
        "requiredDirectWakesDelivered": required_direct_wakes_delivered,
        "requiredWakeRoles": list(scenario.required_wake_roles),
        "requiredWakeRolesMet": required_wake_roles_met,
        "directWakeRequirementMet": direct_wake_requirement_met,
        "wakeMessageIdsByRole": wake_message_ids_by_role,
        "turnStartsByRole": dict(turn_starts_by_role),
        "hollywoodWakeTurnsByRole": dict(hollywood_wake_turns_by_role),
        "internalHollywoodResponsesByRole": dict(internal_hollywood_responses_by_role),
        "peerResponseCount": peer_responses,
        "peerResponseRequirementMet": peer_response_requirement_met,
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


def hollywood_identity_key(
    identity: str,
    agents: list[StartedAgent],
    thread_roles: dict[str, str],
) -> str:
    if not identity:
        return ""
    if identity in thread_roles:
        return thread_roles[identity]
    canonical_identity = canonical_identity_fragment(identity)
    for agent in agents:
        if canonical_identity == canonical_identity_fragment(agent.name):
            return agent.role
    return canonical_identity or identity


def canonical_identity_fragment(identity: str) -> str:
    return "".join(char for char in identity.lower() if char.isalnum())


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
        "| Scenario | Runs | Passed | Wall s | User room messages | Direct messages | Duplicate required | Wake turns | Peer responses | Uncached+out tokens | Tool errors |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
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
        direct_messages = sum(
            result["score"]["directMessageCount"] for result in scenario_results
        )
        duplicate_required = sum(
            len(result["score"].get("duplicatePendingRequiredDirectIds", []))
            for result in scenario_results
        )
        wake_turns = sum(
            sum(result["score"]["hollywoodWakeTurnsByRole"].values())
            for result in scenario_results
        )
        uncached_plus_output_tokens = sum(
            result["score"].get("tokenUsage", {}).get("uncachedPlusOutputTokens", 0)
            for result in scenario_results
        )
        wall_seconds = sum(
            result.get("wallSeconds", 0.0) for result in scenario_results
        )
        tool_errors = sum(
            result["score"]["coordinationToolErrors"] for result in scenario_results
        )
        lines.append(
            f"| {scenario_id} | {len(scenario_results)} | {passed} | {wall_seconds:.1f} | {user_messages} | {direct_messages} | {duplicate_required} | {wake_turns} | {peer_responses} | {uncached_plus_output_tokens} | {tool_errors} |"
        )

    lines.extend(["", "## Runs", ""])
    for result in results:
        score = result["score"]
        lines.extend(
            [
                f"### {result['scenarioId']} / {result['runId']}",
                "",
                f"- Passed: `{score['passed']}`",
                f"- Wall seconds: `{result.get('wallSeconds', 0.0)}`",
                f"- Alice task done: `{score['aliceTaskDone']}`",
                f"- Bob task done: `{score['bobTaskDone']}`",
                f"- Shared notes have Alice: `{score['sharedNotesHaveAlice']}`",
                f"- Shared notes have Bob: `{score['sharedNotesHaveBob']}`",
                f"- Required note terms present: `{score['requiredNoteTermsPresent']}`",
                f"- Required file terms present: `{score['requiredFileTermsPresent']}`",
                f"- Required room terms present: `{score['requiredRoomTermsPresent']}`",
                f"- Conflict markers: `{score['conflictMarkers']}`",
                f"- Message counts by role: `{json.dumps(score['messageCountsByRole'], sort_keys=True)}`",
                f"- Direct messages: `{score['directMessageCount']}`",
                f"- Direct message limit met: `{score['directMessageLimitMet']}`",
                f"- Required direct wakes delivered: `{score['requiredDirectWakesDelivered']}`",
                f"- Duplicate pending required directs: `{score['duplicatePendingRequiredDirects']}`",
                f"- Required wake roles met: `{score['requiredWakeRolesMet']}`",
                f"- Direct wake requirement met: `{score['directWakeRequirementMet']}`",
                f"- Wake message IDs by role: `{json.dumps(score['wakeMessageIdsByRole'], sort_keys=True)}`",
                f"- Hollywood wake turns by role: `{json.dumps(score['hollywoodWakeTurnsByRole'], sort_keys=True)}`",
                f"- Internal Hollywood responses by role: `{json.dumps(score['internalHollywoodResponsesByRole'], sort_keys=True)}`",
                f"- Peer responses: `{score['peerResponseCount']}`",
                f"- Peer response requirement met: `{score['peerResponseRequirementMet']}`",
                f"- Coordination tool errors: `{score['coordinationToolErrors']}`",
                f"- Token usage: `{json.dumps(score.get('tokenUsage', {}), sort_keys=True)}`",
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
