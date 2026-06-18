#!/usr/bin/env python3
"""Evaluate Hollywood context efficiency and task-room decision quality.

This is a narrow model-in-the-loop smoke evaluation for the Hollywood context
surface. It compares the legacy JSON-style Hollywood context against the compact
typed-envelope/task-room context introduced in Losangelex.
"""

import argparse
import json
import math
import subprocess
import sys
import tempfile
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchmark_token_usage import parse_codex_exec_jsonl_token_usage


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_ROOT = REPO_ROOT / "evals/research/2026-06-18-hollywood-context-efficiency"

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "stay_silent",
                "work_solo",
                "hollywood_send",
                "hollywood_team_up",
                "losangelex_team_launch",
                "claim_scope",
            ],
        },
        "speak": {"type": "boolean"},
        "initiate_collaboration": {"type": "boolean"},
        "room": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["action", "speak", "initiate_collaboration", "room", "reason"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Brief:
    wake_reason: str | None
    semantic_kind: str | None
    coordination_policy: str | None
    coordination_phase: str | None
    coordination_role: str | None
    coordination_epoch: int | None
    summary: str | None
    facts: tuple[str, ...]
    suggested_actions: tuple[str, ...]
    stay_silent_if_no_actionable_delta: bool


@dataclass(frozen=True)
class Message:
    message_id: int
    room: str
    sender_id: str
    body: str
    mentions: tuple[str, ...]
    attention: str | None
    message_kind: str | None
    obligation: str | None
    synthetic_brief: Brief | None
    requires_response: bool


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    prompt: str
    message: Message | None
    expected_action: str
    expected_speak: bool
    expected_collaboration: bool
    expected_task_room: bool


def brief_to_json(brief: Brief) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if brief.wake_reason is not None:
        payload["wake_reason"] = brief.wake_reason
    if brief.semantic_kind is not None:
        payload["semantic_kind"] = brief.semantic_kind
    if brief.coordination_policy is not None:
        payload["coordination_policy"] = brief.coordination_policy
    if brief.coordination_phase is not None:
        payload["coordination_phase"] = brief.coordination_phase
    if brief.coordination_role is not None:
        payload["coordination_role"] = brief.coordination_role
    if brief.coordination_epoch is not None:
        payload["coordination_epoch"] = brief.coordination_epoch
    if brief.summary is not None:
        payload["summary"] = brief.summary
    if brief.facts:
        payload["facts"] = list(brief.facts)
    if brief.suggested_actions:
        payload["suggested_actions"] = list(brief.suggested_actions)
    payload["stay_silent_if_no_actionable_delta"] = (
        brief.stay_silent_if_no_actionable_delta
    )
    return payload


def legacy_message_fragment(message: Message) -> str:
    payload: dict[str, Any] = {
        "message_id": message.message_id,
        "room": message.room,
        "sender_id": message.sender_id,
        "mentions": list(message.mentions),
        "body": message.body,
        "synthetic_brief": (
            brief_to_json(message.synthetic_brief)
            if message.synthetic_brief is not None
            else None
        ),
    }
    return (
        "<hollywood_message>\n"
        + json.dumps(payload, separators=(",", ":"))
        + "\n</hollywood_message>"
    )


def truncate_words(value: str, limit: int) -> str:
    words = value.split()
    if len(words) <= limit:
        return value
    head = max(limit - 4, 1)
    return " ".join(words[:head] + ["[...]", f"{len(words) - head}", "more"])


def candidate_message_type(message: Message) -> str:
    if message.obligation == "obligation":
        return "HOLLYWOOD_OBLIGATION"
    if message.obligation == "attention":
        return "HOLLYWOOD_ATTENTION"
    return "HOLLYWOOD_MESSAGE"


def candidate_message_fragment(message: Message) -> str:
    lines = [
        "<hollywood_message>",
        f"Message Type: {candidate_message_type(message)}",
        f"Coordination path: hollywood:{message.room}#{message.message_id}",
        f"Room: {message.room}",
        f"Message id: {message.message_id}",
        f"Sender: {message.sender_id}",
    ]
    if message.message_kind:
        lines.append(f"Kind: {message.message_kind}")
    if message.attention:
        lines.append(f"Attention: {message.attention}")
    lines.append(f"Response required: {'yes' if message.requires_response else 'no'}")
    if message.mentions:
        lines.append(f"Mentions: {', '.join(message.mentions)}")

    brief = message.synthetic_brief
    if brief is not None:
        optional_fields = (
            ("Wake reason", brief.wake_reason),
            ("Semantic kind", brief.semantic_kind),
            ("Coordination policy", brief.coordination_policy),
            ("Coordination phase", brief.coordination_phase),
            ("Coordination role", brief.coordination_role),
        )
        for label, value in optional_fields:
            if value:
                lines.append(f"{label}: {value}")
        if brief.coordination_epoch is not None:
            lines.append(f"Coordination epoch: {brief.coordination_epoch}")
        if brief.stay_silent_if_no_actionable_delta:
            lines.append("Stay silent if no actionable delta: yes")
        if brief.summary and brief.summary.strip() != message.body.strip():
            lines.append("Summary:")
            lines.append(truncate_words(brief.summary.strip(), 120))
        if brief.facts:
            lines.append("Facts:")
            for fact in brief.facts[:4]:
                lines.append(f"- {truncate_words(fact.strip(), 40)}")
            if len(brief.facts) > 4:
                lines.append(f"- ...{len(brief.facts) - 4} more")
        if brief.suggested_actions:
            lines.append("Suggested actions:")
            for action in brief.suggested_actions[:4]:
                lines.append(f"- {truncate_words(action.strip(), 40)}")
            if len(brief.suggested_actions) > 4:
                lines.append(f"- ...{len(brief.suggested_actions) - 4} more")

    lines.extend(["Payload:", truncate_words(message.body.strip(), 350)])
    lines.append("</hollywood_message>")
    return "\n".join(lines)


def legacy_environment_context() -> str:
    return textwrap.dedent(
        """
        Hollywood is attached to room `repo/losangelex`.

        Available coordination tools:
        - hollywood_read: read recent room messages.
        - hollywood_send: send a message. Optional room override defaults to the current attached Hollywood room.
        - hollywood_team_up: create a structured Hollywood team with a leader, purpose, and invited member sessions.
        - losangelex_team_launch: start attached Losangelex peer sessions in the configured room.
        """
    ).strip()


def candidate_environment_context() -> str:
    return textwrap.dedent(
        """
        <environment_context>
          <hollywood>
            <attached>true</attached>
            <url>http://127.0.0.1:8765</url>
            <room>repo/losangelex</room>
            <observed_rooms>
              <room>repo/losangelex</room>
            </observed_rooms>
            <wake_rooms>
              <room>repo/losangelex</room>
            </wake_rooms>
            <task_room_convention>task/repo-slug/task-slug</task_room_convention>
            <attention_mode>focused</attention_mode>
            <agent_name>Responder</agent_name>
            <coordination_identity>responder</coordination_identity>
            <startup_protocol>
              <step>inspect_attached_peers_with_hollywood_read_before_solo_decision</step>
              <step>check_existing_scope_claims_before_editing</step>
              <step>claim_exact_paths_or_modules_before_peer_coordinated_or_overlap_prone_editing</step>
              <step>avoid_overlapping_edits_until_resolved</step>
              <step>prefer_task_rooms_for_bounded_parallel_slices</step>
              <step>keep_repo_room_observed_for_status_handoffs_and_integration</step>
              <step>use_hollywood_first_for_peer_coordination</step>
            </startup_protocol>
            <tools>
              <tool>hollywood_read</tool>
              <tool>hollywood_send</tool>
              <tool>hollywood_team_up</tool>
              <tool>losangelex_team_launch</tool>
            </tools>
          </hollywood>
        </environment_context>

        Available coordination tools:
        - hollywood_read: read recent room messages.
        - hollywood_send: send a message. Optional room override defaults to the current attached Hollywood room. For bounded task slices, use a `task/<repo>/<task>` room instead of broad repo-room traffic.
        - hollywood_team_up: create a structured Hollywood collaboration with a purpose and invited member sessions. Roles are flexible.
        - losangelex_team_launch: start attached Losangelex peer sessions. For bounded parallel slices, prefer a `task/<repo>/<task>` room and keep the repo room observed for status and handoffs.
        - Avoid coordination churn for trivial local edits; use peers, task rooms, and durable path claims when the work is meaningfully splittable, blocked, risky, or overlap-prone.
        """
    ).strip()


def scenario_prompt(scenario: Scenario, variant: str) -> str:
    if variant == "legacy":
        context = legacy_environment_context()
        message = (
            legacy_message_fragment(scenario.message)
            if scenario.message is not None
            else ""
        )
    elif variant == "candidate":
        context = candidate_environment_context()
        message = (
            candidate_message_fragment(scenario.message)
            if scenario.message is not None
            else ""
        )
    else:
        raise ValueError(f"unknown variant: {variant}")

    return textwrap.dedent(
        f"""
        You are evaluating the next move for an attached Losangelex agent.
        This is a frozen model-in-the-loop evaluation. Do not call tools. Do not inspect files.
        Choose exactly one first move based only on the supplied context.

        Action meanings:
        - stay_silent: no message or coordination action is warranted.
        - work_solo: proceed locally without peer coordination.
        - hollywood_send: send a concrete response or claim.
        - hollywood_team_up: invite or organize existing peers for a bounded collaborative slice.
        - losangelex_team_launch: launch new attached Losangelex peers.
        - claim_scope: record a durable scope/path claim before work.

        {context}

        {message}

        Scenario:
        {scenario.prompt}

        Return JSON only.
        """
    ).strip()


def build_scenarios() -> list[Scenario]:
    no_action_message = Message(
        message_id=48,
        room="repo/losangelex",
        sender_id="ray",
        body="Ray owns the browser lane; no clean lane for Responder yet.",
        mentions=(),
        attention="broad",
        message_kind="broadcast",
        obligation="attention",
        synthetic_brief=Brief(
            wake_reason="hollywood_message",
            semantic_kind="broadcast",
            coordination_policy=None,
            coordination_phase=None,
            coordination_role=None,
            coordination_epoch=None,
            summary="Ray owns the browser lane; no clean lane for Responder yet.",
            facts=(
                "sender `ray` in room `repo/losangelex`",
                "message was an explicit broadcast",
                "this is a coordination delta; reply only if it materially changes your owned work",
            ),
            suggested_actions=(
                "check whether this changes your available lane or overlaps your owned paths",
                "stay silent if there is still no clean lane",
            ),
            stay_silent_if_no_actionable_delta=True,
        ),
        requires_response=False,
    )
    handoff_message = Message(
        message_id=77,
        room="repo/losangelex",
        sender_id="tony",
        body="@responder can you take over the browser-proof lane and own practice-surfaces.browser.test.ts?",
        mentions=("responder",),
        attention="focused",
        message_kind="direct",
        obligation="obligation",
        synthetic_brief=Brief(
            wake_reason="hollywood_message",
            semantic_kind="direct",
            coordination_policy="handoff",
            coordination_phase="execution",
            coordination_role="collaborator",
            coordination_epoch=3,
            summary="Tony proposed a handoff for browser-proof verification.",
            facts=(
                "sender `tony` in room `repo/losangelex`",
                "you were directly mentioned",
                "the sender expects an explicit response or decision",
            ),
            suggested_actions=(
                "confirm only if you are taking the handoff",
                "claim the exact replacement scope before editing",
                "use a bounded task room for the browser-proof slice if one is needed",
            ),
            stay_silent_if_no_actionable_delta=False,
        ),
        requires_response=True,
    )
    return [
        Scenario(
            scenario_id="attention_no_action",
            message=no_action_message,
            prompt=(
                "Assume you still have no clean lane and the update does not change your owned work. "
                "What is your next coordination move?"
            ),
            expected_action="stay_silent",
            expected_speak=False,
            expected_collaboration=False,
            expected_task_room=False,
        ),
        Scenario(
            scenario_id="direct_handoff_task_room",
            message=handoff_message,
            prompt=(
                "Assume you are available and willing to take the browser-proof handoff. "
                "Pick the first coordination move and, if using a room, choose the narrowest appropriate room."
            ),
            expected_action="hollywood_send",
            expected_speak=True,
            expected_collaboration=False,
            expected_task_room=False,
        ),
        Scenario(
            scenario_id="splittable_team_task_room",
            message=None,
            prompt=(
                "User directive: Fix reconnect jitter across client retry behavior, server reconnect wording, "
                "and verification notes. Two idle attached peers are available. The task is splittable into "
                "implementation and verification lanes. Pick the first coordination move."
            ),
            expected_action="hollywood_team_up",
            expected_speak=True,
            expected_collaboration=True,
            expected_task_room=True,
        ),
        Scenario(
            scenario_id="tiny_local_edit",
            message=None,
            prompt=(
                "User directive: Change one README heading in this scratch repo. No other files are involved. "
                "Pick the first coordination move."
            ),
            expected_action="work_solo",
            expected_speak=False,
            expected_collaboration=False,
            expected_task_room=False,
        ),
    ]


def approx_tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


def fragment_metrics(scenarios: list[Scenario]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scenario in scenarios:
        legacy_prompt = scenario_prompt(scenario, "legacy")
        candidate_prompt = scenario_prompt(scenario, "candidate")
        row: dict[str, Any] = {
            "scenarioId": scenario.scenario_id,
            "legacyPromptChars": len(legacy_prompt),
            "candidatePromptChars": len(candidate_prompt),
            "legacyPromptApproxTokens": approx_tokens(legacy_prompt),
            "candidatePromptApproxTokens": approx_tokens(candidate_prompt),
            "promptApproxTokenDelta": approx_tokens(candidate_prompt)
            - approx_tokens(legacy_prompt),
        }
        if scenario.message is not None:
            legacy_message = legacy_message_fragment(scenario.message)
            candidate_message = candidate_message_fragment(scenario.message)
            row.update(
                {
                    "legacyMessageChars": len(legacy_message),
                    "candidateMessageChars": len(candidate_message),
                    "legacyMessageApproxTokens": approx_tokens(legacy_message),
                    "candidateMessageApproxTokens": approx_tokens(candidate_message),
                    "messageApproxTokenDelta": approx_tokens(candidate_message)
                    - approx_tokens(legacy_message),
                }
            )
        rows.append(row)

    long_text = "coordinate this browser and server handoff carefully " * 500
    long_message = Message(
        message_id=100,
        room="repo/losangelex",
        sender_id="peer-agent",
        body=long_text,
        mentions=("responder",),
        attention="focused",
        message_kind="direct",
        obligation="obligation",
        synthetic_brief=Brief(
            wake_reason="hollywood_message",
            semantic_kind="direct",
            coordination_policy="handoff",
            coordination_phase="execution",
            coordination_role="collaborator",
            coordination_epoch=4,
            summary="distinct summary " * 500,
            facts=tuple(long_text for _ in range(8)),
            suggested_actions=tuple(long_text for _ in range(8)),
            stay_silent_if_no_actionable_delta=False,
        ),
        requires_response=True,
    )
    legacy_long = legacy_message_fragment(long_message)
    candidate_long = candidate_message_fragment(long_message)
    rows.append(
        {
            "scenarioId": "long_unbounded_message_fragment",
            "legacyMessageChars": len(legacy_long),
            "candidateMessageChars": len(candidate_long),
            "legacyMessageApproxTokens": approx_tokens(legacy_long),
            "candidateMessageApproxTokens": approx_tokens(candidate_long),
            "messageApproxTokenDelta": approx_tokens(candidate_long)
            - approx_tokens(legacy_long),
        }
    )
    return rows


def score_decision(scenario: Scenario, decision: dict[str, Any]) -> dict[str, Any]:
    action = str(decision.get("action", ""))
    room = str(decision.get("room", ""))
    action_ok = (
        action == scenario.expected_action
        or (
            scenario.scenario_id == "direct_handoff_task_room"
            and action in {"hollywood_send", "claim_scope"}
        )
        or (
            scenario.scenario_id == "splittable_team_task_room"
            and action in {"hollywood_team_up", "losangelex_team_launch"}
        )
    )
    speak_ok = bool(decision.get("speak")) == scenario.expected_speak
    collaboration_ok = (
        bool(decision.get("initiate_collaboration")) == scenario.expected_collaboration
    )
    task_room_ok = (room.startswith("task/")) if scenario.expected_task_room else True
    passed = action_ok and speak_ok and collaboration_ok and task_room_ok
    return {
        "passed": passed,
        "actionOk": action_ok,
        "speakOk": speak_ok,
        "collaborationOk": collaboration_ok,
        "taskRoomOk": task_room_ok,
    }


def run_codex_decision(
    *,
    codex: Path,
    model: str,
    effort: str,
    prompt: str,
    output_dir: Path,
    label: str,
) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as schema_file:
        json.dump(OUTPUT_SCHEMA, schema_file)
        schema_path = Path(schema_file.name)
    output_path = output_dir / f"{label}.decision.json"
    command = [
        str(codex),
        "exec",
        "--ephemeral",
        "--json",
        "--color",
        "never",
        "--skip-git-repo-check",
        "--ignore-rules",
        "--sandbox",
        "read-only",
        "-C",
        str(output_dir),
        "-m",
        model,
        "-c",
        f'model_reasoning_effort="{effort}"',
        "--output-schema",
        str(schema_path),
        "-o",
        str(output_path),
        prompt,
    ]
    started = time.time()
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    elapsed = time.time() - started
    usage = parse_codex_exec_jsonl_token_usage(result.stdout)
    record: dict[str, Any] = {
        "command": command[:],
        "returncode": result.returncode,
        "elapsedSeconds": round(elapsed, 3),
        "tokenUsage": usage,
        "stdoutPath": f"{label}.stdout.jsonl",
        "stderrPath": f"{label}.stderr.txt",
    }
    (output_dir / f"{label}.stdout.jsonl").write_text(result.stdout, encoding="utf-8")
    (output_dir / f"{label}.stderr.txt").write_text(result.stderr, encoding="utf-8")
    if result.returncode != 0:
        record["error"] = result.stderr[-2000:]
        return record
    try:
        record["decision"] = json.loads(output_path.read_text(encoding="utf-8"))
    except Exception as exc:
        record["error"] = f"failed to parse decision: {exc}"
    return record


def write_report(
    output_dir: Path,
    metrics: list[dict[str, Any]],
    runs: list[dict[str, Any]],
) -> None:
    model = runs[0]["command"][runs[0]["command"].index("-m") + 1] if runs else "-"
    effort = "-"
    if runs:
        config_value = runs[0]["command"][runs[0]["command"].index("-c") + 1]
        effort = config_value.partition("=")[2].strip('"')
    lines = [
        "# Hollywood Context Efficiency Evaluation",
        "",
        f"Generated: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        "",
        "This is a narrow smoke evaluation of the model-visible Hollywood context change. It is not a full app-server team benchmark.",
        "",
        f"Model-in-the-loop runs: `codex exec --ephemeral`, model `{model}`, reasoning effort `{effort}`, one repeat per scenario.",
        "",
        "Fragment token counts are a simple `ceil(chars / 4)` approximation. `codex exec` input token counts include the fixed Codex harness context and cache effects, so they are useful for same-run comparisons but not fragment-only accounting.",
        "",
        "## Fragment Size",
        "",
        "Rows with Hollywood messages show message-fragment size. Rows without a message show whole prompt/context size. The long row is a deterministic message-only stress fixture.",
        "",
        "| Scenario | Legacy approx tokens | Candidate approx tokens | Delta |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in metrics:
        legacy = row.get(
            "legacyMessageApproxTokens", row.get("legacyPromptApproxTokens")
        )
        candidate = row.get(
            "candidateMessageApproxTokens", row.get("candidatePromptApproxTokens")
        )
        delta = row.get("messageApproxTokenDelta", row.get("promptApproxTokenDelta"))
        lines.append(f"| {row['scenarioId']} | {legacy} | {candidate} | {delta} |")

    lines.extend(
        [
            "",
            "## Model-In-The-Loop Decisions",
            "",
            "| Scenario | Variant | Passed | Action | Speak | Collaboration | Room | Input tokens | Total tokens |",
            "| --- | --- | ---: | --- | ---: | ---: | --- | ---: | ---: |",
        ]
    )
    for run in runs:
        decision = run.get("decision") or {}
        usage = run.get("tokenUsage") or {}
        score = run.get("score") or {}
        lines.append(
            "| "
            + " | ".join(
                [
                    str(run["scenarioId"]),
                    str(run["variant"]),
                    str(score.get("passed", False)),
                    str(decision.get("action", "")),
                    str(decision.get("speak", "")),
                    str(decision.get("initiate_collaboration", "")),
                    str(decision.get("room", "")),
                    str(usage.get("inputTokens", 0)),
                    str(usage.get("totalTokens", 0)),
                ]
            )
            + " |"
        )

    (output_dir / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex", type=Path, default=Path("codex"))
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--effort", default="low")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--runs-per-scenario", type=int, default=1)
    parser.add_argument("--skip-model", action="store_true")
    args = parser.parse_args()

    output_dir = args.out_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    scenarios = build_scenarios()
    metrics = fragment_metrics(scenarios)
    runs: list[dict[str, Any]] = []

    if not args.skip_model:
        for scenario in scenarios:
            for variant in ("legacy", "candidate"):
                for repeat in range(args.runs_per_scenario):
                    label = f"{scenario.scenario_id}.{variant}.{repeat + 1}"
                    prompt = scenario_prompt(scenario, variant)
                    run = run_codex_decision(
                        codex=args.codex,
                        model=args.model,
                        effort=args.effort,
                        prompt=prompt,
                        output_dir=output_dir,
                        label=label,
                    )
                    run.update(
                        {
                            "scenarioId": scenario.scenario_id,
                            "variant": variant,
                            "repeat": repeat + 1,
                            "promptApproxTokens": approx_tokens(prompt),
                        }
                    )
                    if "decision" in run:
                        run["score"] = score_decision(scenario, run["decision"])
                    runs.append(run)
                    print(
                        json.dumps(
                            {
                                "scenarioId": run["scenarioId"],
                                "variant": run["variant"],
                                "repeat": run["repeat"],
                                "returncode": run["returncode"],
                                "score": run.get("score"),
                                "decision": run.get("decision"),
                                "tokenUsage": run.get("tokenUsage"),
                            },
                            sort_keys=True,
                        ),
                        flush=True,
                    )

    (output_dir / "fragment_metrics.json").write_text(
        json.dumps(metrics, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "model_runs.json").write_text(
        json.dumps(runs, indent=2) + "\n", encoding="utf-8"
    )
    write_report(output_dir, metrics, runs)
    print(f"wrote {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
