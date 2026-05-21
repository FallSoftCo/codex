# Losangelex Published Benchmark Completion Ledger

Last updated: 2026-05-21

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
| Silo-Bench | published task JSON, hidden-path model runs, deterministic scoring | Losangelex full hidden matrices: n=2 22/30, n=5 21/30, n=10 20/30, n=20 19/30; paired Codex baselines complete for n=5 and n=10; full-context oracle complete for n=2/n=5/n=10; all zero coordination-tool errors | strongest positive result; fixed-model claim is speed plus near-tied cohort accuracy, while full-context oracle bounds the coordination value |
| MARBLE database | adapted diagnostic packets plus native PostgreSQL/Docker execution | adapted packet run: both systems 5/5 recall, 0/5 exact-set; native file-query bridge verified on `database-001` for both systems after discovering socket access was blocked | native ten-stratum sample must be rerun with the fixed query bridge before paper use |

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
- Reran the balanced Silo n=5 slice under the hardened managed runner:
  `tmp/research/published-agent-benchmarks/silo-managed-hidden-balanced-n5-2026-05-20`.
  The run used a campaign-local managed app-server, hid the Silo repository by
  default, shut the app-server down after completion, and recorded zero
  coordination-tool errors. Codex solved 2/3 tasks and failed `III-21_n5` with
  `S=P=0.200` after `739.4s`; Losangelex solved 3/3 with average time `92.4s`.
- Regenerated the hardened published-benchmark paper at
  `tmp/research/published-agent-benchmarks/paper-2026-05-20-hardened-published-benchmarks/hardened-published-agent-benchmarks.pdf`
  and retained the coordination topology frontier paper at
  `tmp/research/losangelex-vs-codex/world-class-2026-05-20-policy-frontier/frontier-manuscript.pdf`.
  Both PDFs were emailed through the Ozzz production SESv2 path from
  `seo@fallsoft.co` with configuration set `fallsoftco-vc-access`; SES message
  id:
  `0100019e4722458d-038be9a5-2d32-45dc-97fb-b1be9cedc4b5-000000`.
- Ran complete Losangelex hidden-path Silo matrices beyond the earlier balanced
  slice:
  `tmp/research/published-agent-benchmarks/silo-managed-hidden-n5-full-losangelex-2026-05-20`,
  `tmp/research/published-agent-benchmarks/silo-managed-hidden-n10-full-losangelex-2026-05-20`,
  and
  `tmp/research/published-agent-benchmarks/silo-managed-hidden-n20-full-losangelex-2026-05-20`.
  Results:
  - n=5: 21/30 full successes, strict SR `70.0%`, avg `S=0.807`,
    avg `P=0.826`, mean `113.0s`, zero coordination-tool errors.
  - n=10: 20/30 full successes, strict SR `66.7%`, avg `S=0.733`,
    avg `P=0.779`, mean `133.6s`, zero coordination-tool errors.
  - n=20: 19/30 full successes, strict SR `63.3%`, avg `S=0.715`,
    avg `P=0.759`, mean `211.1s`, zero coordination-tool errors.
  Compared to the Silo-Bench paper's Table 12 public open-model baselines, these
  exceed the strongest published same-scale SR values for n=5 (`48.5%`), n=10
  (`39.9%`), and n=20 (`33.6%`); the prior n=2 Losangelex matrix also exceeds
  the strongest published n=2 value (`73.3%` vs. `61.2%`). Claim language must
  stay narrow: this is a Silo small-to-medium scale frontier result for
  Losangelex+GPT-5.4 under our hardened harness, not an official universal SOTA
  claim.
- Regenerated the hardened published-benchmark paper with the full n=5/n=10/n=20
  Silo matrices and public-baseline table, then emailed the updated paper and
  coordination topology paper through the Ozzz production SESv2 path from
  `seo@fallsoft.co` with configuration set `fallsoftco-vc-access`; SES message
  id:
  `0100019e47feb474-4183351a-85d2-461e-b1e9-962cd749c6b6-000000`.
- After the updated PDF attachments did not open in the recipient mail client,
  validated both local PDFs with `pdfinfo`, packaged both PDFs plus
  `SHA256SUMS.txt` into
  `tmp/research/published-agent-benchmarks/email-redelivery-2026-05-21/losangelex-research-papers-2026-05-21.zip`,
  verified the ZIP locally with `unzip -t`, and resent through Ozzz production
  SESv2 with explicit `ContentTransferEncoding=BASE64` on every attachment.
  Redelivery SES message id:
  `0100019e4802159a-31672adc-0c3c-4f72-8a6d-c8219e26f9c2-000000`.

### 2026-05-21

- Added a paper-completion gate so future sessions do not present the current
  papers as final/world-class until the evidence separates fixed-model runtime
  effects, single-agent full-context oracle performance, and non-Silo benchmark
  generality.
- Completed the full paired Codex n=5 Silo matrix:
  `tmp/research/published-agent-benchmarks/silo-managed-hidden-n5-full-codex-2026-05-21`.
  Codex finished 20/30 strict successes, avg `S=0.700`, avg `P=0.714`,
  mean `422.1s`, and zero coordination-tool errors. Combined with the completed
  Losangelex n=5 matrix at
  `tmp/research/published-agent-benchmarks/silo-managed-hidden-n5-full-paired-2026-05-21`:
  Losangelex finished 21/30 strict successes, avg `S=0.807`, avg `P=0.826`,
  mean `113.0s`, and zero coordination-tool errors. Paired task deltas:
  Losangelex had higher strict/partial score on four tasks, Codex on one task,
  and 25 ties; Losangelex was faster on all 30 tasks with mean Codex/Losangelex
  runtime ratio about `3.84x`.
- Added a `codex-full-context` Silo runner mode. It gives one Codex execution
  all original private shards for a task, writes the same per-agent submission
  files, and uses the existing deterministic Silo scorer. This is the planned
  single-agent oracle needed for the coordination-effect gate.
- Added a native MARBLE database evidence mode. `--evidence-mode
  native-postgres` starts the published MARBLE Docker/PostgreSQL substrate with
  a campaign-local compose override, avoids fixed host-port bindings, pins the
  Postgres service to `postgres:16` for compatibility with the published volume
  layout, prepares live root-cause workloads, and gives agents a workspace
  `query_db.py` client backed by a temporary Unix socket query server.
- Validated the native MARBLE substrate without a model run at
  `tmp/research/published-agent-benchmarks/marble-native-postgres-smoke-2026-05-21`.
  The smoke started Docker/PostgreSQL, injected the published `database-001`
  workload, queried `pg_stat_statements` through the generated workspace client,
  returned code `0`, and confirmed the live `INSERT` workload had `20000` rows
  in query statistics. Teardown left no MARBLE containers running.
- Completed the full paired Codex n=10 Silo matrix:
  `tmp/research/published-agent-benchmarks/silo-managed-hidden-n10-full-codex-2026-05-21`.
  Codex finished 21/30 strict successes, avg `S=0.727`, avg `P=0.780`,
  mean `835.5s`, and zero coordination-tool errors. Combined with the completed
  Losangelex n=10 matrix at
  `tmp/research/published-agent-benchmarks/silo-managed-hidden-n10-full-paired-2026-05-21`:
  Losangelex finished 20/30 strict successes, avg `S=0.733`, avg `P=0.779`,
  mean `133.6s`, and zero coordination-tool errors. Paired task deltas:
  Losangelex had higher strict/partial score on three tasks, Codex on two tasks,
  and 25 ties; Losangelex was faster on all 30 tasks with mean
  Codex/Losangelex runtime ratio about `6.56x`.
- The fixed-model paired Silo gate is now satisfied for n=5 and n=10. It does
  not by itself support a broad SOTA claim: n=5 favors Losangelex on
  correctness and speed, while n=10 is essentially accuracy-tied with Codex one
  strict success ahead and Losangelex much faster.
- Completed the single-agent full-context Silo oracle for n=2, n=5, and n=10:
  `tmp/research/published-agent-benchmarks/silo-full-context-oracle-n2-2026-05-21`,
  `tmp/research/published-agent-benchmarks/silo-full-context-oracle-n5-2026-05-21`,
  and
  `tmp/research/published-agent-benchmarks/silo-full-context-oracle-n10-2026-05-21`.
  Results:
  - n=2: 25/30 full successes, avg `S=0.833`, avg `P=0.845`, mean `27.2s`.
  - n=5: 25/30 full successes, avg `S=0.833`, avg `P=0.846`, mean `39.2s`.
  - n=10: 24/30 full successes, avg `S=0.800`, avg `P=0.814`, mean `52.8s`.
  All runs recorded zero coordination-tool errors.
- The oracle result sharply limits the coordination-value claim: for Silo, a
  same-model single execution with all shards visible beats both Losangelex and
  ordinary Codex cohorts on correctness at n=5 and n=10, while also being faster.
  The meaningful current Losangelex result is therefore not "better than full
  context"; it is that the native room runtime can match or improve ordinary
  same-model Codex cohort accuracy while reducing wall-clock time by large
  factors.
- Fixed native MARBLE hidden-path timing so the benchmark repository is hidden
  during model execution but not while the harness starts or tears down the
  Docker/PostgreSQL substrate. The failed pre-fix run was caused by chmod hiding
  the published `db_env_docker` compose directory before Docker setup.
- Completed the first paired native MARBLE model-in-the-loop smoke:
  `tmp/research/published-agent-benchmarks/marble-native-postgres-paired-database-001-fix-2026-05-21`.
  On `database-001`, both systems achieved root-cause recall `1.000`, both
  missed strict exact-set match by over-predicting one extra label, and both
  recorded zero coordination-tool errors. Codex predicted
  `INSERT_LARGE_DATA,FETCH_LARGE_DATA` in `527.4s`; Losangelex predicted
  `INSERT_LARGE_DATA,LOCK_CONTENTION` in `146.9s`. Docker/PostgreSQL teardown
  left no MARBLE containers running.

## Blocking Losangelex Work

## World-Class Paper Completion Gate

Do not present the current paper as final or world-class until the evidence
separates at least three effects:

1. **Runtime effect at fixed model.** Same published task set, same model, same
   hidden-path rules, comparing ordinary Codex cohorts against Losangelex rooms.
   Minimum bar: full paired Silo n=5 and n=10 matrices, not just the existing
   n=2 matrix and n=5 balanced slice. Status: complete for Silo n=5 and n=10.
2. **Coordination effect versus single-agent oracle.** Same model receives the
   full Silo input in one prompt, scored by the same deterministic Silo scorer.
   This tells us whether multi-agent coordination is adding value or only
   recovering part of the single-agent full-context performance. Status:
   complete for Silo n=2, n=5, and n=10; the oracle currently outperforms both
   cohort systems on correctness.
3. **Benchmark generality.** At least one native non-Silo multi-agent benchmark
   path is real, not adapted. The preferred target is native MARBLE database
   execution with the benchmark's Docker/PostgreSQL substrate. Status: substrate
   smoke and single-task file-query bridge model smokes are complete; the
   earlier ten-stratum native sample is invalid as DB-grounded evidence because
   sandboxed agents could not access the Unix-socket helper. Rerun the
   ten-stratum sample with the file-query bridge before paper regeneration.

The world-class paper should make only claims justified by those gates:

- It may claim a **Silo-Bench small-to-medium scale frontier** if Losangelex
  continues to exceed published same-scale Silo baselines and matched fixed-model
  controls remain favorable.
- It may claim **native runtime value** only if fixed-model paired Codex-vs-
  Losangelex matrices show a meaningful correctness, time, or coordination-error
  advantage.
- It must not claim universal multi-agent SOTA until native MARBLE, broader
  SWE-bench, and larger-scale Silo evidence support that.

### Execution Plan Across Sessions

1. Done: run full paired Codex n=5 Silo matrix with the same `gpt-5.4` model
   and hidden benchmark paths; combine with the completed Losangelex n=5 matrix.
2. Done: run full paired Codex n=10 Silo matrix; combine with the completed
   Losangelex n=10 matrix.
3. Done: add and run a single-agent Silo full-context baseline for n=2, n=5,
   and n=10.
4. Repeat the most claim-sensitive Silo scales/tasks for variance, especially
   n=5/n=10 and failure-prone tasks `II-12`, `III-25`, `III-27`, and `III-28`.
5. Implement native MARBLE database execution and score recall, exact match,
   precision, runtime errors, and coordination-tool errors.
6. Expand SWE-bench from the current three-instance negative-control slice to a
   stratified sample that includes multi-file and dependency-chain issues.
7. Regenerate the papers only after the above results are complete, then email
   through Ozzz production SES using explicit base64 attachment encoding and ZIP
   fallback.

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

Current status:

- The native Docker/PostgreSQL substrate now starts from the harness and was
  validated without a model run on `database-001`.
- One paired Codex/Losangelex model-in-the-loop smoke is complete on
  `database-001` with recall `1.000` for both systems, strict exact-set miss for
  both systems, zero coordination-tool errors, and clean Docker teardown.
- A ten-stratum paired native-postgres sample was attempted across one task
  from each published database root-cause stratum. Combined artifacts:
  - partial first campaign:
    `tmp/research/published-agent-benchmarks/marble-native-postgres-paired-stratified-10-2026-05-21/results.json`
  - remaining fixed campaign:
    `tmp/research/published-agent-benchmarks/marble-native-postgres-paired-stratified-remaining-9-2026-05-21/results.json`
  - sampled tasks: `database-001`, `database-003`, `database-005`,
    `database-006`, `database-007`, `database-051`, `database-052`,
    `database-056`, `database-058`, `database-059`.
- Validity finding: the attempted ten-stratum sample is **not valid native
  database evidence**. Failure-trace inspection showed sandboxed model runs were
  blocked from the Unix-socket helper with `PermissionError: [Errno 1]
  Operation not permitted`; the result therefore measures fallback behavior
  under missing DB evidence, not live PostgreSQL diagnosis.
- Invalid sample results, retained only as a failure corpus:
  - Codex: 10 tasks, 3 full-recall successes, 1 exact-set match, avg recall
    `0.450`, avg precision `0.333`, mean seconds `403.6`, coordination-tool
    errors `0`.
  - Losangelex: 10 tasks, 3 full-recall successes, 0 exact-set matches, avg
    recall `0.500`, avg precision `0.350`, mean seconds `143.7`,
    coordination-tool errors `0`.
  - Paired recall deltas: Losangelex higher on 3 tasks (`database-001`,
    `database-005`, `database-052`), Codex higher on 3 tasks
    (`database-003`, `database-058`, `database-059`), 4 ties
    (`database-006`, `database-007`, `database-051`, `database-056`).
  - Runtime: Losangelex faster on all 10 paired tasks; mean Codex/Losangelex
    runtime ratio `2.84x`, median `2.62x`.
  - Failure signal: both systems over-predict insert/fetch in several native DB
    cases; redundant-index and vacuum detection need focused inspection before
    the paper uses MARBLE as strong evidence.
- Harness fixes made during the sample:
  - `wide_table_sql` now accepts MARBLE `colsize` settings instead of failing
    redundant/fetch/vacuum setup with `TypeError`.
  - future result JSON/report summaries now include explicit root-cause
    precision and F1 in addition to recall and exact set match.
  - the native query helper now uses a workspace file-request bridge instead of
    an out-of-workspace Unix socket, avoiding sandbox `connect()` denial while
    keeping SQL execution in the harness.
- Bridge validation after the fix:
  - deterministic local smoke:
    `tmp/research/published-agent-benchmarks/marble-native-file-query-bridge-local-smoke-2026-05-21`;
    `./query_db.py` returned live `pg_stat_statements` output.
  - Losangelex model smoke:
    `tmp/research/published-agent-benchmarks/marble-native-file-query-bridge-losangelex-smoke-2026-05-21/results.json`;
    `database-001`, recall `1.000`, precision `0.500`, F1 `0.667`, `131.6s`,
    zero coordination-tool errors, 18 logged SQL queries, no permission errors.
  - Codex model smoke:
    `tmp/research/published-agent-benchmarks/marble-native-file-query-bridge-codex-smoke-2026-05-21/results.json`;
    `database-001`, recall `1.000`, precision `0.500`, F1 `0.667`, `415.8s`,
    zero coordination-tool errors, 13 logged SQL queries, no permission errors.
- Remaining work: rerun the ten-stratum native MARBLE sample with the file-query
  bridge, then inspect failure traces and expand toward a larger stratified
  subset or full 100-task database run.

### L5. Larger Objective Silo Matrix

Done means:

- hidden-path runs cover levels I, II, and III;
- n=2 and n=5 are complete, n=10 is attempted if cost permits;
- repeated runs are added for variance on at least the highest-value task IDs;
- S/P/C/D metrics are reported using Silo-compatible scoring.

Current status:

- The managed hidden-path n=2 sweep is complete across levels I/II/III and
  combined into one provenance-preserving artifact.
- Complete Losangelex hidden-path matrices are now available for n=5, n=10, and
  n=20, all with managed app-server metadata, default hidden Silo repository
  paths, teardown, and zero coordination-tool errors.
- Full paired fixed-model Codex comparisons are now available for n=5 and n=10.
- Full-context oracle baselines are now available for n=2, n=5, and n=10.
- Remaining work: repeat the highest-value scales/tasks for variance and decide
  whether to attempt n=50/n=100 despite cost/concurrency.

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

## World-Class Paper Execution Contract

This section is the durable plan for continuing the benchmark program across
many sessions without restarting or relying on memory.

### Research Objective

Produce an empirically useful academic-style paper on Losangelex/Hollywood
multi-agent coordination versus same-model Codex agent cohorts. The central
question is not "is multi-agent always better?" but:

- when does a coordinated Losangelex room improve same-model cohort behavior;
- when does single-agent full-context execution dominate both cohort designs;
- what latency/coordination/error tradeoffs appear under objective scoring;
- which benchmark classes actually measure multi-agent value rather than
  prompt decomposition alone.

### Paper-Grade Standards

- Use published or reproducible benchmark tasks wherever possible.
- Keep answer keys, benchmark repositories, labels, and previous results hidden
  from model workspaces during execution.
- Use paired same-model comparisons on the same task instances.
- Report exact task IDs, model, runner commit, hidden paths, runtime settings,
  scoring script, and raw result artifact paths.
- Report negative results and ceiling baselines. Full-context oracle results are
  part of the paper, not a nuisance.
- Separate claims by evidence strength:
  - Supported now: Losangelex can match or improve ordinary same-model Codex
    cohort accuracy on Silo while cutting wall-clock time substantially.
  - Supported now: full-context single-agent oracle remains stronger on Silo
    correctness, so Losangelex is not a universal replacement for context
    aggregation.
  - Not yet supported: SOTA claims on published leaderboards.
  - Not yet supported: benchmark-general claims beyond Silo until native MARBLE
    and SWE-bench expansion finish.
- Regenerate PDFs only after benchmark tables are stable, then verify the PDFs
  open before sending.
- Send final paper artifacts through the existing Ozzz SES production path and
  record SES message IDs in this ledger.

### Current Evidence Snapshot

- Silo hidden-path paired n=5 is complete: Losangelex has higher strict/partial
  score on 4 tasks, Codex on 1, 25 ties, and Losangelex is faster on all 30.
- Silo hidden-path paired n=10 is complete: Codex has one more strict success,
  Losangelex has near-identical average S/P, and Losangelex is faster on all
  30 tasks with about a 6.56x mean Codex/Losangelex runtime ratio.
- Silo full-context oracle is complete for n=2/n=5/n=10 and is more accurate
  and faster than both cohort systems, which sharply limits any simplistic
  "multi-agent beats single-agent" claim.
- Native MARBLE PostgreSQL now has a validated file-query bridge for sandboxed
  model runs. The earlier ten-stratum sample is invalid as DB-grounded evidence
  because agents could not query the live database; rerun it before using MARBLE
  in the paper.

### Execution Queue

1. Native MARBLE: rerun the ten-stratum native-postgres sample with the
   workspace file-query bridge.
2. Native MARBLE: inspect the valid ten-stratum failure traces, especially
   redundant-index, vacuum, and insert/fetch over-prediction cases.
3. Native MARBLE: if the stratified sample is stable, expand toward the full
   100-task database set or a power-justified larger stratified subset.
4. Silo variance: repeat the highest-value n=10 tasks where systems disagree
   and estimate paired variance over correctness and runtime.
5. SWE-bench: add a stratified sample that includes multi-file, ambiguous
   ownership, dependency-chain, and verifier-heavy tasks. Keep tiny single-file
   tasks as negative controls.
6. App-build/coordination evals: preserve them as ecological support, not as
   the primary objective benchmark evidence.
7. Analysis: compute paired deltas, confidence intervals or bootstrap intervals,
   runtime distributions, coordination-tool error rates, and failure taxonomy.
8. Paper: regenerate tables, figures, abstract, related work, threats to
   validity, and conclusion from the frozen artifacts.
9. Delivery: build and open-check PDFs, send by SES through Ozzz, and record
   message IDs here.

### Current Next Step

Rerun the native MARBLE ten-stratum sample with the fixed file-query bridge,
then commit and push both configured Losangelex remotes to the same branch tip.
