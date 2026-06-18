# Published SILO-BENCH Agent Comparison: 2026-06-18-ledger-efficient-silo-n5-stratified-current

This run evaluates the same published SILO-BENCH task files with Codex
agent cohorts and Losangelex Hollywood rooms. Each agent received only its
private benchmark shard prompt; the expected answers were used only after
execution for deterministic scoring.

## Summary

| System | Tasks | Full successes | Avg S | Avg P | Avg S_tol | Avg P_tol | Avg seconds | Avg total tokens | Avg uncached+output | Total tokens/success | Coordination errors |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| codex-subagents | 3 | 3 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 159.6 | 840,545 | 136,972 | 840,545 | 0 |
| losangelex-selector | 3 | 3 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 88.3 | 1,109,471 | 205,194 | 1,109,471 | 0 |

## By Level

| Level | System | Tasks | Full successes | Avg S | Avg P | Avg S_tol | Avg P_tol | Avg seconds | Avg total tokens | Avg uncached+output | Total tokens/success | Coordination errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| I | codex-subagents | 1 | 1 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 134.0 | 777,540 | 65,348 | 777,540 | 0 |
| I | losangelex-selector | 1 | 1 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 60.7 | 528,866 | 158,946 | 528,866 | 0 |
| II | codex-subagents | 1 | 1 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 144.5 | 787,390 | 146,878 | 787,390 | 0 |
| II | losangelex-selector | 1 | 1 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 118.4 | 1,559,699 | 222,867 | 1,559,699 | 0 |
| III | codex-subagents | 1 | 1 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 200.3 | 956,705 | 198,689 | 956,705 | 0 |
| III | losangelex-selector | 1 | 1 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 85.9 | 1,239,848 | 233,768 | 1,239,848 | 0 |

## Tasks

- losangelex-selector `I-01_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=60.7 total_tokens=528,866 uncached_plus_output_tokens=158,946 coordination_errors=0
- codex-subagents `I-01_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=134.0 total_tokens=777,540 uncached_plus_output_tokens=65,348 coordination_errors=0
- losangelex-selector `II-11_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=118.4 total_tokens=1,559,699 uncached_plus_output_tokens=222,867 coordination_errors=0
- codex-subagents `II-11_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=144.5 total_tokens=787,390 uncached_plus_output_tokens=146,878 coordination_errors=0
- losangelex-selector `III-21_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=85.9 total_tokens=1,239,848 uncached_plus_output_tokens=233,768 coordination_errors=0
- codex-subagents `III-21_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=200.3 total_tokens=956,705 uncached_plus_output_tokens=198,689 coordination_errors=0
