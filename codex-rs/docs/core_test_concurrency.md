# Core Test Concurrency Notes

These notes document intentional Losangelex-specific integration-test hardening in `codex-core`.
They exist so future agents do not “simplify” the tests back to fragile upstream shapes without
understanding why the divergence exists.

## Principles

- Prefer direct evidence of concurrency over whole-turn wall-clock duration.
- Use wall-clock bounds only as a coarse smoke check for obvious accidental serialization.
- Isolate timing-sensitive full-suite tests from each other when they share the same process-level
  contention surface.
- Keep harness defaults quiet; features that add background session work should be opt-in for tests
  unless the test is explicitly about that feature.

## Current Decisions

### Shell Snapshot is disabled by default in core integration tests

`core/tests/common/lib.rs` disables `Feature::ShellSnapshot` in `load_default_config_for_test()`.

Rationale:
- shell snapshots are still covered by dedicated `shell_snapshot` tests
- enabling snapshots in every test session adds background startup and wrapper overhead
- that overhead perturbs unrelated prompt-shape and concurrency assertions during `cargo test`

If a test depends on shell snapshots, enable the feature explicitly in that test.

### Timing-sensitive concurrency tests use a shared serial group

The following tests are intentionally marked `#[serial(parallel_timing)]`:
- `tool_parallelism::{read_file_tools_run_in_parallel,shell_tools_run_in_parallel,mixed_parallel_tools_run_in_parallel}`
- `code_mode::code_mode_nested_tool_calls_can_run_in_parallel`

Rationale:
- these tests exercise real concurrency behavior
- but they also include a coarse end-to-end timing bound
- running several such tests at once inside the same integration binary introduces self-interference
  that is not the product behavior under test

Do not remove the serial group unless the tests are rewritten to rely entirely on direct overlap
proofs and no longer depend on a suite-load-sensitive timing bound.

### Realtime websocket assertions should wait for concrete requests

In `realtime_conversation.rs`, prefer `wait_for_matching_websocket_request(...)` over asserting that
`connections()[0].len() == N` after a short poll loop.

Rationale:
- concrete request matching proves the intended outbound behavior directly
- connection-length polling is a race under full-suite scheduler variance

## Guidance For Future Changes

If a concurrency test fails only under full-suite load:

1. Check whether the product invariant is actually broken in isolation.
2. If isolated behavior is correct, prefer strengthening the test signal over changing production
   runtime behavior.
3. Only use larger timing thresholds as a last resort; that usually hides the real problem.

These notes justify deliberate divergence from `origin/main` when upstream tests rely on brittle
performance proxies rather than the actual runtime invariant.
