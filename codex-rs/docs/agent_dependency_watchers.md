# Agent Dependency Watchers

Losangelex already has two relevant pieces of machinery:

- synchronous agent waiting via `wait_agent`
- persisted deferred continuations via watchers

That split is the right one to preserve.

`wait_agent` should remain a short-lived blocking/inspection tool for the current turn. The new capability for "wait for another agent to finish work, then continue later" should be implemented as a watcher-family extension, not as a longer-running `wait_agent`.

## Problem

Today an agent can:

- spawn or message another agent
- block briefly with `wait_agent`
- receive some ad hoc child-completion notifications in specific parent/child paths
- wake later on process exit through the persisted watcher runtime

What it cannot do cleanly is:

- register a durable dependency on another agent's completion
- stop spending the current turn on waiting
- resume automatically after the dependency is satisfied
- survive restarts while that dependency is pending

This makes multi-agent orchestration brittle. The runtime already knows how to persist and claim deferred continuations; agent dependencies should use the same substrate.

## Goals

- Let an agent defer its own continuation until another agent reaches a target state.
- Survive app-server restarts and idle gaps.
- Reuse the existing watcher lease/claim/run model instead of adding a second workflow engine.
- Keep `wait_agent` semantics narrow and synchronous.
- Surface enough transcript/UI state that the user can see what is waiting on what.

## Non-Goals

- Turning Losangelex into a general DAG scheduler.
- Replacing direct inter-agent messages or Hollywood coordination.
- Delivering another agent's full output through the wake result automatically.
- Extending the first version to arbitrary boolean expressions over many runtime signals.

## Proposed Shape

Add a new watcher trigger family for agent dependencies.

Phase 1 should ship one new trigger kind:

- `agent_completion`

Phase 2 can extend the same design with:

- `agent_mailbox_activity`
- `agent_dependency` with richer predicates

The first version should optimize for the common case:

1. parent agent delegates work
2. parent registers an `agent_completion` watcher for the child
3. parent ends the current turn
4. watcher runtime wakes the parent thread once the child reaches a final status
5. parent continues from the follow-up prompt with structured dependency context

## Why A Watcher, Not A Better `wait_agent`

The current watcher subsystem already provides the properties this feature needs:

- persisted definitions in SQLite
- claim/lease ownership in the app-server
- recorded wake runs with `turn_id`
- wake prompts that re-enter the thread cleanly

By contrast, `wait_agent` is intentionally ephemeral:

- v1 waits on live status subscriptions
- v2 waits on mailbox sequence changes
- both are scoped to the current turn
- neither is designed as a durable continuation primitive

So the architectural rule should be:

- `wait_agent`: "I need this result right now."
- `agent_completion` watcher: "Resume me later when that work is done."

## Data Model

The current watcher schema is process-exit-specific because it stores `process_id` directly on the main row. Agent dependency watchers need trigger-specific payload.

The cleanest extension is:

1. Keep common watcher columns in `watchers`.
2. Add a trigger payload table keyed by `watcher_id`.

Suggested new table:

```sql
CREATE TABLE watcher_agent_dependencies (
    watcher_id TEXT PRIMARY KEY REFERENCES watchers(id) ON DELETE CASCADE,
    target_thread_id TEXT NOT NULL,
    target_agent_name TEXT,
    completion_condition TEXT NOT NULL,
    observed_status TEXT,
    satisfied_at INTEGER
);
```

Suggested phase-1 condition values:

- `final`
- `completed`
- `successful`

Where:

- `final` means any final agent status
- `completed` means `AgentStatus::Completed(_)`
- `successful` means completed and not errored/not found/shutdown

This keeps the first API self-documenting and avoids opaque booleans.

Longer-term, if watcher trigger payloads grow, `process_exit` should also move to trigger-specific payload tables for symmetry. That refactor is optional for phase 1.

## Runtime Behavior

### Registration

Add a model-visible tool alongside `watch_process_exit`:

- `watch_agent_completion`

Suggested arguments:

- `target`
- `prompt`
- `title`
- `condition`
- `thread_id`
- `timeout_seconds`
- `requires_response`

Suggested minimal behavior:

- resolve `target` to a thread/agent id at registration time
- reject unknown targets up front
- persist the watcher against the waiting thread

### Evaluation

Extend the watcher poll loop in `codex-rs/app-server/src/codex_message_processor.rs` to handle `WatcherTriggerKind::AgentCompletion`.

Evaluation logic:

1. load the target thread id from `watcher_agent_dependencies`
2. inspect current agent status from `agent_control`
3. if the target is not yet satisfied, release the claim
4. if the target satisfies the configured condition, start a watcher run and wake the waiting thread

This should be poll-based in phase 1, even though local watch receivers exist.

Reason:

- it matches the existing watcher runtime model
- it remains durable across runtime/task restarts
- it avoids needing a second persistent subscription manager

An event-assisted fast path can be added later by nudging the watcher poller when agent status changes.

### Wake Payload

The wake message should mirror process-exit watcher structure and include agent-specific context:

```text
<watcher_context>
title: wait for reviewer
trigger: agent_completion
target_thread_id: ...
target_status: completed
condition: successful
created_at: ...
woke_at: ...
elapsed: ...
requires_response: true
</watcher_context>

Inspect the child agent result and decide the next step.
```

The wake should not inline the child agent's content automatically. The resumed thread can inspect transcript/history or use normal agent tools to fetch what it needs.

## Transcript And UI

This should be visible as watcher work, not overloaded onto `collabToolCall.wait`.

Reason:

- `collabToolCall.wait` currently means synchronous wait behavior
- durable dependency continuation is operationally different
- the user should be able to distinguish "blocked in this turn" from "scheduled to resume later"

Phase 1 can rely on existing watcher CLI and transcript wake behavior.

Phase 2 should add explicit UI/thread items for watcher registration and completion, for example:

- `watcherRegistration`
- `watcherTriggered`

That work can stay independent from the trigger implementation.

## Relationship To Existing Child Completion Notifications

`codex-rs/core/src/agent/control.rs` already has `maybe_start_completion_watcher`, which sends a direct parent notification when a thread-spawned child reaches a final state.

That is useful, but it is not sufficient for durable continuation because it is:

- in-memory
- specific to one parent/child flow
- notification-oriented rather than persisted wake-oriented

The new watcher should replace this as the durable orchestration primitive over time.

Recommended path:

- keep the existing completion notification behavior for now
- add watcher-based continuation as the durable path
- later decide whether direct parent notifications should be reduced, folded into watcher registration defaults, or kept as a lightweight convenience

## Failure Semantics

Phase 1 should keep failure rules simple:

- missing target at registration: reject the tool call
- target disappears later: fail the watcher with `blocked_environment`
- target errors and condition is `completed` or `successful`: fail the watcher run and wake the parent only if the condition semantics say the dependency is satisfied
- timeout: mark watcher failed, same as process-exit watchers

Recommended condition handling:

- `final`: trigger on any final status, including errored/not found/shutdown
- `completed`: trigger only on `Completed`
- `successful`: same as `completed` in phase 1 unless a richer success model is introduced

## API And Tooling

Phase-1 user-facing surface:

- new tool: `watch_agent_completion`
- existing `list_watchers`
- existing `cancel_watcher`
- existing `codex watcher list|runs|remove`

Phase-1 non-goal:

- do not add a generic `watch_agent` tool yet

Keeping the tool name explicit avoids premature abstraction and makes model usage clearer.

## Rollout Plan

### Phase 1

- add `WatcherTriggerKind::AgentCompletion`
- add trigger payload table for agent dependency rows
- add `watch_agent_completion` tool
- extend watcher runtime evaluation and wake formatting
- add docs/tests

### Phase 2

- add watcher UI/thread items
- add event-assisted fast-path wake nudges from agent status changes
- optionally add `agent_mailbox_activity`

### Phase 3

- unify trigger-specific payload storage for all watcher kinds
- consider a broader `agent_dependency` predicate model if real usage justifies it

## Open Questions

- Whether phase 1 should accept multiple targets or force one watcher per target.
- Whether "successful" should differ from "completed" immediately or wait for a stronger status model.
- Whether child completion should wake only the direct parent thread or any specified thread id.
- Whether the tool should optionally capture the target agent nickname/path for better wake text and CLI visibility.

## Recommendation

Ship this as a watcher extension, not a `wait_agent` rewrite.

Concretely:

- preserve `wait_agent` as a synchronous tool
- add a persisted `agent_completion` watcher
- wake the waiting thread with structured dependency context
- build richer dependency predicates only after the completion case proves useful

That approach fits the current Losangelex architecture, reuses the durable machinery that already exists, and gives multi-agent workflows a real continuation primitive instead of a longer timeout.
