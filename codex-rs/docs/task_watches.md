# Periodic Task Watches

Losangelex already has three adjacent primitives:

- `wait_agent` for short-lived blocking in the current turn
- watchers for durable condition-based wakeups
- scheduled tasks for durable time-based wakeups

The missing capability is a durable agent-level primitive for:

> "I should check on this again later."

That is not the same as:

- "wake me when this condition becomes true"
- "wait here until the other agent finishes"
- "run this cron-like automation forever"

It is a recurring reevaluation loop around a task the agent is actively tracking.

## Problem

Today an agent can fake this behavior with `codex schedule add-every` and a handwritten prompt, but that leaves important semantics outside the runtime:

- the schedule is not explicitly attached to a task being watched
- there is no task-specific state such as status, watch rationale, or stop reason
- the cadence cannot adapt based on prior check results without replacing the schedule
- the transcript/UI cannot distinguish "general recurring schedule" from "agent is watching this task"
- periodic check-ins risk turning into noisy cron jobs because they lack task-aware stop/backoff rules

The desired behavior is closer to a persisted self-reminder loop:

1. register a task watch
2. wake the owning thread periodically with task context
3. let the agent inspect the task and decide whether to keep watching
4. persist the decision and next check time
5. stop automatically once the task is done, irrelevant, or blocked long-term

## Goals

- Give agents a first-class way to periodically revisit a task.
- Reuse Losangelex's existing scheduled-task runtime instead of adding a third polling engine.
- Preserve the distinction between synchronous waiting, condition watchers, and periodic check-ins.
- Persist enough task-watch state that the user can see what the agent is watching and why.
- Support backoff, snooze, and explicit stop decisions as part of normal agent work.

## Non-Goals

- Building a general workflow/DAG scheduler.
- Replacing event-based watchers such as `process_exit` or future `agent_completion`.
- Turning every schedule into a task watch.
- Auto-solving the watched task inside the runtime without the agent making a judgment call.

## Core Design

Add a first-class concept: `task_watch`.

Architecturally, a task watch should be implemented as:

- task-watch metadata persisted in its own state tables
- execution hosted by the existing scheduled-task runtime
- a normal thread wake when a periodic check becomes due

This keeps the system model clean:

- `wait_agent`: block now
- watcher: wake on condition
- schedule: wake on time
- task watch: wake on time to reevaluate an explicit task

So a task watch is not a new watcher trigger. It is a specialized scheduled continuation with task-specific state and policy.

## Why Not Extend Watchers

The watcher docs already define watchers as non-time-based condition continuations.

Periodic task checks are fundamentally time-driven:

- "check every 15 minutes"
- "check tomorrow morning"
- "back off to every 2 hours if still pending"

Overloading watchers with interval semantics would blur an important boundary and make the runtime harder to reason about.

The existing scheduled-task runtime already has the right mechanics:

- persisted due-time storage
- claim/lease handling
- retry if the thread is busy
- run records and wake execution

The missing part is task-watch-specific metadata and control surface.

## Proposed User-Facing Surface

### Model Tool

Add a model-visible tool:

- `watch_task_periodically`

Suggested arguments:

- `title`
- `objective`
- `prompt`
- `check_every_seconds`
- `thread_id`
- `initial_delay_seconds`
- `max_checks`

Suggested semantics:

- create a task watch attached to the current thread by default
- store the objective separately from the wake prompt
- schedule the first wake immediately after `initial_delay_seconds` or after one interval if omitted
- return a `task_watch_id`

Recommended simplification for phase 1:

- do not expose a `requires_response` flag unless runtime behavior really differs when it is false
- a task watch wake is normally an intrinsically actionable reevaluation for its owning thread
- if product semantics later need a distinction, prefer a clearer wake/visibility policy name over reusing the generic watcher wording

Add a second control tool:

- `update_task_watch`

Suggested operations:

- stop the watch
- snooze until a concrete time
- change cadence
- record a status/decision note

This keeps the runtime state explicit instead of relying on implicit "delete and recreate schedule" behavior.

### CLI

Add explicit CLI instead of overloading `codex schedule ...`:

```sh
codex task-watch add \
  --thread-id <THREAD_ID> \
  --title "watch staging deploy" \
  --objective "Keep checking whether the staging deploy is complete and whether it needs intervention." \
  --prompt "Inspect the current staging deploy state, summarize what changed since the last check, and decide whether to keep watching." \
  --every 15m

codex task-watch list
codex task-watch runs
codex task-watch update <TASK_WATCH_ID> --every 1h
codex task-watch snooze <TASK_WATCH_ID> --until 2026-04-12T13:00:00Z
codex task-watch stop <TASK_WATCH_ID>
```

## Data Model

Use dedicated task-watch tables plus the existing scheduled-task runtime.

Important invariant:

- keep a single source of truth for due-time and lease state
- if execution is hosted by the scheduled-task runtime, do not duplicate independent claim/due bookkeeping in both generic scheduled-task rows and task-watch rows unless the layering is explicit and mechanically linked
- phase 1 should prefer one authoritative due/lease owner with task-watch metadata layered on top

Suggested tables:

```sql
CREATE TABLE task_watches (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    title TEXT NOT NULL,
    objective TEXT NOT NULL,
    prompt TEXT NOT NULL,
    status TEXT NOT NULL,
    cadence_seconds INTEGER NOT NULL,
    next_check_at INTEGER NOT NULL,
    max_checks INTEGER,
    check_count INTEGER NOT NULL DEFAULT 0,
    last_decision TEXT,
    last_observation TEXT,
    last_error TEXT,
    requires_response INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    stopped_at INTEGER
);

CREATE TABLE task_watch_runs (
    id TEXT PRIMARY KEY,
    task_watch_id TEXT NOT NULL REFERENCES task_watches(id) ON DELETE CASCADE,
    thread_id TEXT NOT NULL,
    turn_id TEXT,
    scheduled_for INTEGER NOT NULL,
    started_at INTEGER NOT NULL,
    finished_at INTEGER,
    status TEXT NOT NULL,
    summary TEXT,
    error TEXT
);
```

Suggested status values:

- `active`
- `snoozed`
- `completed`
- `stopped`
- `blocked_environment`

This is intentionally parallel to scheduled-task and watcher storage so operational behavior stays familiar.

## Runtime Behavior

### Registration

When a task watch is created:

1. persist the task-watch row
2. set `next_check_at`
3. let the existing app-server schedule loop claim due task watches

There are two viable implementation options:

1. add a dedicated task-watch poller that mirrors scheduled-task code
2. generalize the schedule runtime into a shared "time-based continuation" runner

The better choice is option 2 if implementation starts immediately. The code already has similar loops for schedules, watchers, and testers; task watches are a good forcing function to extract a reusable time-based continuation path instead of adding a fourth near-copy.

If the implementation needs to land incrementally, shipping a thin dedicated task-watch loop first is acceptable as long as the design keeps the extraction path open.

Whichever option lands first, the runtime should still preserve one clear ownership boundary for:

- due-time calculation
- lease/claim state
- retry-after-busy behavior
- deduplication of already-fired occurrences after restart

### Due Check Evaluation

When a task watch becomes due:

1. claim it with the same lease model used by schedules
2. if the thread is active, retry later instead of interrupting
3. wake the thread with structured task-watch context
4. mark a running task-watch run
5. when the thread becomes idle again, complete the run and update `check_count`

Unlike condition watchers, the runtime does not decide whether the watch is satisfied. The agent does.

### Wake Payload

Wake with structured context similar to existing watcher wakes:

```text
<task_watch_context>
title: watch staging deploy
objective: Keep checking whether the staging deploy is complete and whether it needs intervention.
task_watch_id: ...
scheduled_for: ...
check_count: 3
cadence_seconds: 900
last_decision: continue
last_observation: deploy still rolling; two pods pending
requires_response: true
</task_watch_context>

Inspect the current staging deploy state, summarize what changed since the last check, and decide whether to keep watching.
```

That gives the agent continuity without forcing it to reconstruct prior reasoning from transcript history alone.

## Agent Control Loop

The agent should treat each wake as a decision point, not just a blind repeated prompt.

After inspecting the task, it should be able to record one of a small set of decisions:

- `continue`
- `continue_with_backoff`
- `snooze`
- `complete`
- `stop`

This argues for `update_task_watch` as a first-class tool. The runtime should not infer these from free-form text.

Recommended behavior:

- `continue`: keep the current cadence
- `continue_with_backoff`: set a larger cadence
- `snooze`: set a one-off `next_check_at`
- `complete`: mark the watch complete and stop future runs
- `stop`: cancel without claiming task success

Mutation semantics should be explicit:

- cadence changes, backoff, snooze, and stop should mutate the same persisted task-watch row in place rather than implicitly creating replacement watches
- each due occurrence should have a stable identity in runtime bookkeeping so restarts do not double-fire an already-claimed or already-completed check
- if a wake is already running when an update happens, define whether the update affects the next due check only or can cancel/reschedule the in-flight occurrence

## Relation To Existing Schedules

Task watches should not replace generic schedules.

Use schedules when:

- the wakeup is operationally time-driven and not attached to a specific watched task
- the same prompt should recur indefinitely or by external policy
- the agent does not need explicit task-watch state

Use task watches when:

- the agent is actively tracking a concrete task
- each wake is a reevaluation checkpoint
- the agent may adjust cadence or stop based on what it learns
- the user should be able to inspect what is being watched and why

## Relation To Existing Watchers

Use watchers when the runtime can observe the trigger directly:

- process exit
- future agent completion
- future mailbox activity or external conditions

Use task watches when the runtime cannot know the answer and the agent needs to periodically inspect the world, for example:

- "check whether the reviewer responded"
- "see if the flaky CI run recovered"
- "revisit this upstream discussion tomorrow"
- "keep an eye on whether the deploy is healthy"

The distinction is:

- watcher: objective signal changed
- task watch: subjective reevaluation is needed

## Transcript And UI

Task watches should surface separately from both schedules and watchers.

Recommended thread/UI items:

- `taskWatchRegistered`
- `taskWatchTriggered`
- `taskWatchUpdated`
- `taskWatchStopped`

The user should be able to tell:

- what the agent is watching
- how often it plans to check
- what the last conclusion was
- whether the watch is still active

## Failure Semantics

- missing target thread at registration: reject
- unloaded or unavailable thread at run time: mark `blocked_environment`
- thread busy when due: retry later, same as scheduled tasks
- repeated wake failures: persist error and keep the watch active unless failure policy says otherwise
- `max_checks` reached: mark `stopped` unless the agent extends it

Phase 1 should keep failure policy simple and explicit. Avoid silent auto-stop based on heuristics other than hard caps such as `max_checks`.

## Rollout Plan

### Phase 1

- add `task_watch` state tables
- add `watch_task_periodically`, list, update, and cancel tooling
- wake threads periodically with structured task-watch context
- let agents explicitly continue, snooze, back off, complete, or stop

### Phase 2

- add richer UI/thread items
- support policy helpers such as bounded exponential backoff
- add "watch this task again" suggestions in prompts/tool guidance where the model currently stretches `wait_agent`

### Phase 3

- unify scheduled tasks and task watches under a shared time-based continuation runtime if phase 1 shipped with parallel code paths

## Recommendation

Ship periodic task watching as a first-class `task_watch` feature built on the schedule runtime, not as a watcher extension and not as a `wait_agent` variant.

That matches the user intent precisely:

- it is durable
- it is periodic
- it is task-oriented
- it leaves the judgment call with the agent
- it fits Losangelex's existing runtime split cleanly
