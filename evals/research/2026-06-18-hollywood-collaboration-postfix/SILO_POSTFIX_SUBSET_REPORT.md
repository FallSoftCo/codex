# Published SILO-BENCH Agent Comparison: silo-postfix-subset-waitfix-2026-06-18-a

This run evaluates the same published SILO-BENCH task files with Codex
agent cohorts and Losangelex Hollywood rooms. Each agent received only its
private benchmark shard prompt; the expected answers were used only after
execution for deterministic scoring.

## Summary

| System | Tasks | Full successes | Avg S | Avg P | Avg S_tol | Avg P_tol | Avg seconds | Avg total tokens | Avg uncached+output | Total tokens/success | Coordination errors |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| codex-subagents | 6 | 6 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 147.2 | 790,865 | 119,739 | 790,865 | 0 |
| losangelex | 6 | 6 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 81.0 | 1,471,166 | 265,257 | 1,471,166 | 0 |

## By Level

| Level | System | Tasks | Full successes | Avg S | Avg P | Avg S_tol | Avg P_tol | Avg seconds | Avg total tokens | Avg uncached+output | Total tokens/success | Coordination errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| I | codex-subagents | 6 | 6 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 147.2 | 790,865 | 119,739 | 790,865 | 0 |
| I | losangelex | 6 | 6 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 81.0 | 1,471,166 | 265,257 | 1,471,166 | 0 |

## Tasks

- codex-subagents `I-01_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=129.1 total_tokens=674,186 uncached_plus_output_tokens=141,706 coordination_errors=0
- losangelex `I-01_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=73.3 total_tokens=1,454,319 uncached_plus_output_tokens=229,231 coordination_errors=0
- codex-subagents `I-02_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=133.0 total_tokens=747,683 uncached_plus_output_tokens=113,699 coordination_errors=0
- losangelex `I-02_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=73.5 total_tokens=1,414,353 uncached_plus_output_tokens=253,393 coordination_errors=0
- codex-subagents `I-03_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=176.6 total_tokens=804,035 uncached_plus_output_tokens=124,227 coordination_errors=0
- losangelex `I-03_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=73.3 total_tokens=1,263,921 uncached_plus_output_tokens=265,137 coordination_errors=0
- codex-subagents `I-04_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=144.0 total_tokens=790,180 uncached_plus_output_tokens=133,412 coordination_errors=0
- losangelex `I-04_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=73.5 total_tokens=1,167,000 uncached_plus_output_tokens=225,688 coordination_errors=0
- codex-subagents `I-05_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=146.1 total_tokens=823,228 uncached_plus_output_tokens=83,644 coordination_errors=0
- losangelex `I-05_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=88.7 total_tokens=1,616,705 uncached_plus_output_tokens=294,465 coordination_errors=0
- codex-subagents `I-06_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=154.3 total_tokens=905,876 uncached_plus_output_tokens=121,748 coordination_errors=0
- losangelex `I-06_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=103.8 total_tokens=1,910,698 uncached_plus_output_tokens=323,626 coordination_errors=0
