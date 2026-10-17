# Testers

Losangelex testers are managed, interactive user-stand-ins. A tester is not a scripted transcript replay; it is a supervised `tester_run` with an explicit execution environment contract, structured reports, and persisted artifacts.

Current implementation:

- tester runs are persisted in SQLite
- the app-server claims queued tester runs and starts dedicated runtime threads for them
- tester runs carry an explicit execution class such as `terminal_full_access` or `terminal_sandboxed`
- structured tester reports are parsed from the tester transcript and persisted separately
- rollout artifacts are persisted for later inspection
- optional controller-thread wakeups are delivered through the scheduled-task runtime
- CLI management lives under `codex tester ...`

## Commands

Create a tester run:

```sh
codex tester create \
  --name "onboarding-check" \
  --objective "Try to deploy the app and report friction." \
  --background "Technical user who is new to this repo." \
  --skill-level intermediate \
  --temperament persistent \
  --starting-knowledge "README only" \
  --constraint "Do not read source code" \
  --allowed-interface terminal_harness \
  --execution-class terminal-full-access \
  --controller-thread-id <THREAD_ID>
```

List tester runs:

```sh
codex tester list
```

Read reports for one tester run:

```sh
codex tester reports --run-id <RUN_ID>
```

Read persisted artifacts for one tester run:

```sh
codex tester artifacts <RUN_ID>
```

Queue another prompt into a started tester:

```sh
codex tester prompt <RUN_ID> \
  --prompt "Continue from where you left off and investigate the deploy failure."
```

Stop a tester run:

```sh
codex tester stop <RUN_ID>
```

## Runtime Behavior

When an app-server is running:

1. `codex tester create` persists a queued tester run.
2. The app-server claims the tester run and provisions its execution class.
3. The tester receives a generated profile block and objective as its first turn.
4. The tester emits explicit `<tester_report ...>` blocks as it progresses, blocks, or finishes.
5. The app-server parses those blocks into persisted `tester_run_reports`, updates the tester-run status, and records the rollout as an artifact.
6. If `controller_thread_id` is set, the app-server schedules immediate wakeups for that controller thread when the tester run changes state.

The tester thread itself is the interactive process, but the public durable abstraction is the tester run. The controller thread can react by inspecting the tester reports and rollout artifact, changing the system under test, and queueing additional prompts back into the tester with `codex tester prompt`.

## Execution Classes

`terminal_full_access`

- approval policy is forced to `never`
- sandbox mode is forced to `danger-full-access`
- intended for production-like terminal harness evaluation without interactive approval deadlocks

`terminal_sandboxed`

- approval policy is forced to `never`
- sandbox mode is forced to `workspace-write`
- intended for more constrained terminal evaluation

The current tester feature has hard tool gating. `terminal_harness` is the only allowed interface label that currently maps to a concrete runtime tool surface.

## Limitations

- `terminal_harness` is the only allowed interface that currently maps to concrete tool access; other interface labels remain profile metadata until additional adapters are implemented.
- Tester reports are transcript-derived but supervisor-owned: the app-server parses explicit `<tester_report>` blocks and persists them separately.
- Controller wakeups depend on the scheduled-task runtime, so an app-server must be running.
- A tester can be stopped from further management, but v1 does not forcibly terminate an already-running turn.
