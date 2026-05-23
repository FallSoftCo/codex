# Losangelex Agent Runtime Evaluation, 2026-05-22

This directory contains the tracked paper and result bundle for the
2026-05-22 same-model evaluation of Losangelex/Hollywood against Codex agent
baselines.

## Files

- `losangelex-hardened-agent-runtime-evaluation-2026-05-22.pdf` - paper PDF.
- `losangelex-hardened-agent-runtime-evaluation-2026-05-22.tex` - paper source.
- `marble-final-primary-results.json` - sanitized MARBLE final-primary result
  bundle with aggregate and per-task metrics.
- `silo-same-model-results.json` - sanitized Silo-Bench summary bundle for
  n=5/n=10 same-model controls and public scale context.
- `marble-final-primary-report.md` - generated MARBLE benchmark report.
- `SHA256SUMS.txt` - checksums for the tracked artifacts in this directory.

## Silo-Bench Result

Silo-Bench is the most meaningful coordination benchmark in this bundle because
it directly tests private-shard distributed coordination.

| Scale | System | Strict success | Avg partial | Mean time | Coord. errors |
| --- | --- | ---: | ---: | ---: | ---: |
| n=5 | Serial Codex cohort | 20/30 | 0.714 | 422.1s | 0 |
| n=5 | Codex subagents | 24/30 | 0.813 | 240.1s | 70 |
| n=5 | Losangelex rooms | 21/30 | 0.826 | 113.0s | 0 |
| n=5 | Full-context Codex oracle | 25/30 | 0.846 | 39.2s | 0 |
| n=10 | Serial Codex cohort | 21/30 | 0.780 | 835.5s | 0 |
| n=10 | Codex subagents | 23/30 | 0.780 | 328.6s | 182 |
| n=10 | Losangelex rooms | 20/30 | 0.779 | 133.6s | 0 |
| n=10 | Full-context Codex oracle | 24/30 | 0.814 | 52.8s | 0 |

This result is meaningful but nuanced: Codex subagents are stronger on strict
observed n=5/n=10 correctness, Losangelex is much faster and records zero
coordination-router errors, and the full-context Codex oracle is the ceiling
when privacy/distribution constraints are removed.

## MARBLE Result

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

## Token Usage

The Silo and MARBLE published-benchmark runs in this bundle did not record
token usage in their result JSON or run logs. Token comparisons should therefore
not be claimed for those runs.

The separate coordination-topology benchmark records `model_tokens` and can
support token-efficiency claims for that controlled synthetic setting. Those
token results should not be extrapolated to Silo or MARBLE until their runners
record usage directly.

## Provenance

The tracked JSON is sanitized for repository publication. It omits local
workspace paths, transcript paths, raw model text, and native PostgreSQL process
metadata from the raw run artifacts. Source raw-result SHA-256 values are
recorded inside the sanitized JSON files.

The run was recorded in
`evals/losangelex_benchmark_completion_ledger.md` with SES delivery message id
`0100019e50c88fb7-c5ed5de7-ab46-4acc-be62-3bb5e4617a1a-000000`.
