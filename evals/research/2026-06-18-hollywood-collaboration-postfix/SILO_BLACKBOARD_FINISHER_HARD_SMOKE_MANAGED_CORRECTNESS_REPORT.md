# SILO Correctness Replay: silo-blackboard-finisher-hard-smoke-managed-2026-06-19-a

This report classifies SILO correctness failures by observed submission
shape. It distinguishes strict exact-output mismatches from peer outliers
and true global-computation failures.

## Summary

| System | Records | Valid | Full successes | Avg S | Avg P | Avg S_tol | Avg P_tol | Strict formatting | Peer outlier | Global computation | Missing/invalid | Tool calls | Hollywood messages |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| codex-subagents | 3 | 3 | 2 | 0.667 | 0.790 | 1.000 | 1.000 | 1 | 0 | 0 | 0 | 12 | 0 |
| losangelex-blackboard-finisher | 3 | 3 | 3 | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 0 | 0 | 0 | 0 | 18 |

## Records

| System | Task | Classification | Success | S | P | S_tol | P_tol | Wrong | Tol-correct wrong | Tool calls | Hollywood messages | Seconds |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| codex-subagents | `II-12_n5.json` | strict-formatting | False | 0.000 | 0.370 | 1.000 | 1.000 | 5 | 5 | 5 | 0 | 272.400 |
| losangelex-blackboard-finisher | `II-12_n5.json` | full-success | True | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 0 | 0 | 6 | 147.600 |
| codex-subagents | `II-14_n5.json` | full-success | True | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 0 | 4 | 0 | 205.800 |
| losangelex-blackboard-finisher | `II-14_n5.json` | full-success | True | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 0 | 0 | 6 | 152.700 |
| codex-subagents | `II-15_n5.json` | full-success | True | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 0 | 3 | 0 | 146.600 |
| losangelex-blackboard-finisher | `II-15_n5.json` | full-success | True | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 0 | 0 | 6 | 102.700 |
