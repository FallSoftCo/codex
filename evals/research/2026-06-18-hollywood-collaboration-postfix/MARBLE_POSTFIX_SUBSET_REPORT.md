# Published MARBLE Database Agent Comparison: marble-postfix-subset-2026-06-18-a

This run evaluates the published MARBLE/MultiAgentBench database diagnosis
cases with Codex agent cohorts and Losangelex Hollywood rooms. The runner
keeps root-cause labels and anomaly trigger fields outside the agent
workspace; they are used only after execution for deterministic scoring.

Evidence mode: `native-postgres`

## Summary

| System | Tasks | Full successes | Exact set matches | Avg recall | Avg precision | Avg F1 | Avg seconds | Avg total tokens | Avg uncached+output | Total tokens/success | Coordination errors |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| codex-subagents | 6 | 6 (100.00%) | 0 (0.00%) | 1.000 | 0.500 | 0.667 | 198.3 | 1,347,910 | 198,790 | 1,347,910 | 0 |
| losangelex | 6 | 6 (100.00%) | 0 (0.00%) | 1.000 | 0.500 | 0.667 | 170.9 | 2,468,825 | 447,705 | 2,468,825 | 0 |

## Tasks

- codex-subagents `database-001`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'VACUUM'] gold=['INSERT_LARGE_DATA'] seconds=231.1 total_tokens=1,336,693 uncached_plus_output_tokens=208,117 coordination_errors=0
- losangelex `database-001`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'VACUUM'] gold=['INSERT_LARGE_DATA'] seconds=153.5 total_tokens=1,903,205 uncached_plus_output_tokens=351,333 coordination_errors=0
- codex-subagents `database-002`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'FETCH_LARGE_DATA'] gold=['INSERT_LARGE_DATA'] seconds=203.0 total_tokens=1,386,933 uncached_plus_output_tokens=201,141 coordination_errors=0
- losangelex `database-002`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'VACUUM'] gold=['INSERT_LARGE_DATA'] seconds=154.1 total_tokens=2,110,668 uncached_plus_output_tokens=327,500 coordination_errors=0
- codex-subagents `database-003`: success=True recall=1.000 predicted=['REDUNDANT_INDEX', 'INSERT_LARGE_DATA'] gold=['REDUNDANT_INDEX'] seconds=193.4 total_tokens=1,461,381 uncached_plus_output_tokens=179,845 coordination_errors=0
- losangelex `database-003`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'REDUNDANT_INDEX'] gold=['REDUNDANT_INDEX'] seconds=200.1 total_tokens=3,031,228 uncached_plus_output_tokens=617,788 coordination_errors=0
- codex-subagents `database-004`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'FETCH_LARGE_DATA'] gold=['INSERT_LARGE_DATA'] seconds=204.1 total_tokens=1,265,121 uncached_plus_output_tokens=194,273 coordination_errors=0
- losangelex `database-004`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'VACUUM'] gold=['INSERT_LARGE_DATA'] seconds=154.4 total_tokens=2,248,163 uncached_plus_output_tokens=412,387 coordination_errors=0
- codex-subagents `database-005`: success=True recall=1.000 predicted=['LOCK_CONTENTION', 'INSERT_LARGE_DATA'] gold=['LOCK_CONTENTION'] seconds=172.7 total_tokens=1,338,242 uncached_plus_output_tokens=200,578 coordination_errors=0
- losangelex `database-005`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'LOCK_CONTENTION'] gold=['LOCK_CONTENTION'] seconds=202.5 total_tokens=3,682,080 uncached_plus_output_tokens=632,608 coordination_errors=0
- codex-subagents `database-006`: success=True recall=1.000 predicted=['VACUUM', 'INSERT_LARGE_DATA'] gold=['VACUUM'] seconds=185.4 total_tokens=1,299,090 uncached_plus_output_tokens=208,786 coordination_errors=0
- losangelex `database-006`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'VACUUM'] gold=['VACUUM'] seconds=160.7 total_tokens=1,837,607 uncached_plus_output_tokens=344,615 coordination_errors=0
