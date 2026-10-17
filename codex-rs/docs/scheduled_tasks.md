# Scheduled Tasks

Losangelex ships a minimal v1 for persisted scheduled thread wakeups.

What it does:

- Stores one-shot and interval schedules in the shared SQLite state database.
- Lets the CLI create, list, remove, inspect, and trigger schedules.
- Uses `codex app-server` as the execution host for due schedules.
- Wakes the target thread by starting a normal user turn with the stored prompt.
- Persists run records and the started `turn_id`.

Current commands:

```sh
codex schedule add-at \
  --thread-id <THREAD_ID> \
  --title "daily summary" \
  --prompt "Summarize the repo status and report back." \
  --at 2026-04-08T13:00:00Z

codex schedule add-every \
  --thread-id <THREAD_ID> \
  --title "deploy check" \
  --prompt "Check whether the deploy is finished and summarize the result." \
  --every 15m

codex schedule list
codex schedule runs
codex schedule run-now <TASK_ID>
codex schedule remove <TASK_ID>
```

Operational notes:

- Schedules are durable, but they only fire while an app-server process is running.
- The target thread transcript remains the canonical persisted output for a scheduled run.
- Run records are currently best-effort. They track task start and later completion heuristically from thread runtime state.
- If a thread is already active when a schedule becomes due, the scheduler records a failed start attempt and retries later instead of interrupting the thread.

Design scope for this v1:

- trigger types: one-shot time, fixed interval
- execution target: existing thread
- wake payload: prompt plus `requires_response`
- reporting: persisted run record plus normal thread history

This is intended as the first step toward broader time-based deferred continuations rather than the final workflow engine shape.

For the next time-based continuation layer above generic schedules, see [Periodic Task Watches](./task_watches.md).
