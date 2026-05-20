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

## Blocking Losangelex Work

### L1. Benchmark-Safe Runtime Mode

Done means:

- app-server startup works from a minimal benchmark `CODEX_HOME`;
- user MCP/plugin/email/reviewer config cannot affect benchmark runs;
- every runner records the effective `CODEX_HOME`, app-server URL, model, and
  feature flags;
- a failed app-server startup becomes a benchmark record rather than a harness
  crash.

### L2. Hollywood Identity and Tool Routing

Done means:

- published agent names like `agent1`, `agent-001`, and generated runtime names
  like `marble-db-agent1-abc123` resolve to the correct live thread;
- `hollywood_team_member_update` and related tools do not emit `unknown live
  Hollywood agent` for fresh attached agents in benchmark rooms;
- ambiguous names fail with a deterministic ambiguity error;
- benchmark reports include counts of unknown-agent, invalid-agent, and
  malformed coordination-tool calls.

### L3. Answer-Key Isolation

Done means:

- all published benchmark runners hide benchmark repos, previous result roots,
  labels, and answer files during agent execution by default;
- the runners record which paths were hidden;
- invalid leakage attempts are detected from stdout/stderr/last-message traces
  where possible and scored as invalid runs.

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
