#!/usr/bin/env python3
"""Combine MARBLE database benchmark result files into one report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from benchmark_token_usage import has_token_usage
from benchmark_token_usage import normalize_token_usage
from benchmark_token_usage import sum_token_usage


def load_records(paths: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        campaign = str(data.get("campaignName", path.parent.name))
        for record in data.get("records", []):
            key = (campaign, str(record["system"]), str(record["caseId"]))
            if key in seen:
                continue
            seen.add(key)
            enriched = dict(record)
            enriched["campaignName"] = campaign
            enriched["evidenceMode"] = data.get("evidenceMode")
            records.append(enriched)
    if not records:
        raise ValueError("no records found")
    return records


def aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_system: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_system.setdefault(str(record["system"]), []).append(record)
    systems: dict[str, Any] = {}
    for system, system_records in sorted(by_system.items()):
        count = len(system_records)
        successes = sum(1 for record in system_records if record["score"]["success"])
        exact = sum(1 for record in system_records if record["score"]["exactSetMatch"])
        avg_recall = (
            sum(
                record["score"]["metrics"]["rootCauseRecall"]
                for record in system_records
            )
            / count
        )
        avg_seconds = sum(record["seconds"] for record in system_records) / count
        token_usage_records = [
            normalize_token_usage(record.get("tokenUsage"))
            for record in system_records
            if has_token_usage(record.get("tokenUsage"))
        ]
        token_usage_count = len(token_usage_records)
        total_token_usage = sum_token_usage(token_usage_records)
        systems[system] = {
            "tasks": count,
            "fullSuccesses": successes,
            "fullSuccessRate": successes / count,
            "exactSetMatches": exact,
            "exactSetMatchRate": exact / count,
            "avgRootCauseRecall": avg_recall,
            "avgSeconds": avg_seconds,
            "tokenUsageTaskCount": token_usage_count,
            "totalTokenUsage": total_token_usage,
            "avgTotalTokens": (
                total_token_usage["totalTokens"] / token_usage_count
                if token_usage_count
                else None
            ),
            "avgUncachedPlusOutputTokens": (
                total_token_usage["uncachedPlusOutputTokens"] / token_usage_count
                if token_usage_count
                else None
            ),
            "totalTokensPerFullSuccess": (
                total_token_usage["totalTokens"] / successes if successes else None
            ),
        }
    return {"systems": systems}


def write_report(
    path: Path,
    *,
    title: str,
    records: list[dict[str, Any]],
    notes: list[str],
) -> None:
    summary = aggregate(records)
    lines = [
        f"# {title}",
        "",
        "Combined MARBLE/MultiAgentBench database diagnosis results. Root-cause",
        "labels and anomaly metadata were held out of the agent workspaces and used",
        "only for post-run scoring.",
        "",
        "## Summary",
        "",
        "| System | Tasks | Full successes | Exact set matches | Avg recall | Avg seconds | Avg total tokens | Avg uncached+output | Total tokens/success |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for system, row in summary["systems"].items():
        lines.append(
            f"| {system} | {row['tasks']} | {row['fullSuccesses']} "
            f"({row['fullSuccessRate']:.2%}) | {row['exactSetMatches']} "
            f"({row['exactSetMatchRate']:.2%}) | {row['avgRootCauseRecall']:.3f} | "
            f"{row['avgSeconds']:.1f} | "
            f"{format_token_value(row['avgTotalTokens'])} | "
            f"{format_token_value(row['avgUncachedPlusOutputTokens'])} | "
            f"{format_token_value(row['totalTokensPerFullSuccess'])} |"
        )
    if notes:
        lines.extend(["", "## Notes", ""])
        lines.extend(f"- {note}" for note in notes)
    lines.extend(["", "## Records", ""])
    for record in records:
        metrics = record["score"]["metrics"]
        token_usage = normalize_token_usage(record.get("tokenUsage"))
        lines.append(
            f"- {record['campaignName']} / {record['system']} `{record['caseId']}` "
            f"mode={record.get('evidenceMode')} "
            f"success={record['score']['success']} "
            f"exact={record['score']['exactSetMatch']} "
            f"recall={metrics['rootCauseRecall']:.3f} "
            f"predicted={record['score']['predicted']} "
            f"gold={record['score']['gold']} "
            f"seconds={record['seconds']:.1f} "
            f"total_tokens={format_token_value(token_usage['totalTokens'])} "
            f"uncached_plus_output_tokens={format_token_value(token_usage['uncachedPlusOutputTokens'])}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def format_token_value(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:,.0f}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", nargs="+", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--title", default="Published MARBLE Database Agent Comparison")
    parser.add_argument("--note", action="append", default=[])
    args = parser.parse_args()

    records = load_records(args.results)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "benchmark": "MARBLE/MultiAgentBench database",
        "records": records,
        "summary": aggregate(records),
        "notes": args.note,
    }
    (args.out_dir / "results.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    write_report(
        args.out_dir / "MARBLE_DATABASE_COMBINED_REPORT.md",
        title=args.title,
        records=records,
        notes=args.note,
    )
    print(f"wrote {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
