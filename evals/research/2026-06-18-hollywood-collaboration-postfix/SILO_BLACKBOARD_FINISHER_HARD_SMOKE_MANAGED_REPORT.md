# Published SILO-BENCH Agent Comparison: silo-blackboard-finisher-hard-smoke-managed-2026-06-19-a

This run evaluates the same published SILO-BENCH task files with Codex
agent cohorts and Losangelex Hollywood rooms. Each agent received only its
private benchmark shard prompt; the expected answers were used only after
execution for deterministic scoring.

## Summary

| System | Valid tasks | Invalid | Full successes | Avg S | Avg P | Avg S_tol | Avg P_tol | Avg seconds | Avg total tokens | Avg uncached+output | Total tokens/success | Coordination errors | Hollywood messages |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| codex-subagents | 3 | 0 | 2 (66.67%) | 0.667 | 0.790 | 1.000 | 1.000 | 208.3 | 1,200,946 | 147,890 | 1,801,419 | 0 | 0 |
| losangelex-blackboard-finisher | 3 | 0 | 3 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 134.3 | 843,944 | 182,312 | 843,944 | 0 | 18 |

## By Level

| Level | System | Valid tasks | Invalid | Full successes | Avg S | Avg P | Avg S_tol | Avg P_tol | Avg seconds | Avg total tokens | Avg uncached+output | Total tokens/success | Coordination errors | Hollywood messages |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| II | codex-subagents | 3 | 0 | 2 (66.67%) | 0.667 | 0.790 | 1.000 | 1.000 | 208.3 | 1,200,946 | 147,890 | 1,801,419 | 0 | 0 |
| II | losangelex-blackboard-finisher | 3 | 0 | 3 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 134.3 | 843,944 | 182,312 | 843,944 | 0 | 18 |

## Tasks

- codex-subagents `II-12_n5.json`: valid success=False S=0.000 P=0.370 S_tol=1.000 P_tol=1.000 seconds=272.4 total_tokens=1,600,139 uncached_plus_output_tokens=193,931 coordination_errors=0 hollywood_messages=0
- losangelex-blackboard-finisher `II-12_n5.json`: valid success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=147.6 total_tokens=798,675 uncached_plus_output_tokens=187,603 coordination_errors=0 hollywood_messages=6
- codex-subagents `II-14_n5.json`: valid success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=205.8 total_tokens=1,102,082 uncached_plus_output_tokens=120,066 coordination_errors=0 hollywood_messages=0
- losangelex-blackboard-finisher `II-14_n5.json`: valid success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=152.7 total_tokens=963,375 uncached_plus_output_tokens=177,583 coordination_errors=0 hollywood_messages=6
- codex-subagents `II-15_n5.json`: valid success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=146.6 total_tokens=900,617 uncached_plus_output_tokens=129,673 coordination_errors=0 hollywood_messages=0
- losangelex-blackboard-finisher `II-15_n5.json`: valid success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=102.7 total_tokens=769,782 uncached_plus_output_tokens=181,750 coordination_errors=0 hollywood_messages=6
