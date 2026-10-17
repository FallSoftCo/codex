## Hollywood Auto Runtime Enforcement - 2026-05-04

This note records the first post-merge runtime-enforced `auto` policy validation on top of upstream `origin/main`.

### What changed

The `auto` room policy is no longer only a brief-generation strategy.

Runtime enforcement now blocks:

- broad discovery-phase implementation `open_task` calls without exact `claim_paths`
- verifier-owned implementation `accept` calls unless the lane was explicitly awarded to the verifier
- discovery-phase self-claim of open implementation work before decomposition has produced concrete lanes

The app-server also now infers the effective `auto` phase from the durable coordination backlog and injects that inferred phase into Hollywood synthetic briefs.

### Validation

Focused tests passed:

- `cargo +stable test -p codex-core auto_ --lib`
- `cargo +stable test -p codex-app-server auto_room_policy_ --lib`

Live replay was rerun on a fresh standalone daemon against the merged upstream tree.

### Live results

`incident_console / auto`

- baseline from `post-merge-frontier-2026-05-04-a`: `424.5s` to green, `5.3s` quiescence lag, `83` Hollywood messages
- runtime-enforced rerun: `197.6s` to green, `88.2s` quiescence lag, `99` Hollywood messages

Observed behavior:

- the room no longer needed Tony to seize the main implementation lane as an emergency recovery move
- Chris owned `app.js`
- James owned `index.html` and `styles.css`
- Ray stayed on QA/gate work
- Tony stayed on integration/closure

`expense_board / auto`

- baseline from `post-merge-frontier-2026-05-04-a`: `258.5s` to green, `249.9s` quiescence lag, `142` Hollywood messages
- runtime-enforced rerun: `334.1s` to green, `31.7s` quiescence lag, `142` Hollywood messages

Observed behavior:

- closure discipline improved substantially
- residual implementation ownership still converged too slowly
- Tony eventually reclaimed the remaining `app.js` critical path and closed it

### Conclusion

The runtime-enforced `auto` policy is materially better at role discipline and closure than the prior brief-only version.

It is not yet the universal default:

- `incident_console` improved sharply
- `expense_board` traded better quiescence for worse throughput

The next frontier is task-shape adaptation inside `auto`, especially around stale implementation-lane takeover and critical-path reassignment.
