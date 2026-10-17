# Published SILO-BENCH Agent Comparison: silo-postfix-prior-failures-n10-2026-06-18-a

This run evaluates the same published SILO-BENCH task files with Codex
agent cohorts and Losangelex Hollywood rooms. Each agent received only its
private benchmark shard prompt; the expected answers were used only after
execution for deterministic scoring.

## Summary

| System | Valid tasks | Invalid | Full successes | Avg S | Avg P | Avg S_tol | Avg P_tol | Avg seconds | Avg total tokens | Avg uncached+output | Total tokens/success | Coordination errors |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| codex-subagents | 3 | 0 | 2 (66.67%) | 0.667 | 0.804 | 1.000 | 1.000 | 467.6 | 1,715,535 | 273,828 | 2,573,302 | 0 |
| losangelex | 3 | 0 | 0 (0.00%) | 0.300 | 0.467 | 0.633 | 0.663 | 175.5 | 6,876,753 | 1,044,902 | n/a | 0 |

## By Level

| Level | System | Valid tasks | Invalid | Full successes | Avg S | Avg P | Avg S_tol | Avg P_tol | Avg seconds | Avg total tokens | Avg uncached+output | Total tokens/success | Coordination errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| II | codex-subagents | 3 | 0 | 2 (66.67%) | 0.667 | 0.804 | 1.000 | 1.000 | 467.6 | 1,715,535 | 273,828 | 2,573,302 | 0 |
| II | losangelex | 3 | 0 | 0 (0.00%) | 0.300 | 0.467 | 0.633 | 0.663 | 175.5 | 6,876,753 | 1,044,902 | n/a | 0 |

## Tasks

- codex-subagents `II-12_n10.json`: valid success=False S=0.000 P=0.412 S_tol=1.000 P_tol=1.000 seconds=853.5 total_tokens=1,606,179 uncached_plus_output_tokens=353,699 coordination_errors=0
- losangelex `II-12_n10.json`: valid success=False S=0.000 P=0.412 S_tol=1.000 P_tol=1.000 seconds=159.2 total_tokens=5,576,897 uncached_plus_output_tokens=904,513 coordination_errors=0
- codex-subagents `II-14_n10.json`: valid success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=309.2 total_tokens=1,924,351 uncached_plus_output_tokens=299,391 coordination_errors=0
- losangelex `II-14_n10.json`: valid success=False S=0.900 P=0.990 S_tol=0.900 P_tol=0.990 seconds=144.1 total_tokens=5,280,327 uncached_plus_output_tokens=898,247 coordination_errors=0
- codex-subagents `II-15_n10.json`: valid success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=240.2 total_tokens=1,616,074 uncached_plus_output_tokens=168,394 coordination_errors=0
- losangelex `II-15_n10.json`: valid success=False S=0.000 P=0.000 S_tol=0.000 P_tol=0.000 seconds=223.3 total_tokens=9,773,034 uncached_plus_output_tokens=1,331,946 coordination_errors=0
