# SILO Correctness Replay: silo-correctness-replay-error-probe-2026-06-19-a

This report classifies SILO correctness failures by observed submission
shape. It distinguishes strict exact-output mismatches from peer outliers
and true global-computation failures.

## Summary

| System | Records | Valid | Full successes | Avg S | Avg P | Avg S_tol | Avg P_tol | Strict formatting | Peer outlier | Global computation | Missing/invalid | Tool calls |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| losangelex-contract | 1 | 0 | 0 | n/a | n/a | n/a | n/a | 0 | 0 | 0 | 0 | 0 |

## Records

| System | Task | Classification | Success | S | P | S_tol | P_tol | Wrong | Tol-correct wrong | Tool calls | Seconds |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| losangelex-contract | `II-14_n10.json` | invalid-attempt | False | 0.000 | 0.000 | 0.000 | 0.000 | 10 | 0 | 0 | 111.600 |
