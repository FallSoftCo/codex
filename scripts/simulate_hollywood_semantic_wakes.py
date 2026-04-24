#!/usr/bin/env python3
"""Replay Losangelex Hollywood wakes against a prototype semantic wake policy.

This is an offline analysis tool. It reads:
- rollout JSONL files for selected sessions
- the Hollywood registry/messages database
- the Losangelex state database

It compares the current raw "recent room activity" wake behavior to a narrow
prototype policy:
- wake on explicit scheduled coordination work
- wake on direct requests or fresh assignments
- suppress repeated "still blocked / no clean lane" turns
- suppress ambient-only or stale-board-cleanup turns when the agent is not the
  creator/owner that can act on them

The goal is not to perfectly emulate the runtime. The goal is to test whether
the proposed architecture would materially reduce obvious no-op turns on the
real April 22, 2026 traffic.
"""

from __future__ import annotations

import argparse
import dataclasses
import glob
import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from typing import Any


AUTONOMOUS_WAKE_BODY = (
    "Autonomous Hollywood follow-up: room activity happened after your last turn started."
)

NOOP_PATTERNS = (
    "no new",
    "no change",
    "no further",
    "no action",
    "no user-facing update",
    "still floating",
    "still unclaimed",
    "standing by",
    "staying off",
)

NO_LANE_PATTERNS = (
    "no clean lane",
    "no additional",
    "no lane",
    "stay off",
    "do not touch",
    "keep your pause",
    "stay unclaimed",
    "owned by another session",
    "not yours right now",
)

STALE_BOARD_PATTERNS = (
    "stale task",
    "board cleanup",
    "creator-control",
    "dead lane",
    "cleanup note",
)

ASSIGNMENT_PATTERNS = (
    "official award",
    "your exact lane",
    "take option",
    "exact slice for you",
    "assigned to you",
    "take the awarded",
    "current clean lane from my side",
)

REQUEST_PATTERNS = (
    "please",
    "what",
    "need",
    "pick",
    "can you",
    "do you",
    "close stale task",
    "name one exact",
    "confirm who",
    "reply",
)


@dataclasses.dataclass
class RegistryEntry:
    session_id: str
    identities: list[str]
    attached: bool
    updated_at: str


@dataclasses.dataclass
class HollywoodMessage:
    message_id: int | None
    room: str | None
    sender_id: str | None
    recipient_id: str | None
    body: str
    message_kind: str | None
    raw: dict[str, Any]


@dataclasses.dataclass
class TurnRecord:
    session_id: str
    agent_name: str
    turn_id: str
    started_at: int | None
    started_timestamp: str | None
    autonomous_wake: bool = False
    scheduled_contexts: list[dict[str, str]] = dataclasses.field(default_factory=list)
    incoming_messages: list[HollywoodMessage] = dataclasses.field(default_factory=list)
    tool_calls: dict[str, str] = dataclasses.field(default_factory=dict)
    list_tasks_outputs: list[list[dict[str, Any]]] = dataclasses.field(default_factory=list)
    assistant_output: str = ""


@dataclasses.dataclass
class SimulatedWake:
    turn: TurnRecord
    label: str
    should_wake: bool
    rationale: str
    noop_output: bool
    task_snapshot: list[dict[str, Any]]


def load_current_tasks_map(state_db: str, task_ids: set[str]) -> dict[str, dict[str, Any]]:
    if not task_ids:
        return {}
    conn = sqlite3.connect(state_db)
    conn.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" for _ in task_ids)
        rows = conn.execute(
            f"""
            SELECT id, owner_thread_id, status, summary
            FROM coordination_tasks
            WHERE id IN ({placeholders})
            """,
            sorted(task_ids),
        ).fetchall()
    finally:
        conn.close()
    return {
        row["id"]: {
            "id": row["id"],
            "owner_thread_id": row["owner_thread_id"],
            "status": row["status"],
            "summary": row["summary"],
        }
        for row in rows
    }


def extract_uuid(text: str) -> str:
    match = re.search(
        r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
        text,
        re.IGNORECASE,
    )
    if not match:
        raise ValueError(f"could not find uuid in {text}")
    return match.group(1)


def shorten(text: str, limit: int = 160) -> str:
    clean = re.sub(r"\s+", " ", text.strip())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3] + "..."


def parse_tag_json(tag: str, text: str) -> dict[str, Any] | None:
    match = re.search(rf"<{tag}>\s*(.+?)\s*</{tag}>", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def parse_key_value_block(tag: str, text: str) -> dict[str, str] | None:
    match = re.search(rf"<{tag}>\n(.*?)\n</{tag}>", text, re.DOTALL)
    if not match:
        return None
    result: dict[str, str] = {}
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip()
    return result


def output_is_obvious_noop(text: str) -> bool:
    lower = text.lower()
    return any(pattern in lower for pattern in NOOP_PATTERNS)


def load_registry_entries(hollywood_db: str) -> list[RegistryEntry]:
    conn = sqlite3.connect(hollywood_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT session_id, identities_json, attached, updated_at
            FROM registry
            ORDER BY updated_at DESC
            """
        ).fetchall()
    finally:
        conn.close()

    entries: list[RegistryEntry] = []
    for row in rows:
        identities = json.loads(row["identities_json"] or "[]")
        entries.append(
            RegistryEntry(
                session_id=row["session_id"],
                identities=identities,
                attached=bool(row["attached"]),
                updated_at=row["updated_at"] or "",
            )
        )
    return entries


def choose_sessions(
    entries: list[RegistryEntry], requested_names: list[str]
) -> tuple[dict[str, RegistryEntry], dict[str, list[str]]]:
    chosen: dict[str, RegistryEntry] = {}
    duplicates: dict[str, list[str]] = {}
    for name in requested_names:
        matches = [
            entry
            for entry in entries
            if entry.attached and name in entry.identities
        ]
        duplicates[name] = [entry.session_id for entry in matches]
        if matches:
            chosen[name] = matches[0]
    return chosen, duplicates


def find_rollout_path(sessions_root: str, session_id: str) -> str:
    matches = glob.glob(os.path.join(sessions_root, f"**/*{session_id}.jsonl"), recursive=True)
    if not matches:
        raise FileNotFoundError(f"no rollout found for {session_id} under {sessions_root}")
    matches.sort()
    return matches[-1]


def load_turns(rollout_path: str, session_id: str, agent_name: str) -> list[TurnRecord]:
    turns: list[TurnRecord] = []
    current: TurnRecord | None = None

    with open(rollout_path, "r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = json.loads(raw_line)
            line_type = line.get("type")
            payload = line.get("payload", {})

            if line_type == "event_msg" and payload.get("type") == "task_started":
                current = TurnRecord(
                    session_id=session_id,
                    agent_name=agent_name,
                    turn_id=payload["turn_id"],
                    started_at=payload.get("started_at"),
                    started_timestamp=line.get("timestamp"),
                )
                turns.append(current)
                continue

            if current is None:
                continue

            if line_type == "response_item":
                item_type = payload.get("type")
                if item_type == "function_call":
                    current.tool_calls[payload["call_id"]] = payload["name"]
                elif item_type == "function_call_output":
                    call_name = current.tool_calls.get(payload.get("call_id", ""))
                    output = payload.get("output", "")
                    if call_name == "list_coordination_tasks":
                        try:
                            parsed = json.loads(output)
                            current.list_tasks_outputs.append(parsed.get("tasks", []))
                        except json.JSONDecodeError:
                            pass
                elif item_type == "message":
                    role = payload.get("role")
                    parts = payload.get("content", [])
                    texts = [
                        part.get("text") or part.get("output_text") or ""
                        for part in parts
                    ]
                    combined = "\n".join(texts)
                    if role == "developer":
                        hm = parse_tag_json("hollywood_message", combined)
                        if hm:
                            message = HollywoodMessage(
                                message_id=hm.get("message_id"),
                                room=hm.get("room"),
                                sender_id=hm.get("sender_id"),
                                recipient_id=hm.get("recipient_id"),
                                body=hm.get("body", ""),
                                message_kind=hm.get("message_kind"),
                                raw=hm,
                            )
                            if (
                                message.sender_id == "hollywood-system"
                                and AUTONOMOUS_WAKE_BODY in message.body
                            ):
                                current.autonomous_wake = True
                            elif message.sender_id != "hollywood-system":
                                current.incoming_messages.append(message)
                    elif role == "user":
                        scheduled = parse_key_value_block("scheduled_task_context", combined)
                        if scheduled:
                            coordination = parse_key_value_block(
                                "coordination_context", combined
                            ) or {}
                            merged = dict(scheduled)
                            merged.update(
                                {
                                    f"coordination_{key}": value
                                    for key, value in coordination.items()
                                }
                            )
                            current.scheduled_contexts.append(merged)
                    elif role == "assistant":
                        text = "\n".join(text for text in texts if text).strip()
                        if text:
                            current.assistant_output = text

            if line_type == "event_msg" and payload.get("type") == "task_complete":
                if payload.get("turn_id") == current.turn_id:
                    current = None

    return turns


def classify_turn(turn: TurnRecord, previous_label: str | None) -> SimulatedWake:
    task_snapshot = turn.list_tasks_outputs[-1] if turn.list_tasks_outputs else []
    owned_or_created = {
        task.get("id")
        for task in task_snapshot
        if task.get("owner_thread_id") == turn.session_id
        or task.get("creator_thread_id") == turn.session_id
    }

    if turn.scheduled_contexts:
        return SimulatedWake(
            turn=turn,
            label="assigned_task",
            should_wake=True,
            rationale="scheduled coordination context attached",
            noop_output=output_is_obvious_noop(turn.assistant_output),
            task_snapshot=task_snapshot,
        )

    bodies = " \n".join(message.body for message in turn.incoming_messages)
    lower = bodies.lower()

    if not turn.incoming_messages:
        return SimulatedWake(
            turn=turn,
            label="ambient_only",
            should_wake=False,
            rationale="generic autonomous wake with no attached non-system messages",
            noop_output=output_is_obvious_noop(turn.assistant_output),
            task_snapshot=task_snapshot,
        )

    if any(pattern in lower for pattern in ASSIGNMENT_PATTERNS):
        return SimulatedWake(
            turn=turn,
            label="assigned_task",
            should_wake=True,
            rationale="incoming message carries a fresh assignment pattern",
            noop_output=output_is_obvious_noop(turn.assistant_output),
            task_snapshot=task_snapshot,
        )

    if any(pattern in lower for pattern in REQUEST_PATTERNS):
        actionable_cleanup = any(
            "close stale task" in message.body.lower() and owned_or_created
            for message in turn.incoming_messages
        )
        if actionable_cleanup or "close stale task" not in lower:
            return SimulatedWake(
                turn=turn,
                label="needs_reply",
                should_wake=True,
                rationale="direct request or question is present",
                noop_output=output_is_obvious_noop(turn.assistant_output),
                task_snapshot=task_snapshot,
            )

    if any(pattern in lower for pattern in NO_LANE_PATTERNS):
        should_wake = previous_label != "blocked_no_lane"
        rationale = "first blocked/no-lane state change" if should_wake else "same blocked/no-lane state repeated"
        return SimulatedWake(
            turn=turn,
            label="blocked_no_lane",
            should_wake=should_wake,
            rationale=rationale,
            noop_output=output_is_obvious_noop(turn.assistant_output),
            task_snapshot=task_snapshot,
        )

    if any(pattern in lower for pattern in STALE_BOARD_PATTERNS):
        actionable = bool(owned_or_created)
        return SimulatedWake(
            turn=turn,
            label="board_cleanup",
            should_wake=actionable,
            rationale=(
                "stale-board cleanup is actionable because this session owns or created a visible task"
                if actionable
                else "stale-board cleanup references work this session cannot directly close"
            ),
            noop_output=output_is_obvious_noop(turn.assistant_output),
            task_snapshot=task_snapshot,
        )

    return SimulatedWake(
        turn=turn,
        label="informational_room_delta",
        should_wake=False,
        rationale="incoming messages are informational only under the prototype policy",
        noop_output=output_is_obvious_noop(turn.assistant_output),
        task_snapshot=task_snapshot,
    )


def simulate_agent(turns: list[TurnRecord]) -> list[SimulatedWake]:
    simulations: list[SimulatedWake] = []
    previous_label: str | None = None
    for turn in turns:
        if not turn.autonomous_wake:
            continue
        simulated = classify_turn(turn, previous_label)
        simulations.append(simulated)
        if simulated.should_wake:
            previous_label = simulated.label
    return simulations


def render_brief(
    simulated: SimulatedWake, current_tasks_map: dict[str, dict[str, Any]] | None = None
) -> list[str]:
    turn = simulated.turn
    current_tasks_map = current_tasks_map or {}
    lines = [
        f"identity: {turn.agent_name}",
        f"turn_id: {turn.turn_id}",
        f"prototype_label: {simulated.label}",
        f"should_wake: {'yes' if simulated.should_wake else 'no'}",
        f"rationale: {simulated.rationale}",
    ]
    if simulated.task_snapshot:
        active_or_open = [
            task
            for task in simulated.task_snapshot
            if task.get("status") in {"active", "open", "awarded", "blocked"}
        ]
        if active_or_open:
            lines.append("task_snapshot:")
            for task in active_or_open:
                current = current_tasks_map.get(task.get("id", ""))
                current_suffix = ""
                if current:
                    current_suffix = (
                        f" current_status={current.get('status')} "
                        f"current_owner={current.get('owner_thread_id') or '-'}"
                    )
                lines.append(
                    "  - {status} {id} owner={owner} summary={summary}{current_suffix}".format(
                        status=task.get("status"),
                        id=task.get("id"),
                        owner=task.get("owner_thread_id") or "-",
                        summary=task.get("summary"),
                        current_suffix=current_suffix,
                    )
                )
    if turn.incoming_messages:
        lines.append("incoming_messages:")
        for message in turn.incoming_messages:
            lines.append(
                "  - {kind} from={sender} to={recipient} body={body}".format(
                    kind=message.message_kind or "-",
                    sender=message.sender_id or "-",
                    recipient=message.recipient_id or "-",
                    body=shorten(message.body, 200),
                )
            )
    lines.append(f"assistant_output: {shorten(turn.assistant_output, 220)}")
    return lines


def print_summary(simulations_by_agent: dict[str, list[SimulatedWake]]) -> None:
    print("Semantic wake replay summary")
    print("===========================")
    total_actual = 0
    total_should_wake = 0
    total_noop = 0
    for agent, sims in simulations_by_agent.items():
        actual = len(sims)
        should_wake = sum(1 for sim in sims if sim.should_wake)
        noops = sum(1 for sim in sims if sim.noop_output)
        total_actual += actual
        total_should_wake += should_wake
        total_noop += noops
        counts = Counter(sim.label for sim in sims)
        label_summary = ", ".join(f"{label}={count}" for label, count in sorted(counts.items()))
        print(
            f"- {agent}: actual_wakes={actual} prototype_wakes={should_wake} suppressed={actual - should_wake} "
            f"obvious_noop_outputs={noops} labels=[{label_summary}]"
        )
    print(
        f"- total: actual_wakes={total_actual} prototype_wakes={total_should_wake} "
        f"suppressed={total_actual - total_should_wake} obvious_noop_outputs={total_noop}"
    )


def print_identity_audit(entries: list[RegistryEntry], chosen: dict[str, RegistryEntry], duplicates: dict[str, list[str]]) -> None:
    print("\nIdentity audit")
    print("==============")
    for name in sorted(duplicates):
        sessions = duplicates[name]
        selected = chosen.get(name)
        selected_id = selected.session_id if selected else "-"
        print(
            f"- {name}: attached_matches={len(sessions)} selected={selected_id} all={', '.join(sessions) if sessions else '-'}"
        )
    dup_counts: Counter[str] = Counter()
    for entry in entries:
        if not entry.attached:
            continue
        for identity in entry.identities:
            dup_counts[identity] += 1
    live_duplicates = [
        (identity, count)
        for identity, count in dup_counts.items()
        if count > 1 and re.fullmatch(r"[a-z][a-z0-9-]*", identity or "")
    ]
    for identity, count in sorted(live_duplicates):
        print(f"- duplicate live logical identity: {identity} x{count}")


def main() -> int:
    home = os.path.expanduser("~")
    parser = argparse.ArgumentParser(
        description="Replay autonomous Hollywood wakes against a semantic wake prototype."
    )
    parser.add_argument(
        "--sessions-root",
        default=os.path.join(home, ".codex", "sessions", "2026", "04", "22"),
    )
    parser.add_argument(
        "--hollywood-db",
        default=os.path.join(home, ".hollywood", "hollywood.db"),
    )
    parser.add_argument(
        "--state-db",
        default=os.path.join(home, ".codex", "state_7.sqlite"),
    )
    parser.add_argument(
        "--agents",
        default="tony,chris,james,ray,duggs",
        help="Comma-separated logical agent names to simulate.",
    )
    parser.add_argument(
        "--detailed-agent",
        default="duggs",
        help="Agent name to print detailed synthetic briefs for.",
    )
    args = parser.parse_args()

    requested_names = [name.strip() for name in args.agents.split(",") if name.strip()]
    entries = load_registry_entries(args.hollywood_db)
    chosen, duplicates = choose_sessions(entries, requested_names)

    simulations_by_agent: dict[str, list[SimulatedWake]] = {}
    for agent_name in requested_names:
        if agent_name not in chosen:
            print(f"warning: no attached registry entry found for {agent_name}")
            continue
        session_id = chosen[agent_name].session_id
        rollout_path = find_rollout_path(args.sessions_root, session_id)
        turns = load_turns(rollout_path, session_id, agent_name)
        simulations_by_agent[agent_name] = simulate_agent(turns)

    print_summary(simulations_by_agent)
    print_identity_audit(entries, chosen, duplicates)

    detailed = simulations_by_agent.get(args.detailed_agent)
    if detailed:
        detailed_task_ids = {
            task.get("id")
            for sim in detailed
            for task in sim.task_snapshot
            if task.get("id")
        }
        current_tasks_map = load_current_tasks_map(args.state_db, detailed_task_ids)
        print(f"\nDetailed synthetic briefs for {args.detailed_agent}")
        print("=" * (31 + len(args.detailed_agent)))
        for sim in detailed:
            print(f"\n[{sim.turn.started_timestamp}]")
            for line in render_brief(sim, current_tasks_map):
                print(line)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
