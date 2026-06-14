# Losangelex Published Benchmark Completion Ledger

Last updated: 2026-05-22

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
| Silo-Bench | published task JSON, hidden-path model runs, deterministic scoring | Losangelex full hidden matrices: n=2 22/30, n=5 21/30, n=10 20/30, n=20 19/30; paired serial Codex baselines complete for n=5 and n=10; true Codex-subagent baselines complete for n=5 at 24/30 strict and n=10 at 23/30 strict; full-context oracle complete for n=2/n=5/n=10 | strongest objective result; fixed-model claim is speed plus cohort reliability, while Codex-subagents and full-context oracle bound the coordination value |
| MARBLE database | native PostgreSQL/Docker execution, hidden benchmark paths, deterministic root-cause scoring | final-primary 30-task holdout complete: serial Codex 30/30 full-recall successes, true Codex-subagents 29/30, Losangelex 30/30; avg precision/F1 `0.583/0.733`, `0.617/0.742`, `0.594/0.740`; mean runtime `393.7s`, `184.0s`, `160.2s`; coordination errors `0`/`25`/`0` | held-out native result is included in the 2026-05-22 paper PDF and emailed through SES |

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

### 2026-05-22

- Completed and recorded the full observed-development Silo n=5 and n=10 true
  Codex-subagent matrices. Codex-subagents beat serial Codex and Losangelex on
  strict Silo success count at both scales, but were slower than Losangelex and
  substantially noisier in coordination-tool errors; full-context Codex remained
  the Silo correctness/runtime ceiling.
- Repeated the observed 20-task native MARBLE true Codex-subagent baseline for
  variance. The repeat again reached 20/20 full-recall successes, with avg
  precision `0.583`, avg F1 `0.733`, mean `197.0s`, and 13 router errors.
- Completed a non-holdout native MARBLE development-extension campaign on 20
  additional database tasks with all three systems:
  `tmp/research/published-agent-benchmarks/marble-native-development-extension-all-systems-2026-05-22/results.json`.
  All systems reached 20/20 benchmark-aligned full recall, 0/20 exact-set
  matches, avg precision `0.583`, and avg F1 `0.733`. Mean runtime was serial
  Codex `403.3s`, true Codex-subagents `234.6s`, and Losangelex `159.3s`.
  Coordination-tool/router errors were serial Codex `0`, true Codex-subagents
  `31`, and Losangelex `0`. Post-run hygiene scan found no permission,
  previous-result, answer-key, gold-label, published-repo, `SPAWN_FAILED`, or
  shell-fallback hits, and Docker/PostgreSQL teardown left no MARBLE containers
  running.
- Interpretation: this extension does not create a MARBLE score advantage for
  Losangelex over true Codex-subagents; it supports a narrower systems claim
  that Losangelex matches Codex-subagent benchmark recall/F1 on this development
  slice while reducing mean wall-clock time by about `1.47x` and avoiding the
  observed subagent router-error/tail-latency profile.
- Combined with the prior observed 20-task native MARBLE all-system evidence
  using the conservative repeated Codex-subagent run for that slice, the current
  40-task development table is: serial Codex 39/40 full-recall successes, true
  Codex-subagents 40/40, Losangelex 40/40; serial/Codex-subagents/Losangelex
  mean runtimes `406.6s`/`215.8s`/`153.8s`; avg precision/F1
  `0.571/0.717`, `0.583/0.733`, and `0.583/0.733`; coordination errors
  `0`/`44`/`0`. Losangelex was faster than serial Codex on 40/40 tasks and
  faster than Codex-subagents on 39/40 tasks.
- Completed the locked native MARBLE final-primary all-system holdout:
  `tmp/research/published-agent-benchmarks/marble-native-final-primary-all-systems-2026-05-22/results.json`.
  - Tasks: `database-010`, `database-016`, `database-017`, `database-018`,
    `database-023`, `database-024`, `database-025`, `database-027`,
    `database-031`, `database-032`, `database-034`, `database-035`,
    `database-036`, `database-037`, `database-041`, `database-065`,
    `database-068`, `database-069`, `database-071`, `database-072`,
    `database-073`, `database-077`, `database-079`, `database-081`,
    `database-082`, `database-083`, `database-087`, `database-088`,
    `database-089`, and `database-091`.
  - Post-run hygiene scan found no permission errors, answer-key/gold-label
    leakage hits, published-repository references, `codex exec` leakage,
    `SPAWN_FAILED` markers, or shell-fallback strings in run/workspace files.
    Docker/PostgreSQL teardown left no MARBLE containers running.
  - Serial Codex cohort: 30/30 full-recall successes, 0 exact-set matches, avg
    recall `1.000`, avg precision `0.583`, avg F1 `0.733`, mean `393.7s`, and
    zero coordination-tool errors.
  - True Codex-subagents: 29/30 full-recall successes, 2 exact-set matches, avg
    recall `0.983`, avg precision `0.617`, avg F1 `0.742`, mean `184.0s`, and
    25 coordination-tool router errors. The only recall miss was `database-091`,
    where the system predicted `REDUNDANT_INDEX` against gold
    `REDUNDANT_INDEX,VACUUM`.
  - Losangelex: 30/30 full-recall successes, 1 exact-set match, avg recall
    `1.000`, avg precision `0.594`, avg F1 `0.740`, mean `160.2s`, and zero
    coordination-tool errors.
  - Paired runtime: Losangelex was faster than serial Codex on 30/30 tasks and
    faster than Codex-subagents on 23/30 tasks. Mean paired runtime ratios were
    serial-Codex/Losangelex `2.51x`, Codex-subagents/Losangelex `1.17x`, and
    serial-Codex/Codex-subagents `2.18x`.
  - Interpretation: this is the strongest native MARBLE evidence so far and is
    no longer development-only. It supports a narrow same-model systems claim:
    Losangelex preserves benchmark-aligned recall on the heldout MARBLE slice,
    avoids the observed Codex-subagent recall miss and router-error profile, and
    reduces mean wall-clock time. It does not support a broad SOTA claim because
    Codex-subagents have slightly better precision/F1 on this same holdout and
    all systems still over-predict extra root-cause labels.
- Regenerated the hardened same-model agent-runtime paper at
  `tmp/research/published-agent-benchmarks/paper-2026-05-22-final-primary-agent-runtime/losangelex-hardened-agent-runtime-evaluation-2026-05-22.pdf`.
  The local PDF passed `pdfinfo` with 4 pages and was packaged with its TeX
  source, the final-primary MARBLE report, and `SHA256SUMS.txt` into
  `tmp/research/published-agent-benchmarks/email-delivery-2026-05-22-final-primary/losangelex-final-primary-agent-runtime-paper-2026-05-22.zip`.
  `unzip -t` reported no errors.
- Emailed the paper artifacts through SESv2 using from
  `Ozzz Research <seo@fallsoft.co>`, configuration set
  `fallsoftco-vc-access`, and explicit `ContentTransferEncoding=BASE64` for
  every attachment. SES message id:
  `0100019e50c88fb7-c5ed5de7-ab46-4acc-be62-3bb5e4617a1a-000000`.

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
   smoke, bridge smokes, development samples, and the locked 30-task
   final-primary holdout are complete. Broader MARBLE or SWE-bench evidence is
   still required before making benchmark-general claims.

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
5. Done: implement native MARBLE database execution and score recall, exact
   match, precision, runtime, and coordination-tool errors; consume the locked
   30-task final-primary holdout after freezing the candidate.
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
- A second ten-stratum run with the first file-query bridge was attempted:
  `tmp/research/published-agent-benchmarks/marble-native-file-query-bridge-paired-stratified-10-2026-05-21/results.json`.
  This run is also **invalid for paper claims**:
  - agents could issue file-bridge requests, but the harness responder still
    used `docker compose exec` while the MARBLE repo was hidden, causing query
    responses such as `stat .../db_env_docker/.env: permission denied`;
  - previous benchmark result directories remained readable, and at least one
    Codex coordinator inspected sibling `database-003` submissions from a prior
    campaign.
- Follow-up harness fixes:
  - active native PostgreSQL queries now use `docker exec` against the running
    `db_env_docker-postgres_db-1` container, so the responder no longer needs
    compose files while the MARBLE repo is hidden;
  - default hidden paths now include prior campaign/result directories under
    the benchmark output root, excluding only the current campaign directory.
- Hidden-path bridge validation after the `docker exec` fix:
  - deterministic hidden-path local smoke:
    `tmp/research/published-agent-benchmarks/marble-native-file-query-hidden-path-local-smoke-2026-05-21`;
    `./query_db.py` returned live `pg_stat_statements` output while the MARBLE
    repo was chmod-hidden.
  - Losangelex hidden-path model smoke:
    `tmp/research/published-agent-benchmarks/marble-native-file-query-hidden-path-losangelex-smoke-2026-05-21/results.json`;
    `database-001`, recall `1.000`, precision `0.500`, F1 `0.667`, `131.5s`,
    zero coordination-tool errors, many logged SQL queries, and no compose
    `.env` permission errors.
- Previous-result hiding validation:
  `tmp/research/published-agent-benchmarks/marble-native-hidden-results-losangelex-smoke-2026-05-21/results.json`;
  `database-001`, recall `1.000`, precision `0.500`, F1 `0.667`, `161.7s`,
  zero coordination-tool errors, 38 logged SQL queries, no compose `.env`
  permission errors, and `46` hidden paths including prior result campaigns.
- Valid isolated ten-stratum native MARBLE sample:
  `tmp/research/published-agent-benchmarks/marble-native-isolated-paired-stratified-10-2026-05-21/results.json`.
  - Hidden paths: `47`, including prior result campaigns.
  - Query bridge: every task/system setup log has live SQL queries; no
    permission errors, compose `.env` errors, or previous-result leakage hits
    were found in the post-run scan.
  - Docker/PostgreSQL teardown left no MARBLE containers running.
  - Codex: 10 tasks, 10 full-recall successes, 0 exact-set matches, avg recall
    `1.000`, avg precision `0.583`, avg F1 `0.733`, mean seconds `422.1`,
    coordination-tool errors `0`.
  - Losangelex: 10 tasks, 10 full-recall successes, 0 exact-set matches, avg
    recall `1.000`, avg precision `0.583`, avg F1 `0.733`, mean seconds
    `148.1`, coordination-tool errors `0`.
  - Paired deltas: recall/precision/F1 ties on all 10 sampled tasks;
    Losangelex faster on all 10. Mean Codex/Losangelex runtime ratio `2.91x`,
    median `2.87x`.
  - Exact-set caveat: the sampled MARBLE prompts request more labels than the
    gold root-cause set contains (`number_of_labels_pred=2` for one-root cases
    and `3` for two-root cases). Both systems followed the prompt, so strict
    exact-set match remains `0/10` for both while recall is `10/10`. The paper
    should report recall as the benchmark-aligned metric and exact-set/precision
    as stricter secondary metrics.
- Published evaluator check: `scripts/database/batch_eval.py` scores database
  tasks as `match_count / len(gold_labels)` after extracting predicted labels,
  so extra predicted labels are not penalized in MARBLE's scaled task score.
  The native isolated sample is therefore `10/10` for both systems under the
  benchmark-aligned recall-style metric; precision and exact-set remain stricter
  auxiliary diagnostics.
- Additional isolated ten-stratum native MARBLE sample:
  `tmp/research/published-agent-benchmarks/marble-native-isolated-paired-stratified-additional-10-2026-05-21/results.json`.
  - Hidden paths: `48`, including prior result campaigns.
  - Post-run hygiene scan found no permission errors, compose `.env` errors, or
    previous-result leakage hits in run/workspace files. Docker/PostgreSQL
    teardown left no MARBLE containers running.
  - Codex: 10 tasks, 9 full-recall successes, 0 exact-set matches, avg recall
    `0.900`, avg precision `0.533`, avg F1 `0.667`, mean seconds `397.8`,
    coordination-tool errors `0`.
  - Losangelex: 10 tasks, 10 full-recall successes, 0 exact-set matches, avg
    recall `1.000`, avg precision `0.583`, avg F1 `0.733`, mean seconds
    `148.3`, coordination-tool errors `0`.
  - Paired deltas: Losangelex higher on 1 task (`database-012`), Codex higher
    on 0, ties on 9; Losangelex faster on all 10. Mean Codex/Losangelex runtime
    ratio `2.68x`, median `2.64x`.
- Combined native MARBLE isolated two-slice evidence:
  - Raw artifacts:
    `tmp/research/published-agent-benchmarks/marble-native-isolated-paired-stratified-10-2026-05-21/results.json`
    and
    `tmp/research/published-agent-benchmarks/marble-native-isolated-paired-stratified-additional-10-2026-05-21/results.json`.
  - Codex: 20 tasks, 19 full-recall successes, 0 exact-set matches, avg recall
    `0.950`, avg precision `0.558`, avg F1 `0.700`, mean seconds `409.9`,
    coordination-tool errors `0`.
  - Losangelex: 20 tasks, 20 full-recall successes, 0 exact-set matches, avg
    recall `1.000`, avg precision `0.583`, avg F1 `0.733`, mean seconds
    `148.2`, coordination-tool errors `0`.
  - Paired deltas: Losangelex higher on 1 task (`database-012`), Codex higher
    on 0, ties on 19; Losangelex faster on all 20. Mean Codex/Losangelex
    runtime ratio `2.79x`, median `2.79x`.
- Validity correction: the native MARBLE "Codex" records above are a serial
  same-model Codex role cohort (`codex exec` per role plus coordinator), not
  true Codex subagents. They remain useful as an ordinary-Codex cohort control,
  but they do not answer whether Losangelex beats Codex's own subagent runtime.
- Added a true `codex-subagents` MARBLE runner mode. It prepares an isolated
  campaign-local `CODEX_HOME`, enables `features.multi_agent_v2`, runs the
  parent `codex exec` without `--ephemeral`, instructs the parent to call real
  `spawn_agent`/`wait_agent` tools with `fork_turns="none"`, forbids shell
  fallback to `codex exec`, records parent stdout/stderr, counts subagent tool
  calls and router errors, and records which expected worker artifacts are
  present or missing.
- True Codex-subagents native MARBLE first slice:
  `tmp/research/published-agent-benchmarks/marble-native-codex-subagents-stratified-10-2026-05-21/results.json`.
  - Sampled tasks: `database-001`, `database-003`, `database-005`,
    `database-006`, `database-007`, `database-051`, `database-052`,
    `database-056`, `database-058`, `database-059`.
  - Post-run hygiene scan found no permission errors, compose `.env` errors,
    previous-result leakage hits, `SPAWN_FAILED` markers, or shell fallback
    strings in run/workspace files. Docker/PostgreSQL teardown left no MARBLE
    containers running.
  - Codex-subagents: 10 tasks, 10 full-recall successes, 1 exact-set match, avg
    recall `1.000`, avg precision `0.617`, avg F1 `0.753`, mean seconds
    `214.4`, coordination-tool router errors `12`.
  - Coordination/execution quality: each case recorded 5 `spawn_agent` calls;
    only 4/10 cases had every expected worker submission present. Missing
    worker submissions and small-timeout `wait_agent` errors are now measured
    outcomes, not hidden harness failures.
  - Same-task comparison against the earlier isolated serial cohort slice:
    serial Codex cohort mean `422.1s`, Codex-subagents mean `214.4s`,
    Losangelex mean `148.1s`. Codex-subagents were faster than serial Codex on
    all 10 tasks; Losangelex was faster than Codex-subagents on 9/10 tasks.
    Mean serial-Codex/Codex-subagents runtime ratio was about `2.02x`; mean
    Codex-subagents/Losangelex runtime ratio was about `1.48x`.
  - Interpretation: true Codex subagents materially reduce the earlier serial
    Codex runtime baseline, but the first slice still favors Losangelex on wall
    time and exposes Codex-subagent aggregation reliability issues. This is not
    yet enough for a broad SOTA claim; expand to the second 10-task slice and
    preferably a larger stratified/native sample.
- True Codex-subagents native MARBLE second slice:
  `tmp/research/published-agent-benchmarks/marble-native-codex-subagents-stratified-additional-10-2026-05-21/results.json`.
  - Sampled tasks: `database-002`, `database-009`, `database-011`,
    `database-012`, `database-019`, `database-053`, `database-054`,
    `database-061`, `database-062`, `database-070`.
  - Post-run hygiene scan again found no permission errors, compose `.env`
    errors, previous-result leakage hits, `SPAWN_FAILED` markers, or shell
    fallback strings in run/workspace files. Docker/PostgreSQL teardown left no
    MARBLE containers running.
  - Codex-subagents: 10 tasks, 10 full-recall successes, 0 exact-set matches,
    avg recall `1.000`, avg precision `0.583`, avg F1 `0.733`, mean seconds
    `190.5`, coordination-tool router errors `5`.
  - The runner/prompt update that explicitly forbids small `wait_agent`
    timeouts reduced, but did not eliminate, coordination-tool router errors
    compared with the first slice.
- Combined true Codex-subagents native MARBLE two-slice evidence:
  - Raw artifacts:
    `tmp/research/published-agent-benchmarks/marble-native-codex-subagents-stratified-10-2026-05-21/results.json`
    and
    `tmp/research/published-agent-benchmarks/marble-native-codex-subagents-stratified-additional-10-2026-05-21/results.json`.
  - Combined summary artifact:
    `tmp/research/published-agent-benchmarks/marble-native-codex-subagents-combined-20-2026-05-21/summary.json`.
  - Codex-subagents: 20 tasks, 20 full-recall successes, 1 exact-set match, avg
    recall `1.000`, avg precision `0.600`, avg F1 `0.743`, mean seconds
    `202.5`, total `100` `spawn_agent` calls, `63` `wait_agent` calls, and
    coordination-tool router errors `17`.
  - Expected worker-submission completeness: 9/20 cases had all five expected
    worker JSON submissions present; 11/20 had at least one missing worker
    submission despite successful parent completion.
  - Same-task comparison against the 20-task isolated serial Codex/Losangelex
    evidence: serial Codex cohort 19/20 full recall, avg precision `0.558`,
    avg F1 `0.700`, mean `409.9s`; Losangelex 20/20 full recall, avg precision
    `0.583`, avg F1 `0.733`, mean `148.2s`; Codex-subagents 20/20 full recall,
    avg precision `0.600`, avg F1 `0.743`, mean `202.5s`.
  - Paired deltas: Codex-subagents improved recall over serial Codex on one
    task (`database-012`) and were lower on none; Codex-subagents tied
    Losangelex recall on all 20 tasks and had slightly higher auxiliary
    precision/F1 on this sample; serial Codex was faster than Codex-subagents
    on 0/20 tasks; Losangelex was faster than Codex-subagents on 19/20 tasks.
    Mean serial-Codex/Codex-subagents runtime ratio was about `2.07x`; mean
    Codex-subagents/Losangelex runtime ratio was about `1.38x`.
  - Interpretation: the real Codex-subagent baseline changes the result. The
    strongest current MARBLE claim is not simply "Losangelex beats Codex"; it is
    that Losangelex matches true Codex-subagent recall on this 20-task native
    sample while running faster and without the observed subagent aggregation
    reliability issues. Codex-subagents may have a small auxiliary precision/F1
    edge on this sample, so paper language must report the full tradeoff.
- Repeated the same observed-development 20-task native MARBLE true
  Codex-subagent baseline for variance:
  `tmp/research/published-agent-benchmarks/marble-native-codex-subagents-observed-20-repeat-2026-05-22/results.json`.
  - Post-run hygiene scan found no permission errors, previous-result leakage
    hits, answer-key/gold-label leakage hits, `SPAWN_FAILED` markers, or shell
    fallback strings. Docker/PostgreSQL teardown left no MARBLE containers
    running.
  - Codex-subagents repeat: 20/20 full-recall successes, 0 exact-set matches,
    avg recall `1.000`, avg precision `0.583`, avg F1 `0.733`, mean `197.0s`,
    and 13 coordination-tool router errors.
  - Compared with the first 20-task Codex-subagent evidence (`20/20` recall,
    avg precision `0.600`, avg F1 `0.743`, mean `202.5s`, 17 router errors),
    the recall result is stable, precision/F1 vary slightly by extra-label
    choices, and runtime/error counts are similar.
  - Interpretation: this repeat strengthens the narrow MARBLE claim that true
    Codex subagents and Losangelex both recover all gold root-cause labels on
    the observed native 20-task sample. It still does not support a broad SOTA
    claim: exact-set match remains `0/20` in the repeat, and the observed sample
    is development evidence rather than the locked MARBLE holdout.
- Completed a native MARBLE development-extension all-system campaign on 20
  additional non-holdout database tasks:
  `tmp/research/published-agent-benchmarks/marble-native-development-extension-all-systems-2026-05-22/results.json`.
  - Tasks: `database-004`, `database-008`, `database-013`, `database-014`,
    `database-015`, `database-020`, `database-021`, `database-022`,
    `database-026`, `database-029`, `database-055`, `database-057`,
    `database-060`, `database-063`, `database-064`, `database-066`,
    `database-067`, `database-074`, `database-075`, and `database-080`.
  - Post-run hygiene scan found no permission errors, previous-result leakage
    hits, answer-key/gold-label leakage hits, published-repository references,
    `SPAWN_FAILED` markers, or shell fallback strings. Docker/PostgreSQL
    teardown left no MARBLE containers running.
  - Serial Codex cohort: 20/20 full-recall successes, 0 exact-set matches, avg
    recall `1.000`, avg precision `0.583`, avg F1 `0.733`, mean `403.3s`, and
    zero coordination-tool errors.
  - True Codex-subagents: 20/20 full-recall successes, 0 exact-set matches, avg
    recall `1.000`, avg precision `0.583`, avg F1 `0.733`, mean `234.6s`,
    and 31 coordination-tool router errors.
  - Losangelex: 20/20 full-recall successes, 0 exact-set matches, avg recall
    `1.000`, avg precision `0.583`, avg F1 `0.733`, mean `159.3s`, and zero
    coordination-tool errors.
  - Paired runtime: Losangelex was faster than serial Codex on 20/20 tasks and
    faster than Codex-subagents on 19/20 tasks. Mean paired runtime ratios were
    serial-Codex/Losangelex `2.61x`, Codex-subagents/Losangelex `1.51x`, and
    serial-Codex/Codex-subagents `1.92x`. Codex-subagents had one large
    tail-latency case (`database-064`, `763.3s`) where Losangelex finished in
    `148.1s`.
  - Interpretation: this campaign strengthens the MARBLE systems result but
    not a leaderboard/SOTA result. On this non-holdout slice, Losangelex does
    not improve benchmark score over true Codex-subagents; it matches score
    while reducing wall-clock time and avoiding the observed subagent
    router-error/tail-latency profile.
- Combined 40-task native MARBLE all-system development table, using the two
  earlier isolated serial-Codex/Losangelex slices, the repeated 20-task
  Codex-subagent baseline, and the 20-task all-system extension:
  - Serial Codex cohort: 39/40 full-recall successes, avg recall `0.975`, avg
    precision `0.571`, avg F1 `0.717`, mean `406.6s`, and zero coordination
    errors.
  - True Codex-subagents: 40/40 full-recall successes, avg recall `1.000`, avg
    precision `0.583`, avg F1 `0.733`, mean `215.8s`, and 44 total router
    errors across the two selected 20-task runs.
  - Losangelex: 40/40 full-recall successes, avg recall `1.000`, avg precision
    `0.583`, avg F1 `0.733`, mean `153.8s`, and zero coordination errors.
  - Paired runtime: Losangelex was faster than serial Codex on 40/40 tasks and
    faster than Codex-subagents on 39/40 tasks. Mean paired runtime ratios were
    serial-Codex/Losangelex `2.70x`, Codex-subagents/Losangelex `1.43x`, and
    serial-Codex/Codex-subagents `2.03x`.
  - Interpretation: the 40-task development evidence supports a meaningful
    same-model systems claim: Losangelex matches true Codex-subagent MARBLE
    recall/F1 while reducing wall-clock time and coordination errors. It still
    does not establish leaderboard SOTA or held-out generalization.
- Remaining work: expand toward a larger stratified subset or full 100-task
  database run, repeat true Codex-subagent runs for variance, and report the
  evaluator/auxiliary-metric distinction clearly in the paper.

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
- Remaining work: repeat the highest-value scales/tasks for variance, rerun
  the observed n=5/n=10 comparison table with corrected tolerance metrics for
  every system if auxiliary numeric-tolerance claims are used, and decide
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
  - Supported now: native MARBLE final-primary shows a narrow same-model runtime
    and reliability result, but not a broad benchmark-general SOTA result.
  - Not yet supported: benchmark-general claims beyond Silo/MARBLE until
    SWE-bench expansion and larger-scale Silo evidence finish.
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
- Native MARBLE PostgreSQL has both development evidence and a locked
  final-primary holdout. The 40-task development table is: serial Codex 39/40
  recall successes, Codex-subagents 40/40, Losangelex 40/40; Codex-subagents
  and Losangelex tie avg precision/F1 at `0.583/0.733`, while Losangelex is
  faster than Codex-subagents on 39/40 tasks and has zero observed
  coordination-tool errors versus 44 router errors for Codex-subagents.
- The locked native MARBLE final-primary 30-task holdout is complete. Serial
  Codex and Losangelex reached 30/30 full-recall successes; true
  Codex-subagents reached 29/30 after missing `VACUUM` on `database-091`.
  Average precision/F1 were serial Codex `0.583/0.733`, Codex-subagents
  `0.617/0.742`, and Losangelex `0.594/0.740`. Mean runtimes were `393.7s`,
  `184.0s`, and `160.2s`, respectively, with coordination errors `0`/`25`/`0`.
  Losangelex was faster than serial Codex on 30/30 tasks and faster than
  Codex-subagents on 23/30 tasks. MARBLE's evaluator emphasizes recall over
  gold labels, so exact-set and precision/F1 are reported as stricter auxiliary
  metrics and prevent overclaiming.
- Locked a SOTA-without-overfit protocol in
  `evals/losangelex_sota_protocol.md` and a task manifest in
  `evals/losangelex_benchmark_manifest.json`. Previously observed MARBLE/Silo
  tasks are now development/evidence tasks; MARBLE final-primary has been
  consumed as the locked 30-task stratified holdout for the current frozen
  candidate, and Silo n50 remains the primary held-out scale with n100 as the
  stretch scale.
- Added true `codex-subagents` support to the Silo runner. The runner prepares
  an isolated campaign-local `CODEX_HOME`, enables `features.multi_agent_v2`,
  uses real `spawn_agent`/`wait_agent` calls, records parent stdout/stderr,
  counts subagent tool calls/errors, records worker artifact completeness, and
  hides the Silo repository plus previous result directories by default.
  Validity caveat: because the Codex parent must pass worker prompts into
  `spawn_agent`, this is a true Codex-subagent orchestration baseline, not a
  strict parent-blind private-shard runtime. The existing full-context oracle
  remains the ceiling control.
- Silo true Codex-subagent smoke:
  `tmp/research/published-agent-benchmarks/silo-codex-subagents-smoke-I01-n2-aggregate-2026-05-21/results.json`.
  Task `I-01_n2` completed with S/P `1.000/1.000`, 2 `spawn_agent` calls, 1
  `wait_agent` call, zero router errors, all worker notes/submissions present,
  and no shell fallback or leakage hits in the post-run scan.
- Silo true Codex-subagent observed-development n=5 slice:
  `tmp/research/published-agent-benchmarks/silo-codex-subagents-dev-n5-slice-2026-05-21/results.json`.
  Tasks: `I-01_n5`, `II-12_n5`, `III-25_n5`.
  - Codex-subagents: 1/3 strict successes, avg S `0.333`, avg P `0.457`,
    mean `233.7s`, 15 `spawn_agent` calls, complete worker notes/submissions
    in all three cases, and 2 coordination-tool router errors.
  - Same-task prior baselines: serial Codex also 1/3, mean `483.0s`;
    Losangelex also 1/3, mean `132.6s`; full-context oracle also 1/3, mean
    `43.7s`.
  - Interpretation: on this small Silo slice, true Codex-subagents preserve the
    same correctness pattern as serial Codex/Losangelex/full-context, improve
    materially over serial Codex runtime, and remain slower than Losangelex.
    The `II-12_n5` and `III-25_n5` misses are not obviously reasoning failures:
    all systems produced numerically correct-looking floating outputs at full
    precision while the published expected values are rounded to two decimals
    and the Silo verification logic uses exact list equality. Before using Silo
    for final SOTA claims, decide whether to preserve strict published scoring
    only, add a disclosed tolerance-normalized auxiliary metric, or rerun all
    systems with a benchmark-general numeric-output formatting contract.
- Added disclosed auxiliary numeric-tolerance metrics to future Silo runner
  outputs: `S_numeric_tolerance_success_rate` and
  `P_numeric_tolerance_partial_correctness`. These do not replace the official
  strict S/P fields; they separate exact-format misses from numerically close
  distributed reasoning. Retrospective check on the observed n=5 Codex-subagent
  slice: strict S/P aggregate was `0.333/0.457`, while numeric-tolerance S/P was
  `1.000/1.000`, confirming that the level II/III failures in that slice were
  primarily rounded-output mismatches.
- Reran the same observed Silo n=5 Codex-subagent slice after adding the
  auxiliary fields:
  `tmp/research/published-agent-benchmarks/silo-codex-subagents-dev-n5-slice-tolerance-2026-05-21/results.json`.
  The emitted result JSON now records strict avg S/P `0.333/0.457` and numeric-
  tolerance avg S/P `1.000/1.000`. This run also exposed a distinct
  Codex-subagent reliability issue: `II-12_n5` produced the numerically correct
  answer under tolerance but logged 11 coordination/tool router errors,
  including small `wait_agent` timeouts, bad live-agent paths, blocked shell
  cleanup, and failed patch attempts. `III-25_n5` produced all expected
  submissions but missed two expected shared notes. These are substrate-quality
  signals to report separately from task correctness.
- Completed the full observed-development Silo n=5 true Codex-subagent matrix:
  `tmp/research/published-agent-benchmarks/silo-codex-subagents-n5-full-observed-2026-05-21/results.json`.
  The run used a campaign-local `CODEX_HOME`, enabled `multi_agent_v2`, hid the
  Silo repository and previous result directories, and passed the post-run scan
  for answer-key, published-repo, and `codex exec` leakage strings.
  - Codex-subagents: 30 tasks, 24/30 strict full successes, avg S `0.800`,
    avg P `0.813`, mean `240.1s`, and 70 coordination-tool router errors.
    By level: I `10/10`, II `7/10`, III `7/10`.
  - After fixing the disclosed auxiliary numeric-tolerance metric to recurse
    through dictionary-shaped answers, the same artifact reports numeric-
    tolerance success `28/30`, avg S_tol `0.933`, avg P_tol `0.934`. These
    auxiliary fields do not replace strict Silo scoring.
  - Same n=5 comparison set: serial Codex `20/30` strict, mean `422.1s`;
    Losangelex `21/30` strict, mean `113.0s`; full-context Codex oracle
    `25/30` strict, mean `39.2s`.
  - Failure taxonomy: `II-12`, `III-25`, `III-27`, and `III-28` are exact-
    numeric-format failures under strict scoring but tolerance-correct.
    `II-15` is a real semantic miss shared by the same-model controls on this
    n=5 task. `II-17` is a Codex-subagent submission-contract failure: the
    parent wrote a corrected final answer, but the scored submission files kept
    an extra first difference value.
  - Interpretation: true Codex-subagents are more accurate than serial Codex
    and Losangelex on observed n=5 under strict scoring, but slower than
    Losangelex and much slower than the full-context oracle. Losangelex remains
    the lower-latency native-room baseline; the current evidence does not
    support a broad SOTA claim against Codex subagents.
- Completed the full observed-development Silo n=10 true Codex-subagent matrix:
  `tmp/research/published-agent-benchmarks/silo-codex-subagents-n10-full-observed-2026-05-21/results.json`.
  The run used the same hidden-path and isolated-`CODEX_HOME` harness as n=5
  and passed the post-run scan for answer-key, published-repo, and `codex exec`
  leakage strings.
  - Codex-subagents: 30 tasks, 23/30 strict full successes, avg S `0.767`,
    avg P `0.780`, mean `328.6s`, and 182 coordination-tool router errors.
    By level: I `10/10`, II `7/10`, III `6/10`.
  - Auxiliary numeric-tolerance metrics: avg S_tol `0.863`, avg P_tol `0.863`.
    The strict failures split into exact-format/tolerance-correct tasks
    (`II-12`, `III-25`), mixed format plus missing-submission task
    (`III-28`, 9/10 tolerance-correct), and real semantic or coordination
    failures (`II-15`, `II-18`, `III-22`, `III-27`).
  - Same n=10 comparison set: serial Codex `21/30` strict, mean `835.5s`;
    Losangelex `20/30` strict, mean `133.6s`; full-context Codex oracle
    `24/30` strict, mean `52.8s`.
  - Paired runtime: Codex-subagents were faster than serial Codex on all 30
    tasks, slower than Losangelex on all 30 tasks, and slower than the
    full-context oracle on all 30 tasks.
  - Interpretation: true Codex-subagents improve strict n=10 correctness over
    both serial Codex and Losangelex, but their latency and coordination-error
    profile are substantially worse than Losangelex. The oracle remains more
    accurate and faster, so Silo still supports a constrained runtime tradeoff
    result, not a broad multi-agent SOTA claim.

### Execution Queue

1. Silo scoring/prompt gate: keep strict published scoring as primary and
   report numeric tolerance only as a disclosed auxiliary metric; before any
   held-out Silo n50 run, rerun the full observed n=5 comparison table with
   corrected tolerance metrics for every system if auxiliary claims are used.
2. Native MARBLE: final-primary holdout is complete; optional next evidence is
   the full 100-task database set or a power-justified larger stratified subset,
   but do not retune Losangelex against the consumed holdout.
3. Silo variance: repeat the highest-value n=10 tasks where systems disagree
   and estimate paired variance over correctness and runtime.
4. SWE-bench: add a stratified sample that includes multi-file, ambiguous
   ownership, dependency-chain, and verifier-heavy tasks. Keep tiny single-file
   tasks as negative controls.
5. App-build/coordination evals: preserve them as ecological support, not as
   the primary objective benchmark evidence.
6. Analysis: compute paired deltas, confidence intervals or bootstrap intervals,
   runtime distributions, coordination-tool error rates, and failure taxonomy.
7. Paper: regenerate tables, figures, abstract, related work, threats to
   validity, and conclusion from the frozen artifacts.
8. Delivery: build and open-check PDFs, send by SES through Ozzz, and record
   message IDs here.

### Current Next Step

The final-primary MARBLE paper has been generated and emailed. Continue with
held-out Silo n50 and SWE-bench expansion in later sessions if a broader
benchmark-general paper claim is still desired.

## 2026-06-14 Current-Upstream SILO Pilot

- After merging current upstream Codex changes, ran a four-task matched SILO
  n=5 pilot across current Codex subagents, normal Losangelex/Hollywood rooms,
  and an experimental `losangelex-first-finisher` coordination pattern.
- Frozen artifact bundle:
  `evals/research/2026-06-14-current-upstream-silo-first-finisher/`.
- Task files: `I-01_n5`, `I-02_n5`, `II-11_n5`, and `III-21_n5`.
- All three systems reached `4/4` strict full success on this small sample.
- Mean runtime and token summary:
  - Codex subagents: `154.3s`, `827,710` avg total tokens, `118,558`
    avg uncached+output.
  - Losangelex: `113.6s`, `1,104,493` avg total tokens, `166,893`
    avg uncached+output.
  - Losangelex first-finisher: `157.9s`, `912,785` avg total tokens,
    `120,209` avg uncached+output.
- Interpretation: current upstream Codex subagents are much more token-efficient
  than the older June 1 subagent runs, normal Hollywood remains the latency
  leader on this sample, and the first-finisher pattern is a useful
  coordination-design probe rather than an across-the-board replacement.
