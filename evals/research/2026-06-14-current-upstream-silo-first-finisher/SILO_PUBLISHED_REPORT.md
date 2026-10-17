# Published SILO-BENCH Agent Comparison: silo-current-upstream-first-finisher-pilot-2026-06-14

This run evaluates the same published SILO-BENCH task files with Codex
agent cohorts and Losangelex Hollywood rooms. Each agent received only its
private benchmark shard prompt; the expected answers were used only after
execution for deterministic scoring.

## Summary

| System | Tasks | Full successes | Avg S | Avg P | Avg S_tol | Avg P_tol | Avg seconds | Avg total tokens | Avg uncached+output | Total tokens/success | Coordination errors |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| codex-subagents | 4 | 4 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 154.3 | 827,710 | 118,558 | 827,710 | 0 |
| losangelex | 4 | 4 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 113.6 | 1,104,493 | 166,893 | 1,104,493 | 0 |
| losangelex-first-finisher | 4 | 4 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 157.9 | 912,785 | 120,209 | 912,785 | 0 |

## By Level

| Level | System | Tasks | Full successes | Avg S | Avg P | Avg S_tol | Avg P_tol | Avg seconds | Avg total tokens | Avg uncached+output | Total tokens/success | Coordination errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| I | codex-subagents | 2 | 2 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 135.7 | 757,554 | 116,530 | 757,554 | 0 |
| I | losangelex | 2 | 2 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 101.8 | 1,029,401 | 157,209 | 1,029,401 | 0 |
| I | losangelex-first-finisher | 2 | 2 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 169.1 | 937,044 | 101,140 | 937,044 | 0 |
| II | codex-subagents | 1 | 1 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 137.4 | 703,554 | 91,074 | 703,554 | 0 |
| II | losangelex | 1 | 1 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 101.2 | 1,181,017 | 147,801 | 1,181,017 | 0 |
| II | losangelex-first-finisher | 1 | 1 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 147.0 | 892,060 | 151,580 | 892,060 | 0 |
| III | codex-subagents | 1 | 1 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 208.4 | 1,092,178 | 150,098 | 1,092,178 | 0 |
| III | losangelex | 1 | 1 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 149.6 | 1,178,152 | 205,352 | 1,178,152 | 0 |
| III | losangelex-first-finisher | 1 | 1 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 146.3 | 884,992 | 126,976 | 884,992 | 0 |

## Tasks

- losangelex `I-01_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=101.8 total_tokens=1,034,182 uncached_plus_output_tokens=175,046 coordination_errors=0
- codex-subagents `I-01_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=145.6 total_tokens=903,224 uncached_plus_output_tokens=148,536 coordination_errors=0
- losangelex-first-finisher `I-01_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=101.7 total_tokens=795,567 uncached_plus_output_tokens=85,935 coordination_errors=0
- losangelex `I-02_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=101.7 total_tokens=1,024,620 uncached_plus_output_tokens=139,372 coordination_errors=0
- losangelex-first-finisher `I-02_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=236.5 total_tokens=1,078,520 uncached_plus_output_tokens=116,344 coordination_errors=0
- losangelex `II-11_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=101.2 total_tokens=1,181,017 uncached_plus_output_tokens=147,801 coordination_errors=0
- losangelex-first-finisher `II-11_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=147.0 total_tokens=892,060 uncached_plus_output_tokens=151,580 coordination_errors=0
- losangelex `III-21_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=149.6 total_tokens=1,178,152 uncached_plus_output_tokens=205,352 coordination_errors=0
- losangelex-first-finisher `III-21_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=146.3 total_tokens=884,992 uncached_plus_output_tokens=126,976 coordination_errors=0
- codex-subagents `I-02_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=125.7 total_tokens=611,884 uncached_plus_output_tokens=84,524 coordination_errors=0
- codex-subagents `II-11_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=137.4 total_tokens=703,554 uncached_plus_output_tokens=91,074 coordination_errors=0
- codex-subagents `III-21_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=208.4 total_tokens=1,092,178 uncached_plus_output_tokens=150,098 coordination_errors=0
