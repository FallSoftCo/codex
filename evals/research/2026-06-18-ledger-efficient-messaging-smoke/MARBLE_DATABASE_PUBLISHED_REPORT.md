# Published MARBLE Database Agent Comparison: 2026-06-18-ledger-efficient-marble-smoke

This run evaluates the published MARBLE/MultiAgentBench database diagnosis
cases with Codex agent cohorts and Losangelex Hollywood rooms. The runner
keeps root-cause labels and anomaly trigger fields outside the agent
workspace; they are used only after execution for deterministic scoring.

Evidence mode: `native-postgres`

## Summary

| System | Tasks | Full successes | Exact set matches | Avg recall | Avg precision | Avg F1 | Avg seconds | Avg total tokens | Avg uncached+output | Total tokens/success | Coordination errors |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| losangelex | 1 | 1 (100.00%) | 0 (0.00%) | 1.000 | 0.500 | 0.667 | 135.6 | 1,731,339 | 327,179 | 1,731,339 | 0 |

## Tasks

- losangelex `database-001`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'VACUUM'] gold=['INSERT_LARGE_DATA'] seconds=135.6 total_tokens=1,731,339 uncached_plus_output_tokens=327,179 coordination_errors=0
