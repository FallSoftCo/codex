# SILO Correctness Replay: silo-correctness-replay-hard-smoke-2026-06-19-a

This report classifies SILO correctness failures by observed submission
shape. It distinguishes strict exact-output mismatches from peer outliers
and true global-computation failures.

## Summary

| System | Records | Valid | Full successes | Avg S | Avg P | Avg S_tol | Avg P_tol | Strict formatting | Peer outlier | Global computation | Missing/invalid | Tool calls |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| losangelex | 3 | 3 | 1 | 0.333 | 0.457 | 0.667 | 0.667 | 1 | 0 | 1 | 0 | 0 |
| losangelex-contract | 3 | 3 | 2 | 0.667 | 0.790 | 1.000 | 1.000 | 1 | 0 | 0 | 0 | 0 |
| losangelex-peer-review | 3 | 3 | 1 | 0.333 | 0.457 | 0.667 | 0.667 | 1 | 0 | 1 | 0 | 0 |

## Records

| System | Task | Classification | Success | S | P | S_tol | P_tol | Wrong | Tol-correct wrong | Tool calls | Seconds |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| losangelex | `II-12_n5.json` | strict-formatting | False | 0.000 | 0.370 | 1.000 | 1.000 | 5 | 5 | 0 | 149.100 |
| losangelex-contract | `II-12_n5.json` | strict-formatting | False | 0.000 | 0.370 | 1.000 | 1.000 | 5 | 5 | 0 | 148.800 |
| losangelex-peer-review | `II-12_n5.json` | strict-formatting | False | 0.000 | 0.370 | 1.000 | 1.000 | 5 | 5 | 0 | 149.700 |
| losangelex | `II-14_n5.json` | full-success | True | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 0 | 0 | 149.500 |
| losangelex-contract | `II-14_n5.json` | full-success | True | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 0 | 0 | 150.000 |
| losangelex-peer-review | `II-14_n5.json` | full-success | True | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 0 | 0 | 196.000 |
| losangelex | `II-15_n5.json` | global-computation | False | 0.000 | 0.000 | 0.000 | 0.000 | 5 | 0 | 0 | 196.700 |
| losangelex-contract | `II-15_n5.json` | full-success | True | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 0 | 0 | 196.300 |
| losangelex-peer-review | `II-15_n5.json` | global-computation | False | 0.000 | 0.000 | 0.000 | 0.000 | 5 | 0 | 0 | 244.100 |
