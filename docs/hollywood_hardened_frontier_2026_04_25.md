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

## Apply Patch Recovery Frontier

The next live failure mode after passive-wait hardening was not a router crash. It was stale or invalid file targeting during `apply_patch` recovery on a real `habit_dashboard / leader_award` run.

Two things were hardened:

- `apply_patch` verification failures for stale patch context now include a direct recovery hint to re-read the current file or diff before regenerating the patch.
- missing-file verification failures now include a stronger hint:
  - `apply_patch` paths must reference real files in the current workspace
  - absolute paths should be rewritten relative to the workspace root
  - if the file still does not exist, the agent should inspect the workspace and retarget or reopen the task instead of retrying the same patch

Live validation on the rebuilt daemon at `ws://127.0.0.1:41263` showed the new handler output reaching the model. In the first rerun, the tool emitted:

- `apply_patch verification failed: Failed to read file to update .../app.js: No such file or directory`
- followed by the new recovery hint

That did improve observability, but the stronger conclusion from the next rerun is architectural:

- prompt-level tightening did not eliminate leader-mode critical-file drift
- `leader_award` still allowed a run to fall behind on the `app.js` critical path
- the room eventually reached a state where `app.js` had to be recreated explicitly in the workspace root to recover

The latest `habit_dashboard / leader_award` slice therefore disproves the idea that better recovery phrasing alone is enough. The control plane stayed healthy, but policy quality still let a critical-path file disappear long enough to blow the evaluation budget.

Current frontier after this rerun:

- runtime/tooling: materially better
- model-facing diagnostics: materially better
- leader-mode critical-file guardianship: still not strong enough

The next likely fix is not more generic runtime hardening. It is stronger coordination policy around critical-path ownership, reclamation, and verification when a claimed file disappears or diverges.

### Follow-up Policy Probe

I tightened the `leader_award` evaluation prompt after that failed run:

- leaders must verify the current existence and workspace-relative path of a critical file before reclaiming or reassigning it
- workers must verify the file still exists before editing it
- if the expected file is actually missing, they must stop retrying the same patch and either recreate the file at the intended workspace path or hand the lane back

On the next rerun of `habit_dashboard / leader_award` against the same hardened daemon generation, the team still experienced a transient `app.js` delete/add window and still emitted `apply_patch` verification failures, but the run recovered instead of timing out:

- room: `repo/habit_dashboard-leader_award-a5c41c`
- workspace: `/home/ai/Development/losangelex/tmp/app_build_eval/habit_dashboard-leader_award-0e56b2b4`
- `passed: true`
- `passedAtSeconds: 269.5`
- `quiescedAtSeconds: 356.8`
- `allThreadsIdleAfterRun: true`
- `activeThreadsAfterRun: 0`

This is a useful result because it narrows the diagnosis:

- prompt-level critical-file guidance can improve recovery enough to get leader-mode back under budget
- prompt-level guidance still does not eliminate critical-file churn entirely

So the next frontier is now sharper than before:

- tool/runtime recovery is good enough to surface and survive the failure
- policy guidance can mitigate the failure
- but fully stable long-horizon behavior still needs stronger protection around temporary deletion/recreation of critical-path files

## Post-Merge Direct-Closure Validation

After merging upstream `origin/main`, the worst remaining leader-mode outlier was still
`expense_board / leader_award`.

Old merged-tree baseline:

- room: `repo/expense_board-leader_award-e495f4`
- `passedAtSeconds: 133.8`
- `quiescenceLagSeconds: 357.7`
- `messageCount: 289`

Room inspection showed the tail was dominated by direct-message closure ping-pong:

- `thread closed. do not reply ...`
- `no further reply needed ...`
- `closing this dm thread ...`

Those messages were being classified as wake-worthy `DirectRequest` traffic instead of
ack/closure traffic.

The wake classifier now treats explicit closure directives as ack-only when they do not
contain a real question or new assignment, including phrases such as:

- `do not reply`
- `closing this dm thread`
- `i will only contact you again if i assign new work or hit a real blocker`
- `no assignment is being made`

Validation on a fresh merged daemon:

- daemon: `ws://127.0.0.1:46461`
- command:
  `python3 /home/ai/Development/losangelex/scripts/eval_hollywood_app_builds.py --challenge expense_board --policy leader_award --timeout-seconds 420 --poll-seconds 40 --post-pass-soak-seconds 120 --max-quiescence-wait-seconds 360 --app-server-url ws://127.0.0.1:46461`
- room: `repo/expense_board-leader_award-4b57c8`
- workspace: `/home/ai/Development/losangelex/tmp/app_build_eval/expense_board-leader_award-c8370888`
- `passedAtSeconds: 216.6`
- `quiescedAtSeconds: 284.0`
- `quiescenceLagSeconds: 67.4`
- `messageCount: 23`
- `allThreadsIdleAfterRun: true`
- `activeThreadsAfterRun: 0`

This is a real control-plane improvement, not just another lucky run:

- message volume dropped from `289` to `23`
- quiescence lag dropped from `357.7s` to `67.4s`
- all four threads ended cleanly idle with no pending Hollywood diagnostics

The remaining `leader_award` weakness is no longer DM closure ping-pong. The next
residual instability is still critical-path file churn during longer implementation
flows.
