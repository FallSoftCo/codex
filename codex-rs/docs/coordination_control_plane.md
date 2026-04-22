# Coordination Control Plane [proposal]

See also:
[`speech_act_contract_net.md`](./speech_act_contract_net.md) for the scalable
task/lease/contract-layer design that builds on this control-plane foundation.

This document proposes the next-release Losangelex design for:

- role-driven multi-agent coordination
- thread-scoped shared user context
- runtime coordination status
- Hollywood wake and interruption policy

The goal is to make coordination durable, queryable, and low-noise without
turning Hollywood room traffic into the only source of truth.

## Summary

The next release should add a coordination control plane with four explicit
pieces:

1. A new thread-scoped append-only `user_context_entries` state substrate for
   durable shared user context.
2. A runtime-scoped coordination status API for loaded sessions. This should
   stay out of durable sqlite for v1 except for existing durable role defaults.
3. A small explicit role model with `lead` as the only default auto-recruiting
   role.
4. A typed Hollywood handling path in app-server that distinguishes
   `interrupt`, `annotate`, and `queue` before Hollywood input reaches core as
   ordinary model input.

The design is intentionally narrow for the next release:

- keep shared context thread-scoped first
- keep fast-changing availability/runtime coordination state out of persistent
  sqlite
- do not overload `Thread.hollywood` or `thread/hollywood/list` as semantic
  coordination truth
- do not add global/workspace context, semantic search, or inferred fact
  extraction yet

## Current Anchors

The proposal builds on existing codepaths rather than introducing a separate
coordination subsystem:

- `codex-rs/app-server/src/hollywood.rs`
- `codex-rs/app-server/src/codex_message_processor.rs`
- `codex-rs/app-server/src/thread_status.rs`
- `codex-rs/state/src/model/thread_metadata.rs`
- `codex-rs/state/src/runtime/threads.rs`
- `codex-rs/state/src/extract.rs`
- `codex-rs/core/src/codex.rs`
- `codex-rs/core/src/state/session.rs`
- `codex-rs/core/src/tasks/mod.rs`
- `codex-rs/core/src/session_prefix.rs`
- `codex-rs/core/src/tools/handlers/hollywood.rs`
- `codex-rs/app-server-protocol/src/protocol/common.rs`
- `codex-rs/app-server-protocol/src/protocol/v2.rs`

Important existing constraints:

- `thread_status.rs` models execution/runtime status, not semantic coordination
  status.
- `thread_metadata.rs` and `threads.rs` only persist a narrow subset of
  Hollywood attachment metadata (`url`, `room`, `attention_mode`,
  `include_at_all`, `include_at_room`). On read, `observed_rooms` and
  `wake_rooms` round-trip as empty vectors today
  (`state/src/model/thread_metadata.rs`), so this path is both lossy and too
  narrow to grow into a full coordination store.
- `codex_message_processor.rs` already classifies some Hollywood traffic with
  `response_policy` and acknowledgement heuristics, but the current flow is
  still too binary: wake and submit vs do not wake.

## Design Goals

- Agents should not need to infer coordination truth from room scrollback.
- Durable user-directed context should survive resume and handoff.
- Low-value traffic should stop interrupting useful work.
- Roles should cause different coordination behavior automatically.
- The next release should be implementable with narrow additive protocol and
  state changes.

## Non-goals

The next release should not attempt:

- workspace-wide or global shared context
- window-local replicated state
- semantic search over shared context
- automatic inferred fact extraction from arbitrary turns
- persistent full coordination availability state in sqlite
- recruitment RPCs or broad automatic swarm behavior

## Roles

Use a small explicit role set:

- `lead`
- `member`
- `reviewer`
- `devils_advocate`
- `observer`

Meaning:

- `lead`: decomposes work, synthesizes results, and is the only role that
  auto-recruits by default.
- `member`: owns an assigned implementation or investigation slice.
- `reviewer`: evaluates risk, regressions, coverage, and merge-readiness.
- `devils_advocate`: pressure-tests assumptions, ambiguity, and tradeoffs.
- `observer`: tracks capacity/blockers/drift and suggests coordination changes
  without taking work by default.

### Role persistence

For the next release:

- reuse existing durable `agent_role` only as a default role/home for the
  thread when needed
- keep live coordination availability and active role execution runtime-scoped
- do not add a broad persisted role/availability store in sqlite

## Automatic Coordination Policy

Only `lead` should auto-recruit by default.

Auto-recruit when all are true:

- current session role is `lead`
- work has been decomposed into disjoint slices or is clearly parallelizable
- a relevant agent in the current repo/task room is `idle` or `available`
- no existing owner already covers the slice
- effective shared user context has been read for the current coordination cycle

Initial heuristics:

Auto-request a `reviewer` when:

- shared/core/protocol/state/runtime behavior changes
- the change is user-visible or regression-prone
- the lead is about to finalize substantial work without an independent pass

Auto-request a `devils_advocate` when:

- user intent is ambiguous or conflicting
- coordination semantics or persistence semantics are changing
- the design introduces a new default policy or high-cost assumption

Guardrails:

- no auto-recruitment for tiny or linear tasks
- recruit from the current repo/task room first
- do not auto-recruit from `main` by default
- cap automatic recruitment to a small number of clearly scoped roles per phase
- if no relevant idle agent exists, continue locally and record degraded
  coverage when it matters

## Shared User Context

Raw thread history remains canonical, but coordination-relevant durable user
context gets its own append-only substrate.

### State model

Add a new sqlite table in `codex-state`:

- `user_context_entries`
  - `id` TEXT PRIMARY KEY
  - `thread_id` TEXT NOT NULL
  - `scope` TEXT NOT NULL
  - `entry_type` TEXT NOT NULL
  - `status` TEXT NOT NULL
  - `semantic_key` TEXT NULL
  - `payload_json` TEXT NOT NULL
  - `source_turn_id` TEXT NULL
  - `source_message_id` TEXT NULL
  - `supersedes_entry_id` TEXT NULL
  - `created_by_thread_id` TEXT NOT NULL
  - `created_at` INTEGER NOT NULL

For v1:

- `scope` is fixed to `thread` and reserved for future expansion
- do not add workspace/global/window-local scope yet

Suggested `entry_type` values:

- `raw_user_message`
- `directive`
- `constraint`
- `preference`
- `decision`
- `correction`
- `resolution`

Suggested `status` values:

- `active`
- `superseded`
- `conflicted`
- `retracted`

### Why a new table

Do not grow `threads` metadata into this role.

Reasons:

- `threads` metadata is row-shaped and already strained
- Hollywood attachment persistence there is already lossy, including the
  current loss of `observed_rooms` and `wake_rooms` on sqlite round-trip
- shared user context needs append/list/fold/query semantics closer to
  schedules/watchers than to static thread columns

### Write policy

Automatic by runtime:

- the intended steady-state behavior is that inbound end-user messages that
  should survive resume or handoff get a `raw_user_message` entry; if rollout
  is phased, the migration and APIs may land before automatic write coverage is
  complete

Explicit narrow durable writes only for:

- directives affecting other windows
- corrections invalidating prior guidance
- durable preferences or constraints
- explicit decisions
- explicit resolutions of conflicts

Do not auto-promote arbitrary inferred summaries in the next release.

### Conflict handling

The store is append-only.

Fold rules:

- thread scope only for v1
- explicit `supersedes_entry_id` wins
- conflicting active entries with the same `semantic_key` surface an explicit
  conflict instead of silently merging

Agents should consume unresolved conflicts as unresolved state.

## Runtime Coordination Status

Coordination availability/status is needed, but it should remain mostly
runtime-scoped for the next release.

Do not persist rapidly changing values such as:

- `idle`
- `available`
- `active`
- `reviewing`
- `blocked`
- `waiting`

Those values should remain derived from app-server runtime state for loaded
sessions first, reusing the existing thread-status and loaded-thread machinery
where possible instead of introducing a broad new durable store in v1.

### API shape

A likely v2 runtime coordination API shape is:

- `thread/coordination/runtime/list`
- `thread/coordination/runtime/update`

This API should expose fields such as:

- `threadId`
- `sessionId`
- `role`
- `room`
- `workscope`
- `state`
- `ownedScope`
- `blockedOn`
- `updatedAt`

`thread/hollywood/list` should remain transport/runtime attachment state, not
semantic coordination truth.

## Wake, Interrupt, Annotate, Queue

This is the most important behavior change for the next release.

Today app-server primarily decides whether Hollywood traffic is wakeworthy via:

- `hollywood_input_delivery_metadata(...)`
- `hollywood_message_needs_wake(...)`
- `hollywood_message_is_ack_only(...)`

That is not enough. The next release should add an explicit runtime action
classification before Hollywood input is submitted to core. Those helpers
currently implement the binary wake-vs-non-wake path in app-server today; the
next release should replace that binary path with explicit
`interrupt|annotate|queue` classification.

### Message classes

Introduce a small explicit app-server-side classification layer at the
Hollywood boundary, initially heuristic-backed, that maps inbound traffic into
a stable set of message classes:

- `action_required`
- `blocking_update`
- `review_or_risk`
- `informational`
- `acknowledgment`
- `heartbeat_status`
- `ambient_broadcast`

`response_policy` remains useful, but it should answer "is a response owed"
rather than "should this interrupt active work."

### Runtime actions

Map inbound Hollywood traffic into one of three runtime actions:

- `interrupt`
- `annotate`
- `queue`

Policy:

- `action_required`, `blocking_update`, and `review_or_risk` usually
  `interrupt`
- relevant `informational` and relevant `ambient_broadcast` usually `annotate`
- `acknowledgment`, `heartbeat_status`, and duplicate/no-new-information
  traffic usually `queue`

### Behavioral rules

- Only `interrupt` traffic should create an immediate interruption of active
  work by default.
- `annotate` traffic should be recorded and surfaced to the active task
  context through a lightweight non-turn path when possible, without
  defaulting to a fresh active-work turn.
- `queue` traffic should be recorded/unread-visible without entering the active
  execution path.
- After `annotate` or lightweight non-blocking handling, runtime should
  automatically resume prior work.
- Waiting threads should only wake on relevant blocking/actionable updates.

This must be enforced in app-server before Hollywood input becomes ordinary
core input.

That rule matters because otherwise:

- persistence becomes better, but interruption spam remains
- low-value traffic still enters core as normal actionable input

## Cooperation Boundary Preload

To avoid dead metadata, runtime should preload effective shared context
automatically at cooperation boundaries.

Initial preload points for the next release should be startup, resume, and
explicit cooperation boundaries that already have app-server injection seams
(for example handoff and review creation). Fork and broader cross-window
preload can remain follow-on work unless their wiring is already touched by the
implementation.

The preload should inject:

- compact effective shared context
- explicit conflict block

Do not inject full raw logs or large coordination blobs.

Current seam to use:

- app-server already injects Hollywood context on attach/resume paths
- the same attach/resume/session-prefix seams are the likely insertion points
  for effective user context and conflicts

## API Additions

Additive v2 APIs for next release:

- `userContext/list`
- `userContext/effective`
- `userContext/create`
- `userContext/resolve`
- `thread/coordination/runtime/list`
- `thread/coordination/runtime/update`

Do not add for v1:

- recruitment RPCs
- semantic search
- AI merge endpoints
- bulk mutation surfaces

## Source Touchpoints

Primary implementation touchpoints:

- `codex-rs/state/src/model/`
- `codex-rs/state/src/model/thread_metadata.rs`
- `codex-rs/state/src/runtime/`
- `codex-rs/state/src/runtime/threads.rs`
- `codex-rs/state/src/extract.rs`
- `codex-rs/app-server-protocol/src/protocol/common.rs`
- `codex-rs/app-server-protocol/src/protocol/v2.rs`
- `codex-rs/app-server/src/codex_message_processor.rs`
- `codex-rs/app-server/src/hollywood.rs`
- `codex-rs/app-server/src/thread_status.rs`
- `codex-rs/core/src/codex.rs`
- `codex-rs/core/src/state/session.rs`
- `codex-rs/core/src/tasks/mod.rs`
- `codex-rs/core/src/session_prefix.rs`
- `codex-rs/core/src/tools/handlers/hollywood.rs`

Important app-server wake seams today:

- `CodexMessageProcessor::hollywood_input_delivery_metadata(...)`
- `CodexMessageProcessor::hollywood_message_needs_wake(...)`
- `CodexMessageProcessor::hollywood_message_is_ack_only(...)`

Expected enforcement split:

- app-server:
  - classify Hollywood traffic
  - decide `interrupt|annotate|queue`
  - trigger persistence of raw user-context entries through state/runtime APIs
  - preload effective shared context
- core:
  - keep obligation handling narrow to actionable traffic
  - avoid treating non-blocking messages as fresh user work
  - `codex-rs/core/src/state/session.rs` currently resolves Hollywood obligations
    coarsely by room for a turn (`resolve_hollywood_obligations_for_turn`),
    so v1 should avoid promising message-granular obligation reconciliation
    unless that seam is tightened

## Rollout Plan

Phase 1:

- add `user_context_entries` migration
- add state models/runtime repo methods
- add fold/effective/conflict unit tests

Phase 2:

- add v2 `userContext/*` APIs
- add v2 runtime coordination status APIs

Phase 3:

- automatically persist durable inbound user messages
- preload effective shared context on startup/resume/handoff/cooperation
  boundaries

Phase 4:

- replace current binary Hollywood wake path with explicit
  `interrupt|annotate|queue`
- suppress no-op autonomous follow-up for purely non-blocking traffic
- auto-resume prior work after non-blocking handling

Phase 5:

- focused end-to-end tests:
  - raw user message persisted once
  - effective context returns explicit conflicts
  - no-op ack/status chatter does not interrupt
  - actionable message does interrupt/create obligation
  - active work resumes after informational update
  - lead-only auto-recruitment respects room and idle-status gating

## Final Release Cut

The next release should ship:

- thread-scoped append-only shared user context
- runtime-only coordination availability/status API
- small explicit role set with lead-only automatic coordination
- explicit `interrupt|annotate|queue` routing in app-server for Hollywood
  traffic, initially using narrow typed classifications plus heuristics rather
  than a full semantic coordination engine
- automatic preload of effective shared context at cooperation boundaries

It should not ship:

- workspace/global shared context
- persistent fast-changing availability state
- broad inferred semantic memory
- coordination truth embedded in `Thread.hollywood`
- continued reliance on room scrollback and acknowledgement heuristics as the
  main coordination model
