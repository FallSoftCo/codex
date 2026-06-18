# Published MARBLE Database Agent Comparison: 2026-06-18-ledger-efficient-marble-db-current

This run evaluates the published MARBLE/MultiAgentBench database diagnosis
cases with Codex agent cohorts and Losangelex Hollywood rooms. The runner
keeps root-cause labels and anomaly trigger fields outside the agent
workspace; they are used only after execution for deterministic scoring.

Evidence mode: `native-postgres`

## Summary

| System | Tasks | Full successes | Exact set matches | Avg recall | Avg precision | Avg F1 | Avg seconds | Avg total tokens | Avg uncached+output | Total tokens/success | Coordination errors |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| codex-subagents | 2 | 2 (100.00%) | 0 (0.00%) | 1.000 | 0.500 | 0.667 | 188.8 | 1,353,278 | 248,254 | 1,353,278 | 0 |
| losangelex | 2 | 2 (100.00%) | 0 (0.00%) | 1.000 | 0.500 | 0.667 | 150.8 | 1,924,300 | 387,084 | 1,924,300 | 0 |

## Tasks

- losangelex `database-001`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'VACUUM'] gold=['INSERT_LARGE_DATA'] seconds=168.6 total_tokens=2,001,162 uncached_plus_output_tokens=421,514 coordination_errors=0
- codex-subagents `database-001`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'VACUUM'] gold=['INSERT_LARGE_DATA'] seconds=190.1 total_tokens=1,367,184 uncached_plus_output_tokens=309,264 coordination_errors=0
- losangelex `database-032`: success=True recall=1.000 predicted=['REDUNDANT_INDEX', 'INSERT_LARGE_DATA'] gold=['REDUNDANT_INDEX'] seconds=133.0 total_tokens=1,847,437 uncached_plus_output_tokens=352,653 coordination_errors=0
- codex-subagents `database-032`: success=True recall=1.000 predicted=['REDUNDANT_INDEX', 'INSERT_LARGE_DATA'] gold=['REDUNDANT_INDEX'] seconds=187.5 total_tokens=1,339,372 uncached_plus_output_tokens=187,244 coordination_errors=0
