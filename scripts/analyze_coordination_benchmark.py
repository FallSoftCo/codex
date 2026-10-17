#!/usr/bin/env python3
"""Generate reproducible analysis artifacts for coordination-policy benchmarks."""

from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
import random
import statistics
from collections import defaultdict
from typing import Any

try:
    from benchmark_coordination_policies import POLICY_DESCRIPTIONS, SCENARIOS
except ImportError:
    POLICY_DESCRIPTIONS: dict[str, str] = {}
    SCENARIOS: dict[str, Any] = {}


METRICS = (
    "completion_time",
    "model_calls",
    "model_tokens",
    "idle_ratio",
    "duplicate_attempts",
    "scope_conflicts",
    "invalid_actions",
    "waits_with_work",
)

REFERENCES = (
    (
        "SWE-bench: Can Language Models Resolve Real-World GitHub Issues?",
        "https://arxiv.org/abs/2310.06770",
    ),
    (
        "AgentBench: Evaluating LLMs as Agents",
        "https://arxiv.org/abs/2308.03688",
    ),
    (
        "AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation",
        "https://arxiv.org/abs/2308.08155",
    ),
    (
        "ChatDev: Communicative Agents for Software Development",
        "https://arxiv.org/abs/2307.07924",
    ),
    (
        "SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering",
        "https://arxiv.org/abs/2405.15793",
    ),
    (
        "Agentless: Demystifying LLM-based Software Engineering Agents",
        "https://arxiv.org/abs/2407.01489",
    ),
    (
        "Multi-SWE-bench: A Multilingual Benchmark for Issue Resolving",
        "https://arxiv.org/abs/2504.02605",
    ),
    (
        "MultiAgentBench: Evaluating the Collaboration and Competition of LLM Agents",
        "https://arxiv.org/abs/2503.01935",
    ),
    (
        "Silo-Bench: A Scalable Environment for Evaluating Distributed Coordination in Multi-Agent LLM Systems",
        "https://arxiv.org/abs/2603.01045",
    ),
)


def mean(values: list[float]) -> float | None:
    return statistics.mean(values) if values else None


def bootstrap_ci(
    values: list[float],
    *,
    samples: int = 10_000,
    seed: str,
) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "low": None, "high": None}
    if len(values) == 1:
        value = values[0]
        return {"mean": value, "low": value, "high": value}

    rng = random.Random(seed)
    estimates = []
    for _ in range(samples):
        draw = [values[rng.randrange(len(values))] for _ in values]
        estimates.append(statistics.mean(draw))
    estimates.sort()
    low_idx = math.floor(0.025 * (samples - 1))
    high_idx = math.ceil(0.975 * (samples - 1))
    return {
        "mean": statistics.mean(values),
        "low": estimates[low_idx],
        "high": estimates[high_idx],
    }


def wilson_ci(
    successes: int, total: int, z: float = 1.959963984540054
) -> dict[str, float | None]:
    if total == 0:
        return {"rate": None, "low": None, "high": None}
    phat = successes / total
    denom = 1 + z**2 / total
    center = (phat + z**2 / (2 * total)) / denom
    margin = z * math.sqrt((phat * (1 - phat) + z**2 / (4 * total)) / total) / denom
    return {
        "rate": phat,
        "low": max(0.0, center - margin),
        "high": min(1.0, center + margin),
    }


def exact_two_sided_sign_p(values: list[float]) -> float | None:
    non_zero = [value for value in values if value != 0]
    n = len(non_zero)
    if n == 0:
        return None
    positives = sum(1 for value in non_zero if value > 0)
    extreme = min(positives, n - positives)
    tail = sum(math.comb(n, k) for k in range(extreme + 1)) / 2**n
    return min(1.0, 2 * tail)


def fmt_number(value: float | int | None, digits: int = 2) -> str:
    if value is None:
        return "-"
    if isinstance(value, int):
        return str(value)
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    return f"{value:.{digits}f}"


def fmt_ci(item: dict[str, float | None], *, key: str = "mean", digits: int = 2) -> str:
    center = item.get(key)
    low = item.get("low")
    high = item.get("high")
    if center is None:
        return "-"
    return f"{fmt_number(center, digits)} [{fmt_number(low, digits)}, {fmt_number(high, digits)}]"


def metric_value(run: dict[str, Any], metric: str) -> float | None:
    value = run.get(metric)
    if value is None:
        return None
    return float(value)


def group_results(
    results: list[dict[str, Any]],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for run in results:
        grouped[(run["scenario"], run["policy"])].append(run)
    return dict(grouped)


def summarize_groups(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary = []
    for (scenario, policy), runs in sorted(group_results(results).items()):
        item: dict[str, Any] = {
            "scenario": scenario,
            "policy": policy,
            "runs": len(runs),
            "success": wilson_ci(sum(1 for run in runs if run["success"]), len(runs)),
        }
        for metric in METRICS:
            values = [
                value
                for run in runs
                if (value := metric_value(run, metric)) is not None
            ]
            item[metric] = bootstrap_ci(
                values,
                seed=f"group:{scenario}:{policy}:{metric}",
            )
        summary.append(item)
    return summary


def paired_comparisons(
    results: list[dict[str, Any]],
    *,
    policy_a: str,
    policy_b: str,
) -> list[dict[str, Any]]:
    by_key = {
        (run["scenario"], run["policy"], int(run["repeat"])): run for run in results
    }
    scenarios = sorted({run["scenario"] for run in results})
    rows = []

    for scenario in [*scenarios, "__all__"]:
        if scenario == "__all__":
            repeats = sorted(
                {
                    (run["scenario"], int(run["repeat"]))
                    for run in results
                    if run["policy"] in {policy_a, policy_b}
                }
            )
        else:
            repeats = sorted(
                {
                    (run["scenario"], int(run["repeat"]))
                    for run in results
                    if run["scenario"] == scenario
                    and run["policy"] in {policy_a, policy_b}
                }
            )

        for metric in METRICS:
            diffs = []
            ratios = []
            pairs = 0
            for scenario_id, repeat in repeats:
                a = by_key.get((scenario_id, policy_a, repeat))
                b = by_key.get((scenario_id, policy_b, repeat))
                if a is None or b is None:
                    continue
                a_value = metric_value(a, metric)
                b_value = metric_value(b, metric)
                if a_value is None or b_value is None:
                    continue
                pairs += 1
                diffs.append(b_value - a_value)
                if a_value != 0:
                    ratios.append(b_value / a_value)
            if not diffs:
                continue
            rows.append(
                {
                    "scenario": scenario,
                    "metric": metric,
                    "pairs": pairs,
                    "policy_a": policy_a,
                    "policy_b": policy_b,
                    "mean_a": mean(
                        [
                            metric_value(
                                by_key[(scenario_id, policy_a, repeat)], metric
                            )
                            for scenario_id, repeat in repeats
                            if (scenario_id, policy_a, repeat) in by_key
                            and (scenario_id, policy_b, repeat) in by_key
                            and metric_value(
                                by_key[(scenario_id, policy_a, repeat)], metric
                            )
                            is not None
                            and metric_value(
                                by_key[(scenario_id, policy_b, repeat)], metric
                            )
                            is not None
                        ]
                    ),
                    "mean_b": mean(
                        [
                            metric_value(
                                by_key[(scenario_id, policy_b, repeat)], metric
                            )
                            for scenario_id, repeat in repeats
                            if (scenario_id, policy_a, repeat) in by_key
                            and (scenario_id, policy_b, repeat) in by_key
                            and metric_value(
                                by_key[(scenario_id, policy_a, repeat)], metric
                            )
                            is not None
                            and metric_value(
                                by_key[(scenario_id, policy_b, repeat)], metric
                            )
                            is not None
                        ]
                    ),
                    "diff": bootstrap_ci(
                        diffs,
                        seed=f"diff:{scenario}:{metric}:{policy_a}:{policy_b}",
                    ),
                    "ratio": bootstrap_ci(
                        ratios,
                        seed=f"ratio:{scenario}:{metric}:{policy_a}:{policy_b}",
                    ),
                    "sign_test_p": exact_two_sided_sign_p(diffs),
                }
            )

    return rows


def write_summary_csv(path: pathlib.Path, summary: list[dict[str, Any]]) -> None:
    fieldnames = [
        "scenario",
        "policy",
        "runs",
        "success_rate",
        "success_low",
        "success_high",
    ]
    for metric in METRICS:
        fieldnames.extend([f"{metric}_mean", f"{metric}_low", f"{metric}_high"])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in summary:
            row: dict[str, Any] = {
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


def write_paired_csv(path: pathlib.Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "scenario",
        "metric",
        "pairs",
        "policy_a",
        "policy_b",
        "mean_a",
        "mean_b",
        "diff_mean",
        "diff_low",
        "diff_high",
        "ratio_mean",
        "ratio_low",
        "ratio_high",
        "sign_test_p",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in rows:
            writer.writerow(
                {
                    "scenario": item["scenario"],
                    "metric": item["metric"],
                    "pairs": item["pairs"],
                    "policy_a": item["policy_a"],
                    "policy_b": item["policy_b"],
                    "mean_a": item["mean_a"],
                    "mean_b": item["mean_b"],
                    "diff_mean": item["diff"]["mean"],
                    "diff_low": item["diff"]["low"],
                    "diff_high": item["diff"]["high"],
                    "ratio_mean": item["ratio"]["mean"],
                    "ratio_low": item["ratio"]["low"],
                    "ratio_high": item["ratio"]["high"],
                    "sign_test_p": item["sign_test_p"],
                }
            )


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    output = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    output.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(output)


def shorten(text: str, limit: int = 120) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def write_report(
    path: pathlib.Path,
    *,
    payload: dict[str, Any],
    summary: list[dict[str, Any]],
    paired: list[dict[str, Any]],
    policy_a: str,
    policy_b: str,
    run_notes: list[str],
    run_command: str | None,
) -> None:
    results = payload["results"]
    scenarios = sorted({run["scenario"] for run in results})
    policies = sorted({run["policy"] for run in results})
    total_runs = len(results)
    scenario_label = "scenario" if len(scenarios) == 1 else "scenarios"
    policy_label = "policy" if len(policies) == 1 else "policies"
    complete_pairs = next(
        (
            item["pairs"]
            for item in paired
            if item["scenario"] == "__all__" and item["metric"] == "model_tokens"
        ),
        0,
    )

    group_rows = []
    for item in summary:
        group_rows.append(
            [
                item["scenario"],
                item["policy"],
                str(item["runs"]),
                fmt_ci(item["success"], key="rate"),
                fmt_ci(item["completion_time"]),
                fmt_ci(item["model_calls"]),
                fmt_ci(item["model_tokens"], digits=0),
                fmt_ci(item["scope_conflicts"]),
                fmt_ci(item["idle_ratio"]),
            ]
        )

    paired_focus = [
        item
        for item in paired
        if item["scenario"] == "__all__"
        and item["metric"]
        in {
            "completion_time",
            "model_calls",
            "model_tokens",
            "scope_conflicts",
            "idle_ratio",
        }
    ]
    paired_rows = []
    for item in paired_focus:
        paired_rows.append(
            [
                item["metric"],
                str(item["pairs"]),
                fmt_number(item["mean_a"]),
                fmt_number(item["mean_b"]),
                fmt_ci(item["diff"]),
                fmt_ci(item["ratio"]),
                fmt_number(item["sign_test_p"], digits=4),
            ]
        )

    scenario_rows = []
    for item in paired:
        if item["scenario"] == "__all__" or item["metric"] != "model_tokens":
            continue
        scenario_rows.append(
            [
                item["scenario"],
                str(item["pairs"]),
                fmt_number(item["mean_a"], digits=0),
                fmt_number(item["mean_b"], digits=0),
                fmt_ci(item["diff"], digits=0),
                fmt_ci(item["ratio"]),
            ]
        )

    design_scenario_rows = []
    for scenario in scenarios:
        spec = SCENARIOS.get(scenario)
        if spec is None:
            design_scenario_rows.append([scenario, "-", "-", "-", "-"])
            continue
        design_scenario_rows.append(
            [
                scenario,
                shorten(spec.broad_goal),
                str(len(spec.agents)),
                str(len(spec.probes)),
                str(len(spec.tasks)),
            ]
        )

    policy_rows = []
    for policy in policies:
        policy_rows.append(
            [
                policy,
                shorten(POLICY_DESCRIPTIONS.get(policy, "-"), limit=160),
            ]
        )

    reproducibility_lines = [
        "Artifacts generated from the raw benchmark JSON:",
        "",
        "- `results.json`: raw run records and harness summary.",
        "- `analysis.json`: bootstrap intervals and paired comparisons.",
        "- `summary.csv`: per-scenario policy aggregates.",
        "- `paired_differences.csv`: paired metric deltas and ratios.",
    ]
    if run_command is not None:
        reproducibility_lines.extend(
            [
                "",
                "Run command:",
                "",
                f"```sh\n{run_command}\n```",
            ]
        )
    if run_notes:
        reproducibility_lines.extend(["", "Run notes:", ""])
        reproducibility_lines.extend(f"- {note}" for note in run_notes)

    reference_lines = [f"- {title} {url}" for title, url in REFERENCES]

    lines = [
        "# Losangelex vs Codex Subagent Coordination Benchmark",
        "",
        "## Abstract",
        "",
        (
            "This study compares a Losangelex-style hybrid coordination policy against an "
            "independent Codex-subagent market baseline in a deterministic model-in-the-loop "
            "benchmark. The model remains inside the decision loop through `codex exec`, while "
            "task availability, durations, dependencies, and scoring are fixed by the harness. "
            f"The dataset contains {total_runs} runs across {len(scenarios)} {scenario_label} and "
            f"{len(policies)} {policy_label}, with {complete_pairs} paired scenario-repeat comparisons "
            f"between `{policy_a}` and `{policy_b}`."
        ),
        "",
        "## Experimental Design",
        "",
        (
            f"Model: `{payload.get('model', '-')}`. Policies: "
            + ", ".join(f"`{policy}`" for policy in policies)
            + ". Scenarios: "
            + ", ".join(f"`{scenario}`" for scenario in scenarios)
            + "."
        ),
        "",
        markdown_table(
            ["Scenario", "Broad Goal", "Agents", "Probes", "Tasks"],
            design_scenario_rows,
        ),
        "",
        markdown_table(["Policy", "Operationalization"], policy_rows),
        "",
        (
            "Each scenario begins with broad, ambiguous work, hidden probes, worker capabilities, "
            "task dependencies, scope groups, and deterministic durations. The benchmark asks the "
            "model to decide assignments, then the harness deterministically executes only valid "
            "assignments. This separates semantic coordination from execution noise."
        ),
        "",
        (
            f"`{policy_a}` is treated as the Losangelex-style policy. `{policy_b}` is treated as "
            "the Codex-subagent baseline: each idle worker produces its own bids, and the backend "
            "resolves conflicts after the fact."
        ),
        "",
        "## Protocol Controls",
        "",
        (
            "The experiment is paired by scenario and repeat number, so policy comparisons use "
            "matched hidden-task order, worker roster, task graph, and deterministic execution "
            "rules. The only stochastic surface intentionally left inside the loop is the model's "
            "coordination decision."
        ),
        "",
        (
            "The harness records every simulated action, rejected action, duplicate attempt, scope "
            "conflict, wait-with-work event, completion time, and token count. Output JSON is "
            "written atomically after every run so interrupted experiments can be audited and "
            "resumed without overwriting prior evidence."
        ),
        "",
        "## Related Work",
        "",
        (
            "The study is closest to model-in-the-loop agent benchmarks such as AgentBench "
            "(arXiv:2308.03688), multi-agent software-development systems such as ChatDev "
            "(arXiv:2307.07924) and AutoGen (arXiv:2308.08155), and coding-agent evaluations "
            "such as SWE-bench (arXiv:2310.06770), SWE-agent (arXiv:2405.15793), Agentless "
            "(arXiv:2407.01489), and Multi-SWE-bench (arXiv:2504.02605). It also relates to "
            "multi-agent collaboration and coordination benchmarks such as MultiAgentBench "
            "(arXiv:2503.01935) and Silo-Bench (arXiv:2603.01045). The distinguishing focus here "
            "is not final patch correctness, but coordination policy efficiency under paired "
            "hidden-task discovery and worker-allocation decisions."
        ),
        "",
        "## Metrics",
        "",
        (
            "Primary outcomes are success, simulated completion time, model calls, model tokens, "
            "idle-with-work ratio, duplicate target picks, scope conflicts, invalid actions, and "
            "waits despite eligible work. Confidence intervals are nonparametric bootstrap 95% "
            "intervals for means and Wilson 95% intervals for success rates. Paired rows compare "
            f"`{policy_b}` minus `{policy_a}` on matched scenario-repeat keys; positive deltas mean "
            f"`{policy_b}` is larger."
        ),
        "",
        "## Group Results",
        "",
        markdown_table(
            [
                "Scenario",
                "Policy",
                "Runs",
                "Success",
                "Time",
                "Calls",
                "Tokens",
                "Scope",
                "Idle Ratio",
            ],
            group_rows,
        ),
        "",
        "## Paired Overall Effects",
        "",
        markdown_table(
            [
                "Metric",
                "Pairs",
                f"Mean {policy_a}",
                f"Mean {policy_b}",
                f"{policy_b} - {policy_a}",
                f"{policy_b} / {policy_a}",
                "Sign p",
            ],
            paired_rows,
        ),
        "",
        "## Token Overhead By Scenario",
        "",
        markdown_table(
            [
                "Scenario",
                "Pairs",
                f"Mean {policy_a}",
                f"Mean {policy_b}",
                "Token Delta",
                "Token Ratio",
            ],
            scenario_rows,
        ),
        "",
        "## Interpretation",
        "",
        (
            "The comparison is strongest for model-call and token-efficiency claims because both "
            "policies solve the same fixed task graph and are paired by scenario and repeat. Claims "
            "about real-world delivery speed should be phrased as simulated coordination latency, "
            "not wall-clock developer throughput."
        ),
        "",
        "## Conclusion",
        "",
        (
            "Within this benchmark, the primary claim should be stated as a controlled coordination "
            "result: for the same model and deterministic work graph, the policies differ in how "
            "many model decisions and tokens they require to converge. Treat the outcome as evidence "
            "about coordination mechanisms, not as a universal ranking of all Losangelex and Codex "
            "agent deployments."
        ),
        "",
        "## Threats To Validity",
        "",
        (
            "The benchmark uses synthetic but repository-motivated scenarios rather than live "
            "shared-state rooms. Execution is deterministic, so it does not measure patch quality, "
            "review negotiation, or live tool failures. The tested model and prompt surface are "
            "part of the treatment; different models, context windows, or worker instructions may "
            "change the absolute rates. A broader paper should add more frozen real-world fixtures "
            "before making general claims beyond these coordination patterns."
        ),
        "",
        "## Reproducibility",
        "",
        *reproducibility_lines,
        "",
        "## References",
        "",
        *reference_lines,
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("results_json", type=pathlib.Path)
    parser.add_argument("--out-dir", type=pathlib.Path)
    parser.add_argument("--policy-a", default="hybrid")
    parser.add_argument("--policy-b", default="independent_market")
    parser.add_argument("--run-command")
    parser.add_argument(
        "--run-note",
        action="append",
        default=[],
        help="Protocol note to include in the generated report. May be repeated.",
    )
    args = parser.parse_args()

    payload = json.loads(args.results_json.read_text(encoding="utf-8"))
    results = payload["results"]
    out_dir = args.out_dir or args.results_json.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = summarize_groups(results)
    paired = paired_comparisons(results, policy_a=args.policy_a, policy_b=args.policy_b)
    analysis = {
        "model": payload.get("model"),
        "policy_a": args.policy_a,
        "policy_b": args.policy_b,
        "summary": summary,
        "paired": paired,
    }

    (out_dir / "analysis.json").write_text(
        json.dumps(analysis, indent=2) + "\n",
        encoding="utf-8",
    )
    write_summary_csv(out_dir / "summary.csv", summary)
    write_paired_csv(out_dir / "paired_differences.csv", paired)
    write_report(
        out_dir / "REPORT.md",
        payload=payload,
        summary=summary,
        paired=paired,
        policy_a=args.policy_a,
        policy_b=args.policy_b,
        run_notes=args.run_note,
        run_command=args.run_command,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
