# SILO Correctness Replay: silo-correctness-replay-refined-2026-06-19-a

This report classifies SILO correctness failures by observed submission
shape. It distinguishes strict exact-output mismatches from peer outliers
and true global-computation failures.

## Summary

| System | Records | Valid | Full successes | Avg S | Avg P | Avg S_tol | Avg P_tol | Strict formatting | Peer outlier | Global computation | Missing/invalid | Tool calls |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| losangelex-contract | 2 | 2 | 2 | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 0 | 0 | 0 | 0 |
| losangelex-peer-review | 2 | 2 | 2 | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 0 | 0 | 0 | 0 |

## Records

| System | Task | Classification | Success | S | P | S_tol | P_tol | Wrong | Tol-correct wrong | Tool calls | Seconds |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| losangelex-contract | `II-12_n5.json` | full-success | True | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 0 | 0 | 149.700 |
| losangelex-peer-review | `II-12_n5.json` | full-success | True | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 0 | 0 | 148.300 |
| losangelex-contract | `II-15_n5.json` | full-success | True | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 0 | 0 | 148.600 |
| losangelex-peer-review | `II-15_n5.json` | full-success | True | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 0 | 0 | 149.400 |
