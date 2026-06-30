#!/usr/bin/env python3
"""Evaluate whether Losangelex team agents naturally communicate through Hollywood."""

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchmark_app_server import prepare_minimal_codex_home
from benchmark_token_usage import normalize_token_usage
from benchmark_token_usage import sum_token_usage
from eval_collaboration_first_debug import fetch_room_messages
from eval_collaboration_first_debug import managed_debug_app_server
from eval_collaboration_first_debug import managed_hollywood_server
from eval_collaboration_first_debug import wait_for_tracked_turns
from eval_hollywood_app_builds import DEFAULT_EVAL_MODEL_PROVIDER
from losangelex_codex_bin import DEFAULT_CODEX
from losangelex_codex_bin import ensure_default_codex
from replay_hollywood_operator import JsonRpcWs
from replay_hollywood_operator import initialize
from replay_hollywood_operator import read_thread_state
from replay_hollywood_operator import send_turn
from replay_hollywood_operator import start_agent
from replay_hollywood_operator import summarize_notifications


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_ROOT = REPO_ROOT / "tmp/research/hollywood-communication-tendency"
PROFILE_CHOICES = (
    "current",
    "communication",
    "dependency_prompt",
    "structured_brief",
    "dependency_structured",
)

COMMUNICATION_GUIDANCE = """Losangelex team communication expectation:
- Hollywood is the shared working room for this team, not just an emergency channel.
- Before starting your lane, send one concise Hollywood message in your own voice saying what you are taking up and when you expect to report back.
- If you change direction, become blocked, need attention, or finish, send a concise Hollywood update before or alongside your final answer.
- These work-state messages are not chatter; they are how teammates know the team is active.
"""

DEPENDENCY_GUIDANCE = """Dependency-aware communication expectation:
- If your lane verifies, summarizes, reviews, or integrates another lane, do not finalize from stale assumptions.
- Before finishing dependency-sensitive work, read recent Hollywood updates and inspect the relevant workspace files after the producing lane has had a chance to report.
- If the dependency has not reported yet, wait briefly or state exactly what evidence you used and what remains uncertain.
- Your finish message should name the dependency evidence you relied on when another lane affects your result.
"""

START_TERMS = (
    "accept",
    "accepted",
    "begin",
    "beginning",
    "start",
    "started",
    "starting",
    "taking",
    "i'll",
    "i will",
    "working on",
    "inspecting",
    "checking",
    "claim",
    "claimed",
    "claiming",
)

FINISH_TERMS = (
    "done",
    "finish",
    "finished",
    "complete",
    "completed",
    "result",
    "updated",
    "changed",
    "wrote",
    "verified",
)

COLLABORATIVE_EDIT_TERMS = (
    "append-only",
    "collaborative edit",
    "conflict-free",
    "same file",
    "shared file",
    "sidecar",
    "slice",
    "section",
    "handoff",
    "integrator",
    "reread",
    "current diff",
)


@dataclass(frozen=True)
class AgentSpec:
    name: str
    lane: str
    expected: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class CommunicationScenario:
    scenario_id: str
    description: str
    method: str
    files: dict[str, str]
    agents: tuple[AgentSpec, ...]


METHOD_DESCRIPTIONS = {
    "independent_files": "Agents work in separate files and coordinate only because outputs/dependencies matter.",
    "direct_same_file_slices": "Agents edit the same file in parallel by agreeing on narrow sections or hunks.",
    "serial_same_file_handoff": "Agents edit the same file in an explicit order, handing off after each slice.",
    "append_only_shared_ledger": "Agents write unique append-only sections in a shared ledger-style file.",
    "conflict_free_sidecars": "Agents write separate sidecar files, then an integrator merges those sidecars.",
}


SCENARIOS: dict[str, CommunicationScenario] = {
    "docs_pair": CommunicationScenario(
        scenario_id="docs_pair",
        description="Two-agent docs update where both agents have independent lanes.",
        method="independent_files",
        files={
            "README.md": "# Communication Eval\n",
            "docs/status.md": "# Status\n\nCurrent status is unknown.\n",
            "docs/review.md": "# Review\n\nNo review has been recorded.\n",
        },
        agents=(
            AgentSpec(
                name="StatusWriter",
                lane="Update docs/status.md to mention a handoff checkpoint and keep the file concise.",
                expected={"docs/status.md": ("handoff checkpoint",)},
            ),
            AgentSpec(
                name="ReviewWriter",
                lane="Update docs/review.md to say that the status note was reviewed for the release handoff.",
                expected={"docs/review.md": ("release handoff",)},
            ),
        ),
    ),
    "retry_pair": CommunicationScenario(
        scenario_id="retry_pair",
        description="Two-agent implementation and verification note.",
        method="independent_files",
        files={
            "src/retry.js": """export function retryDelay(attempt) {
  return Math.min(attempt, 4) * 250;
}
""",
            "tests/retry_notes.md": "# Retry Notes\n\nNo jitter check yet.\n",
        },
        agents=(
            AgentSpec(
                name="RetryImplementer",
                lane="Update src/retry.js so retryDelay applies small jitter using Math.random while keeping the capped base delay.",
                expected={"src/retry.js": ("Math.random", "retryDelay")},
            ),
            AgentSpec(
                name="RetryVerifier",
                lane="Inspect the retry helper and update tests/retry_notes.md with the observed retryDelay behavior and whether jitter is present.",
                expected={"tests/retry_notes.md": ("retryDelay", "Math.random")},
            ),
        ),
    ),
    "shared_file_pair": CommunicationScenario(
        scenario_id="shared_file_pair",
        description="Two-agent same-file edit with separate sections.",
        method="direct_same_file_slices",
        files={
            "docs/guide.md": """# Operator Guide

## Setup

Pending.

## Validation

Pending.
""",
        },
        agents=(
            AgentSpec(
                name="SetupEditor",
                lane="Collaboratively edit docs/guide.md. Own only the Setup section: replace its placeholder with one concise setup instruction mentioning dependency installation. Coordinate with ValidationEditor because they will edit another section in the same file.",
                expected={"docs/guide.md": ("dependenc", "install")},
            ),
            AgentSpec(
                name="ValidationEditor",
                lane="Collaboratively edit docs/guide.md. Own only the Validation section: replace its placeholder with one concise validation instruction mentioning tests pass. Coordinate with SetupEditor because they will edit another section in the same file.",
                expected={"docs/guide.md": ("validation", "test", "pass")},
            ),
        ),
    ),
    "shared_file_trio": CommunicationScenario(
        scenario_id="shared_file_trio",
        description="Three-agent same-file edit with separate sections.",
        method="direct_same_file_slices",
        files={
            "docs/guide.md": """# Operator Guide

## Setup

Pending.

## Validation

Pending.

## Troubleshooting

Pending.
""",
        },
        agents=(
            AgentSpec(
                name="SetupEditor",
                lane="Collaboratively edit docs/guide.md. Own only the Setup section: replace its placeholder with one concise setup instruction mentioning dependency installation. Coordinate with ValidationEditor and TroubleshootingEditor because they will edit other sections in the same file.",
                expected={"docs/guide.md": ("dependenc", "install")},
            ),
            AgentSpec(
                name="ValidationEditor",
                lane="Collaboratively edit docs/guide.md. Own only the Validation section: replace its placeholder with one concise validation instruction mentioning tests pass. Coordinate with SetupEditor and TroubleshootingEditor because they will edit other sections in the same file.",
                expected={"docs/guide.md": ("validation", "test", "pass")},
            ),
            AgentSpec(
                name="TroubleshootingEditor",
                lane="Collaboratively edit docs/guide.md. Own only the Troubleshooting section: replace its placeholder with one concise troubleshooting instruction mentioning logs. Coordinate with SetupEditor and ValidationEditor because they will edit other sections in the same file.",
                expected={"docs/guide.md": ("troubleshoot", "logs")},
            ),
        ),
    ),
    "permissions_trio": CommunicationScenario(
        scenario_id="permissions_trio",
        description="Three-agent server, UI, and verification split.",
        method="independent_files",
        files={
            "server/permissions.js": """export function canViewDashboard(role) {
  return role === "admin" || role === "operator";
}
""",
            "ui/permissions_panel.js": """export function permissionRows() {
  return ["Dashboard view"];
}
""",
            "tests/permissions_notes.md": "# Permission Notes\n\nAudit export is not documented.\n",
        },
        agents=(
            AgentSpec(
                name="ServerAgent",
                lane="Add a canExportAudit(role) helper in server/permissions.js that only allows admin.",
                expected={"server/permissions.js": ("canExportAudit", "admin")},
            ),
            AgentSpec(
                name="UiAgent",
                lane="Update ui/permissions_panel.js so permissionRows includes Audit export.",
                expected={"ui/permissions_panel.js": ("Audit export",)},
            ),
            AgentSpec(
                name="VerifierAgent",
                lane="Update tests/permissions_notes.md with a concise note that Audit export is admin-only and visible in the UI list.",
                expected={"tests/permissions_notes.md": ("Audit export", "admin-only")},
            ),
        ),
    ),
    "incident_trio": CommunicationScenario(
        scenario_id="incident_trio",
        description="Three-agent investigation with separate findings and summary files.",
        method="independent_files",
        files={
            "logs/service.log": """10:02 ok boot
10:04 warn queue depth 91
10:05 error throttle limit exceeded
""",
            "config/limits.json": """{"queueDepthLimit": 80, "retryLimit": 3}
""",
            "docs/log-findings.md": "# Log Findings\n\n",
            "docs/config-findings.md": "# Config Findings\n\n",
            "docs/incident.md": "# Incident Summary\n\nPending.\n",
        },
        agents=(
            AgentSpec(
                name="LogReader",
                lane="Inspect logs/service.log and update docs/log-findings.md with the throttle limit symptom.",
                expected={"docs/log-findings.md": ("throttle limit",)},
            ),
            AgentSpec(
                name="ConfigReader",
                lane="Inspect config/limits.json and update docs/config-findings.md with the queueDepthLimit value.",
                expected={"docs/config-findings.md": ("queueDepthLimit", "80")},
            ),
            AgentSpec(
                name="IncidentSummarizer",
                lane="Update docs/incident.md with a concise summary mentioning throttle limit and queue depth.",
                expected={"docs/incident.md": ("throttle limit", "queue depth")},
            ),
        ),
    ),
    "release_quad": CommunicationScenario(
        scenario_id="release_quad",
        description="Four-agent release checklist with independent artifacts.",
        method="independent_files",
        files={
            "package.json": """{"name": "communication-eval", "version": "0.1.0"}
""",
            "docs/runbook.md": "# Runbook\n\nPending.\n",
            "tests/smoke.md": "# Smoke Test\n\nPending.\n",
            "release/summary.md": "# Release Summary\n\nPending.\n",
            "release/risk.md": "# Risk Notes\n\nPending.\n",
        },
        agents=(
            AgentSpec(
                name="VersionAgent",
                lane="Update package.json version to 0.1.1 without changing the package name.",
                expected={"package.json": ("0.1.1",)},
            ),
            AgentSpec(
                name="RunbookAgent",
                lane="Update docs/runbook.md with a concise rollback step for release 0.1.1.",
                expected={"docs/runbook.md": ("rollback", "0.1.1")},
            ),
            AgentSpec(
                name="SmokeAgent",
                lane="Update tests/smoke.md with one smoke check for the release version.",
                expected={"tests/smoke.md": ("smoke", "version", "0.1.1")},
            ),
            AgentSpec(
                name="SummaryAgent",
                lane="Update release/summary.md and release/risk.md with concise release and risk notes for 0.1.1.",
                expected={
                    "release/summary.md": ("0.1.1",),
                    "release/risk.md": ("risk",),
                },
            ),
        ),
    ),
    "serial_handoff_trio": CommunicationScenario(
        scenario_id="serial_handoff_trio",
        description="Three-agent same-file edit with an explicit serial handoff order.",
        method="serial_same_file_handoff",
        files={
            "docs/guide.md": """# Operator Guide

## Setup

Pending.

## Validation

Pending.

## Troubleshooting

Pending.
""",
        },
        agents=(
            AgentSpec(
                name="SetupFirst",
                lane="Serial collaborative edit of docs/guide.md. You are first: update only the Setup section with one concise setup instruction mentioning dependency installation, then report the handoff to ValidationSecond in Hollywood.",
                expected={"docs/guide.md": ("dependenc", "install")},
            ),
            AgentSpec(
                name="ValidationSecond",
                lane="Serial collaborative edit of docs/guide.md. Wait for SetupFirst's handoff if needed, then update only the Validation section with one concise validation instruction mentioning tests pass, then report the handoff to TroubleshootingThird in Hollywood.",
                expected={"docs/guide.md": ("validation", "test", "pass")},
            ),
            AgentSpec(
                name="TroubleshootingThird",
                lane="Serial collaborative edit of docs/guide.md. Wait for ValidationSecond's handoff if needed, then update only the Troubleshooting section with one concise troubleshooting instruction mentioning logs, then report completion in Hollywood.",
                expected={"docs/guide.md": ("troubleshoot", "logs")},
            ),
        ),
    ),
    "append_only_trio": CommunicationScenario(
        scenario_id="append_only_trio",
        description="Three-agent append-only shared ledger with unique owned sections.",
        method="append_only_shared_ledger",
        files={
            "docs/team-ledger.md": """# Team Ledger

## SetupEditor

Pending.

## ValidationEditor

Pending.

## TroubleshootingEditor

Pending.
""",
        },
        agents=(
            AgentSpec(
                name="SetupEditor",
                lane="Append-only collaborative ledger edit. In docs/team-ledger.md, replace only the Pending line under ## SetupEditor with one concise setup note mentioning dependency installation. Treat your section as conflict-free and report when done.",
                expected={"docs/team-ledger.md": ("dependenc", "install")},
            ),
            AgentSpec(
                name="ValidationEditor",
                lane="Append-only collaborative ledger edit. In docs/team-ledger.md, replace only the Pending line under ## ValidationEditor with one concise validation note mentioning tests pass. Treat your section as conflict-free and report when done.",
                expected={"docs/team-ledger.md": ("validation", "test", "pass")},
            ),
            AgentSpec(
                name="TroubleshootingEditor",
                lane="Append-only collaborative ledger edit. In docs/team-ledger.md, replace only the Pending line under ## TroubleshootingEditor with one concise troubleshooting note mentioning logs. Treat your section as conflict-free and report when done.",
                expected={"docs/team-ledger.md": ("troubleshoot", "logs")},
            ),
        ),
    ),
    "conflict_free_quad": CommunicationScenario(
        scenario_id="conflict_free_quad",
        description="Four-agent conflict-free sidecar write pattern with an integrator merge.",
        method="conflict_free_sidecars",
        files={
            "docs/guide.md": """# Operator Guide

## Setup

Pending.

## Validation

Pending.

## Troubleshooting

Pending.
""",
            "work/setup.md": "# Setup Sidecar\n\nPending.\n",
            "work/validation.md": "# Validation Sidecar\n\nPending.\n",
            "work/troubleshooting.md": "# Troubleshooting Sidecar\n\nPending.\n",
        },
        agents=(
            AgentSpec(
                name="SetupSidecar",
                lane="Conflict-free sidecar method. Edit only work/setup.md with one concise setup instruction mentioning dependency installation, then report that sidecar to GuideIntegrator in Hollywood. Do not edit docs/guide.md.",
                expected={"work/setup.md": ("dependenc", "install")},
            ),
            AgentSpec(
                name="ValidationSidecar",
                lane="Conflict-free sidecar method. Edit only work/validation.md with one concise validation instruction mentioning tests pass, then report that sidecar to GuideIntegrator in Hollywood. Do not edit docs/guide.md.",
                expected={"work/validation.md": ("validation", "test", "pass")},
            ),
            AgentSpec(
                name="TroubleshootingSidecar",
                lane="Conflict-free sidecar method. Edit only work/troubleshooting.md with one concise troubleshooting instruction mentioning logs, then report that sidecar to GuideIntegrator in Hollywood. Do not edit docs/guide.md.",
                expected={"work/troubleshooting.md": ("troubleshoot", "logs")},
            ),
            AgentSpec(
                name="GuideIntegrator",
                lane="Conflict-free sidecar method. Integrate docs/guide.md only after reading the sidecar files and/or Hollywood reports from SetupSidecar, ValidationSidecar, and TroubleshootingSidecar. Replace the three Pending placeholders in docs/guide.md with the sidecar instructions, then report what was integrated.",
                expected={
                    "docs/guide.md": (
                        "dependenc",
                        "install",
                        "validation",
                        "test",
                        "pass",
                        "troubleshoot",
                        "logs",
                    )
                },
            ),
        ),
    ),
}


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
        ["git", "commit", "-q", "-m", "initial fixture"],
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


def dependency_names(
    scenario: CommunicationScenario, agent: AgentSpec
) -> tuple[str, ...]:
    dependencies = {
        "docs_pair": {
            "ReviewWriter": ("StatusWriter",),
        },
        "retry_pair": {
            "RetryVerifier": ("RetryImplementer",),
        },
        "shared_file_pair": {
            "SetupEditor": ("ValidationEditor",),
            "ValidationEditor": ("SetupEditor",),
        },
        "shared_file_trio": {
            "SetupEditor": ("ValidationEditor", "TroubleshootingEditor"),
            "ValidationEditor": ("SetupEditor", "TroubleshootingEditor"),
            "TroubleshootingEditor": ("SetupEditor", "ValidationEditor"),
        },
        "permissions_trio": {
            "VerifierAgent": ("ServerAgent", "UiAgent"),
        },
        "incident_trio": {
            "IncidentSummarizer": ("LogReader", "ConfigReader"),
        },
        "release_quad": {
            "SmokeAgent": ("VersionAgent",),
            "SummaryAgent": ("VersionAgent",),
        },
        "serial_handoff_trio": {
            "ValidationSecond": ("SetupFirst",),
            "TroubleshootingThird": ("ValidationSecond",),
        },
        "append_only_trio": {
            "SetupEditor": ("ValidationEditor", "TroubleshootingEditor"),
            "ValidationEditor": ("SetupEditor", "TroubleshootingEditor"),
            "TroubleshootingEditor": ("SetupEditor", "ValidationEditor"),
        },
        "conflict_free_quad": {
            "GuideIntegrator": (
                "SetupSidecar",
                "ValidationSidecar",
                "TroubleshootingSidecar",
            ),
        },
    }
    return dependencies.get(scenario.scenario_id, {}).get(agent.name, ())


def profile_guidance(profile: str) -> str:
    parts = []
    if profile in {"communication", "dependency_prompt", "dependency_structured"}:
        parts.append(COMMUNICATION_GUIDANCE)
    if profile in {"dependency_prompt", "dependency_structured"}:
        parts.append(DEPENDENCY_GUIDANCE)
    return "\n".join(parts)


def structured_brief(scenario: CommunicationScenario, agent: AgentSpec) -> str:
    dependencies = dependency_names(scenario, agent)
    dependency_lines = []
    for dependency_name in dependencies:
        dependency_agent = next(
            peer for peer in scenario.agents if peer.name == dependency_name
        )
        dependency_lines.append(f"- {dependency_agent.name}: {dependency_agent.lane}")
    if not dependency_lines:
        dependency_lines.append("- none explicit")

    other_lanes = [
        f"- {peer.name}: {peer.lane}"
        for peer in scenario.agents
        if peer.name != agent.name
    ]
    return "\n".join(
        [
            "Team lane structure:",
            f"- Your lane owner name: {agent.name}",
            f"- Your lane: {agent.lane}",
            "- Other active lanes:",
            *other_lanes,
            "- Dependency-sensitive lanes for your work:",
            *dependency_lines,
            "Use this structure to decide which Hollywood updates and files matter before finalizing.",
        ]
    )


def agent_prompt(
    scenario: CommunicationScenario,
    agent: AgentSpec,
    *,
    profile: str,
) -> str:
    teammates = ", ".join(
        peer.name for peer in scenario.agents if peer.name != agent.name
    )
    guidance = profile_guidance(profile)
    if guidance:
        guidance += "\n"
    lane_text = (
        structured_brief(scenario, agent)
        if profile in {"structured_brief", "dependency_structured"}
        else f"Your lane:\n{agent.lane}"
    )
    return f"""{guidance}You are one member of a Losangelex team attached to the same Hollywood room.

Scenario: {scenario.description}
Your agent name: {agent.name}
Other team members: {teammates}

{lane_text}

Work only inside this scratch workspace. Keep the change minimal. Avoid blind
clobbering: when lanes touch the same file, use Hollywood to agree on slices,
handoff/integrator expectations, and report-back points, and reread the current
file or diff before patching. Use normal Losangelex/Hollywood team behavior.
"""


def expected_matches(workspace: Path, scenario: CommunicationScenario) -> bool:
    expected: dict[str, list[str]] = {}
    for agent in scenario.agents:
        for relative, substrings in agent.expected.items():
            expected.setdefault(relative, []).extend(substrings)
    for relative, substrings in expected.items():
        path = workspace / relative
        if not path.exists():
            return False
        folded = path.read_text(encoding="utf-8").casefold()
        if any(substring.casefold() not in folded for substring in substrings):
            return False
    return True


def expects_collaborative_editing(scenario: CommunicationScenario) -> bool:
    per_file_agent_count: Counter[str] = Counter()
    for agent in scenario.agents:
        for relative in agent.expected:
            per_file_agent_count[relative] += 1
    return any(count > 1 for count in per_file_agent_count.values())


def message_body(message: dict[str, Any]) -> str:
    return str(message.get("body") or "")


def message_sender(message: dict[str, Any]) -> str:
    return str(message.get("sender_id") or message.get("senderId") or "")


def message_kind(message: dict[str, Any]) -> str:
    return str(message.get("message_kind") or message.get("messageKind") or "").lower()


def summarize_turn_timing(
    notifications: list[dict[str, Any]], tracked_threads: set[str]
) -> dict[str, Any]:
    by_thread: dict[str, dict[str, int]] = {}
    durations: list[int] = []
    first_started_at: int | None = None
    last_completed_at: int | None = None
    for message in notifications:
        if message.get("method") != "turn/completed":
            continue
        params = message.get("params", {})
        thread_id = params.get("threadId")
        if thread_id not in tracked_threads:
            continue
        turn = params.get("turn")
        if not isinstance(turn, dict):
            continue
        duration_ms = _int_value(turn.get("durationMs"))
        if duration_ms is None:
            continue
        started_at = _int_value(turn.get("startedAt"))
        completed_at = _int_value(turn.get("completedAt"))
        if started_at is not None:
            first_started_at = (
                started_at
                if first_started_at is None
                else min(first_started_at, started_at)
            )
        if completed_at is not None:
            last_completed_at = (
                completed_at
                if last_completed_at is None
                else max(last_completed_at, completed_at)
            )
        durations.append(duration_ms)
        thread_summary = by_thread.setdefault(
            str(thread_id),
            {
                "turns": 0,
                "totalDurationMs": 0,
                "maxDurationMs": 0,
            },
        )
        thread_summary["turns"] += 1
        thread_summary["totalDurationMs"] += duration_ms
        thread_summary["maxDurationMs"] = max(
            thread_summary["maxDurationMs"], duration_ms
        )

    total_duration_ms = sum(durations)
    return {
        "turnCount": len(durations),
        "totalTurnDurationMs": total_duration_ms,
        "avgTurnDurationMs": round(total_duration_ms / len(durations), 1)
        if durations
        else 0,
        "maxTurnDurationMs": max(durations) if durations else 0,
        "observedSpanSeconds": (
            last_completed_at - first_started_at
            if first_started_at is not None and last_completed_at is not None
            else None
        ),
        "byThread": by_thread,
    }


def _int_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def performance_summary(
    *,
    wall_seconds: float,
    notification_summary: dict[str, Any],
    turn_timing: dict[str, Any],
    team_size: int,
) -> dict[str, Any]:
    token_usage = normalize_token_usage(notification_summary.get("tokenUsage"))
    wall_seconds = round(wall_seconds, 1)
    return {
        "wallSeconds": wall_seconds,
        "turnTiming": turn_timing,
        "tokenUsage": token_usage,
        "totalTokensPerWallSecond": _rate(token_usage["totalTokens"], wall_seconds),
        "uncachedPlusOutputTokensPerWallSecond": _rate(
            token_usage["uncachedPlusOutputTokens"], wall_seconds
        ),
        "totalTokensPerAgent": round(token_usage["totalTokens"] / team_size, 1)
        if team_size
        else 0,
        "uncachedPlusOutputTokensPerAgent": round(
            token_usage["uncachedPlusOutputTokens"] / team_size,
            1,
        )
        if team_size
        else 0,
    }


def _rate(value: int, seconds: float) -> float:
    if seconds <= 0:
        return 0
    return round(value / seconds, 1)


def read_collaborative_edit_plans(codex_home: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for db_path in sorted(codex_home.glob("state_*.sqlite")):
        try:
            with sqlite3.connect(db_path) as db:
                db.row_factory = sqlite3.Row
                query_rows = db.execute(
                    """
                    SELECT actor_thread_id, room, file_path, edit_slice, intent,
                           peers_json, handoff, integrator, report_back,
                           created_at, lease_expires_at
                    FROM collaborative_edit_plans
                    ORDER BY created_at
                    """
                ).fetchall()
        except sqlite3.Error:
            continue
        for row in query_rows:
            item = dict(row)
            item["dbPath"] = str(db_path)
            rows.append(item)
    return rows


def count_rollout_function_calls(codex_home: Path, tool_name: str) -> int:
    sessions_dir = codex_home / "sessions"
    if not sessions_dir.exists():
        return 0
    count = 0
    for path in sessions_dir.rglob("*.jsonl"):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "response_item":
                continue
            payload = event.get("payload")
            if not isinstance(payload, dict):
                continue
            if (
                payload.get("type") == "function_call"
                and payload.get("name") == tool_name
            ):
                count += 1
    return count


def classify_messages(
    *,
    agents: list[dict[str, str]],
    room_messages: list[dict[str, Any]],
    notification_summary: dict[str, Any],
    collaborative_edit_plans: list[dict[str, Any]],
    collaborative_edit_plan_calls: int,
    workspace: Path,
    scenario: CommunicationScenario,
    diff: str,
) -> dict[str, Any]:
    thread_to_name = {agent["threadId"]: agent["name"] for agent in agents}
    messages_by_agent: dict[str, list[str]] = {agent["name"]: [] for agent in agents}
    message_kinds: Counter[str] = Counter()
    unknown_sender_count = 0

    for message in room_messages:
        sender = message_sender(message)
        name = thread_to_name.get(sender)
        message_kinds[message_kind(message)] += 1
        if name is None:
            unknown_sender_count += 1
            continue
        messages_by_agent[name].append(message_body(message))

    start_like: dict[str, bool] = {}
    finish_like: dict[str, bool] = {}
    collaborative_edit_like: dict[str, bool] = {}
    for agent in agents:
        name = agent["name"]
        bodies = "\n".join(messages_by_agent[name]).casefold()
        start_like[name] = any(term in bodies for term in START_TERMS)
        finish_like[name] = any(term in bodies for term in FINISH_TERMS)
        collaborative_edit_like[name] = any(
            term in bodies for term in COLLABORATIVE_EDIT_TERMS
        )

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
    collaborative_edit_plan_messages = sum(
        1
        for message in room_messages
        if message_body(message).startswith("Collaborative edit plan:")
    )
    agents_with_messages = sum(1 for bodies in messages_by_agent.values() if bodies)
    agents_with_start = sum(1 for value in start_like.values() if value)
    agents_with_finish = sum(1 for value in finish_like.values() if value)
    agents_with_collaborative_edit = sum(
        1 for value in collaborative_edit_like.values() if value
    )
    expected_content_matches = expected_matches(workspace, scenario)
    collaborative_edit_expected = expects_collaborative_editing(scenario)
    complete = (
        expected_content_matches
        and bool(diff.strip())
        and tool_errors == 0
        and (
            not collaborative_edit_expected
            or agents_with_collaborative_edit == len(agents)
        )
    )

    return {
        "complete": complete,
        "expectedContentMatches": expected_content_matches,
        "workspaceChanged": bool(diff.strip()),
        "roomMessageCount": len(room_messages),
        "messageKinds": dict(message_kinds),
        "unknownSenderCount": unknown_sender_count,
        "agentsWithMessages": agents_with_messages,
        "agentsWithStartLikeMessage": agents_with_start,
        "agentsWithFinishLikeMessage": agents_with_finish,
        "agentsWithCollaborativeEditLikeMessage": agents_with_collaborative_edit,
        "allAgentsMessaged": agents_with_messages == len(agents),
        "allAgentsStartLike": agents_with_start == len(agents),
        "allAgentsFinishLike": agents_with_finish == len(agents),
        "allAgentsCollaborativeEditLike": agents_with_collaborative_edit == len(agents),
        "messagesByAgent": messages_by_agent,
        "startLikeByAgent": start_like,
        "finishLikeByAgent": finish_like,
        "collaborativeEditLikeByAgent": collaborative_edit_like,
        "hollywoodSendCalls": int(tool_calls.get("hollywood_send", 0)),
        "collaborativeEditPlanCalls": collaborative_edit_plan_calls,
        "collaborativeEditPlanRows": len(collaborative_edit_plans),
        "collaborativeEditPlanMessages": collaborative_edit_plan_messages,
        "coordinationToolErrors": tool_errors,
    }


def run_single(
    *,
    scenario: CommunicationScenario,
    profile: str,
    codex: Path,
    model: str,
    output_dir: Path,
    codex_home_source: Path,
    startup_timeout_seconds: int,
    turn_timeout_seconds: int,
) -> dict[str, Any]:
    started = time.time()
    run_id = uuid.uuid4().hex[:8]
    run_dir = output_dir / profile / scenario.scenario_id / run_id
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
        room = f"repo/comm-{scenario.scenario_id}-{run_id}"
        conn = JsonRpcWs(app_server.url, request_timeout=turn_timeout_seconds + 30)
        agents: list[dict[str, str]] = []
        try:
            initialize(conn)
            for agent in scenario.agents:
                thread_id = start_agent(
                    conn,
                    workspace=str(workspace),
                    hollywood_url=str(hollywood["url"]),
                    room=room,
                    observed_rooms=[room],
                    wake_rooms=[room],
                    name=f"{agent.name}-{run_id}",
                    model=model,
                    model_provider=DEFAULT_EVAL_MODEL_PROVIDER,
                )
                agents.append({"name": agent.name, "threadId": thread_id})

            conn.drain(3)
            for agent in scenario.agents:
                prompt = agent_prompt(scenario, agent, profile=profile)
                (run_dir / f"prompt-{agent.name}.txt").write_text(
                    prompt,
                    encoding="utf-8",
                )
                thread_id = next(
                    item["threadId"] for item in agents if item["name"] == agent.name
                )
                send_turn(conn, thread_id, prompt)

            tracked_threads = {agent["threadId"] for agent in agents}
            wait_for_tracked_turns(
                conn,
                tracked_threads,
                timeout_seconds=turn_timeout_seconds,
            )
            conn.drain(8)
            thread_states = {
                agent["threadId"]: read_thread_state(conn, agent["threadId"])
                for agent in agents
            }
            notification_summary = summarize_notifications(
                conn.notifications,
                tracked_threads,
            )
            turn_timing = summarize_turn_timing(conn.notifications, tracked_threads)
            notifications = list(conn.notifications)
        finally:
            conn.close()

        room_messages = fetch_room_messages(str(hollywood["url"]), room)

    collaborative_edit_plans = read_collaborative_edit_plans(app_server.codex_home)
    collaborative_edit_plan_calls = count_rollout_function_calls(
        app_server.codex_home,
        "collaborative_edit_plan",
    )
    diff = workspace_diff(workspace)
    score = classify_messages(
        agents=agents,
        room_messages=room_messages,
        notification_summary=notification_summary,
        collaborative_edit_plans=collaborative_edit_plans,
        collaborative_edit_plan_calls=collaborative_edit_plan_calls,
        workspace=workspace,
        scenario=scenario,
        diff=diff,
    )
    wall_seconds = round(time.time() - started, 1)
    performance = performance_summary(
        wall_seconds=wall_seconds,
        notification_summary=notification_summary,
        turn_timing=turn_timing,
        team_size=len(scenario.agents),
    )
    result = {
        "profile": profile,
        "scenarioId": scenario.scenario_id,
        "description": scenario.description,
        "method": scenario.method,
        "teamSize": len(scenario.agents),
        "model": model,
        "runId": run_id,
        "seconds": wall_seconds,
        "performance": performance,
        "tokenUsage": performance["tokenUsage"],
        "workspace": str(workspace),
        "room": room,
        "appServer": app_server.metadata(),
        "hollywood": hollywood,
        "agents": agents,
        "threadStates": thread_states,
        "notificationSummary": notification_summary,
        "turnTiming": turn_timing,
        "collaborativeEditPlans": collaborative_edit_plans,
        "collaborativeEditPlanCalls": collaborative_edit_plan_calls,
        "roomMessages": room_messages,
        "workspaceDiff": diff,
        "score": score,
    }
    (run_dir / "result.json").write_text(
        json.dumps(result, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_dir / "room-messages.json").write_text(
        json.dumps(room_messages, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_dir / "notifications.json").write_text(
        json.dumps(notifications, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_dir / "notification-summary.json").write_text(
        json.dumps(notification_summary, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_dir / "workspace.diff").write_text(diff, encoding="utf-8")
    return result


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_profile: dict[str, list[dict[str, Any]]] = {}
    by_method: dict[str, list[dict[str, Any]]] = {}
    by_scenario: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        by_profile.setdefault(result["profile"], []).append(result)
        by_method.setdefault(result["method"], []).append(result)
        by_scenario.setdefault(result["scenarioId"], []).append(result)
    return {
        "overall": summarize_records(results),
        "byProfile": {
            key: summarize_records(records)
            for key, records in sorted(by_profile.items())
        },
        "byMethod": {
            key: summarize_records(records)
            for key, records in sorted(by_method.items())
        },
        "byScenario": {
            key: summarize_records(records)
            for key, records in sorted(by_scenario.items())
        },
    }


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(records)
    token_usage = sum_token_usage([record.get("tokenUsage") for record in records])
    wall_seconds = [float(record.get("seconds") or 0) for record in records]
    turn_seconds = [
        float(record.get("turnTiming", {}).get("totalTurnDurationMs", 0)) / 1000
        for record in records
    ]
    return {
        "runs": count,
        "complete": sum(1 for record in records if record["score"]["complete"]),
        "allAgentsMessaged": sum(
            1 for record in records if record["score"]["allAgentsMessaged"]
        ),
        "allAgentsStartLike": sum(
            1 for record in records if record["score"]["allAgentsStartLike"]
        ),
        "allAgentsFinishLike": sum(
            1 for record in records if record["score"]["allAgentsFinishLike"]
        ),
        "allAgentsCollaborativeEditLike": sum(
            1 for record in records if record["score"]["allAgentsCollaborativeEditLike"]
        ),
        "avgWallSeconds": average(wall_seconds),
        "maxWallSeconds": max(wall_seconds) if wall_seconds else 0,
        "avgTotalTurnSeconds": average(turn_seconds),
        "avgRoomMessages": average(
            [record["score"]["roomMessageCount"] for record in records]
        ),
        "avgHollywoodSendCalls": average(
            [record["score"]["hollywoodSendCalls"] for record in records]
        ),
        "avgCollaborativeEditPlanCalls": average(
            [record["score"]["collaborativeEditPlanCalls"] for record in records]
        ),
        "avgCollaborativeEditPlanRows": average(
            [record["score"]["collaborativeEditPlanRows"] for record in records]
        ),
        "toolErrors": sum(
            record["score"]["coordinationToolErrors"] for record in records
        ),
        "tokenUsage": token_usage,
        "avgTotalTokens": round(token_usage["totalTokens"] / count, 1) if count else 0,
        "avgUncachedPlusOutputTokens": round(
            token_usage["uncachedPlusOutputTokens"] / count,
            1,
        )
        if count
        else 0,
    }


def average(values: list[int | float]) -> float:
    return round(sum(values) / len(values), 1) if values else 0


def write_report(output_dir: Path, results: list[dict[str, Any]]) -> None:
    summary = aggregate(results)
    lines = [
        "# Hollywood Communication Tendency Evaluation",
        "",
        f"Generated: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        "",
        "This live model-in-the-loop evaluation starts isolated Hollywood and app-server processes, assigns scratch tasks across team sizes 2, 3, and 4, and scores whether agents coordinate through Hollywood while completing the workspace task.",
        "",
        "Time is reported two ways: wall seconds measures elapsed run time, while total turn seconds sums completed agent turn durations and therefore captures aggregate model work even when agents run concurrently.",
        "",
        "Token usage comes from app-server `thread/tokenUsage/updated` notifications. `uncachedPlusOutputTokens` is the main cost-pressure proxy because it removes cached input tokens but includes generated output.",
        "",
        "## Method Catalog",
        "",
        "| Method | Description |",
        "| --- | --- |",
    ]
    for method, description in sorted(METHOD_DESCRIPTIONS.items()):
        lines.append(f"| {method} | {description} |")

    lines.extend(["", "## Overall Summary", ""])
    lines.extend(summary_table({"overall": summary["overall"]}, group_label="Group"))

    lines.extend(["", "## By Method", ""])
    lines.extend(summary_table(summary["byMethod"], group_label="Method"))

    lines.extend(["", "## By Profile", ""])
    lines.extend(summary_table(summary["byProfile"], group_label="Profile"))

    lines.extend(["", "## By Scenario", ""])
    lines.extend(summary_table(summary["byScenario"], group_label="Scenario"))

    lines.extend(["", "## Runs", ""])
    for result in results:
        score = result["score"]
        performance = result["performance"]
        usage = performance["tokenUsage"]
        turn_timing = performance["turnTiming"]
        lines.extend(
            [
                f"### {result['profile']} / {result['scenarioId']} / {result['runId']}",
                "",
                f"- Method: `{result['method']}`",
                f"- Team size: `{result['teamSize']}`",
                f"- Complete: `{score['complete']}`",
                f"- Wall seconds: `{performance['wallSeconds']}`",
                f"- Total turn seconds: `{round(turn_timing['totalTurnDurationMs'] / 1000, 1)}`",
                f"- Max turn seconds: `{round(turn_timing['maxTurnDurationMs'] / 1000, 1)}`",
                f"- Total tokens: `{usage['totalTokens']}`",
                f"- Cached input tokens: `{usage['cachedInputTokens']}`",
                f"- Uncached + output tokens: `{usage['uncachedPlusOutputTokens']}`",
                f"- Output tokens: `{usage['outputTokens']}`",
                f"- Room messages: `{score['roomMessageCount']}`",
                f"- Hollywood send calls: `{score['hollywoodSendCalls']}`",
                f"- Collaborative edit plan calls: `{score['collaborativeEditPlanCalls']}`",
                f"- Collaborative edit plan rows: `{score['collaborativeEditPlanRows']}`",
                f"- Agents with messages: `{score['agentsWithMessages']}/{result['teamSize']}`",
                f"- Agents with start-like messages: `{score['agentsWithStartLikeMessage']}/{result['teamSize']}`",
                f"- Agents with finish-like messages: `{score['agentsWithFinishLikeMessage']}/{result['teamSize']}`",
                f"- Tool errors: `{score['coordinationToolErrors']}`",
                f"- Result: `{result['profile']}/{result['scenarioId']}/{result['runId']}/result.json`",
                "",
            ]
        )
        for agent in result["agents"]:
            name = agent["name"]
            bodies = score["messagesByAgent"].get(name, [])
            preview = " | ".join(body.replace("\n", " ")[:160] for body in bodies)
            lines.append(f"  - `{name}` messages: {preview or '`none`'}")
        lines.append("")

    lines.extend(
        [
            "## Limitations",
            "",
            "- These are live model-in-the-loop runs, so conclusions are rate-based rather than deterministic proof.",
            "- A single campaign measures this machine, model, and account state at the run time; repeat campaigns are needed for confidence intervals.",
            "- The conflict-free sidecar method intentionally adds an integrator lane, so lower conflict risk may cost extra wall time or tokens.",
            "- `collaborative_edit_plan` calls are counted from app-server notifications and durable state rows; older artifacts created before this script change may undercount tool calls in their coordination summary.",
            "",
        ]
    )

    (output_dir / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "runs.json").write_text(
        json.dumps(run_index(results), indent=2) + "\n",
        encoding="utf-8",
    )


def summary_table(grouped: dict[str, dict[str, Any]], *, group_label: str) -> list[str]:
    lines = [
        f"| {group_label} | Runs | Complete | All msg | All start | All finish | Avg wall s | Avg turn s | Avg room msg | Avg plan rows | Avg total tokens | Avg uncached+out | Tool errors |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for group, stats in sorted(grouped.items()):
        lines.append(
            f"| {group} | {stats['runs']} | {stats['complete']} | "
            f"{stats['allAgentsMessaged']} | {stats['allAgentsStartLike']} | "
            f"{stats['allAgentsFinishLike']} | {stats['avgWallSeconds']:.1f} | "
            f"{stats['avgTotalTurnSeconds']:.1f} | {stats['avgRoomMessages']:.1f} | "
            f"{stats['avgCollaborativeEditPlanRows']:.1f} | "
            f"{stats['avgTotalTokens']:.1f} | "
            f"{stats['avgUncachedPlusOutputTokens']:.1f} | {stats['toolErrors']} |"
        )
    return lines


def run_index(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for result in results:
        usage = result["tokenUsage"]
        turn_timing = result["turnTiming"]
        score = result["score"]
        records.append(
            {
                "profile": result["profile"],
                "scenarioId": result["scenarioId"],
                "method": result["method"],
                "teamSize": result["teamSize"],
                "repeatIndex": result.get("repeatIndex"),
                "runId": result["runId"],
                "complete": score["complete"],
                "wallSeconds": result["seconds"],
                "totalTurnSeconds": round(
                    turn_timing["totalTurnDurationMs"] / 1000,
                    1,
                ),
                "totalTokens": usage["totalTokens"],
                "uncachedPlusOutputTokens": usage["uncachedPlusOutputTokens"],
                "roomMessageCount": score["roomMessageCount"],
                "collaborativeEditPlanRows": score["collaborativeEditPlanRows"],
                "toolErrors": score["coordinationToolErrors"],
                "result": f"{result['profile']}/{result['scenarioId']}/{result['runId']}/result.json",
            }
        )
    return records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex", type=Path, default=DEFAULT_CODEX)
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument(
        "--campaign-name",
        default=f"communication-tendency-{time.strftime('%Y-%m-%d-%H%M%S')}",
    )
    parser.add_argument(
        "--profile",
        action="append",
        choices=PROFILE_CHOICES,
        help="Prompt profile(s) to run. Defaults to current and communication.",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        choices=sorted(SCENARIOS),
        help="Scenario(s) to run. Defaults to all scenarios.",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Number of times to run each profile/scenario pair.",
    )
    parser.add_argument(
        "--codex-home-source", type=Path, default=Path.home() / ".codex"
    )
    parser.add_argument("--startup-timeout-seconds", type=int, default=45)
    parser.add_argument("--turn-timeout-seconds", type=int, default=240)
    args = parser.parse_args()

    ensure_default_codex(args.codex)
    profiles = args.profile or ["current", "communication"]
    scenarios = [SCENARIOS[name] for name in (args.scenario or sorted(SCENARIOS))]
    output_dir = args.out_root / args.campaign_name
    output_dir.mkdir(parents=True, exist_ok=True)

    prepare_minimal_codex_home(
        codex_home=output_dir / "codex-home-check",
        source_home=args.codex_home_source,
        output_dir=output_dir,
    )

    results = []
    for repeat_index in range(args.repeat):
        for scenario in scenarios:
            for profile in profiles:
                result = run_single(
                    scenario=scenario,
                    profile=profile,
                    codex=args.codex,
                    model=args.model,
                    output_dir=output_dir,
                    codex_home_source=args.codex_home_source,
                    startup_timeout_seconds=args.startup_timeout_seconds,
                    turn_timeout_seconds=args.turn_timeout_seconds,
                )
                result["repeatIndex"] = repeat_index
                result_path = (
                    output_dir
                    / result["profile"]
                    / result["scenarioId"]
                    / result["runId"]
                    / "result.json"
                )
                result_path.write_text(
                    json.dumps(result, indent=2) + "\n",
                    encoding="utf-8",
                )
                results.append(result)
                print(
                    json.dumps(
                        {
                            "profile": result["profile"],
                            "scenarioId": result["scenarioId"],
                            "method": result["method"],
                            "teamSize": result["teamSize"],
                            "repeatIndex": repeat_index,
                            "runId": result["runId"],
                            "seconds": result["seconds"],
                            "tokenUsage": result["tokenUsage"],
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
