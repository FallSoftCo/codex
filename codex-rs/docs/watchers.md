# Watchers

Losangelex watchers are persisted deferred continuations that wake a thread when a non-time-based condition is met.

The first shipped watcher trigger is `process_exit`: watch an `exec_command` session, then resume the owning thread once that process exits.

## What Exists Today

- persisted watcher definitions in SQLite
- persisted watcher-run records with wake status and `turn_id`
- app-server-hosted watcher claiming and wake execution
- CLI management via `codex watcher ...`
- model-visible watcher tooling via `watch_process_exit`, `list_watchers`, and `cancel_watcher`
- structured wake context with elapsed time, exit status, and the original follow-up prompt
- `exec_command` and `write_stdin` advisory nudges that point the model toward watchers for long waits

## CLI

Create a process-exit watcher:

```sh
codex watcher add-process-exit \
  --thread-id <THREAD_ID> \
  --session-id <EXEC_SESSION_ID> \
  --title "wait for cargo check" \
  --prompt "Inspect the finished build and summarize any failures."
```

Inspect active watchers and prior runs:

```sh
codex watcher list
codex watcher runs
```

Cancel an armed watcher:

```sh
codex watcher remove <WATCHER_ID>
```

## Operational Notes

- app-server must be running for watchers to be claimed and executed
- v1 only supports `process_exit`
- the watched process must come from an existing `exec_command` session id
- the app-server must be able to load the watched thread from persisted rollout/state metadata when the watcher fires
- watcher runs persist wake/failure status, but the resumed thread transcript remains the canonical detailed output

## Relation To Scheduled Tasks

Scheduled tasks are time-based: wake a thread at a specific time or interval.

Watchers are condition-based: wake a thread when an observed runtime condition changes.

In practice:

- use `codex schedule ...` when you know the time to wake up
- use `codex watcher ...` when you are waiting for a background process to finish
- use periodic task watches when the runtime cannot observe completion directly and the agent needs to reevaluate later on a time cadence
- use `wait_agent` only for short-lived blocking when you need another agent's status/result in the current turn
- use watcher-family extensions for durable "resume me later when that dependency is satisfied" behavior

## Next Extension

The natural next watcher family is agent dependency waiting: persist a continuation that resumes a thread when another agent reaches a target state, instead of stretching `wait_agent` into a long-lived blocking tool.

See [Agent Dependency Watchers](./agent_dependency_watchers.md).
