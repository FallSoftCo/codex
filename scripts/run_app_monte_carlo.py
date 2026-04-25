#!/usr/bin/env python3
"""Run a multi-challenge Hollywood app-build campaign and summarize the results."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from pathlib import Path
from typing import Any

from eval_hollywood_app_builds import CHALLENGES, POLICY_PROMPTS, evaluate_policy


REPO_ROOT = Path("/home/ai/Development/losangelex")
OUTPUT_ROOT = REPO_ROOT / "tmp" / "app_build_eval"
DEFAULT_POLICIES = ["room_message", "leader_award", "semantic_market", "hybrid"]
DEFAULT_CHALLENGES = ["habit_dashboard", "incident_console", "expense_board"]


def active_thread_count(result: dict[str, Any]) -> int:
    if "activeThreadsAfterRun" in result:
        return int(result["activeThreadsAfterRun"])
    count = 0
    for state in result["threadStates"].values():
        status = state.get("status")
        if isinstance(status, dict) and status.get("type") == "active":
            count += 1
    return count


def summarize(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for result in results:
        grouped.setdefault((result["challenge"], result["policy"]), []).append(result)

    summary: list[dict[str, Any]] = []
    for (challenge, policy), runs in sorted(grouped.items()):
        passed = [run for run in runs if run["passed"]]
        summary.append(
            {
                "challenge": challenge,
                "policy": policy,
                "runs": len(runs),
                "passRate": sum(1 for run in runs if run["passed"]) / len(runs),
                "avgPassSeconds": (
                    statistics.mean(run["passedAtSeconds"] for run in passed if run["passedAtSeconds"])
                    if passed
                    else None
                ),
                "avgHollywoodMessages": statistics.mean(
                    run.get("messageCount", len(run["summary"]["hollywoodMessages"]))
                    for run in runs
                ),
                "avgActiveThreadsAfterRun": statistics.mean(
                    active_thread_count(run) for run in runs
                ),
                "avgChangedFiles": statistics.mean(
                    run.get("changedFilesCount", len(run["changedFiles"])) for run in runs
                ),
                "quiescenceRate": sum(
                    1 for run in runs if run.get("eventuallyQuiesced", False)
                )
                / len(runs),
                "avgQuiescenceLagSeconds": (
                    statistics.mean(
                        run["quiescenceLagSeconds"]
                        for run in runs
                        if run.get("quiescenceLagSeconds") is not None
                    )
                    if any(run.get("quiescenceLagSeconds") is not None for run in runs)
                    else None
                ),
            }
        )
    return summary


def overall_summary(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        grouped.setdefault(result["policy"], []).append(result)

    summary: list[dict[str, Any]] = []
    for policy, runs in grouped.items():
        passed = [run for run in runs if run["passed"]]
        summary.append(
            {
                "policy": policy,
                "runs": len(runs),
                "passRate": sum(1 for run in runs if run["passed"]) / len(runs),
                "avgPassSeconds": (
                    statistics.mean(run["passedAtSeconds"] for run in passed if run["passedAtSeconds"])
                    if passed
                    else None
                ),
                "avgHollywoodMessages": statistics.mean(
                    run.get("messageCount", len(run["summary"]["hollywoodMessages"]))
                    for run in runs
                ),
                "avgActiveThreadsAfterRun": statistics.mean(
                    active_thread_count(run) for run in runs
                ),
                "avgChangedFiles": statistics.mean(
                    run.get("changedFilesCount", len(run["changedFiles"])) for run in runs
                ),
                "quiescenceRate": sum(
                    1 for run in runs if run.get("eventuallyQuiesced", False)
                )
                / len(runs),
                "avgQuiescenceLagSeconds": (
                    statistics.mean(
                        run["quiescenceLagSeconds"]
                        for run in runs
                        if run.get("quiescenceLagSeconds") is not None
                    )
                    if any(run.get("quiescenceLagSeconds") is not None for run in runs)
                    else None
                ),
            }
        )
    return sorted(
        summary,
        key=lambda row: (
            -row["passRate"],
            math.inf if row["avgPassSeconds"] is None else row["avgPassSeconds"],
            row["avgActiveThreadsAfterRun"],
            row["avgHollywoodMessages"],
            row["policy"],
        ),
    )


def render_markdown(
    *,
    app_server_url: str,
    challenges: list[str],
    policies: list[str],
    repeats: int,
    timeout_seconds: int,
    poll_seconds: int,
    max_quiescence_wait_seconds: int | None,
    completed_runs: int,
    total_runs: int,
    overall: list[dict[str, Any]],
    summary: list[dict[str, Any]],
) -> str:
    lines = [
        "# Hollywood App Monte Carlo Evaluation",
        "",
        f"- Updated at: {time.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"- App server: `{app_server_url}`",
        f"- Challenges: {', '.join(f'`{challenge}`' for challenge in challenges)}",
        f"- Policies: {', '.join(f'`{policy}`' for policy in policies)}",
        f"- Repeats per challenge/policy: `{repeats}`",
        f"- Timeout per run: `{timeout_seconds}s`",
        f"- Poll interval: `{poll_seconds}s`",
        (
            f"- Max quiescence wait after green: `{max_quiescence_wait_seconds}s`"
            if max_quiescence_wait_seconds is not None
            else "- Max quiescence wait after green: `match soak window`"
        ),
        f"- Completed runs: `{completed_runs}/{total_runs}`",
        "",
        "## Overall Leaderboard",
        "",
        "| Policy | Pass Rate | Avg Time To Green | Quiescence Rate | Avg Quiescence Lag | Avg Hollywood Messages | Avg Active Threads After Run | Avg Changed Files |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in overall:
        avg_time = "-" if row["avgPassSeconds"] is None else f"{row['avgPassSeconds']:.1f}s"
        avg_quiescence = (
            "-"
            if row["avgQuiescenceLagSeconds"] is None
            else f"{row['avgQuiescenceLagSeconds']:.1f}s"
        )
        lines.append(
            f"| `{row['policy']}` | {row['passRate']:.2f} | {avg_time} | "
            f"{row['quiescenceRate']:.2f} | {avg_quiescence} | {row['avgHollywoodMessages']:.1f} | "
            f"{row['avgActiveThreadsAfterRun']:.1f} | {row['avgChangedFiles']:.1f} |"
        )
    lines.extend(
        [
            "",
            "## Per-Challenge Summary",
            "",
            "| Challenge | Policy | Pass Rate | Avg Time To Green | Quiescence Rate | Avg Quiescence Lag | Avg Hollywood Messages | Avg Active Threads After Run | Avg Changed Files |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in summary:
        avg_time = "-" if row["avgPassSeconds"] is None else f"{row['avgPassSeconds']:.1f}s"
        avg_quiescence = (
            "-"
            if row["avgQuiescenceLagSeconds"] is None
            else f"{row['avgQuiescenceLagSeconds']:.1f}s"
        )
        lines.append(
            f"| `{row['challenge']}` | `{row['policy']}` | {row['passRate']:.2f} | {avg_time} | "
            f"{row['quiescenceRate']:.2f} | {avg_quiescence} | {row['avgHollywoodMessages']:.1f} | "
            f"{row['avgActiveThreadsAfterRun']:.1f} | {row['avgChangedFiles']:.1f} |"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- `Avg Active Threads After Run` uses the recorded final thread states after the post-pass soak window.",
            "- Lower `Avg Hollywood Messages` is not automatically better; it only becomes a positive signal when pass rate stays high.",
            "- `Avg Changed Files` is a rough proxy for how broad the resulting workspace delta was relative to the scaffold.",
            "",
        ]
    )
    return "\n".join(lines)


def write_artifacts(
    *,
    output_dir: Path,
    app_server_url: str,
    campaign_name: str,
    challenges: list[str],
    policies: list[str],
    repeats: int,
    timeout_seconds: int,
    poll_seconds: int,
    post_pass_soak_seconds: int,
    max_quiescence_wait_seconds: int | None,
    results: list[dict[str, Any]],
) -> tuple[Path, Path]:
    total_runs = len(challenges) * len(policies) * repeats
    summary = summarize(results)
    overall = overall_summary(results)
    raw_path = output_dir / "results.json"
    raw_path.write_text(
        json.dumps(
            {
                "appServerUrl": app_server_url,
                "campaignName": campaign_name,
                "challenges": challenges,
                "policies": policies,
                "repeats": repeats,
                "timeoutSeconds": timeout_seconds,
                "pollSeconds": poll_seconds,
                "postPassSoakSeconds": post_pass_soak_seconds,
                "maxQuiescenceWaitSeconds": max_quiescence_wait_seconds,
                "completedRuns": len(results),
                "totalRuns": total_runs,
                "results": results,
                "overallSummary": overall,
                "summary": summary,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    report_path = output_dir / "REPORT.md"
    report_path.write_text(
        render_markdown(
            app_server_url=app_server_url,
            challenges=challenges,
            policies=policies,
            repeats=repeats,
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
            max_quiescence_wait_seconds=max_quiescence_wait_seconds,
            completed_runs=len(results),
            total_runs=total_runs,
            overall=overall,
            summary=summary,
        ),
        encoding="utf-8",
    )
    return raw_path, report_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-server-url", required=True)
    parser.add_argument("--challenge", choices=sorted(CHALLENGES), action="append")
    parser.add_argument("--policy", choices=sorted(POLICY_PROMPTS), action="append")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=int, default=240)
    parser.add_argument("--poll-seconds", type=int, default=40)
    parser.add_argument("--post-pass-soak-seconds", type=int, default=20)
    parser.add_argument("--max-quiescence-wait-seconds", type=int)
    parser.add_argument("--campaign-name", default=f"campaign-{int(time.time())}")
    args = parser.parse_args()

    challenges = args.challenge or DEFAULT_CHALLENGES
    policies = args.policy or DEFAULT_POLICIES
    output_dir = OUTPUT_ROOT / args.campaign_name
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for challenge in challenges:
        for policy in policies:
            for repeat in range(1, args.repeats + 1):
                result = evaluate_policy(
                    policy=policy,
                    challenge=challenge,
                    app_server_url=args.app_server_url,
                    timeout_seconds=args.timeout_seconds,
                    poll_seconds=args.poll_seconds,
                    post_pass_soak_seconds=args.post_pass_soak_seconds,
                    max_quiescence_wait_seconds=args.max_quiescence_wait_seconds,
                )
                result["repeat"] = repeat
                results.append(result)
                raw_path, report_path = write_artifacts(
                    output_dir=output_dir,
                    app_server_url=args.app_server_url,
                    campaign_name=args.campaign_name,
                    challenges=challenges,
                    policies=policies,
                    repeats=args.repeats,
                    timeout_seconds=args.timeout_seconds,
                    poll_seconds=args.poll_seconds,
                    post_pass_soak_seconds=args.post_pass_soak_seconds,
                    max_quiescence_wait_seconds=args.max_quiescence_wait_seconds,
                    results=results,
                )
                print(
                    f"completed challenge={challenge} policy={policy} repeat={repeat} "
                    f"passed={result['passed']} passAt={result['passedAtSeconds']}",
                    flush=True,
                )
    raw_path, report_path = write_artifacts(
        output_dir=output_dir,
        app_server_url=args.app_server_url,
        campaign_name=args.campaign_name,
        challenges=challenges,
        policies=policies,
        repeats=args.repeats,
        timeout_seconds=args.timeout_seconds,
        poll_seconds=args.poll_seconds,
        post_pass_soak_seconds=args.post_pass_soak_seconds,
        max_quiescence_wait_seconds=args.max_quiescence_wait_seconds,
        results=results,
    )

    print(f"wrote {raw_path}")
    print(f"wrote {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
