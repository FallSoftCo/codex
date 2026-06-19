#!/usr/bin/env python3
"""Classify SILO-BENCH correctness failures in runner result artifacts."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from run_silo_published_agents import _numeric_values_close
from run_silo_published_agents import record_valid


def load_records(paths: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        loaded = data.get("records")
        if not isinstance(loaded, list):
            raise ValueError(f"{path} does not contain a records array")
        records.extend(loaded)
    return records


def coordination_tool_call_count(record: dict[str, Any]) -> int:
    summary = record.get("coordinationToolSummary", {})
    if not isinstance(summary, dict):
        return 0
    tool_calls = summary.get("toolCalls", {})
    if not isinstance(tool_calls, dict):
        return 0
    total = tool_calls.get("total", 0)
    return int(total) if isinstance(total, (int, float)) else 0


def hollywood_message_count(record: dict[str, Any]) -> int:
    summary = record.get("hollywoodMessageSummary", {})
    if not isinstance(summary, dict):
        return 0
    total = summary.get("total", 0)
    return int(total) if isinstance(total, (int, float)) else 0


def classify_record(record: dict[str, Any]) -> dict[str, Any]:
    score = record.get("score", {})
    metrics = score.get("metrics", {})
    submissions = score.get("submissions", [])
    wrong = []
    missing = 0
    parse_errors = 0
    tolerance_correct = 0
    for submission in submissions if isinstance(submissions, list) else []:
        if submission.get("correct"):
            continue
        wrong.append(submission)
        if not submission.get("exists"):
            missing += 1
        if submission.get("parse_error"):
            parse_errors += 1
        if _numeric_values_close(submission.get("answer"), submission.get("expected")):
            tolerance_correct += 1

    wrong_count = len(wrong)
    success_rate = float(metrics.get("S_success_rate", 0.0))
    partial = float(metrics.get("P_partial_correctness", 0.0))
    tolerance_success = float(
        metrics.get("S_numeric_tolerance_success_rate", success_rate)
    )
    tolerance_partial = float(
        metrics.get("P_numeric_tolerance_partial_correctness", partial)
    )

    if not record_valid(record):
        classification = "invalid-attempt"
    elif wrong_count == 0 and score.get("success"):
        classification = "full-success"
    elif missing or parse_errors:
        classification = "missing-or-invalid-submission"
    elif wrong_count and tolerance_correct == wrong_count:
        classification = "strict-formatting"
    elif tolerance_success == 1.0 and tolerance_partial == 1.0:
        classification = "strict-formatting"
    elif success_rate >= 0.8 or partial >= 0.8:
        classification = "peer-outlier"
    elif success_rate == 0.0 and partial <= 0.2 and tolerance_partial <= 0.2:
        classification = "global-computation"
    else:
        classification = "mixed"

    return {
        "classification": classification,
        "wrongCount": wrong_count,
        "missingCount": missing,
        "parseErrorCount": parse_errors,
        "toleranceCorrectWrongCount": tolerance_correct,
        "coordinationToolCalls": coordination_tool_call_count(record),
        "hollywoodMessages": hollywood_message_count(record),
    }


def format_float(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.3f}"
    return "n/a"


def format_int(value: Any) -> str:
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.0f}"
    return "n/a"


def write_report(
    path: Path,
    *,
    records: list[dict[str, Any]],
    title: str,
) -> None:
    analyzed = [(record, classify_record(record)) for record in records]
    by_system: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for item in analyzed:
        by_system.setdefault(str(item[0].get("system", "unknown")), []).append(item)

    lines = [
        f"# {title}",
        "",
        "This report classifies SILO correctness failures by observed submission",
        "shape. It distinguishes strict exact-output mismatches from peer outliers",
        "and true global-computation failures.",
        "",
        "## Summary",
        "",
        "| System | Records | Valid | Full successes | Avg S | Avg P | Avg S_tol | Avg P_tol | Strict formatting | Peer outlier | Global computation | Missing/invalid | Tool calls | Hollywood messages |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for system, items in sorted(by_system.items()):
        valid_items = [item for item in items if record_valid(item[0])]
        classifications = Counter(item[1]["classification"] for item in items)
        valid_count = len(valid_items)
        successes = sum(1 for record, _ in valid_items if record["score"]["success"])
        tool_calls = sum(item[1]["coordinationToolCalls"] for item in valid_items)
        hollywood_messages = sum(item[1]["hollywoodMessages"] for item in valid_items)
        if valid_count:
            avg_s = sum(
                record["score"]["metrics"]["S_success_rate"]
                for record, _ in valid_items
            ) / valid_count
            avg_p = sum(
                record["score"]["metrics"]["P_partial_correctness"]
                for record, _ in valid_items
            ) / valid_count
            avg_s_tol = sum(
                record["score"]["metrics"].get(
                    "S_numeric_tolerance_success_rate",
                    record["score"]["metrics"]["S_success_rate"],
                )
                for record, _ in valid_items
            ) / valid_count
            avg_p_tol = sum(
                record["score"]["metrics"].get(
                    "P_numeric_tolerance_partial_correctness",
                    record["score"]["metrics"]["P_partial_correctness"],
                )
                for record, _ in valid_items
            ) / valid_count
        else:
            avg_s = avg_p = avg_s_tol = avg_p_tol = None
        lines.append(
            f"| {system} | {len(items)} | {valid_count} | {successes} | "
            f"{format_float(avg_s)} | {format_float(avg_p)} | "
            f"{format_float(avg_s_tol)} | {format_float(avg_p_tol)} | "
            f"{classifications['strict-formatting']} | "
            f"{classifications['peer-outlier']} | "
            f"{classifications['global-computation']} | "
            f"{classifications['missing-or-invalid-submission']} | "
            f"{format_int(tool_calls)} | {format_int(hollywood_messages)} |"
        )

    lines.extend(
        [
            "",
            "## Records",
            "",
            "| System | Task | Classification | Success | S | P | S_tol | P_tol | Wrong | Tol-correct wrong | Tool calls | Hollywood messages | Seconds |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for record, details in analyzed:
        metrics = record.get("score", {}).get("metrics", {})
        lines.append(
            f"| {record.get('system', 'unknown')} | `{record.get('taskFile', 'unknown')}` | "
            f"{details['classification']} | {record.get('score', {}).get('success')} | "
            f"{format_float(metrics.get('S_success_rate'))} | "
            f"{format_float(metrics.get('P_partial_correctness'))} | "
            f"{format_float(metrics.get('S_numeric_tolerance_success_rate'))} | "
            f"{format_float(metrics.get('P_numeric_tolerance_partial_correctness'))} | "
            f"{details['wrongCount']} | {details['toleranceCorrectWrongCount']} | "
            f"{details['coordinationToolCalls']} | {details['hollywoodMessages']} | "
            f"{format_float(record.get('seconds'))} |"
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", type=Path, nargs="+")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--title", default="SILO Correctness Failure Analysis")
    parser.add_argument("--system", action="append", dest="systems", default=[])
    args = parser.parse_args()

    records = load_records(args.results)
    if args.systems:
        wanted = set(args.systems)
        records = [record for record in records if record.get("system") in wanted]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_report(args.out, records=records, title=args.title)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
