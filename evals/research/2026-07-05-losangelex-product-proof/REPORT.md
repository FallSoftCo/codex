# Losangelex Product Proof - 2026-07-05

This report is about the Losangelex product claim, not benchmark ranking: a Codex fork where a user can control multiple interactive collaborative agents through Hollywood rooms, inspect what they are doing, and get useful code work done.

## Verdict

The product proof passed for the slices tested:

- Real TUI user orchestration launched two Losangelex/Hollywood collaborators, not Codex subagents.
- Agents communicated accepted/started/finished status in Hollywood.
- Agents edited files collaboratively without clobbering or conflict markers.
- Multi-user app-server scenarios showed simultaneous user-facing agents, required direct wakes, same-file edit plans, and dependency handoffs.
- A real scratch app task was implemented by a team, tested with `npm test -- --run`, and quiesced to zero active threads.
- A resumed TUI session recovered the prior room/file/task state and collaborator identities from persisted state.

## Product Bugs Found And Fixed

1. App-build harness did not attach agents to the managed Hollywood server.

   Early `code-deliverable-a` passed app tests but had `messageCount = 0` in the managed room. The evaluator now passes `hollywood_url` into `start_agent(...)` and records `roomMessages`, `messageCount`, and `notificationHollywoodMessageCount`.

2. Optional observed Hollywood traffic caused stale no-op wake turns.

   `code-deliverable-b` and `code-deliverable-c` completed the app but did not quiesce: optional observed/direct messages kept producing autonomous follow-up work after the team was done. The app-server now only starts Hollywood follow-up turns when `response_policy = required`; optional traffic remains visible but does not create autonomous wake churn.

3. App-build prompts allowed long-running verification habits.

   The evaluator prompt now asks agents to prefer bounded verification commands and to stop long-running processes before finalizing.

## Live Evidence

### Communication And Collaborative Editing

Artifact: `tmp/research/losangelex-product-proof/2026-07-05/comm-initial-a/REPORT.md`

- Runs: 6/6 complete across team sizes 2, 3, and 4.
- Same-file collaborative edit slices: 2/2 complete, both with collaborative edit plans, no conflict markers.
- Conflict-free sidecar/integrator slices: 2/2 complete.
- Independent cross-file permissions slices: 2/2 complete.
- Agents with work-state messages: 6/6.
- Agents with start-like messages: 6/6.
- Agents with finish-like messages: 5/6 by classifier; manual room review showed the miss was still semantically a finish report.
- Average wall time: 72.1s.
- Average uncached plus output tokens: 123,219.
- Coordination tool errors: 0.

### Multi-User Control

Initial artifact: `tmp/research/losangelex-product-proof/2026-07-05/multi-user-initial-a/REPORT.md`

- Runs: 3/3 passed.
- Same-file three-user release plan: 3 user-facing agents edited one file by section, 3 collaborative edit plans, no conflict markers.
- Direct dependency: Alice required-woke Bob, Bob responded, Alice used the answer.
- Third-agent verification: Alice required-woke Bob and a verifier, both responded.
- Coordination tool errors: 0.

Post-fix artifact: `tmp/research/losangelex-product-proof/2026-07-05/multi-user-postwake-a/REPORT.md`

- Runs: 2/2 passed after optional wake suppression.
- Same-file release plan: 73.17s, 3 collaborative edit plans, 0 wake turns, 85,282 uncached plus output tokens.
- Direct dependency: required direct wake still worked, Bob woke and replied, 73,002 uncached plus output tokens.
- Duplicate pending required directs: 0.
- Coordination tool errors: 0.

### Real Deliverable Code

Final artifact: `tmp/research/losangelex-product-proof/2026-07-05/code-deliverable-d/result.json`

- Challenge: `expense_board`.
- Policy: `gpgp_blackboard`.
- App tests: passed.
- Passed at: 103.6s.
- Quiesced at: 134.0s.
- Active threads after run: 0.
- All threads idle after run: true.
- Changed files: `app.js`, `index.html`.
- Hollywood room messages: 24.
- Coordination tool errors: 0.
- Token usage: 1,998,725 input, 1,666,176 cached input, 332,549 non-cached input, 19,006 output, 2,515 reasoning output, 351,555 uncached plus output.

The earlier code-delivery attempts are intentionally kept as failure evidence:

- `code-deliverable-a`: tests passed, but invalid as Hollywood proof because agents were not attached to the managed Hollywood server.
- `code-deliverable-b`: tests passed and room messages were captured, but the run did not quiesce.
- `code-deliverable-c`: tests passed with 46 room messages, but stale optional wake traffic kept threads active.

### TUI Orchestration

Artifact root: `tmp/research/losangelex-product-proof/2026-07-05/tui-proof-c/`

- Started a real inline TUI with isolated `CODEX_HOME`, isolated Hollywood DB, `RUST_LOG=trace`, and dedicated log dir.
- User prompt asked the parent to form a real Losangelex/Hollywood team with two collaborators.
- Parent launched two collaborators:
  - `alpha-doc` created `docs/alpha.md`.
  - `beta-doc` created `docs/beta.md`.
- Hollywood room `repo/tui-proof-c` has 15 messages including:
  - accepted/started-like lane claims from both collaborators,
  - finish messages from both collaborators,
  - durable task open/done messages,
  - stand-down messages,
  - explicit accepted/started/finished audit lines from both collaborators.
- Final TUI output reported both files verified, tasks done, collaborators idle, and no helper process left running.
- TUI token usage after initial proof: total 91,005; input 86,239 plus 553,984 cached; output 4,766; reasoning 1,623.

### Recovery / Resume

Artifact: `tmp/research/losangelex-product-proof/2026-07-05/tui-proof-c/resume-logs/codex-tui.log`

The TUI resumed session `019f3297-776b-77f2-9bee-f82774ce5425` against the saved workspace and Hollywood DB. The recovery prompt asked for read-only verification only.

Recovered evidence:

- `docs/alpha.md` still existed.
- `docs/beta.md` still existed.
- Hollywood room `repo/tui-proof-c` still had accepted/started/finished audit messages:
  - Alpha message id 15.
  - Beta message id 14.
- Prior collaborator identities were visible:
  - Alpha owner/thread: `019f3297-e291-7772-a50c-19f7d6bb956e`.
  - Beta owner/thread: `019f3297-eb8b-7bf2-80a9-94b7660cbf74`.
- Both persisted coordination tasks were `done`.
- State missing for requested recovery checks: none.

Nuance: the live peer roster was empty after restart because the collaborators were no longer running. The product still recovered collaborator identity and ownership through persisted room messages and coordination tasks.

## Validation

- `python3 -m py_compile scripts/eval_hollywood_app_builds.py`
- `cd codex-rs && just fmt`
- `cd codex-rs && just test -p codex-app-server select_hollywood_followup`
- `cd codex-rs && just test -p codex-app-server hollywood_input`
- `cd codex-rs && just fix -p codex-app-server`
- Live model-in-the-loop campaigns listed above.

Final push verification is run after this report update.
