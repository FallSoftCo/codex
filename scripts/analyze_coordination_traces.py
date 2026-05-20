#!/usr/bin/env python3
"""Classify coordination benchmark traces into reproducible failure modes."""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import statistics
from collections import defaultdict
from typing import Any

from analyze_coordination_benchmark import fmt_number, wilson_ci
from analyze_coordination_frontier import load_results


COUNTER_FIELDS = (
    "duplicate_attempts",
    "scope_conflicts",
    "invalid_actions",
    "waits_with_work",
    "idle_with_actionable_work",
)

TAIL_CATEGORIES = {
    "duplicate_pick": "duplicate picks",
    "scope_conflict": "scope conflict",
    "invalid_action": "invalid action",
    "unavailable_target": "chose unavailable",
    "ineligible_target": "is ineligible for",
    "explicit_wait_with_work": "waited despite eligible work",
    "implicit_idle_with_work": "left idle while work existed",
    "started_work": " started ",
    "completed_probe": "completed probe",
    "completed_task": "completed task",
}

REPORT_CATEGORIES = (
    "duplicate_pick",
    "scope_conflict",
    "invalid_action",
    "unavailable_target",
    "ineligible_target",
    "explicit_wait_with_work",
    "implicit_idle_with_work",
)


def mean(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


def classify_tail_line(line: str) -> list[str]:
    return [
        category
        for category, needle in TAIL_CATEGORIES.items()
        if needle in line
    ]


def run_trace(run: dict[str, Any]) -> dict[str, Any]:
    tail_events = {category: 0 for category in TAIL_CATEGORIES}
    examples: dict[str, list[str]] = {category: [] for category in TAIL_CATEGORIES}
    for line in run.get("log_tail", []):
        for category in classify_tail_line(line):
            tail_events[category] += 1
            if len(examples[category]) < 3:
                examples[category].append(line)

    modes = []
    if not run.get("success", False):
        modes.append("failed_to_complete")
    if run.get("deadlock", False):
        modes.append("deadlock")
    if run.get("duplicate_attempts", 0):
        modes.append("duplicate_assignment")
    if run.get("scope_conflicts", 0):
        modes.append("scope_conflict")
    if run.get("invalid_actions", 0):
        modes.append("invalid_action")
    if run.get("waits_with_work", 0):
        modes.append("missed_parallelism")

    return {
        "scenario": run["scenario"],
        "policy": run["policy"],
        "repeat": int(run["repeat"]),
        "success": bool(run["success"]),
        "deadlock": bool(run["deadlock"]),
        "completion_time": run.get("completion_time"),
        "rounds": run.get("rounds"),
        "counters": {
            field: run.get(field, 0)
            for field in COUNTER_FIELDS
        },
        "idle_ratio": run.get("idle_ratio", 0.0),
        "model_calls": run.get("model_calls", 0),
        "model_tokens": run.get("model_tokens", 0),
        "tail_events": tail_events,
        "tail_examples": {
            category: lines
            for category, lines in examples.items()
            if lines
        },
        "modes": modes,
    }


def aggregate_traces(
    traces: list[dict[str, Any]],
    *,
    group_fields: tuple[str, ...],
    example_limit: int,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for trace in traces:
        groups[tuple(trace[field] for field in group_fields)].append(trace)

    rows = []
    for key, runs in sorted(groups.items()):
        row: dict[str, Any] = {
            field: value for field, value in zip(group_fields, key, strict=True)
        }
        row["runs"] = len(runs)
        row["success"] = wilson_ci(sum(1 for run in runs if run["success"]), len(runs))
        row["deadlock"] = wilson_ci(sum(1 for run in runs if run["deadlock"]), len(runs))
        row["failure"] = wilson_ci(sum(1 for run in runs if not run["success"]), len(runs))
        for field in COUNTER_FIELDS:
            row[f"avg_{field}"] = mean(
                [float(run["counters"].get(field, 0)) for run in runs]
            )
        row["avg_idle_ratio"] = mean([float(run.get("idle_ratio", 0.0)) for run in runs])
        row["avg_model_calls"] = mean([float(run.get("model_calls", 0)) for run in runs])
        row["avg_model_tokens"] = mean([float(run.get("model_tokens", 0)) for run in runs])
        row["tail_events"] = {
            category: sum(run["tail_events"].get(category, 0) for run in runs)
            for category in TAIL_CATEGORIES
        }
        row["mode_counts"] = {
            mode: sum(1 for run in runs if mode in run["modes"])
            for mode in (
                "failed_to_complete",
                "deadlock",
                "duplicate_assignment",
                "scope_conflict",
                "invalid_action",
                "missed_parallelism",
            )
        }
        examples: dict[str, list[str]] = {}
        for category in REPORT_CATEGORIES:
            lines = []
            for run in runs:
                for line in run["tail_examples"].get(category, []):
                    if line not in lines:
                        lines.append(line)
                    if len(lines) >= example_limit:
                        break
                if len(lines) >= example_limit:
                    break
            if lines:
                examples[category] = lines
        row["examples"] = examples
        rows.append(row)
    return rows


def pct(item: dict[str, float | None]) -> str:
    value = item["rate"]
    if value is None:
        return "-"
    return f"{100 * value:.1f}%"


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def report_rows(rows: list[dict[str, Any]], *, include_scenario: bool) -> list[list[str]]:
    output = []
    for row in rows:
        cells = []
        if include_scenario:
            cells.append(row["scenario"])
        cells.extend(
            [
                row["policy"],
                str(row["runs"]),
                pct(row["success"]),
                pct(row["deadlock"]),
                fmt_number(row["avg_duplicate_attempts"]),
                fmt_number(row["avg_scope_conflicts"]),
                fmt_number(row["avg_invalid_actions"]),
                fmt_number(row["avg_waits_with_work"]),
                fmt_number(row["avg_idle_with_actionable_work"]),
                str(row["tail_events"]["explicit_wait_with_work"]),
                str(row["tail_events"]["scope_conflict"]),
            ]
        )
        output.append(cells)
    return output


def write_csv(path: pathlib.Path, rows: list[dict[str, Any]], *, include_scenario: bool) -> None:
    fields = []
    if include_scenario:
        fields.append("scenario")
    fields.extend(
        [
            "policy",
            "runs",
            "success_rate",
            "deadlock_rate",
            "failure_rate",
            "avg_duplicate_attempts",
            "avg_scope_conflicts",
            "avg_invalid_actions",
            "avg_waits_with_work",
            "avg_idle_with_actionable_work",
            "avg_idle_ratio",
            "avg_model_calls",
            "avg_model_tokens",
        ]
    )
    fields.extend(f"tail_{category}" for category in TAIL_CATEGORIES)
    if rows:
        fields.extend(f"mode_{mode}" for mode in rows[0]["mode_counts"])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in rows:
            row: dict[str, Any] = {
                "policy": item["policy"],
                "runs": item["runs"],
                "success_rate": item["success"]["rate"],
                "deadlock_rate": item["deadlock"]["rate"],
                "failure_rate": item["failure"]["rate"],
                "avg_duplicate_attempts": item["avg_duplicate_attempts"],
                "avg_scope_conflicts": item["avg_scope_conflicts"],
                "avg_invalid_actions": item["avg_invalid_actions"],
                "avg_waits_with_work": item["avg_waits_with_work"],
                "avg_idle_with_actionable_work": item["avg_idle_with_actionable_work"],
                "avg_idle_ratio": item["avg_idle_ratio"],
                "avg_model_calls": item["avg_model_calls"],
                "avg_model_tokens": item["avg_model_tokens"],
            }
            if include_scenario:
                row["scenario"] = item["scenario"]
            for category, count in item["tail_events"].items():
                row[f"tail_{category}"] = count
            for mode, count in item["mode_counts"].items():
                row[f"mode_{mode}"] = count
            writer.writerow(row)


def write_report(
    path: pathlib.Path,
    *,
    model: str | None,
    traces: list[dict[str, Any]],
    overall: list[dict[str, Any]],
    by_scenario: list[dict[str, Any]],
) -> None:
    lines = [
        "# Coordination Trace Taxonomy",
        "",
        "## Scope",
        "",
        (
            "This artifact classifies the existing coordination benchmark records into "
            "failure-mode evidence. Full-run simulator counters are used for duplicate "
            "assignments, scope conflicts, invalid actions, waits with eligible work, and "
            "idle-with-work opportunities. Log-tail labels are limited to the last ten "
            "recorded events per run and are included as qualitative examples rather than "
            "complete trace counts."
        ),
        "",
        f"Model: `{model or '-'}`. Runs: {len(traces)}.",
        "",
        "## Overall Failure Taxonomy",
        "",
        markdown_table(
            [
                "Policy",
                "Runs",
                "Success",
                "Deadlock",
                "Dup/run",
                "Scope/run",
                "Invalid/run",
                "Wait/run",
                "Idle/run",
                "Tail waits",
                "Tail scope",
            ],
            report_rows(overall, include_scenario=False),
        ),
        "",
        "## Scenario Failure Taxonomy",
        "",
        markdown_table(
            [
                "Scenario",
                "Policy",
                "Runs",
                "Success",
                "Deadlock",
                "Dup/run",
                "Scope/run",
                "Invalid/run",
                "Wait/run",
                "Idle/run",
                "Tail waits",
                "Tail scope",
            ],
            report_rows(by_scenario, include_scenario=True),
        ),
        "",
        "## Example Trace Fragments",
        "",
    ]

    for row in overall:
        if not row["examples"]:
            continue
        lines.extend([f"### {row['policy']}", ""])
        for category in REPORT_CATEGORIES:
            examples = row["examples"].get(category)
            if not examples:
                continue
            lines.append(f"- `{category}`:")
            lines.extend(f"  - `{line}`" for line in examples)
        lines.append("")

    lines.extend(
        [
            "## Reproducibility",
            "",
            "- `trace-taxonomy.json`: classified per-run traces and aggregates.",
            "- `trace-taxonomy.csv`: scenario-policy aggregate counters.",
            "- `trace-taxonomy-overall.csv`: policy aggregate counters.",
            "- `TRACE_TAXONOMY_REPORT.md`: this report.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("results_json", nargs="+", type=pathlib.Path)
    parser.add_argument("--out-dir", type=pathlib.Path, required=True)
    parser.add_argument("--example-limit", type=int, default=3)
    args = parser.parse_args()
    if args.example_limit < 1:
        parser.error("--example-limit must be at least 1")

    model, results = load_results(args.results_json)
    traces = [run_trace(run) for run in results]
    overall = aggregate_traces(
        traces,
        group_fields=("policy",),
        example_limit=args.example_limit,
    )
    by_scenario = aggregate_traces(
        traces,
        group_fields=("scenario", "policy"),
        example_limit=args.example_limit,
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "model": model,
        "runs": len(traces),
        "traces": traces,
        "overall": overall,
        "by_scenario": by_scenario,
    }
    (args.out_dir / "trace-taxonomy.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    write_csv(args.out_dir / "trace-taxonomy-overall.csv", overall, include_scenario=False)
    write_csv(args.out_dir / "trace-taxonomy.csv", by_scenario, include_scenario=True)
    write_report(
        args.out_dir / "TRACE_TAXONOMY_REPORT.md",
        model=model,
        traces=traces,
        overall=overall,
        by_scenario=by_scenario,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
