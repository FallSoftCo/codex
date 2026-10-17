## Hollywood Auto Policy Frontier (April 30, 2026)

This note records the post-upstream adaptive-policy results for the room-level
`coordination_policy=auto` runtime.

### What Changed

Two production/runtime changes were applied on top of the merged upstream tree:

1. `auto` discovery now resolves to a leadered decomposition policy instead of
   `dual_command_lease`.
2. `auto` execution now preserves leader/verifier roles instead of treating the
   room as anonymous `kanban_pull`.

The eval harness was also updated so the initial user turn for `auto` starts
with discovery/decomposition guidance instead of a generic runtime-policy prompt.

### Incident Console A/B/C

All three runs used the real model through `codex-app-server` and the artifact
gate `npm test -- --run`.

| Variant | Room | Time to Green | Message Count | Quiescence Lag | Notable Behavior |
| --- | --- | ---: | ---: | ---: | --- |
| Pre-fix `auto` | `repo/incident_console-auto-dd8e85` | `257.5s` | `176` | `69.7s` | Began with a broad implementation claim, later cancelled/re-split, and converged only after reclaim churn. |
| Discovery fix only | `repo/incident_console-auto-3cfde0` | `258.1s` | `59` | `53.0s` | Discovery was much cleaner and only `app.js` changed, but the verifier eventually took the main implementation lane. |
| Discovery + role-preserving execution | `repo/incident_console-auto-ddf759` | `177.2s` | `92` | `53.3s` | Clean three-lane split: `app.js` implementation, `index.html`/`styles.css` support, and QA coverage stayed with the verifier. Reached full-room idle. |

### Main Conclusion

The adaptive room-policy substrate is now doing useful runtime work rather than
just carrying labels:

- discovery can be forced into exact-lane decomposition before broad claims
- execution can keep role continuity instead of erasing leader/verifier duties
- closure still converges to zero active threads

The most important improvement is qualitative: the final run kept the verifier on
QA while an executor owned `app.js`, which is much closer to the intended
long-running team shape than the earlier reclaim-heavy runs.

### Remaining Gaps

- The final run still emitted `92` Hollywood messages, so `auto` is better but
  not yet the quietest policy.
- The verifier added one QA coverage test (`tests/incident-console.test.js`) in
  the final run; that is acceptable, but it means `auto` can still widen the
  surface area late in the task.
- We still need a clean same-daemon comparison against fixed `leader_award`,
  `kanban_pull`, and `dual_command_lease` on the merged upstream tree.
