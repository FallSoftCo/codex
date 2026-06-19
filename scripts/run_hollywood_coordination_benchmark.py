#!/usr/bin/env python3
"""Run a live coordination benchmark across Codex and Losangelex substrates."""

import argparse
import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from benchmark_app_server import prepare_minimal_codex_home
from benchmark_token_usage import changed_rollout_files
from benchmark_token_usage import normalize_token_usage
from benchmark_token_usage import parse_codex_exec_jsonl_token_usage
from benchmark_token_usage import run_codex_exec_with_retries
from benchmark_token_usage import snapshot_rollout_files
from benchmark_token_usage import summarize_codex_exec_collab_tools
from benchmark_token_usage import summarize_rollout_token_usage
from eval_collaboration_first_debug import SCENARIOS
from eval_collaboration_first_debug import Scenario
from eval_collaboration_first_debug import expected_file_content_matches
from eval_collaboration_first_debug import fresh_workspace
from eval_collaboration_first_debug import run_single_eval
from eval_collaboration_first_debug import workspace_diff
from losangelex_codex_bin import DEFAULT_CODEX
from losangelex_codex_bin import ensure_default_codex
from run_silo_published_agents import write_codex_subagents_config


REPO_ROOT = Path("/home/ai/Development/losangelex")
DEFAULT_OUT_ROOT = REPO_ROOT / "tmp/research/hollywood-coordination-benchmark"
SYSTEMS = ("codex", "codex-subagents", "losangelex-baseline", "losangelex")


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


def file_manifest(scenario: Scenario) -> str:
    return "\n".join(f"- `{path}`" for path in sorted(scenario.files))


def codex_prompt(scenario: Scenario) -> str:
    return f"""You are running a frozen live coordination benchmark scenario.

System under evaluation: codex single agent.

Initial workspace files:
{file_manifest(scenario)}

User task:
{scenario.respondent_prompt}

Benchmark rules:
- Work only inside this workspace.
- Do not inspect benchmark repositories, previous result directories, or answer artifacts outside this workspace.
- Complete the requested file changes. The scorer ignores final chat unless the workspace files changed correctly.
- You do not have teammates in this run. Still write `coordination/decision.md` with one concise sentence explaining whether a collaborator would have helped and why.
- Keep edits minimal and finish when the files are in the desired state.
"""


def subagent_worker_prompt(scenario: Scenario, worker_name: str) -> str:
    return f"""You are Codex subagent `{worker_name}` in a frozen coordination benchmark.

Initial workspace files:
{file_manifest(scenario)}

User task:
{scenario.respondent_prompt}

Worker rules:
- Work only inside this workspace.
- Do not spawn subagents and do not run Codex recursively.
- Take one narrow implementation, review, or verification lane that fits the parent request.
- Avoid overlapping edits when another worker or the parent has already claimed a file.
- Write `coordination/{worker_name}.md` with the lane you took, files inspected, files edited, and any blockers.
- If no useful lane remains, write that note and finish without churn.
"""


def codex_subagents_prompt(scenario: Scenario) -> str:
    worker_sections = "\n\n".join(
        f"### Worker `{peer_name}`\n{subagent_worker_prompt(scenario, peer_name)}"
        for peer_name in scenario.peer_names
    )
    return f"""You are running a frozen live coordination benchmark scenario.

System under evaluation: codex-subagents.

Initial workspace files:
{file_manifest(scenario)}

User task:
{scenario.respondent_prompt}

Parent coordination rules:
- First inspect the workspace and decide whether spawned collaborators make the task easier, safer, or faster.
- For tiny local single-file work, do not spawn workers; record the solo decision in `coordination/parent-decision.md` and complete the task directly.
- For cross-surface implementation, review-heavy, or verification-heavy work, spawn useful workers before claiming all scope yourself.
- Spawn at most one worker per worker prompt below. For every `spawn_agent` call, set `fork_turns` to exactly `none`.
- Do not include `agent_type`, `model`, `reasoning_effort`, `service_tier`, or `fork_context` in any `spawn_agent` call.
- Do not run `codex`, `codex exec`, or any other shell fallback to simulate workers.
- Wait for all spawned workers. Use `wait_agent` with `timeout_ms` of at least `10000`; prefer `600000`.
- Incorporate, reject, or repair worker output explicitly before finalizing.
- Complete the requested file changes. The scorer ignores final chat unless the workspace files changed correctly.
- Write `coordination/parent-decision.md` with spawned workers, lanes, and whether coordination helped.

Available worker prompts:

{worker_sections}
"""


def run_codex_system(
    *,
    scenario: Scenario,
    system: str,
    codex: Path,
    model: str,
    output_dir: Path,
    timeout_seconds: int,
    codex_home_source: Path,
) -> dict[str, Any]:
    run_id = uuid.uuid4().hex[:8]
    run_dir = output_dir / system / scenario.scenario_id / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    workspace = run_dir / "workspace"
    fresh_workspace(workspace, scenario.files)

    started = time.time()
    if system == "codex":
        prompt = codex_prompt(scenario)
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
                    str(run_dir / "last-message.txt"),
                    "-",
                ],
                cwd=workspace,
                timeout=timeout_seconds,
                input_text=prompt,
            )
        )
        token_usage = parse_codex_exec_jsonl_token_usage(result.stdout)
        token_usage_summary = {
            "source": "codex-exec-jsonl",
            "parentExecJsonl": token_usage,
        }
        coordination_summary = summarize_codex_exec_collab_tools(
            result.stdout, result.stderr
        )
    elif system == "codex-subagents":
        prompt = codex_subagents_prompt(scenario)
        codex_home = run_dir / "codex-home"
        prepare_minimal_codex_home(
            codex_home=codex_home,
            source_home=codex_home_source,
            output_dir=run_dir,
        )
        write_codex_subagents_config(codex_home)
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
                    str(run_dir / "last-message.txt"),
                    "-",
                ],
                cwd=workspace,
                timeout=timeout_seconds,
                input_text=prompt,
                env=env,
            )
        )
        parent_token_usage = parse_codex_exec_jsonl_token_usage(result.stdout)
        rollout_token_usage = summarize_rollout_token_usage(
            changed_rollout_files(codex_home, rollout_snapshot)
        )
        token_usage = (
            rollout_token_usage["tokenUsage"]
            if rollout_token_usage["fileCount"] > 0
            else parent_token_usage
        )
        token_usage_summary = {
            "source": (
                "codex-session-rollouts"
                if rollout_token_usage["fileCount"] > 0
                else "codex-exec-jsonl"
            ),
            "rollouts": rollout_token_usage,
            "parentExecJsonl": parent_token_usage,
        }
        coordination_summary = summarize_codex_exec_collab_tools(
            result.stdout, result.stderr
        )
    else:
        raise ValueError(f"unsupported codex system: {system}")

    (run_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    (run_dir / "stdout.log").write_text(result.stdout, encoding="utf-8")
    (run_dir / "stderr.log").write_text(result.stderr, encoding="utf-8")
    diff = workspace_diff(workspace)
    (run_dir / "workspace.diff").write_text(diff, encoding="utf-8")

    score = score_codex_run(
        scenario=scenario,
        system=system,
        returncode=result.returncode,
        workspace=workspace,
        diff=diff,
        coordination_summary=coordination_summary,
    )
    record = {
        "system": system,
        "scenarioId": scenario.scenario_id,
        "description": scenario.description,
        "model": model,
        "runId": run_id,
        "seconds": round(time.time() - started, 1),
        "workspace": str(workspace),
        "promptPath": str(run_dir / "prompt.txt"),
        "stdoutPath": str(run_dir / "stdout.log"),
        "stderrPath": str(run_dir / "stderr.log"),
        "lastMessagePath": str(run_dir / "last-message.txt"),
        "returncode": result.returncode,
        "transientRetries": transient_retries,
        "tokenUsage": token_usage,
        "tokenUsageSummary": token_usage_summary,
        "coordinationToolSummary": coordination_summary,
        "workspaceDiff": diff,
        "score": score,
    }
    (run_dir / "result.json").write_text(
        json.dumps(record, indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def score_codex_run(
    *,
    scenario: Scenario,
    system: str,
    returncode: int,
    workspace: Path,
    diff: str,
    coordination_summary: dict[str, Any],
) -> dict[str, Any]:
    tool_calls = coordination_summary.get("toolCalls", {})
    tool_by_name = tool_calls.get("byTool", {}) if isinstance(tool_calls, dict) else {}
    error_calls = coordination_summary.get("errorCalls", {})
    tool_errors = int(error_calls.get("total", 0)) if isinstance(error_calls, dict) else 0
    spawn_calls = int(tool_by_name.get("spawn_agent", 0))
    wait_calls = int(tool_by_name.get("wait", 0))
    if system == "codex-subagents":
        coordination_requirement_met = (
            spawn_calls > 0 and wait_calls > 0
            if scenario.expect_collaboration
            else spawn_calls == 0
        )
    else:
        coordination_requirement_met = True

    expected_content_matches = expected_file_content_matches(
        workspace, scenario.expected_file_substrings
    )
    workspace_changed = bool(diff.strip())
    passed = (
        returncode == 0
        and expected_content_matches
        and workspace_changed
        and tool_errors == 0
    )
    return {
        "passed": passed,
        "expectedCollaboration": scenario.expect_collaboration,
        "coordinationRequirementMet": coordination_requirement_met,
        "expectedContentMatches": expected_content_matches,
        "workspaceChanged": workspace_changed,
        "coordinationToolErrors": tool_errors,
        "spawnAgentCalls": spawn_calls,
        "waitAgentCalls": wait_calls,
    }


def run_losangelex_system(
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
    raw_system = "candidate" if system == "losangelex" else "baseline"
    record = run_single_eval(
        scenario=scenario,
        system=raw_system,
        codex=codex,
        model=model,
        output_dir=output_dir,
        codex_home_source=codex_home_source,
        startup_timeout_seconds=startup_timeout_seconds,
        turn_timeout_seconds=turn_timeout_seconds,
    )
    run_dir = Path(record["workspace"]).parent
    record["sourceSystem"] = raw_system
    record["system"] = system
    record["resultPath"] = str(run_dir / "result.json")
    score = record.get("score", {})
    if isinstance(score, dict):
        score["coordinationRequirementMet"] = score.get(
            "collaborationRequirementMet"
        )
    record["tokenUsage"] = record.get("notificationSummary", {}).get(
        "tokenUsage",
        normalize_token_usage(None),
    )
    (run_dir / "benchmark-result.json").write_text(
        json.dumps(record, indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def token_value(record: dict[str, Any], key: str) -> int:
    return normalize_token_usage(record.get("tokenUsage")).get(key, 0)


def aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_system: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_system.setdefault(str(record["system"]), []).append(record)

    systems: dict[str, Any] = {}
    for system, system_records in sorted(by_system.items()):
        count = len(system_records)
        passed = sum(1 for record in system_records if record["score"]["passed"])
        expected = sum(
            1 for record in system_records if record["score"]["expectedContentMatches"]
        )
        coord_met = sum(
            1
            for record in system_records
            if record["score"].get("coordinationRequirementMet")
        )
        token_records = [
            record
            for record in system_records
            if token_value(record, "totalTokens") > 0
        ]
        token_count = len(token_records)
        systems[system] = {
            "runs": count,
            "passed": passed,
            "passRate": passed / count if count else 0,
            "expectedContentMatches": expected,
            "coordinationRequirementMet": coord_met,
            "avgSeconds": sum(record.get("seconds", 0) for record in system_records)
            / count,
            "tokenUsageTaskCount": token_count,
            "avgTotalTokens": (
                sum(token_value(record, "totalTokens") for record in token_records)
                / token_count
                if token_count
                else None
            ),
            "avgUncachedPlusOutputTokens": (
                sum(
                    token_value(record, "uncachedPlusOutputTokens")
                    for record in token_records
                )
                / token_count
                if token_count
                else None
            ),
            "spawnAgentCalls": sum(
                record["score"].get("spawnAgentCalls", 0) for record in system_records
            ),
            "requiredPeerRequests": sum(
                record["score"].get("requiredPeerRequestCount", 0)
                for record in system_records
            ),
            "peerResponses": sum(
                record["score"].get("peerResponseCount", 0)
                for record in system_records
            ),
            "toolErrors": sum(
                record["score"].get("coordinationToolErrors", 0)
                for record in system_records
            ),
        }
    return {"systems": systems}


def format_token_value(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:,.0f}"


def write_report(output_dir: Path, records: list[dict[str, Any]]) -> None:
    summary = aggregate(records)
    lines = [
        "# Hollywood Coordination Benchmark",
        "",
        f"Generated: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        "",
        "Live model-in-the-loop comparison using frozen scratch coordination scenarios.",
        "",
        "## Summary",
        "",
        "| System | Runs | Passed | Content matches | Coord met | Avg seconds | Avg total tokens | Avg uncached+output | Spawn calls | Required peer requests | Peer responses | Tool errors |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for system, row in summary["systems"].items():
        lines.append(
            f"| {system} | {row['runs']} | {row['passed']} ({row['passRate']:.1%}) | "
            f"{row['expectedContentMatches']} | {row['coordinationRequirementMet']} | "
            f"{row['avgSeconds']:.1f} | {format_token_value(row['avgTotalTokens'])} | "
            f"{format_token_value(row['avgUncachedPlusOutputTokens'])} | "
            f"{row['spawnAgentCalls']} | {row['requiredPeerRequests']} | "
            f"{row['peerResponses']} | {row['toolErrors']} |"
        )

    lines.extend(["", "## Runs", ""])
    for record in records:
        score = record["score"]
        usage = normalize_token_usage(record.get("tokenUsage"))
        lines.extend(
            [
                f"### {record['system']} / {record['scenarioId']} / {record['runId']}",
                "",
                f"- Passed: `{score['passed']}`",
                f"- Expected collaboration: `{score['expectedCollaboration']}`",
                f"- Coordination requirement met: `{score.get('coordinationRequirementMet')}`",
                f"- Expected content matches: `{score['expectedContentMatches']}`",
                f"- Workspace changed: `{score['workspaceChanged']}`",
                f"- Seconds: `{record.get('seconds')}`",
                f"- Total tokens: `{usage['totalTokens']}`",
                f"- Uncached+output tokens: `{usage['uncachedPlusOutputTokens']}`",
                f"- Spawn calls: `{score.get('spawnAgentCalls', 0)}`",
                f"- Required peer requests: `{score.get('requiredPeerRequestCount', 0)}`",
                f"- Peer responses: `{score.get('peerResponseCount', 0)}`",
                f"- Tool errors: `{score.get('coordinationToolErrors', 0)}`",
                f"- Workspace: `{record['workspace']}`",
                "",
            ]
        )

    (output_dir / "HOLLYWOOD_COORDINATION_REPORT.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex", type=Path, default=DEFAULT_CODEX)
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument(
        "--campaign-name",
        default=f"hollywood-coordination-{time.strftime('%Y-%m-%d-%H%M%S')}",
    )
    parser.add_argument("--system", action="append", choices=SYSTEMS)
    parser.add_argument("--scenario", action="append", choices=sorted(SCENARIOS))
    parser.add_argument("--runs-per-scenario", type=int, default=1)
    parser.add_argument(
        "--codex-home-source", type=Path, default=Path.home() / ".codex"
    )
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--startup-timeout-seconds", type=int, default=45)
    parser.add_argument("--turn-timeout-seconds", type=int, default=240)
    args = parser.parse_args()

    ensure_default_codex(args.codex)
    systems = args.system or list(SYSTEMS)
    scenarios = [SCENARIOS[name] for name in (args.scenario or sorted(SCENARIOS))]
    output_dir = args.out_root / args.campaign_name
    output_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    for scenario in scenarios:
        for system in systems:
            for _ in range(args.runs_per_scenario):
                if system in {"codex", "codex-subagents"}:
                    record = run_codex_system(
                        scenario=scenario,
                        system=system,
                        codex=args.codex,
                        model=args.model,
                        output_dir=output_dir,
                        timeout_seconds=args.timeout_seconds,
                        codex_home_source=args.codex_home_source,
                    )
                else:
                    record = run_losangelex_system(
                        scenario=scenario,
                        system=system,
                        codex=args.codex,
                        model=args.model,
                        output_dir=output_dir,
                        codex_home_source=args.codex_home_source,
                        startup_timeout_seconds=args.startup_timeout_seconds,
                        turn_timeout_seconds=args.turn_timeout_seconds,
                    )
                records.append(record)
                print(
                    json.dumps(
                        {
                            "system": record["system"],
                            "scenarioId": record["scenarioId"],
                            "runId": record["runId"],
                            "score": record["score"],
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )

    payload = {
        "benchmark": "Hollywood coordination",
        "campaignName": args.campaign_name,
        "model": args.model,
        "systems": systems,
        "records": records,
        "summary": aggregate(records),
    }
    (output_dir / "results.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    write_report(output_dir, records)
    print(f"wrote {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
