# Losangelex Agent Runtime Evaluation, 2026-05-22

This directory contains the tracked paper and result bundle for the
2026-05-22 same-model evaluation of Losangelex/Hollywood against Codex agent
baselines.

## Files

- `losangelex-hardened-agent-runtime-evaluation-2026-05-22.pdf` - paper PDF.
- `losangelex-hardened-agent-runtime-evaluation-2026-05-22.tex` - paper source.
- `marble-final-primary-results.json` - sanitized MARBLE final-primary result
  bundle with aggregate and per-task metrics.
- `marble-final-primary-report.md` - generated MARBLE benchmark report.
- `SHA256SUMS.txt` - checksums for the tracked artifacts in this directory.

## Headline Result

The locked native MARBLE database final-primary holdout contains 30 tasks run
with the same model family across three systems:

| System | Full recall | Exact set | Avg recall | Avg precision | Avg F1 | Mean time | Coord. errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Serial Codex cohort | 30/30 | 0/30 | 1.000 | 0.583 | 0.733 | 393.7s | 0 |
| Codex subagents | 29/30 | 2/30 | 0.983 | 0.617 | 0.742 | 184.0s | 25 |
| Losangelex rooms | 30/30 | 1/30 | 1.000 | 0.594 | 0.740 | 160.2s | 0 |

The paper frames this as a narrow systems result, not a universal SOTA claim:
Losangelex preserves full MARBLE recall and improves runtime/error profile, but
Codex subagents have slightly better precision/F1 on this holdout and the Silo
full-context oracle remains an important ceiling control.

## Provenance

The tracked JSON is sanitized for repository publication. It omits local
workspace paths, transcript paths, raw model text, and native PostgreSQL process
metadata from the raw run artifact. The source raw-result SHA-256 is recorded
inside `marble-final-primary-results.json`.

The run was recorded in
`evals/losangelex_benchmark_completion_ledger.md` with SES delivery message id
`0100019e50c88fb7-c5ed5de7-ab46-4acc-be62-3bb5e4617a1a-000000`.
