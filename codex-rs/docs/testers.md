# Testers

Losangelex testers are managed, interactive user-stand-ins. A tester is not a scripted transcript replay; it is a dedicated Codex thread started with tester-specific framing and allowed to pursue an objective through user-facing interfaces.

Current implementation:

- testers are persisted in SQLite
- the app-server starts pending testers as dedicated threads
- tester lifecycle reports are persisted
- optional controller-thread wakeups are delivered through the scheduled-task runtime
- CLI management lives under `codex tester ...`

## Commands

Create a tester:

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
  --controller-thread-id <THREAD_ID>
```

List testers:

```sh
codex tester list
```

Read reports:

```sh
codex tester reports --tester-id <TESTER_ID>
```

Queue another prompt into a started tester:

```sh
codex tester prompt <TESTER_ID> \
  --prompt "Continue from where you left off and investigate the deploy failure."
```

Stop a tester:

```sh
codex tester stop <TESTER_ID>
```

## Runtime Behavior

When an app-server is running:

1. `codex tester create` persists a pending tester.
2. The app-server claims the tester and starts a dedicated thread for it.
3. The tester receives a generated profile block and objective as its first turn.
4. The app-server records reports as the tester starts, becomes active, becomes idle, or fails.
5. If `controller_thread_id` is set, the app-server schedules immediate wakeups for that controller thread when the tester changes state.

The tester thread itself is the interactive process. The controller thread can react by inspecting the tester thread transcript, changing the system under test, and queueing additional prompts back into the tester with `codex tester prompt`.

## Limitations

- Testers are real Codex threads, but their allowed interfaces are currently enforced by instructions, not by hard tool gating.
- Testers currently report lifecycle changes and summaries, not rich structured evaluations.
- Controller wakeups depend on the scheduled-task runtime, so an app-server must be running.
- A tester can be stopped from further management, but v1 does not forcibly terminate an already-running turn.
