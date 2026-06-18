# GPT-5.5 Current-Upstream Agent Runtime Appendix, 2026-06-16

This bundle records the GPT-5.5 benchmark campaign launched on June 16, 2026 and
completed on June 17, 2026 at 15:03:04 America/New_York. It is an appendix to
the June 2 Losangelex/Hollywood runtime study and the June 14 current-upstream
coordination probes.

The SILO-BENCH n5 and n10 runs are complete, token-covered comparisons across
Codex, Codex full-context, Codex subagents, and Losangelex. The MARBLE
native-postgres run is included as an operational artifact only: it was started
as a 100-case run, but the account hit a usage limit after database-032, leaving
zero-token, empty-prediction rows from database-033 onward. Do not use that
MARBLE file as a fair 100-case model/runtime comparison.

## Files

| File | Description |
|---|---|
| `UPSTREAM_SUBAGENT_MESSAGING.md` | Commit-level note on upstream Codex subagent messaging changes included in the catch-up window. |
| `silo-gpt55-n5-report.md` | Sanitized aggregate SILO-BENCH n5 report. |
| `silo-gpt55-n5-results.json` | Sanitized SILO-BENCH n5 result data, 120 rows. |
| `silo-gpt55-n10-report.md` | Sanitized aggregate SILO-BENCH n10 report. |
| `silo-gpt55-n10-results.json` | Sanitized SILO-BENCH n10 result data, 120 rows. |
| `marble-gpt55-native-postgres-report.md` | Sanitized exploratory MARBLE report with usage-limit cutoff rows. |
| `marble-gpt55-native-postgres-results.json` | Sanitized exploratory MARBLE data, 300 rows, not a fair 100-case comparison. |
| `SHA256SUMS.txt` | Checksums for the bundle. |

## SILO-BENCH n5

| System | Tasks | Full successes | Avg S | Avg P | Avg seconds | Avg total tokens | Avg uncached+output |
|---|---:|---:|---:|---:|---:|---:|---:|
| Codex | 30 | 23 | 0.800 | 0.818 | 841.0 | 1,173,682 | 301,098 |
| Full-context Codex | 30 | 25 | 0.833 | 0.846 | 41.4 | 84,428 | 26,402 |
| Codex subagents | 30 | 24 | 0.800 | 0.812 | 220.8 | 954,987 | 161,852 |
| Losangelex | 30 | 25 | 0.833 | 0.846 | 170.9 | 1,679,657 | 317,729 |

Losangelex tied full-context Codex on strict success and beat Codex subagents by
one strict success while averaging 22.6 percent less wall time than Codex
subagents. Codex subagents were substantially more token efficient.

## SILO-BENCH n10

| System | Tasks | Full successes | Avg S | Avg P | Avg seconds | Avg total tokens | Avg uncached+output |
|---|---:|---:|---:|---:|---:|---:|---:|
| Codex | 30 | 21 | 0.727 | 0.746 | 1670.0 | 2,555,300 | 601,064 |
| Full-context Codex | 30 | 25 | 0.833 | 0.847 | 62.8 | 106,320 | 33,560 |
| Codex subagents | 30 | 23 | 0.767 | 0.780 | 289.4 | 1,698,260 | 246,053 |
| Losangelex | 30 | 23 | 0.793 | 0.813 | 177.6 | 3,737,636 | 650,741 |

Losangelex and Codex subagents tied on strict success. Losangelex had higher
mean agent success and partial correctness and averaged 38.7 percent less wall
time than Codex subagents, but used about 2.20x total tokens and 2.64x
uncached-plus-output tokens.

## MARBLE Exploratory Cutoff

| System | Tasks in file | Full successes before cutoff | Token rows | Avg seconds | Avg total tokens | Avg uncached+output |
|---|---:|---:|---:|---:|---:|---:|
| Codex | 100 | 32 | 32 | 159.6 | 906,202 | 240,554 |
| Codex subagents | 100 | 32 | 32 | 71.4 | 1,364,638 | 232,046 |
| Losangelex | 100 | 32 | 33 | 104.4 | 2,011,101 | 380,788 |

The headline 32/100 values in the report are an artifact of the usage-limit
cutoff, not a benchmark result. The primary MARBLE evidence remains the June 2
30-case run with complete token coverage and no zero-token error rows.

## Interpretation

The upstream Codex subagent substrate changed meaningfully in June 2026. The
most relevant changes are typed/plaintext agent-message history, typed
multi-agent message envelopes, terminal subagent error surfacing, and app-client
join keys for inter-agent messages. See `UPSTREAM_SUBAGENT_MESSAGING.md`.

The June 16 SILO results show current Codex subagents are much more token
efficient than Losangelex/Hollywood on private-shard coordination. Losangelex is
still materially faster in the n10 run and ties strict success there, but the
token gap is too large to call it a universal win. The public conclusion should
stay task-conditional.

## Validity Notes

- SILO n5 and n10 each contain 120 rows: 30 tasks for each of four systems.
- SILO n5 and n10 have complete nonzero token coverage.
- The MARBLE file contains 300 rows, but database-033 onward reflects account
  usage-limit failures, empty predictions, and zero token rows.
- This campaign completed before the local merge commit that caught the branch
  up to upstream. Treat it as a June 16 GPT-5.5 current-upstream appendix, not
  as a post-merge branch-tip benchmark.
