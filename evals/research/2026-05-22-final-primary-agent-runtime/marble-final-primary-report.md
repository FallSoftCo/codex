# Published MARBLE Database Agent Comparison: marble-native-final-primary-all-systems-2026-05-22

This run evaluates the published MARBLE/MultiAgentBench database diagnosis
cases with Codex agent cohorts and Losangelex Hollywood rooms. The runner
keeps root-cause labels and anomaly trigger fields outside the agent
workspace; they are used only after execution for deterministic scoring.

Evidence mode: `native-postgres`

## Summary

| System | Tasks | Full successes | Exact set matches | Avg recall | Avg precision | Avg F1 | Avg seconds | Coordination errors |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| codex | 30 | 30 (100.00%) | 0 (0.00%) | 1.000 | 0.583 | 0.733 | 393.7 | 0 |
| codex-subagents | 30 | 29 (96.67%) | 2 (6.67%) | 0.983 | 0.617 | 0.742 | 184.0 | 25 |
| losangelex | 30 | 30 (100.00%) | 1 (3.33%) | 1.000 | 0.594 | 0.740 | 160.2 | 0 |

## Tasks

- codex `database-010`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'FETCH_LARGE_DATA'] gold=['INSERT_LARGE_DATA'] seconds=365.7 coordination_errors=0
- codex-subagents `database-010`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'VACUUM'] gold=['INSERT_LARGE_DATA'] seconds=200.3 coordination_errors=1
- losangelex `database-010`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'VACUUM'] gold=['INSERT_LARGE_DATA'] seconds=146.7 coordination_errors=0
- codex `database-016`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'LOCK_CONTENTION'] gold=['LOCK_CONTENTION'] seconds=376.4 coordination_errors=0
- codex-subagents `database-016`: success=True recall=1.000 predicted=['LOCK_CONTENTION', 'INSERT_LARGE_DATA'] gold=['LOCK_CONTENTION'] seconds=218.3 coordination_errors=0
- losangelex `database-016`: success=True recall=1.000 predicted=['LOCK_CONTENTION', 'INSERT_LARGE_DATA'] gold=['LOCK_CONTENTION'] seconds=193.7 coordination_errors=0
- codex `database-017`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'VACUUM'] gold=['INSERT_LARGE_DATA'] seconds=399.4 coordination_errors=0
- codex-subagents `database-017`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'FETCH_LARGE_DATA'] gold=['INSERT_LARGE_DATA'] seconds=165.6 coordination_errors=0
- losangelex `database-017`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'FETCH_LARGE_DATA'] gold=['INSERT_LARGE_DATA'] seconds=146.6 coordination_errors=0
- codex `database-018`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'LOCK_CONTENTION'] gold=['LOCK_CONTENTION'] seconds=493.6 coordination_errors=0
- codex-subagents `database-018`: success=True recall=1.000 predicted=['LOCK_CONTENTION', 'INSERT_LARGE_DATA'] gold=['LOCK_CONTENTION'] seconds=181.8 coordination_errors=0
- losangelex `database-018`: success=True recall=1.000 predicted=['LOCK_CONTENTION', 'INSERT_LARGE_DATA'] gold=['LOCK_CONTENTION'] seconds=148.6 coordination_errors=0
- codex `database-023`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'VACUUM'] gold=['INSERT_LARGE_DATA'] seconds=359.0 coordination_errors=0
- codex-subagents `database-023`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'FETCH_LARGE_DATA'] gold=['INSERT_LARGE_DATA'] seconds=159.7 coordination_errors=0
- losangelex `database-023`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'FETCH_LARGE_DATA'] gold=['INSERT_LARGE_DATA'] seconds=146.6 coordination_errors=0
- codex `database-024`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'VACUUM'] gold=['VACUUM'] seconds=346.0 coordination_errors=0
- codex-subagents `database-024`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'VACUUM'] gold=['VACUUM'] seconds=225.5 coordination_errors=0
- losangelex `database-024`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'VACUUM'] gold=['VACUUM'] seconds=192.2 coordination_errors=0
- codex `database-025`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'VACUUM'] gold=['VACUUM'] seconds=356.8 coordination_errors=0
- codex-subagents `database-025`: success=True recall=1.000 predicted=['VACUUM', 'INSERT_LARGE_DATA'] gold=['VACUUM'] seconds=170.9 coordination_errors=0
- losangelex `database-025`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'VACUUM'] gold=['VACUUM'] seconds=191.9 coordination_errors=0
- codex `database-027`: success=True recall=1.000 predicted=['LOCK_CONTENTION', 'INSERT_LARGE_DATA'] gold=['LOCK_CONTENTION'] seconds=441.1 coordination_errors=0
- codex-subagents `database-027`: success=True recall=1.000 predicted=['LOCK_CONTENTION', 'INSERT_LARGE_DATA'] gold=['LOCK_CONTENTION'] seconds=204.6 coordination_errors=0
- losangelex `database-027`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'LOCK_CONTENTION'] gold=['LOCK_CONTENTION'] seconds=148.8 coordination_errors=0
- codex `database-031`: success=True recall=1.000 predicted=['REDUNDANT_INDEX', 'FETCH_LARGE_DATA'] gold=['REDUNDANT_INDEX'] seconds=431.3 coordination_errors=0
- codex-subagents `database-031`: success=True recall=1.000 predicted=['REDUNDANT_INDEX', 'INSERT_LARGE_DATA'] gold=['REDUNDANT_INDEX'] seconds=168.0 coordination_errors=0
- losangelex `database-031`: success=True recall=1.000 predicted=['REDUNDANT_INDEX', 'INSERT_LARGE_DATA'] gold=['REDUNDANT_INDEX'] seconds=147.7 coordination_errors=0
- codex `database-032`: success=True recall=1.000 predicted=['REDUNDANT_INDEX', 'INSERT_LARGE_DATA'] gold=['REDUNDANT_INDEX'] seconds=392.5 coordination_errors=0
- codex-subagents `database-032`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'REDUNDANT_INDEX'] gold=['REDUNDANT_INDEX'] seconds=198.8 coordination_errors=3
- losangelex `database-032`: success=True recall=1.000 predicted=['REDUNDANT_INDEX', 'INSERT_LARGE_DATA'] gold=['REDUNDANT_INDEX'] seconds=147.5 coordination_errors=0
- codex `database-034`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'REDUNDANT_INDEX'] gold=['REDUNDANT_INDEX'] seconds=380.5 coordination_errors=0
- codex-subagents `database-034`: success=True recall=1.000 predicted=['REDUNDANT_INDEX', 'INSERT_LARGE_DATA'] gold=['REDUNDANT_INDEX'] seconds=142.5 coordination_errors=0
- losangelex `database-034`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'REDUNDANT_INDEX'] gold=['REDUNDANT_INDEX'] seconds=147.0 coordination_errors=0
- codex `database-035`: success=True recall=1.000 predicted=['VACUUM', 'INSERT_LARGE_DATA'] gold=['VACUUM'] seconds=410.0 coordination_errors=0
- codex-subagents `database-035`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'VACUUM'] gold=['VACUUM'] seconds=190.7 coordination_errors=0
- losangelex `database-035`: success=True recall=1.000 predicted=['VACUUM', 'FETCH_LARGE_DATA'] gold=['VACUUM'] seconds=192.8 coordination_errors=0
- codex `database-036`: success=True recall=1.000 predicted=['FETCH_LARGE_DATA', 'INSERT_LARGE_DATA'] gold=['FETCH_LARGE_DATA'] seconds=358.8 coordination_errors=0
- codex-subagents `database-036`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'FETCH_LARGE_DATA'] gold=['FETCH_LARGE_DATA'] seconds=246.8 coordination_errors=3
- losangelex `database-036`: success=True recall=1.000 predicted=['FETCH_LARGE_DATA', 'INSERT_LARGE_DATA'] gold=['FETCH_LARGE_DATA'] seconds=147.5 coordination_errors=0
- codex `database-037`: success=True recall=1.000 predicted=['FETCH_LARGE_DATA', 'INSERT_LARGE_DATA'] gold=['FETCH_LARGE_DATA'] seconds=354.7 coordination_errors=0
- codex-subagents `database-037`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'FETCH_LARGE_DATA'] gold=['FETCH_LARGE_DATA'] seconds=156.6 coordination_errors=0
- losangelex `database-037`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'FETCH_LARGE_DATA'] gold=['FETCH_LARGE_DATA'] seconds=147.6 coordination_errors=0
- codex `database-041`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'FETCH_LARGE_DATA'] gold=['FETCH_LARGE_DATA'] seconds=330.7 coordination_errors=0
- codex-subagents `database-041`: success=True recall=1.000 predicted=['FETCH_LARGE_DATA', 'INSERT_LARGE_DATA'] gold=['FETCH_LARGE_DATA'] seconds=150.7 coordination_errors=0
- losangelex `database-041`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'FETCH_LARGE_DATA'] gold=['FETCH_LARGE_DATA'] seconds=147.7 coordination_errors=0
- codex `database-065`: success=True recall=1.000 predicted=['REDUNDANT_INDEX', 'LOCK_CONTENTION', 'INSERT_LARGE_DATA'] gold=['LOCK_CONTENTION', 'REDUNDANT_INDEX'] seconds=406.0 coordination_errors=0
- codex-subagents `database-065`: success=True recall=1.000 predicted=['LOCK_CONTENTION', 'REDUNDANT_INDEX', 'INSERT_LARGE_DATA'] gold=['LOCK_CONTENTION', 'REDUNDANT_INDEX'] seconds=213.5 coordination_errors=0
- losangelex `database-065`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'LOCK_CONTENTION', 'REDUNDANT_INDEX'] gold=['LOCK_CONTENTION', 'REDUNDANT_INDEX'] seconds=195.2 coordination_errors=0
- codex `database-068`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'LOCK_CONTENTION', 'REDUNDANT_INDEX'] gold=['INSERT_LARGE_DATA', 'LOCK_CONTENTION'] seconds=431.3 coordination_errors=0
- codex-subagents `database-068`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'LOCK_CONTENTION', 'VACUUM'] gold=['INSERT_LARGE_DATA', 'LOCK_CONTENTION'] seconds=172.1 coordination_errors=0
- losangelex `database-068`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'LOCK_CONTENTION', 'FETCH_LARGE_DATA'] gold=['INSERT_LARGE_DATA', 'LOCK_CONTENTION'] seconds=149.1 coordination_errors=0
- codex `database-069`: success=True recall=1.000 predicted=['REDUNDANT_INDEX', 'LOCK_CONTENTION', 'INSERT_LARGE_DATA'] gold=['LOCK_CONTENTION', 'REDUNDANT_INDEX'] seconds=394.4 coordination_errors=0
- codex-subagents `database-069`: success=True recall=1.000 predicted=['LOCK_CONTENTION', 'REDUNDANT_INDEX', 'FETCH_LARGE_DATA'] gold=['LOCK_CONTENTION', 'REDUNDANT_INDEX'] seconds=168.8 coordination_errors=2
- losangelex `database-069`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'LOCK_CONTENTION', 'REDUNDANT_INDEX'] gold=['LOCK_CONTENTION', 'REDUNDANT_INDEX'] seconds=149.6 coordination_errors=0
- codex `database-071`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'LOCK_CONTENTION', 'REDUNDANT_INDEX'] gold=['INSERT_LARGE_DATA', 'LOCK_CONTENTION'] seconds=389.9 coordination_errors=0
- codex-subagents `database-071`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'LOCK_CONTENTION', 'FETCH_LARGE_DATA'] gold=['INSERT_LARGE_DATA', 'LOCK_CONTENTION'] seconds=190.5 coordination_errors=0
- losangelex `database-071`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'LOCK_CONTENTION', 'VACUUM'] gold=['INSERT_LARGE_DATA', 'LOCK_CONTENTION'] seconds=149.9 coordination_errors=0
- codex `database-072`: success=True recall=1.000 predicted=['LOCK_CONTENTION', 'REDUNDANT_INDEX', 'FETCH_LARGE_DATA'] gold=['LOCK_CONTENTION', 'REDUNDANT_INDEX'] seconds=364.9 coordination_errors=0
- codex-subagents `database-072`: success=True recall=1.000 predicted=['REDUNDANT_INDEX', 'LOCK_CONTENTION', 'INSERT_LARGE_DATA'] gold=['LOCK_CONTENTION', 'REDUNDANT_INDEX'] seconds=207.2 coordination_errors=8
- losangelex `database-072`: success=True recall=1.000 predicted=['LOCK_CONTENTION', 'REDUNDANT_INDEX', 'INSERT_LARGE_DATA'] gold=['LOCK_CONTENTION', 'REDUNDANT_INDEX'] seconds=150.4 coordination_errors=0
- codex `database-073`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'VACUUM', 'FETCH_LARGE_DATA'] gold=['VACUUM', 'FETCH_LARGE_DATA'] seconds=388.9 coordination_errors=0
- codex-subagents `database-073`: success=True recall=1.000 predicted=['FETCH_LARGE_DATA', 'VACUUM', 'LOCK_CONTENTION'] gold=['VACUUM', 'FETCH_LARGE_DATA'] seconds=160.2 coordination_errors=3
- losangelex `database-073`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'FETCH_LARGE_DATA', 'VACUUM'] gold=['VACUUM', 'FETCH_LARGE_DATA'] seconds=104.1 coordination_errors=0
- codex `database-077`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'LOCK_CONTENTION', 'FETCH_LARGE_DATA'] gold=['INSERT_LARGE_DATA', 'LOCK_CONTENTION'] seconds=401.0 coordination_errors=0
- codex-subagents `database-077`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'LOCK_CONTENTION'] gold=['INSERT_LARGE_DATA', 'LOCK_CONTENTION'] seconds=166.8 coordination_errors=0
- losangelex `database-077`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'LOCK_CONTENTION'] gold=['INSERT_LARGE_DATA', 'LOCK_CONTENTION'] seconds=194.1 coordination_errors=0
- codex `database-079`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'FETCH_LARGE_DATA', 'VACUUM'] gold=['FETCH_LARGE_DATA', 'INSERT_LARGE_DATA'] seconds=412.4 coordination_errors=0
- codex-subagents `database-079`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'FETCH_LARGE_DATA', 'REDUNDANT_INDEX'] gold=['FETCH_LARGE_DATA', 'INSERT_LARGE_DATA'] seconds=251.2 coordination_errors=2
- losangelex `database-079`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'FETCH_LARGE_DATA', 'VACUUM'] gold=['FETCH_LARGE_DATA', 'INSERT_LARGE_DATA'] seconds=148.3 coordination_errors=0
- codex `database-081`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'FETCH_LARGE_DATA', 'VACUUM'] gold=['VACUUM', 'FETCH_LARGE_DATA'] seconds=368.1 coordination_errors=0
- codex-subagents `database-081`: success=True recall=1.000 predicted=['FETCH_LARGE_DATA', 'VACUUM', 'INSERT_LARGE_DATA'] gold=['VACUUM', 'FETCH_LARGE_DATA'] seconds=162.7 coordination_errors=0
- losangelex `database-081`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'VACUUM', 'FETCH_LARGE_DATA'] gold=['VACUUM', 'FETCH_LARGE_DATA'] seconds=148.2 coordination_errors=0
- codex `database-082`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'FETCH_LARGE_DATA', 'REDUNDANT_INDEX'] gold=['FETCH_LARGE_DATA', 'INSERT_LARGE_DATA'] seconds=377.2 coordination_errors=0
- codex-subagents `database-082`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'FETCH_LARGE_DATA', 'VACUUM'] gold=['FETCH_LARGE_DATA', 'INSERT_LARGE_DATA'] seconds=174.6 coordination_errors=0
- losangelex `database-082`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'FETCH_LARGE_DATA', 'LOCK_CONTENTION'] gold=['FETCH_LARGE_DATA', 'INSERT_LARGE_DATA'] seconds=148.2 coordination_errors=0
- codex `database-083`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'FETCH_LARGE_DATA', 'VACUUM'] gold=['FETCH_LARGE_DATA', 'INSERT_LARGE_DATA'] seconds=397.3 coordination_errors=0
- codex-subagents `database-083`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'FETCH_LARGE_DATA'] gold=['FETCH_LARGE_DATA', 'INSERT_LARGE_DATA'] seconds=152.7 coordination_errors=0
- losangelex `database-083`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'FETCH_LARGE_DATA', 'VACUUM'] gold=['FETCH_LARGE_DATA', 'INSERT_LARGE_DATA'] seconds=193.1 coordination_errors=0
- codex `database-087`: success=True recall=1.000 predicted=['VACUUM', 'REDUNDANT_INDEX', 'FETCH_LARGE_DATA'] gold=['REDUNDANT_INDEX', 'VACUUM'] seconds=435.5 coordination_errors=0
- codex-subagents `database-087`: success=True recall=1.000 predicted=['VACUUM', 'REDUNDANT_INDEX', 'INSERT_LARGE_DATA'] gold=['REDUNDANT_INDEX', 'VACUUM'] seconds=213.1 coordination_errors=0
- losangelex `database-087`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'REDUNDANT_INDEX', 'VACUUM'] gold=['REDUNDANT_INDEX', 'VACUUM'] seconds=148.5 coordination_errors=0
- codex `database-088`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'VACUUM', 'REDUNDANT_INDEX'] gold=['REDUNDANT_INDEX', 'VACUUM'] seconds=442.8 coordination_errors=0
- codex-subagents `database-088`: success=True recall=1.000 predicted=['VACUUM', 'REDUNDANT_INDEX', 'INSERT_LARGE_DATA'] gold=['REDUNDANT_INDEX', 'VACUUM'] seconds=164.5 coordination_errors=1
- losangelex `database-088`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'VACUUM', 'REDUNDANT_INDEX'] gold=['REDUNDANT_INDEX', 'VACUUM'] seconds=147.8 coordination_errors=0
- codex `database-089`: success=True recall=1.000 predicted=['FETCH_LARGE_DATA', 'VACUUM', 'INSERT_LARGE_DATA'] gold=['VACUUM', 'FETCH_LARGE_DATA'] seconds=384.4 coordination_errors=0
- codex-subagents `database-089`: success=True recall=1.000 predicted=['FETCH_LARGE_DATA', 'INSERT_LARGE_DATA', 'VACUUM'] gold=['VACUUM', 'FETCH_LARGE_DATA'] seconds=163.3 coordination_errors=2
- losangelex `database-089`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'VACUUM', 'FETCH_LARGE_DATA'] gold=['VACUUM', 'FETCH_LARGE_DATA'] seconds=193.3 coordination_errors=0
- codex `database-091`: success=True recall=1.000 predicted=['REDUNDANT_INDEX', 'VACUUM', 'FETCH_LARGE_DATA'] gold=['REDUNDANT_INDEX', 'VACUUM'] seconds=419.3 coordination_errors=0
- codex-subagents `database-091`: success=False recall=0.500 predicted=['REDUNDANT_INDEX'] gold=['REDUNDANT_INDEX', 'VACUUM'] seconds=179.2 coordination_errors=0
- losangelex `database-091`: success=True recall=1.000 predicted=['INSERT_LARGE_DATA', 'VACUUM', 'REDUNDANT_INDEX'] gold=['REDUNDANT_INDEX', 'VACUUM'] seconds=193.0 coordination_errors=0
