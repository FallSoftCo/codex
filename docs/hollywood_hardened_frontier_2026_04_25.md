# Hollywood Hardened Frontier - 2026-04-25

This note captures the first policy readout after the latest app-server hardening work:

- interrupted turns now close in thread-history diagnostics
- stale `autonomousTurnPending` flags are reconciled away once a thread is truly idle
- latest live room state no longer leaves orphaned `awarded` tasks, path claims, scheduled tasks, or task watches after quiescence

## Hardened Frontier Slice

Campaign artifacts:

- [results.json](/home/ai/Development/losangelex/tmp/app_build_eval/hardened-frontier-2026-04-24-a/results.json)
- [REPORT.md](/home/ai/Development/losangelex/tmp/app_build_eval/hardened-frontier-2026-04-24-a/REPORT.md)

Configuration:

- daemon: `ws://127.0.0.1:46447`
- challenges: `incident_console`, `expense_board`
- policies: `leader_award`, `kanban_pull`, `dual_command`
- timeout: `420s`
- poll interval: `40s`
- post-pass soak: `120s`

Overall leaderboard from that slice:

| Policy | Pass Rate | Avg Time To Green | Avg Hollywood Messages | Avg Active Threads After Run |
| --- | ---: | ---: | ---: | ---: |
| `dual_command` | `1.00` | `224.6s` | `105.0` | `0.5` |
| `kanban_pull` | `1.00` | `244.7s` | `160.5` | `1.0` |
| `leader_award` | `1.00` | `246.2s` | `94.5` | `0.5` |

Interpretation:

- The hardened runtime shifts the frontier again. On this slice, `dual_command` is now the fastest policy family.
- `leader_award` remains the quietest reliable policy.
- `kanban_pull` still works, but it is the noisiest of the three and trails on time-to-green here.

## Evaluation Correction

The fixed soak window can under-report quiescence. In the hardened frontier slice, several rooms were still active at the `120s` soak cutoff but later settled fully idle with clean Hollywood diagnostics.

To address that, the evaluation harness now supports `--max-quiescence-wait-seconds` and records:

- `eventuallyQuiesced`
- `quiescedAtSeconds`
- `quiescenceLagSeconds`

Validation run:

- command:
  `python3 /home/ai/Development/losangelex/scripts/eval_hollywood_app_builds.py --challenge incident_console --policy dual_command --timeout-seconds 420 --poll-seconds 40 --post-pass-soak-seconds 120 --max-quiescence-wait-seconds 360 --app-server-url ws://127.0.0.1:46447`
- result:
  - `passedAtSeconds: 224.9`
  - `quiescedAtSeconds: 269.6`
  - `quiescenceLagSeconds: 44.7`
  - `allThreadsIdleAfterRun: true`

This means the previous `Avg Active Threads After Run` metric is still useful, but it should no longer be treated as the whole story for long-horizon stability. The stronger signal is:

1. time to green
2. time from green to full-room quiescence
3. whether durable state is clean after quiescence

## Current State

What now looks materially solid:

- no stale `currentTurnOpen` leak after interrupted turns
- no stale `autonomousTurnPending` leak after room settlement
- no leftover path claims after completed implementation work
- no leftover scheduled tasks or task watches for the validated room
- no `apply_patch verification failed` entries in the latest validated rollouts

What still needs work:

- some policies still take tens of seconds after green to fully quiesce
- policy comparisons should be rerun with the new quiescence metric before making broader claims
- long-horizon benchmarks still need restart/recovery and dependency-heavy scenarios
