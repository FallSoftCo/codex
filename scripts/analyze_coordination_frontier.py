#!/usr/bin/env python3
"""Analyze multi-policy coordination benchmark frontiers."""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import statistics
from collections import defaultdict
from typing import Any

from analyze_coordination_benchmark import (
    METRICS,
    bootstrap_ci,
    fmt_ci,
    fmt_number,
    wilson_ci,
)
from benchmark_coordination_policies import POLICY_DESCRIPTIONS, SCENARIOS, aggregate


LOWER_IS_BETTER = (
    "completion_time",
    "model_calls",
    "model_tokens",
    "idle_ratio",
    "duplicate_attempts",
    "scope_conflicts",
    "invalid_actions",
    "waits_with_work",
)


def load_results(paths: list[pathlib.Path]) -> tuple[str | None, list[dict[str, Any]]]:
    model: str | None = None
    by_key: dict[tuple[str, str, int], dict[str, Any]] = {}
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if model is None:
            model = payload.get("model")
        for result in payload["results"]:
            key = (result["scenario"], result["policy"], int(result["repeat"]))
            by_key[key] = result
    return model, [by_key[key] for key in sorted(by_key)]


def grouped(
    results: list[dict[str, Any]],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        groups[(result["scenario"], result["policy"])].append(result)
    return dict(groups)


def mean(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


def summarize(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for (scenario, policy), runs in sorted(grouped(results).items()):
        row: dict[str, Any] = {
            "scenario": scenario,
            "policy": policy,
            "runs": len(runs),
            "success": wilson_ci(sum(1 for run in runs if run["success"]), len(runs)),
        }
        for metric in METRICS:
            values = [float(run[metric]) for run in runs if run.get(metric) is not None]
            row[metric] = bootstrap_ci(
                values,
                seed=f"frontier:{scenario}:{policy}:{metric}",
            )
        rows.append(row)
    return rows


def overall_policy_summary(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    expected_pairs = {(result["scenario"], int(result["repeat"])) for result in results}
    expected_count = len(expected_pairs)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        groups[result["policy"]].append(result)
    rows = []
    for policy, runs in sorted(groups.items()):
        covered_pairs = {(result["scenario"], int(result["repeat"])) for result in runs}
        row: dict[str, Any] = {
            "scenario": "__all__",
            "policy": policy,
            "runs": len(runs),
            "coverage": len(covered_pairs),
            "expected_coverage": expected_count,
            "coverage_rate": len(covered_pairs) / expected_count
            if expected_count
            else 0,
            "success": wilson_ci(sum(1 for run in runs if run["success"]), len(runs)),
        }
        for metric in METRICS:
            values = [float(run[metric]) for run in runs if run.get(metric) is not None]
            row[metric] = bootstrap_ci(
                values, seed=f"frontier:__all__:{policy}:{metric}"
            )
        rows.append(row)
    return rows


def dominates(a: dict[str, Any], b: dict[str, Any]) -> bool:
    a_success = a["success"]["rate"] or 0.0
    b_success = b["success"]["rate"] or 0.0
    if a_success < b_success:
        return False

    strictly_better = a_success > b_success
    for metric in LOWER_IS_BETTER:
        a_value = a[metric]["mean"]
        b_value = b[metric]["mean"]
        if a_value is None or b_value is None:
            continue
        if a_value > b_value:
            return False
        if a_value < b_value:
            strictly_better = True
    return strictly_better


def frontier(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for candidate in rows:
        if not any(
            dominates(other, candidate) for other in rows if other is not candidate
        ):
            output.append(candidate)
    return sorted(
        output,
        key=lambda row: (
            -(row["success"]["rate"] or 0),
            row["completion_time"]["mean"] or 0,
            row["model_tokens"]["mean"] or 0,
        ),
    )


def primary_frontier(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the cost/error frontier among rows with the best observed success."""
    if not rows:
        return []
    best_success = max(row["success"]["rate"] or 0.0 for row in rows)
    successful_rows = [
        row for row in rows if (row["success"]["rate"] or 0.0) == best_success
    ]
    return frontier(successful_rows)


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def write_summary_csv(path: pathlib.Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "scenario",
        "policy",
        "runs",
        "success_rate",
        "success_low",
        "success_high",
    ]
    for metric in METRICS:
        fields.extend([f"{metric}_mean", f"{metric}_low", f"{metric}_high"])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in rows:
            row = {
                "scenario": item["scenario"],
                "policy": item["policy"],
                "runs": item["runs"],
                "success_rate": item["success"]["rate"],
                "success_low": item["success"]["low"],
                "success_high": item["success"]["high"],
            }
            for metric in METRICS:
                row[f"{metric}_mean"] = item[metric]["mean"]
                row[f"{metric}_low"] = item[metric]["low"]
                row[f"{metric}_high"] = item[metric]["high"]
            writer.writerow(row)


def report_rows(rows: list[dict[str, Any]]) -> list[list[str]]:
    return [
        [
            row["policy"],
            str(row["runs"]),
            (
                f"{row['coverage']}/{row['expected_coverage']}"
                if "coverage" in row
                else "-"
            ),
            fmt_ci(row["success"], key="rate"),
            fmt_ci(row["completion_time"]),
            fmt_ci(row["model_calls"]),
            fmt_ci(row["model_tokens"], digits=0),
            fmt_ci(row["scope_conflicts"]),
            fmt_ci(row["idle_ratio"]),
        ]
        for row in rows
    ]


def write_report(
    path: pathlib.Path,
    *,
    model: str | None,
    results: list[dict[str, Any]],
    summary_rows: list[dict[str, Any]],
    overall_rows: list[dict[str, Any]],
) -> None:
    scenarios = sorted({result["scenario"] for result in results})
    policies = sorted({result["policy"] for result in results})
    complete_overall_rows = [
        row
        for row in overall_rows
        if row.get("coverage") == row.get("expected_coverage")
    ]
    overall_frontier = primary_frontier(complete_overall_rows)
    scenario_frontiers = {
        scenario: primary_frontier(
            [row for row in summary_rows if row["scenario"] == scenario]
        )
        for scenario in scenarios
    }

    lines = [
        "# Coordination Policy Frontier Benchmark",
        "",
        "## Abstract",
        "",
        (
            "This report expands the two-policy Losangelex/Codex comparison into an all-policy "
            "coordination frontier. It asks which coordination topologies are Pareto-efficient "
            "when success, simulated latency, model calls, token use, and coordination-error "
            "metrics are measured under the same deterministic model-in-the-loop harness."
        ),
        "",
        "## Experiment",
        "",
        (
            f"Model: `{model or '-'}`. Runs: {len(results)}. Scenarios: "
            + ", ".join(f"`{scenario}`" for scenario in scenarios)
            + ". Policies: "
            + ", ".join(f"`{policy}`" for policy in policies)
            + "."
        ),
        "",
        markdown_table(
            ["Policy", "Operationalization"],
            [[policy, POLICY_DESCRIPTIONS.get(policy, "-")] for policy in policies],
        ),
        "",
        "## Overall Policy Summary",
        "",
        markdown_table(
            [
                "Policy",
                "Runs",
                "Coverage",
                "Success",
                "Time",
                "Calls",
                "Tokens",
                "Scope",
                "Idle",
            ],
            report_rows(overall_rows),
        ),
        "",
        "## Overall Pareto Frontier",
        "",
        markdown_table(
            [
                "Policy",
                "Runs",
                "Coverage",
                "Success",
                "Time",
                "Calls",
                "Tokens",
                "Scope",
                "Idle",
            ],
            report_rows(overall_frontier),
        ),
        "",
        "## Scenario Frontiers",
        "",
    ]

    for scenario in scenarios:
        spec = SCENARIOS.get(scenario)
        if spec is not None:
            lines.extend(["### " + scenario, "", spec.broad_goal, ""])
        lines.extend(
            [
                markdown_table(
                    [
                        "Policy",
                        "Runs",
                        "Success",
                        "Time",
                        "Calls",
                        "Tokens",
                        "Scope",
                        "Idle",
                    ],
                    [
                        row[0:2] + row[3:]
                        for row in report_rows(scenario_frontiers[scenario])
                    ],
                ),
                "",
            ]
        )

    lines.extend(
        [
            "## Interpretation",
            "",
            (
                "World-class claims should be frontier claims, not single-winner claims. The "
                "primary frontier first filters to policies with the best observed success rate, "
                "then keeps policies that are not dominated over simulated time, model calls, "
                "tokens, and coordination-error metrics. Deterministic matchers are useful lower "
                "bounds on model cost, but they do not test semantic interpretation. Per-agent "
                "markets test decentralized model judgement but can multiply calls and tokens. "
                "Overall frontiers include only policies with complete scenario-repeat coverage."
            ),
            "",
            "## Reproducibility",
            "",
            "- `combined-results.json`: merged raw records.",
            "- `frontier-summary.csv`: per-scenario policy summaries.",
            "- `frontier-overall.csv`: overall policy summaries.",
            "- `FRONTIER_REPORT.md`: this report.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("results_json", nargs="+", type=pathlib.Path)
    parser.add_argument("--out-dir", type=pathlib.Path, required=True)
    args = parser.parse_args()

    model, results = load_results(args.results_json)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    combined = {
        "model": model,
        "results": results,
        "summary": aggregate(results),
    }
    (args.out_dir / "combined-results.json").write_text(
        json.dumps(combined, indent=2) + "\n",
        encoding="utf-8",
    )

    summary_rows = summarize(results)
    overall_rows = overall_policy_summary(results)
    complete_overall_rows = [
        row
        for row in overall_rows
        if row.get("coverage") == row.get("expected_coverage")
    ]
    analysis = {
        "model": model,
        "summary": summary_rows,
        "overall": overall_rows,
        "overall_frontier": primary_frontier(complete_overall_rows),
        "scenario_frontiers": {
            scenario: primary_frontier(
                [row for row in summary_rows if row["scenario"] == scenario]
            )
            for scenario in sorted({result["scenario"] for result in results})
        },
    }
    (args.out_dir / "frontier-analysis.json").write_text(
        json.dumps(analysis, indent=2) + "\n",
        encoding="utf-8",
    )
    write_summary_csv(args.out_dir / "frontier-summary.csv", summary_rows)
    write_summary_csv(args.out_dir / "frontier-overall.csv", overall_rows)
    write_report(
        args.out_dir / "FRONTIER_REPORT.md",
        model=model,
        results=results,
        summary_rows=summary_rows,
        overall_rows=overall_rows,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
