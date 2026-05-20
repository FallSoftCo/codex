# Losangelex Published Benchmark Completion Ledger

Last updated: 2026-05-20

## Goal

Produce research-grade papers that compare Losangelex/Hollywood native agent
teams against Codex agent baselines on published benchmarks, with enough
execution hygiene that negative and positive results are both publishable.

The durable standard is:

- benchmark answer keys are unreachable during model-in-the-loop execution;
- native Losangelex runtime failures are scored as outcomes, not hidden in logs;
- each benchmark family has a stated evidence mode and threat model;
- every claim traces to raw result artifacts and reproducible runner commands;
- paper PDFs are generated and emailed through the Ozzz production SES path.

## Current Evidence

| Benchmark family | Evidence mode | Current result | Paper status |
| --- | --- | --- | --- |
| Coordination topology frontier | controlled model-in-the-loop synthetic coordination | 270 GPT-5.4 trials; topology changes calls/tokens/errors with success held constant | paper PDF generated and emailed |
| SWE-bench Lite | official SWE-bench scoring | Codex 3/3, Losangelex 3/3; Losangelex slower | included as negative-control slice |
| Silo-Bench | published task JSON, hidden-path model runs, deterministic scoring | n=5 balanced hidden slice: Codex 2/3, Losangelex 3/3 | strongest positive result |
| MARBLE database | adapted diagnostic-observation packets, deterministic scoring | both systems 5/5 recall, 0/5 exact-set match | useful but not native MARBLE |

## Session Log

### 2026-05-20

- Wrote this ledger so the benchmark program can survive context/session
  boundaries.
- Implemented the first L2 runtime fix: generated benchmark identities such as
  `marble-db-agent1-7c45ba` and `silo-agent-002-5b254e` now resolve from short
  benchmark mentions such as `agent1` and `agent-002`, while ambiguous short
  names still fail deterministically.
- Verification completed before fixer cleanup:
  `cargo test -p codex-core live_identity_matches_target_accepts_exact_and_generated_runtime_suffixes`
  and `cargo test -p codex-core resolve_live_session_id_from_entries`.
- `just fmt` could not complete its Python ruff phase on this Linux host because
  the pinned `openai-codex-cli-bin==0.131.0a4` has no compatible wheel; Rust
  formatting was run directly with `cargo fmt -- --config imports_granularity=Item`.
  `just fix -p codex-core` completed.
- A follow-up MARBLE diagnostic validity probe exposed that attached app-server
  threads were not published to the Hollywood registry at all. A second probe
  confirmed registry rows existed but only carried UUID aliases, not benchmark
  runtime names. The app-server attach path now publishes a registry heartbeat
  immediately after `thread/hollywood/attach` and uses stored `thread/name/set`
  metadata so entries include identities such as `marble-db-agent5-b68b8c`.
- Live validation after the app-server fix:
  `tmp/research/published-agent-benchmarks/marble-db-validity-l2-named-registry-2026-05-20`.
  Case `database-001` completed with recall `1.000`, exact-set match `false`,
  no captured `unknown live Hollywood agent`, no MCP auth contamination under a
  throwaway `CODEX_HOME`, and five exact-room registry entries containing
  runtime identities.
- Implemented periodic app-server registry refresh for attached Hollywood
  sessions. The listener now upserts registry snapshots on the existing
  15-second sync cadence and at turn start/turn completion, preserving runtime
  names from `thread/name/set`.
- Live heartbeat validation:
  `tmp/research/published-agent-benchmarks/marble-db-heartbeat-validity-2026-05-20`.
  Case `database-001` ran for `97.7s`, completed with recall `1.000` and exact
  set match `true`, and the exact room had five registry entries with runtime
  identities and fresh `last_heartbeat_at` timestamps after the former 90-second
  staleness boundary.
- Remaining L2 gap: benchmark runners still need to count unknown-agent,
  invalid-agent, and malformed coordination-tool errors in result JSON instead
  of relying on ad hoc log scans.
- Added shared benchmark notification analysis for Losangelex coordination tools.
  Future MARBLE, Silo, SWE-bench, and app-build records now include
  `coordinationToolSummary` with total calls, error calls by tool/thread/category,
  and bounded examples; MARBLE and Silo Markdown summaries include coordination
  error totals.
- Hardened the published Silo and MARBLE runners so their benchmark repositories
  are hidden by default during agent execution. The result JSON records the
  effective `hiddenPaths` and whether default hiding was enabled.
- Added managed benchmark app-server startup for Silo and MARBLE. When
  Losangelex runs do not pass `--app-server-url`, the runners now create an
  isolated campaign-local `CODEX_HOME`, copy only auth identity files, start
  `codex app-server`, record URL/log/PID/home metadata in `results.json`, and
  shut the server down after the campaign. `--reuse-current-app-server` preserves
  the old current-server path for debugging.
- Live managed-run validation:
  `tmp/research/published-agent-benchmarks/marble-db-managed-l1-smoke-2026-05-20`.
  The result JSON records a managed app-server, campaign-local `codex-home`,
  default hidden MARBLE repo path, and zero coordination-tool errors; the managed
  app-server was unreachable after runner exit, confirming teardown.
- A full managed hidden-path Silo n=2 sweep reached 48 scored records before
  exposing a level III scorer defect on `III-25_n2`: some expected sequence
  items are nested lists and therefore cannot be used directly as dictionary
  keys. The level III LIS partial-correctness scorer now canonicalizes nested
  sequence values before matching them. The completed portion is preserved at
  `tmp/research/published-agent-benchmarks/silo-managed-hidden-n2-2026-05-20`;
  the remaining `III-25_n2` through `III-30_n2` tail still needs to be rerun
  with the fixed scorer.
- Reran the Silo level III n=2 tail and combined it with the completed records:
  `tmp/research/published-agent-benchmarks/silo-managed-hidden-n2-combined-2026-05-20`.
  Both systems finished 22/30 full-success tasks with average `S=0.750`,
  average `P=0.762`, and zero coordination-tool errors. Losangelex averaged
  `88.3s` per task versus Codex `126.8s`; by level, both systems were 10/10 on
  level I, 7/10 on level II, and 5/10 on level III.

## Blocking Losangelex Work

### L1. Benchmark-Safe Runtime Mode

Done means:

- app-server startup works from a minimal benchmark `CODEX_HOME`;
- user MCP/plugin/email/reviewer config cannot affect benchmark runs;
- every runner records the effective `CODEX_HOME`, app-server URL, model, and
  feature flags;
- a failed app-server startup becomes a benchmark record rather than a harness
  crash.

Current status:

- Silo and MARBLE have managed isolated app-server startup and campaign-level
  app-server metadata.
- A MARBLE smoke run validated managed startup, hidden-path defaults,
  coordination-tool summary emission, and teardown.
- Remaining work: SWE-bench and app-build runners still need the same managed
  startup path, and startup failures should be represented as scored benchmark
  records instead of process-level failures.

### L2. Hollywood Identity and Tool Routing

Done means:

- published agent names like `agent1`, `agent-001`, and generated runtime names
  like `marble-db-agent1-abc123` resolve to the correct live thread;
- `hollywood_team_member_update` and related tools do not emit `unknown live
  Hollywood agent` for fresh attached agents in benchmark rooms;
- ambiguous names fail with a deterministic ambiguity error;
- benchmark reports include counts of unknown-agent, invalid-agent, and
  malformed coordination-tool calls.

Current status:

- Short benchmark mentions now resolve against generated runtime identities.
- App-server attach now publishes registry entries with stored runtime thread
  names.
- App-server listener heartbeats now refresh active registry entries during long
  turns and immediately at turn boundaries.
- Benchmark runners now count coordination-tool errors in result JSON for future
  runs.
- L2 is complete for the current published-runner surface; rerun benchmark
  campaigns before paper regeneration so the archived result JSON carries these
  fields.

### L3. Answer-Key Isolation

Done means:

- all published benchmark runners hide benchmark repos, previous result roots,
  labels, and answer files during agent execution by default;
- the runners record which paths were hidden;
- invalid leakage attempts are detected from stdout/stderr/last-message traces
  where possible and scored as invalid runs.

Current status:

- Silo and MARBLE now hide their published benchmark repositories by default and
  still record all hidden paths.
- Remaining work: default hiding should also cover previous result roots where
  practical, and leakage attempts should become explicit invalid-run metadata
  instead of post-hoc manual review.

### L4. Native MARBLE Database

Done means:

- the MARBLE database Docker/PostgreSQL environment runs from the harness;
- agents receive live SQL/tool observations instead of generated diagnostic
  packets;
- scoring reports both published recall and strict exact-set/precision metrics;
- runtime/log errors are included in the result JSON.

### L5. Larger Objective Silo Matrix

Done means:

- hidden-path runs cover levels I, II, and III;
- n=2 and n=5 are complete, n=10 is attempted if cost permits;
- repeated runs are added for variance on at least the highest-value task IDs;
- S/P/C/D metrics are reported using Silo-compatible scoring.

Current status:

- The managed hidden-path n=2 sweep is complete across levels I/II/III and
  combined into one provenance-preserving artifact.
- Remaining work: add n=5 repeats and decide whether to start an n=10 attempt.

### L6. Stratified SWE-bench Expansion

Done means:

- small single-file tasks remain as negative controls;
- sample includes multi-file, ambiguous ownership, dependency-chain, and
  verifier-heavy issues;
- official SWE-bench scoring is run with prebuilt images where available;
- Losangelex overhead and coordination pathologies are reported alongside
  resolved/not-resolved.

## Execution Order

1. Fix L2 identity/tool routing.
2. Harden L1 benchmark runtime setup in the runners.
3. Make L3 hidden-path execution the default for Silo and MARBLE runners.
4. Run the larger Silo matrix.
5. Implement native MARBLE DB execution.
6. Expand SWE-bench stratified slice.
7. Regenerate papers, send through Ozzz SES, and record message IDs.

## Resume Checklist for Future Sessions

1. `cd /home/ai/Development/losangelex`
2. `git status --short`
3. Read this ledger.
4. Check latest pushed tip on both remotes:
   `git ls-remote fallsoftco refs/heads/hollywood-native-integration-clean`
   and `git ls-remote fork refs/heads/hollywood-native-integration-clean`.
5. Continue from the first incomplete blocker above.
