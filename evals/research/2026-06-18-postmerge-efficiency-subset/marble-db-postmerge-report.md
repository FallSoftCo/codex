# Published MARBLE Database Agent Comparison: 2026-06-18-postmerge-efficiency-marble-db

This run evaluates the published MARBLE/MultiAgentBench database diagnosis
cases with Codex agent cohorts and Losangelex Hollywood rooms. The runner
keeps root-cause labels and anomaly trigger fields outside the agent
workspace; they are used only after execution for deterministic scoring.

Evidence mode: `native-postgres`

## Summary

| System | Tasks | Full successes | Exact set matches | Avg recall | Avg precision | Avg F1 | Avg seconds | Avg total tokens | Avg uncached+output | Total tokens/success | Coordination errors |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| codex-subagents | 2 | 2 (100.00%) | 0 (0.00%) | 1.000 | 0.500 | 0.667 | 203.7 | 1,426,958 | 220,494 | 1,426,958 | 0 |
| losangelex | 2 | 2 (100.00%) | 0 (0.00%) | 1.000 | 0.500 | 0.667 | 169.3 | 2,213,849 | 424,665 | 2,213,849 | 0 |

## Tasks

- codex-subagents `database-001`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'FETCH_LARGE_DATA'] gold=['INSERT_LARGE_DATA'] seconds=219.2 total_tokens=1,486,591 uncached_plus_output_tokens=195,583 coordination_errors=0
- losangelex `database-001`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'FETCH_LARGE_DATA'] gold=['INSERT_LARGE_DATA'] seconds=169.2 total_tokens=2,227,318 uncached_plus_output_tokens=406,902 coordination_errors=0
- codex-subagents `database-032`: success=True recall=1.000 predicted=['REDUNDANT_INDEX', 'INSERT_LARGE_DATA'] gold=['REDUNDANT_INDEX'] seconds=188.2 total_tokens=1,367,324 uncached_plus_output_tokens=245,404 coordination_errors=0
- losangelex `database-032`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'REDUNDANT_INDEX'] gold=['REDUNDANT_INDEX'] seconds=169.4 total_tokens=2,200,380 uncached_plus_output_tokens=442,428 coordination_errors=0
