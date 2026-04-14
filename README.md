<p align="center">
  <strong>Losangelex</strong><br />
  FallSoftCo's multi-agent Codex fork for local coordination and long-running agent workflows
</p>

<p align="center">
  <a href="https://github.com/FallSoftCo/losangelex">Losangelex</a>
  ·
  <a href="https://github.com/FallSoftCo/hollywood">Hollywood</a>
</p>

<p align="center">
  <strong>Status:</strong> Experimental but active<br />
  <strong>Maintainer:</strong> FallSoftCo<br />
  <strong>Base:</strong> Upstream Codex, replayed onto current upstream main
</p>

Losangelex is a FallSoftCo project built on top of upstream Codex.

It keeps the upstream Codex CLI, TUI, and app-server foundation, then layers on:

- native Hollywood room integration in the app-server/runtime
- Losangelex launcher defaults for full-access local work
- workspace-scoped Hollywood bootstrap and room setup
- persisted scheduled thread wakeups
- persisted process-exit watchers for deferred continuations
- managed tester runtimes for interactive user-like evaluation
- upstream-aligned branch history rather than a permanently drifting fork

The current integration target is current upstream `main`, with Losangelex behavior adapted onto that architecture instead of preserving old fork-only seams.

## Table of Contents

- [What Losangelex Is](#what-losangelex-is)
- [Why Losangelex](#why-losangelex)
- [What Exists Today](#what-exists-today)
- [Architecture](#architecture)
- [Current Status](#current-status)
- [Quickstart](#quickstart)
- [Scheduled Tasks](#scheduled-tasks)
- [Watchers](#watchers)
- [Testers](#testers)
- [Demo](#demo)
- [Relationship to Upstream Codex](#relationship-to-upstream-codex)
- [Docs](#docs)
- [License](#license)

## What Losangelex Is

Losangelex is the runtime side of the FallSoftCo local multi-agent stack.

That stack currently consists of two repositories:

- `FallSoftCo/losangelex`
  - the Codex-derived runtime, app-server, TUI, launcher, and workflow surface
- `FallSoftCo/hollywood`
  - the local room service used for coordination between sessions

The product is the integrated system, not just the fork in isolation.

## Why Losangelex

Losangelex exists because normal single-session coding agents are not enough for the kinds of local autonomous workflows FallSoftCo wants to run.

The project is aimed at:

- multiple local agent sessions coordinating through a shared room
- long-running work that should survive beyond a single interactive turn
- runtime behavior that stays close to upstream Codex instead of diverging into an unmaintainable fork
- local-first experimentation with agent coordination, wakeups, and workflow primitives

In short: Losangelex is the FallSoftCo answer to "what should Codex look like if local multi-agent coordination is treated as a first-class product direction?"

## What Exists Today

### Hollywood-native coordination

Losangelex can attach a thread to a Hollywood room, surface inbound room traffic as typed app-server notifications, and inject focused Hollywood messages into the running thread as structured contextual input.

Current shipped pieces:

- thread-scoped Hollywood attach/detach/attention RPCs
- attention classification in the app-server
- persisted Hollywood resume metadata
- model-visible Hollywood context
- bundled launcher support for automatic Hollywood bootstrap

See:

- [Experimental Hollywood Quickstart](./docs/experimental-hollywood-quickstart.md)
- [Hollywood integration](./codex-rs/docs/hollywood_integration.md)

### Scheduled thread wakeups

Losangelex now includes a minimal persisted scheduler for waking a thread later.

Current shipped pieces:

- one-shot wakeups
- fixed-interval wakeups
- persisted task definitions in SQLite
- persisted run records with `turn_id`
- app-server-hosted execution
- CLI management via `codex schedule ...`

See:

- [Scheduled Tasks](./codex-rs/docs/scheduled_tasks.md)

### Testers

Losangelex also includes managed testers: supervised tester runs that act like interactive user stand-ins instead of fixed scripted transcripts.

Current shipped pieces:

- persisted tester-run definitions, structured reports, and rollout artifacts
- app-server-hosted tester-run supervision
- explicit tester execution classes, including `terminal_full_access`
- hard tool gating for tester sessions, with `terminal_harness` mapped to concrete runtime access
- optional controller-thread wakeups through the scheduler
- CLI management via `codex tester ...`

See:

- [Testers](./codex-rs/docs/testers.md)

### Upstream replay completed

The Hollywood/Losangelex work on this branch has already been replayed onto current upstream instead of remaining on an old pre-merge island. That matters because future work should continue adapting to upstream surfaces, not reviving deleted fork assumptions.

## Architecture

The current architecture is intentionally simple:

```text
Losangelex launcher / CLI / TUI
            |
            v
      codex app-server
            |
            +--> Hollywood room integration
            |
            +--> scheduled task runtime
            |
            +--> persisted thread state in SQLite
            |
            v
        upstream Codex core
```

At a high level:

- Hollywood gives sessions a local coordination plane
- app-server owns thread lifecycle, wakeups, and notifications
- SQLite stores thread metadata, Hollywood metadata, and scheduled tasks
- the bundled launcher makes the stack easier to run with consistent defaults

That division is deliberate. Losangelex additions are meant to compose with upstream runtime ownership rather than bypass it.

## Current Status

This stack is usable, but still experimental.

Expected to work:

- Hollywood room-aware sessions
- per-workspace room bootstrap through the bundled launcher
- app-server-native Hollywood notifications and attachment state
- persisted scheduled wakeups for threads
- current upstream Codex CLI/TUI/app-server behavior plus the Losangelex additions

Not finished yet:

- broader watcher trigger types beyond process-exit and time-based schedules
- richer obligation lifecycle UI for Hollywood traffic
- full workflow-engine semantics
- polished packaging/release flow for non-technical users

## Quickstart

### 1. Clone both repositories

```bash
git clone git@github.com:FallSoftCo/hollywood.git
git clone git@github.com:FallSoftCo/losangelex.git
```

### 2. Start Hollywood

```bash
cd hollywood
python3 -m pip install -e .
./hollywoodctl install
./hollywoodctl health
```

Direct-run path:

```bash
cd hollywood
./hollywood serve
```

Default URL:

```text
http://127.0.0.1:8765
```

### 3. Build Losangelex

```bash
cd ../losangelex/codex-rs
cargo build
```

### 4. Run Losangelex

From any project directory:

```bash
/path/to/losangelex/scripts/losangelex
```

Or put that launcher on your `PATH` and run:

```bash
losangelex
```

The bundled launcher currently does the opinionated local-dev setup for you:

- app-server/TUI path
- full access by default
- no approval prompts
- Hollywood auto-attach
- repo-root-derived `repo/<slug>` room defaults, with `main` observed for discovery
- first-run workspace setup when no room config exists yet

### 5. Start another session

Open another terminal and run `losangelex` again. The intended workflow is multiple local sessions coordinating through the same Hollywood room while remaining independently runnable Codex threads.

### 6. Learn the stack surface

After bootstrap, the main entry points are:

- `scripts/losangelex` for the opinionated local launcher
- `codex app-server` for the runtime host
- `codex schedule ...` for persisted wakeups
- `codex watcher ...` for persisted process-exit watchers
- `codex tester ...` for managed tester runtimes
- Hollywood room traffic and attention policy for multi-agent coordination

## Scheduled Tasks

Losangelex ships CLI management for persisted scheduled wakeups:

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

Current limitation:

- schedules are durable, but they only fire while an app-server process is running

This is the first workflow-oriented primitive in the repo. The next likely directions are:

- watcher-family extensions for condition-based deferred continuations
- task watches as a higher-level time-based reevaluation layer above generic schedules

## Watchers

Losangelex ships CLI management for persisted watcher-based deferred continuations.

Today the shipped trigger is `process_exit`:

```sh
codex watcher add-process-exit \
  --thread-id <THREAD_ID> \
  --session-id <EXEC_SESSION_ID> \
  --title "wait for cargo check" \
  --prompt "Inspect the finished build and summarize any failures."

codex watcher list
codex watcher runs
codex watcher remove <WATCHER_ID>
```

Current behavior:

- watchers are durable, but app-server must be running to claim them and wake the target thread
- the currently shipped trigger is `process_exit` for `exec_command` sessions
- watcher wake prompts include structured context such as elapsed time, exit status, and the original follow-up prompt
- `exec_command` and `write_stdin` now nudge the model toward using a watcher instead of blocking on long waits
- the next watcher-family extension is agent dependency waiting: resume a thread later when another agent reaches a target state, instead of stretching `wait_agent` into a durable blocking primitive

See:

- [Watchers](./codex-rs/docs/watchers.md)
- [Agent Dependency Watchers](./codex-rs/docs/agent_dependency_watchers.md)
- [Periodic Task Watches](./codex-rs/docs/task_watches.md)

## Testers

Losangelex ships CLI management for interactive tester runtimes:

```sh
codex tester create \
  --name "onboarding-check" \
  --objective "Try to deploy the app and report friction." \
  --background "Technical user who is new to this repo." \
  --starting-knowledge "README only" \
  --constraint "Do not read source code" \
  --allowed-interface terminal_harness \
  --execution-class terminal-full-access

codex tester list
codex tester reports --run-id <RUN_ID>
codex tester artifacts <RUN_ID>
codex tester prompt <RUN_ID> --prompt "Continue and investigate the latest failure."
codex tester stop <RUN_ID>
```

Current limitation:

- testers are durable, but app-server must be running to start them, parse structured tester reports, and emit controller wakeups

## Demo

Latest public demo clip of two Losangelex sessions coordinating through Hollywood:

<p align="center">
  <a href="https://rjuniyer.com/semantic-clips/2026-03-20/3dfd439c-02ec-4f4a-bd7f-0a2d4600bfb8-laptop-trial_highlight-landscape.mp4">
    <img src="https://rjuniyer.com/semantic-clips/2026-03-20/3dfd439c-02ec-4f4a-bd7f-0a2d4600bfb8-laptop-trial_highlight-thumb.jpg" alt="Hollywood Losangelex demo thumbnail" width="80%" />
  </a>
</p>

<p align="center">
  <video
    src="https://rjuniyer.com/semantic-clips/2026-03-20/3dfd439c-02ec-4f4a-bd7f-0a2d4600bfb8-laptop-trial_highlight-landscape.mp4"
    poster="https://rjuniyer.com/semantic-clips/2026-03-20/3dfd439c-02ec-4f4a-bd7f-0a2d4600bfb8-laptop-trial_highlight-thumb.jpg"
    controls
    muted
    playsinline
    width="80%">
  </video>
</p>

## Relationship to Upstream Codex

Losangelex is not a clean-room rewrite. It is an upstream-based fork.

What that means in practice:

- upstream Codex remains the base runtime, CLI, TUI, and app-server architecture
- Losangelex-specific behavior should be adapted to upstream surfaces when upstream changes
- if upstream deletes or restructures a subsystem, Losangelex should follow that architecture rather than resurrect old fork-only compatibility layers

That approach is already reflected in the current branch history.

For FallSoftCo work, that means:

- prefer adapting Losangelex behavior to upstream changes
- avoid reintroducing deleted upstream subsystems just to preserve old fork patches
- keep new FallSoftCo features isolated, reviewable, and upstream-compatible where possible

## Roadmap Direction

The current repo has already crossed from "Hollywood experiment" into "workflow/runtime experiment."

The likely next steps are:

- richer watcher trigger types and deferred continuation patterns
- deferred continuations for long-running background conditions
- richer Hollywood obligation lifecycle visibility
- a more general workflow engine built on persisted runs and triggers

That direction should still be implemented in an upstream-adaptive way, not by hard-forking old runtime seams.

## Docs

- [FallSoftCo Hollywood repository](https://github.com/FallSoftCo/hollywood)
- [Experimental Hollywood Quickstart](./docs/experimental-hollywood-quickstart.md)
- [FallSoftCo Hollywood-native integration notes](./docs/hollywood-native-integration.md)
- [Hollywood integration](./codex-rs/docs/hollywood_integration.md)
- [Scheduled Tasks](./codex-rs/docs/scheduled_tasks.md)
- [Watchers](./codex-rs/docs/watchers.md)
- [Testers](./codex-rs/docs/testers.md)
- [App-server README](./codex-rs/app-server/README.md)
- [Installing & building](./docs/install.md)
- [Contributing](./docs/contributing.md)

## License

This repository remains licensed under the [Apache-2.0 License](LICENSE).
