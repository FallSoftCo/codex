#!/usr/bin/env python3
"""Combine published SILO-BENCH runner outputs into one comparison artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from run_silo_published_agents import aggregate, write_report


def load_records(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    records = data.get("records")
    if not isinstance(records, list):
        raise ValueError(f"{path} does not contain records")
    return data, records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", type=Path, nargs="+")
    parser.add_argument("--campaign-name", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--replace-duplicates",
        action="store_true",
        help=(
            "Replace earlier records with later records that have the same "
            "system, caseId, and taskFile."
        ),
    )
    args = parser.parse_args()

    combined_records: list[dict[str, Any]] = []
    record_keys: list[tuple[Any, Any, Any]] = []
    records_by_key: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    source_results: list[dict[str, Any]] = []
    for path in args.results:
        data, records = load_records(path)
        if args.replace_duplicates:
            for record in records:
                key = (
                    record.get("system"),
                    record.get("caseId"),
                    record.get("taskFile"),
                )
                if key not in records_by_key:
                    record_keys.append(key)
                records_by_key[key] = record
        else:
            combined_records.extend(records)
        source_results.append(
            {
                "path": str(path),
                "campaignName": data.get("campaignName"),
                "systems": data.get("systems"),
                "appServer": data.get("appServer"),
                "hiddenPaths": data.get("hiddenPaths"),
                "defaultHiddenPathsEnabled": data.get("defaultHiddenPathsEnabled"),
                "summary": data.get("summary"),
            }
        )

    if args.replace_duplicates:
        combined_records = [records_by_key[key] for key in record_keys]

    args.out_dir.mkdir(parents=True, exist_ok=True)
    combined = {
        "benchmark": "SILO-BENCH",
        "campaignName": args.campaign_name,
        "sourceResults": source_results,
        "records": combined_records,
        "summary": aggregate(combined_records),
    }
    (args.out_dir / "results.json").write_text(
        json.dumps(combined, indent=2) + "\n",
        encoding="utf-8",
    )
    write_report(
        args.out_dir / "SILO_PUBLISHED_REPORT.md",
        campaign_name=args.campaign_name,
        records=combined_records,
    )
    print(json.dumps(combined["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
