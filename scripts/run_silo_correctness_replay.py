#!/usr/bin/env python3
"""Run targeted SILO correctness replay suites and classify the results."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path("/home/ai/Development/losangelex")
DEFAULT_OUT_ROOT = REPO_ROOT / "tmp" / "research" / "published-agent-benchmarks"

SUITES = {
    "format": [
        "II-12_n5",
        "II-12_n10",
        "III-25_n5",
        "III-27_n5",
        "III-28_n5",
    ],
    "outlier": [
        "II-14_n5",
        "II-14_n10",
        "II-20_n5",
    ],
    "global": [
        "II-15_n5",
        "II-15_n10",
    ],
    "hard-smoke": [
        "II-12_n5",
        "II-14_n5",
        "II-15_n5",
    ],
}
SUITES["all"] = sorted(
    {
        task_id
        for suite, task_ids in SUITES.items()
        if suite != "hard-smoke"
        for task_id in task_ids
    }
)


def selected_task_ids(suites: list[str], explicit_task_ids: list[str]) -> list[str]:
    task_ids: list[str] = []
    seen: set[str] = set()
    for suite in suites:
        for task_id in SUITES[suite]:
            if task_id not in seen:
                task_ids.append(task_id)
                seen.add(task_id)
    for task_id in explicit_task_ids:
        if task_id not in seen:
            task_ids.append(task_id)
            seen.add(task_id)
    return task_ids


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--suite",
        action="append",
        choices=sorted(SUITES),
        default=[],
        help="Replay suite to run. Defaults to hard-smoke.",
    )
    parser.add_argument("--task-id", action="append", dest="task_ids", default=[])
    parser.add_argument(
        "--system",
        action="append",
        choices=(
            "losangelex",
            "losangelex-contract",
            "losangelex-peer-review",
            "codex-subagents",
            "codex-full-context",
        ),
        default=[],
    )
    parser.add_argument("--campaign-name")
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--round-timeout-seconds", type=int, default=300)
    parser.add_argument("--per-agent-timeout-seconds", type=int, default=600)
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--poll-seconds", type=int, default=45)
    parser.add_argument("--submission-settle-seconds", type=float, default=5.0)
    parser.add_argument(
        "--runner-arg",
        action="append",
        default=[],
        help="Additional single argument passed through to run_silo_published_agents.py.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    suites = args.suite or ([] if args.task_ids else ["hard-smoke"])
    systems = args.system or [
        "losangelex",
        "losangelex-contract",
        "losangelex-peer-review",
    ]
    task_ids = selected_task_ids(suites, args.task_ids)
    campaign_name = args.campaign_name or (
        f"silo-correctness-replay-{'-'.join(suites)}-{time.strftime('%Y-%m-%d-%H%M%S')}"
    )
    output_dir = args.out_root / campaign_name

    runner = REPO_ROOT / "scripts" / "run_silo_published_agents.py"
    command = [
        sys.executable,
        str(runner),
        "--campaign-name",
        campaign_name,
        "--out-root",
        str(args.out_root),
        "--model",
        args.model,
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--round-timeout-seconds",
        str(args.round_timeout_seconds),
        "--per-agent-timeout-seconds",
        str(args.per_agent_timeout_seconds),
        "--max-rounds",
        str(args.max_rounds),
        "--poll-seconds",
        str(args.poll_seconds),
        "--submission-settle-seconds",
        str(args.submission_settle_seconds),
    ]
    for system in systems:
        command.extend(["--system", system])
    for task_id in task_ids:
        command.extend(["--task-id", task_id])
    command.extend(args.runner_arg)

    print("Running:")
    print(" ".join(command))
    if args.dry_run:
        return 0

    result = subprocess.run(command, cwd=REPO_ROOT, check=False)
    if result.returncode != 0:
        return result.returncode

    report = output_dir / "SILO_CORRECTNESS_REPLAY_REPORT.md"
    analysis_command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "analyze_silo_correctness_failures.py"),
        str(output_dir / "results.json"),
        "--out",
        str(report),
        "--title",
        f"SILO Correctness Replay: {campaign_name}",
    ]
    print("Analyzing:")
    print(" ".join(analysis_command))
    return subprocess.run(analysis_command, cwd=REPO_ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
