# Experimental Hollywood Quickstart

This is the primary entrypoint for the experimental Losangelex + Hollywood stack.

Use this document if you want to clone both repositories, start the local
coordination service, and run a Hollywood-aware Losangelex build with the
smallest possible amount of branching.

## What You Are Setting Up

You are running two separate repositories together:

- `FallSoftCo/losangelex`
  - the experimental Codex fork with native Hollywood-aware runtime behavior
- `FallSoftCo/hollywood`
  - the local room service used for multi-agent coordination

The integrated stack is the product. Hollywood is required if you want the
room-aware behavior described here.

## Status

This setup is experimental.

What is expected to work:

- attaching Codex threads to a Hollywood room
- surfacing inbound room traffic as thread-scoped notifications
- model-visible Hollywood context
- environment-based auto-attach in the TUI flow

What is not yet guaranteed:

- stable packaging/release compatibility across published versions
- fully first-class core semantics for external Hollywood messages
- polished onboarding for non-technical users

## Requirements

Required:

- Python 3
- Rust toolchain with `cargo`
- two local checkouts: `losangelex` and `hollywood`

Optional but recommended:

- `git`
- a second terminal window for a second Losangelex session
- `python3 -m pip install -e .` in the Hollywood repo instead of running the
  checked-in scripts directly

## Fast Path

### 1. Clone Both Repositories

```bash
git clone git@github.com:FallSoftCo/hollywood.git
git clone git@github.com:FallSoftCo/losangelex.git
```

If you are working locally before publication, replace the GitHub paths with
your local checkout locations.

### 2. Install and Start Hollywood

```bash
cd hollywood
python3 -m pip install -e .
./hollywoodctl install
./hollywoodctl health
```

If you do not want the managed service path yet, run it directly:

```bash
cd hollywood
./hollywood serve
```

Default URL: `http://127.0.0.1:8765`

### 3. Build Losangelex

```bash
cd ../losangelex/codex-rs
cargo build
```

### 4. Export the Shared Hollywood Environment

Run these in each terminal where you want a Hollywood-aware Losangelex session:

```bash
export HOLLYWOOD_AUTO_ATTACH=1
export HOLLYWOOD_URL=http://127.0.0.1:8765
export HOLLYWOOD_ROOM=main
export HOLLYWOOD_ATTENTION_MODE=focused
```

Required:

- `HOLLYWOOD_AUTO_ATTACH=1`
- `HOLLYWOOD_URL`
- `HOLLYWOOD_ROOM`

Optional:

- `HOLLYWOOD_ATTENTION_MODE`
  - `focused` is the recommended default
  - `ambient` and `broad` are noisier modes for heavier room visibility

### 5. Start Losangelex

From the `losangelex` repository root:

```bash
just codex
```

Or directly from the Rust workspace:

```bash
cd codex-rs
cargo run --bin codex
```

### 6. Start a Second Session

Open a second terminal, export the same Hollywood environment, and start
Losangelex again.

That gives you two sessions attached to the same room.

### 7. Confirm the Integration

Expected behavior:

- each session should auto-attach to the Hollywood room during bootstrap
- room traffic can be surfaced to the runtime as Hollywood context
- direct mentions and configured room escalation should be treated as attention
  signals

For a manual service-side check, you can also inspect room traffic directly:

```bash
cd /path/to/hollywood
./hollywood tail --agent-id "$CODEX_THREAD_ID" --cursor --from-now
```

## Recommended First Demo

1. Start two Losangelex sessions with the same Hollywood environment.
2. In session one, work on a normal coding task.
3. In session two, ask it to inspect Hollywood room traffic and coordinate with
   the other session.
4. Confirm that the second session can see room activity and that the first
   session can continue working without treating every message as a command.

## What Is Required vs Optional

Required for the integrated experience:

- both repositories
- a running Hollywood service
- Hollywood environment variables in the Losangelex session environment

Optional:

- `hollywoodctl install` instead of `./hollywood serve`
- multiple extra sessions beyond the first two
- manual `hollywood send` / `poll` / `tail` usage outside Losangelex

## Where To Go Next

- For the runtime integration details, see
  [`codex-rs/docs/hollywood_integration.md`](../codex-rs/docs/hollywood_integration.md).
- For the app-server protocol/API details, see
  [`codex-rs/app-server/README.md`](../codex-rs/app-server/README.md).
- For the standalone Hollywood service details, see
  `FallSoftCo/hollywood`:
  `README.md`, `FALLSOFTCO_INSTALL.md`, and the `examples/` directory.

## Current Gap

This document is the intended primary onboarding path, but it should still be
verified from a clean machine before claiming fully turnkey external adoption.
