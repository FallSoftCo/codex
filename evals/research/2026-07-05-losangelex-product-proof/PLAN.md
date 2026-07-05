# Losangelex Product Proof Plan - 2026-07-05

Purpose: prove the Losangelex product claim directly: a Codex fork where a user can control multiple interactive collaborative agents in shared Hollywood rooms, including coordinated communication, collaborative editing, real code delivery, compilation/testing, and recovery.

This is not a benchmark comparison plan. The target evidence is product behavior and UX validity.

## Ground Rules

- Use isolated `CODEX_HOME`, app-server processes, Hollywood servers/databases, and scratch workspaces.
- Prefer real app-server/TUI/product paths over mocks.
- Keep the model in the loop for semantic collaboration claims.
- Record transcripts, room ledgers, notifications, diffs, wall time, token usage, and test output.
- Treat deterministic tests as substrate proof only; do not use them as proof that agents naturally collaborate.
- Do not interrupt unrelated running Losangelex/Hollywood sessions.

## Evidence Required

- [x] A user can launch/control multiple Losangelex agents attached to one Hollywood room.
- [x] Agents naturally send useful Hollywood work-state messages: accepted/started/blocked/done/handoff.
- [x] Multiple agents collaboratively edit one shared file without clobbering or conflict markers.
- [x] Multiple agents collaboratively edit real code across files and produce a coherent patch.
- [x] The patch compiles/tests in the scratch repo.
- [x] The app-server/TUI state remains inspectable enough for a user to understand who is doing what.
- [x] Recovery works after app-server/TUI restart or an agent interruption.
- [x] The behavior holds across different team sizes and collaboration methods.
- [x] Time and token overhead are measured.

## Phase A - Existing Live Harness Smoke

- [x] Run communication tendency scenarios for same-file, sidecar, and cross-file teams.
- [x] Run multi-user team scenarios for simultaneous user-facing agents.
- [x] Inspect failures for missing Hollywood communication, duplicate work, clobbering, or token waste.

## Phase B - Real Deliverable Code Task

- [x] Create or reuse a scratch app with a test suite.
- [x] Assign multiple agents disjoint implementation, UI/contract, and validation lanes.
- [x] Require the agents to coordinate through Hollywood before edits and at handoff points.
- [x] Run the scratch app tests and capture the final patch.

## Phase C - TUI Orchestration Proof

- [x] Start `just codex` with `RUST_LOG=trace` and a dedicated log dir.
- [x] Drive a real TUI session programmatically using the tested text-then-Enter input pattern.
- [x] Launch or attach multiple room agents.
- [x] Verify the user can observe/steer the team from the product surface, not only raw logs.

## Phase D - Recovery Proof

- [x] Restart app-server/TUI while a room exists.
- [x] Verify room attachment, agent identities, tasks/claims, and collaborative edit plans remain readable.
- [x] Verify a stale/interrupted lane can be recovered or reassigned.

## Artifact Index

- Root: `tmp/research/losangelex-product-proof/2026-07-05/`
- Initial communication tendency campaign: `tmp/research/losangelex-product-proof/2026-07-05/comm-initial-a/REPORT.md`
- Initial multi-user campaign: `tmp/research/losangelex-product-proof/2026-07-05/multi-user-initial-a/REPORT.md`
- Post-wake-policy multi-user regression: `tmp/research/losangelex-product-proof/2026-07-05/multi-user-postwake-a/REPORT.md`
- Real deliverable code task: `tmp/research/losangelex-product-proof/2026-07-05/code-deliverable-d/result.json`
- TUI transcript/logs: `tmp/research/losangelex-product-proof/2026-07-05/tui-proof-c/logs/codex-tui.log`
- Recovery transcript/logs: `tmp/research/losangelex-product-proof/2026-07-05/tui-proof-c/resume-logs/codex-tui.log`
- Tracked summary: `evals/research/2026-07-05-losangelex-product-proof/REPORT.md`

## Current Status

- Product-level proof passed for real TUI orchestration, Hollywood communication, collaborative same-file editing, multi-user control, real code delivery with app tests, quiescence, and TUI resume recovery.
- Product gap found and fixed: optional observed Hollywood messages could start autonomous no-op follow-up turns. The app-server now starts autonomous follow-up only for `response_policy = required`; optional observed/direct traffic remains visible but does not wake a thread by itself.
- Harness gap found and fixed: the app-build evaluator was not passing the managed Hollywood URL into started agents, so early code-delivery artifacts were not valid Hollywood proof. The harness now attaches app-build agents to the managed server and records room messages.
- Recovery nuance: after TUI restart, the live peer roster was empty because the collaborators were no longer running, but collaborator identities and task ownership were recovered from persisted room messages and coordination tasks.
- Targeted Rust substrate tests and live model-in-the-loop product proofs passed. Branch push status is handled after final validation.
