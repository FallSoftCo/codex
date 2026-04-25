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

## Passive Wait Hardening

The next control-plane failure after the earlier quiescence fixes was not a shell-path problem after all. In the failing `expense_board` replay on the previous daemon generation, an agent issued:

- `exec_command { cmd: "sleep 20", workdir: ".../expense_board-leward-0883a99c" }`

The typo in `leader_award` (`leward`) caused unified exec startup to fail deep inside process creation with a low-level `os error 2`, even though the command itself was just a passive wait.

The runtime now hardens that path in two ways:

- pure passive waits like `sleep 0.1` are handled directly in `exec_command` without spawning a shell or depending on `workdir`
- non-passive commands now validate `workdir` up front and return a model-visible `workdir ... does not exist` error instead of bubbling a low-level spawn failure

Validation on rebuilt binaries:

- rebuilt locally from the patched tree with:
  `CARGO_HOME=/tmp/losangelex-cargo-home-test1 CARGO_TARGET_DIR=/tmp/losangelex-cargo-target-test1 cargo +stable build -p codex-cli --bin codex -p codex-app-server --manifest-path /home/ai/Development/losangelex/codex-rs/Cargo.toml`
- fresh daemon:
  `ws://127.0.0.1:33269`
- rerun command:
  `python3 /home/ai/Development/losangelex/scripts/eval_hollywood_app_builds.py --challenge expense_board --policy leader_award --timeout-seconds 420 --poll-seconds 40 --post-pass-soak-seconds 120 --max-quiescence-wait-seconds 360 --app-server-url ws://127.0.0.1:33269`
- result:
  - room: `repo/expense_board-leader_award-ffdb50`
  - workspace: `/home/ai/Development/losangelex/tmp/app_build_eval/expense_board-leader_award-45f34370`
  - `passed: true`
  - `passedAtSeconds: 308.8`
  - `quiescedAtSeconds: 428.2`
  - `allThreadsIdleAfterRun: true`
  - `activeThreadsAfterRun: 0`

Most importantly, that rerun produced no fresh `Failed to create unified exec process` entries for the new room or workspace. The prior failure class is now converted from a control-plane crash source into either a no-op passive wait or a clean model-facing workdir error.
