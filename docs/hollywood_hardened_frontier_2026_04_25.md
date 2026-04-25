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

## Post-Merge Dual-Command Closure-FYI Validation

After the direct-closure fix, the worst remaining post-merge outlier shifted to
`habit_dashboard / dual_command`.

Old merged-tree baseline:

- room: `repo/habit_dashboard-dual_command-f70d73`
- `passedAtSeconds: 257.4`
- `eventuallyQuiesced: false`
- `messageCount: 466`
- `activeThreadsAfterRun: 4`

The tail was no longer explicit "do not reply" traffic. Instead it was dominated by
non-action closure FYIs that still looked like direct requests to the wake classifier:

- `Seen. Closure-only FYI on my side too; no action and no further replies unless scope changes or a new failure appears.`
- `Handled as non-actionable. No action is needed from my side, and I’m ending this closure-only thread here unless scope changes or a new failure appears.`
- `Understood. Same on my side: non-actionable, no work claimed, and I’m ending this closure-only thread unless scope changes or a new failure appears.`

The classifier now treats those broader non-action closure phrases as ack-only even
without an `Acknowledged`/`Understood` opener, including phrases such as:

- `no action is needed`
- `closure-only`
- `non-actionable`
- `ending this closure-only thread`
- `no further replies unless`
- `remain silent unless`

Validation on a fresh merged daemon:

- daemon: `ws://127.0.0.1:46462`
- command:
  `python3 /home/ai/Development/losangelex/scripts/eval_hollywood_app_builds.py --challenge habit_dashboard --policy dual_command --timeout-seconds 420 --poll-seconds 40 --post-pass-soak-seconds 120 --max-quiescence-wait-seconds 360 --app-server-url ws://127.0.0.1:46462`
- room: `repo/habit_dashboard-dual_command-81570d`
- workspace: `/home/ai/Development/losangelex/tmp/app_build_eval/habit_dashboard-dual_command-28aa6813`
- `passedAtSeconds: 216.1`
- `quiescedAtSeconds: 297.0`
- `quiescenceLagSeconds: 80.9`
- `messageCount: 59`
- `allThreadsIdleAfterRun: true`
- `activeThreadsAfterRun: 0`

This closes the old dual-command quiescence leak materially:

- message volume dropped from `466` to `59`
- the run now fully quiesces instead of leaving all four threads active
- the fix holds on a fresh daemon generation rather than only on the previously warmed
  post-merge process

The remaining dual-command weakness is not closure ping-pong anymore. What still shows
up in the room trace is noisy ownership correction and mid-run lane churn around the
critical path before the implementation settles.

## Lease-Based Dual Command

The next hypothesis was that `dual_command` was still too eager to treat "no visible
workspace diff yet" as a stalled lane. That produced unnecessary status checks,
ownership corrections, and reassignment churn even after the closure wake fixes.

To test that, I added a new policy variant, `dual_command_lease`, with three explicit
rules:

- active owners keep a lane by sending short progress heartbeats
- Ray treats a recent heartbeat as active ownership rather than idle work
- Tony only reassigns after missed heartbeat checks or an explicit yield/blocker

### Habit Dashboard Comparison

Existing post-fix `dual_command` baseline:

- room: `repo/habit_dashboard-dual_command-dcb6ee`
- `passedAtSeconds: 257.9`
- `quiescenceLagSeconds: 69.1`
- `messageCount: 64`
- `activeThreadsAfterRun: 0`

Lease variant:

- room: `repo/habit_dashboard-dual_command_lease-aca6b6`
- `passedAtSeconds: 215.4`
- `quiescenceLagSeconds: 91.6`
- `messageCount: 30`
- `activeThreadsAfterRun: 0`

What changed in the room trace:

- no late ownership-correction storm
- no Tony/Ray reassignment loop while the active owner was still working
- one blocking `app.js` lane stayed with James until handback, while Chris stayed
  parked on the surface layer

This is a real improvement on the critical-path churn we still saw in plain
`dual_command`:

- time to green improved from `257.9s` to `215.4s`
- message volume dropped from `64` to `30`
- the run still fully quiesced

### Incident Console Validation

To make sure the lease idea was not only rescuing the simpler dashboard case, I ran the
same variant on the more coupled `incident_console` challenge.

- room: `repo/incident_console-dual_command_lease-3c3313`
- `passedAtSeconds: 175.0`
- `quiescedAtSeconds: 243.5`
- `quiescenceLagSeconds: 68.5`
- `messageCount: 42`
- `activeThreadsAfterRun: 0`

That run held the intended shape:

- Tony published the lane map once
- James kept the blocking `app.js` lane
- Chris stayed on a parked static review lane after confirming no markup changes were needed
- Ray stayed verification-only and used heartbeat semantics instead of pushing early reassignment

Current conclusion:

- closure wake hardening fixed the old no-op ping-pong
- lease-style dual command is the first policy change after that hardening that also
  materially reduces critical-path churn
- the next serious frontier candidate is no longer plain `dual_command`; it is
  `dual_command_lease`

## Lease Frontier Comparison

I then reran the live frontier on the same hardened daemon with the three current
serious candidates:

- `leader_award`
- `kanban_pull`
- `dual_command_lease`

Campaign:

- report: `tmp/app_build_eval/lease-frontier-2026-04-25-a/REPORT.md`
- raw results: `tmp/app_build_eval/lease-frontier-2026-04-25-a/results.json`
- daemon: `ws://127.0.0.1:46462`
- challenges: `habit_dashboard`, `incident_console`, `expense_board`

Overall leaderboard from that run:

| Policy | Avg Time To Green | Avg Quiescence Lag | Avg Hollywood Messages |
| --- | ---: | ---: | ---: |
| `kanban_pull` | `202.8s` | `193.6s` | `201.7` |
| `dual_command_lease` | `257.4s` | `103.3s` | `35.3` |
| `leader_award` | `270.5s` | `80.2s` | `34.7` |

What this means:

- `kanban_pull` is still the throughput winner, but it remains extremely noisy and has
  the worst convergence lag by a wide margin.
- `leader_award` is still the quietest disciplined closer, but it remains the slowest
  of the three on this slice.
- `dual_command_lease` is the new balanced frontier policy. It is much quieter and
  more stable than `kanban_pull`, while staying materially faster than `leader_award`
  on `habit_dashboard` and `incident_console`.

Per-challenge read:

- `habit_dashboard`: `dual_command_lease` and `kanban_pull` were essentially tied on
  time to green (`258.0s` vs `258.2s`), but `dual_command_lease` used far fewer room
  messages (`33` vs `277`).
- `incident_console`: `dual_command_lease` clearly won on time to green (`175.3s`)
  while staying quieter than both anchors.
- `expense_board`: `kanban_pull` won decisively on raw throughput (`133.9s`), while
  `dual_command_lease` stayed much quieter but slower (`339.0s`).

Current frontier conclusion:

- `kanban_pull` is best when we optimize aggressively for raw throughput.
- `leader_award` is best when we optimize for disciplined closure and minimum chatter.
- `dual_command_lease` is now the strongest all-around compromise for stable,
  long-running coordination because it preserved full pass/quiescence while cutting the
  false-reassignment churn that previously made plain `dual_command` unreliable.
