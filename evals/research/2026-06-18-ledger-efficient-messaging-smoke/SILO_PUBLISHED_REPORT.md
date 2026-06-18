# Published SILO-BENCH Agent Comparison: 2026-06-18-ledger-efficient-silo-smoke

This run evaluates the same published SILO-BENCH task files with Codex
agent cohorts and Losangelex Hollywood rooms. Each agent received only its
private benchmark shard prompt; the expected answers were used only after
execution for deterministic scoring.

## Summary

| System | Tasks | Full successes | Avg S | Avg P | Avg S_tol | Avg P_tol | Avg seconds | Avg total tokens | Avg uncached+output | Total tokens/success | Coordination errors |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| losangelex-selector | 1 | 1 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 43.9 | 212,600 | 68,856 | 212,600 | 0 |

## By Level

| Level | System | Tasks | Full successes | Avg S | Avg P | Avg S_tol | Avg P_tol | Avg seconds | Avg total tokens | Avg uncached+output | Total tokens/success | Coordination errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| I | losangelex-selector | 1 | 1 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 43.9 | 212,600 | 68,856 | 212,600 | 0 |

## Tasks

- losangelex-selector `I-01_n2.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=43.9 total_tokens=212,600 uncached_plus_output_tokens=68,856 coordination_errors=0
