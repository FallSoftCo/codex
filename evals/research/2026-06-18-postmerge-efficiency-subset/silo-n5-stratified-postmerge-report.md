# Published SILO-BENCH Agent Comparison: 2026-06-18-postmerge-efficiency-silo-n5-stratified

This run evaluates the same published SILO-BENCH task files with Codex
agent cohorts and Losangelex Hollywood rooms. Each agent received only its
private benchmark shard prompt; the expected answers were used only after
execution for deterministic scoring.

## Summary

| System | Tasks | Full successes | Avg S | Avg P | Avg S_tol | Avg P_tol | Avg seconds | Avg total tokens | Avg uncached+output | Total tokens/success | Coordination errors |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| codex-subagents | 3 | 3 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 157.6 | 908,818 | 176,360 | 908,818 | 0 |
| losangelex-selector | 3 | 3 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 112.8 | 1,449,053 | 227,037 | 1,449,053 | 0 |

## By Level

| Level | System | Tasks | Full successes | Avg S | Avg P | Avg S_tol | Avg P_tol | Avg seconds | Avg total tokens | Avg uncached+output | Total tokens/success | Coordination errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| I | codex-subagents | 1 | 1 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 128.9 | 770,144 | 192,864 | 770,144 | 0 |
| I | losangelex-selector | 1 | 1 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 72.6 | 446,859 | 131,339 | 446,859 | 0 |
| II | codex-subagents | 1 | 1 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 143.2 | 756,985 | 250,233 | 756,985 | 0 |
| II | losangelex-selector | 1 | 1 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 132.9 | 2,208,661 | 335,637 | 2,208,661 | 0 |
| III | codex-subagents | 1 | 1 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 200.7 | 1,199,326 | 85,982 | 1,199,326 | 0 |
| III | losangelex-selector | 1 | 1 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 132.8 | 1,691,639 | 214,135 | 1,691,639 | 0 |

## Tasks

- codex-subagents `I-01_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=128.9 total_tokens=770,144 uncached_plus_output_tokens=192,864 coordination_errors=0
- losangelex-selector `I-01_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=72.6 total_tokens=446,859 uncached_plus_output_tokens=131,339 coordination_errors=0
- codex-subagents `II-11_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=143.2 total_tokens=756,985 uncached_plus_output_tokens=250,233 coordination_errors=0
- losangelex-selector `II-11_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=132.9 total_tokens=2,208,661 uncached_plus_output_tokens=335,637 coordination_errors=0
- codex-subagents `III-21_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=200.7 total_tokens=1,199,326 uncached_plus_output_tokens=85,982 coordination_errors=0
- losangelex-selector `III-21_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=132.8 total_tokens=1,691,639 uncached_plus_output_tokens=214,135 coordination_errors=0
