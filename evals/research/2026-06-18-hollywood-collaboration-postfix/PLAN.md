# Losangelex Coordination Benchmark Plan - 2026-06-18

Purpose: validate whether the post-fix default-on Hollywood collaboration behavior improves real model-in-the-loop task outcomes, cost, and latency, and produce artifacts suitable for community-facing comparison.

Current branch: `hollywood-native-integration-clean`.

## Ground Rules

- Treat June 15/16 SILO and MARBLE artifacts as pre-fix baselines only.
- Keep existing SILO/MARBLE runners unchanged for comparable published-benchmark evidence unless a runner bug is found.
- Add a separate Hollywood-native coordination benchmark instead of replacing SILO/MARBLE.
- Compare the same frozen task fixtures across systems where possible.
- Track outcome, wall time, total tokens, uncached+output tokens, agent count, peer requests, peer responses, tool errors, duplicate/conflict indicators, and whether collaboration actually changed the result.
- Use isolated CODEX_HOME, isolated app-server processes, isolated Hollywood servers/databases, and scratch workspaces.

## Systems To Compare

- `codex`: single Codex exec run on the coordination scenario.
- `codex-subagents`: Codex parent using real `spawn_agent` workers.
- `losangelex-baseline`: live Losangelex app-server room with `LOSANGELEX_COLLABORATION_FIRST=0`.
- `losangelex`: live Losangelex app-server room with default-on Hollywood collaboration.

## Work Plan

- [x] Confirm existing full comparable benchmarks are pre-fix artifacts.
- [x] Create this file-based plan for compaction-safe continuation.
- [x] Add live Hollywood coordination comparison runner.
- [x] Run syntax checks for benchmark scripts.
- [x] Run small live coordination benchmark across all four systems.
- [x] Run post-fix SILO subset with current branch.
- [x] Run post-fix MARBLE subset with current branch.
- [x] Summarize results and decide whether full SILO/MARBLE reruns are justified immediately.
- [x] Run targeted SILO pre-June-16 hard-case slice.
- [x] Run bounded targeted SILO n10 hard-case slice.
- [ ] If subset is stable, start full SILO and MARBLE runs in detached tmux sessions.
- [x] Update research artifacts/reports with post-fix results.

## Existing Pre-Fix Benchmark Artifacts

- SILO gpt-5.5 n5 full systems: `tmp/research/published-agent-benchmarks/silo-gpt55-full-n5-all-systems-2026-06-16/results.json`
- SILO gpt-5.5 n10 full systems: `tmp/research/published-agent-benchmarks/silo-gpt55-full-n10-all-systems-2026-06-16/results.json`
- MARBLE gpt-5.5 native full systems: `tmp/research/published-agent-benchmarks/marble-native-gpt55-full-all-systems-2026-06-16/results.json`

## Post-Fix Collaboration Evidence

- Targeted live collaboration eval: `tmp/research/collaboration-first-debug/collaboration-first-polling-2026-06-18-a/REPORT.md`
- Result: candidate passed 3/3, with required peer requests and peer responses. This proves the wake path works, but it is not a published benchmark comparison.

## Live Coordination Benchmark Result

- Clean artifact: `tmp/research/hollywood-coordination-benchmark/hollywood-coordination-postfix-2026-06-18-c/`
- Report: `tmp/research/hollywood-coordination-benchmark/hollywood-coordination-postfix-2026-06-18-c/HOLLYWOOD_COORDINATION_REPORT.md`
- Summary:
  - `codex`: 3/3 passed, avg 56.8s, avg uncached+output 19,119, no coordination expected/used.
  - `codex-subagents`: 3/3 passed, coordination criterion 1/3, avg 107.9s, avg uncached+output 57,641, 0 spawn calls.
  - `losangelex-baseline`: 1/3 passed, coordination criterion 1/3, avg 110.1s, avg uncached+output 60,424, 2 required peer requests, 0 peer responses.
  - `losangelex`: 3/3 passed, coordination criterion 3/3, avg 136.3s, avg uncached+output 103,884, 3 required peer requests, 9 peer responses.
- Removed generated pilot artifacts `hollywood-coordination-postfix-2026-06-18-a` and `hollywood-coordination-postfix-2026-06-18-b`.

## SILO Subset Notes

- Interrupted diagnostic artifact was removed after extracting the key numbers.
- Diagnostic result before runner wait fix:
  - `codex-subagents` completed `I-01_n5` and `I-02_n5`: 2/2, avg 128.4s, avg uncached+output 101,070.
  - `losangelex` completed `I-01_n5`: 1/1, 312.7s, 9,350,312 total tokens, 593,832 uncached+output.
  - Notification summary showed 138 started turns, 134 completed turns, zero coordination tool calls; this was benchmark wait/poll waste, not useful task work.
- Runner fix: `scripts/run_silo_published_agents.py` now lets the Losangelex wait loop stop once all expected SILO submission files exist after initial turn completion.
- Wait-fix probe artifact was removed after extracting the key numbers.
  - Same `I-01_n5` Losangelex task passed in 74.3s, 1,535,661 total tokens, 228,013 uncached+output.
  - Turn count dropped from 138 started turns to 18 started turns.
- Clean wait-fix subset artifact: `tmp/research/published-agent-benchmarks/silo-postfix-subset-waitfix-2026-06-18-a/`
  - 6 paired Level I five-agent tasks.
  - `codex-subagents`: 6/6, avg 147.2s, avg total tokens 790,865, avg uncached+output 119,739.
  - `losangelex`: 6/6, avg 81.0s, avg total tokens 1,471,166, avg uncached+output 265,257.
  - Interpretation: after removing benchmark wait waste, Losangelex remains much faster on this SILO slice but still costs about 2.2x uncached+output tokens.

## SILO Prior Hard-Case Result

- Clean artifact: `tmp/research/published-agent-benchmarks/silo-postfix-prior-failures-n5-2026-06-18-a/`
- Copied tracked report: `evals/research/2026-06-18-hollywood-collaboration-postfix/SILO_POSTFIX_PRIOR_FAILURES_N5_REPORT.md`
- Scope: five-agent SILO tasks that were partial/failing before the June 16 snapshot:
  - `II-12_n5`, `II-14_n5`, `II-15_n5`, `II-17_n5`, `II-20_n5`
  - `III-25_n5`, `III-26_n5`, `III-27_n5`, `III-28_n5`
- The first pass hit the model usage limit during the Level III tail. The backend said to try again at 7:25 PM EDT; local time was 4:52 PM EDT when diagnosed.
- The runner now marks quota/backend failures with `validAttempt=false` and excludes them from aggregates. The following intermediate invalid rows were rerun after the reset and replaced in the consolidated artifact:
  - `losangelex` `III-26_n5`
  - `codex-subagents` `III-27_n5`
  - `losangelex` `III-27_n5`
  - `codex-subagents` `III-28_n5`
  - `losangelex` `III-28_n5`
- Consolidated valid aggregate:
  - `codex-subagents`: 9 valid, 0 invalid, 5/9 successes, avg 203.5s, avg total tokens 977,628, avg uncached+output 160,604.
  - `losangelex`: 9 valid, 0 invalid, 2/9 successes, avg 135.0s, avg total tokens 2,413,434, avg uncached+output 380,993.
- Case-level signal:
  - `II-12_n5`: both systems partial with the same score; Losangelex faster.
  - `II-14_n5`: Codex subagents succeeded; Losangelex partial, despite June 16 having improved this case.
  - `II-15_n5`: Codex subagents succeeded; Losangelex still failed.
  - `II-17_n5`: both succeeded; Losangelex faster.
  - `II-20_n5`: Codex subagents succeeded; Losangelex partial, despite June 16 having improved this case.
  - `III-25_n5`: both valid attempts failed; Losangelex faster.
  - `III-26_n5`: both systems succeeded; Losangelex was faster but more expensive.
  - `III-27_n5`: both systems failed; Losangelex was faster but more expensive.
  - `III-28_n5`: both systems failed; Losangelex was faster but more expensive.
- Interpretation: current default collaboration does not broadly rescue historical SILO hard cases. It preserves the latency advantage, but quality is worse on this slice and token cost is about 2.4x uncached+output on valid attempts.

## SILO Prior Hard-Case n10 Result

- Clean artifact: `tmp/research/published-agent-benchmarks/silo-postfix-prior-failures-n10-2026-06-18-a/`
- Copied tracked report: `evals/research/2026-06-18-hollywood-collaboration-postfix/SILO_POSTFIX_PRIOR_FAILURES_N10_REPORT.md`
- Scope: three ten-agent SILO tasks that were partial/failing before the June 16 snapshot:
  - `II-12_n10`, `II-14_n10`, `II-15_n10`
- Aggregate:
  - `codex-subagents`: 3 valid, 0 invalid, 2/3 successes, avg 467.6s, avg total tokens 1,715,535, avg uncached+output 273,828.
  - `losangelex`: 3 valid, 0 invalid, 0/3 successes, avg 175.5s, avg total tokens 6,876,753, avg uncached+output 1,044,902.
- Case-level signal:
  - `II-12_n10`: both systems partial with the same score; Losangelex was much faster but much more expensive.
  - `II-14_n10`: Codex subagents succeeded; Losangelex was near-correct partial at S=0.900/P=0.990.
  - `II-15_n10`: Codex subagents succeeded; Losangelex failed.
- Interpretation: the n10 hard slice reinforces the n5 conclusion. Default collaboration preserves latency advantage but loses strict quality and is roughly 3.8x token-heavier on uncached+output.

## MARBLE Subset Result

- Clean artifact: `tmp/research/published-agent-benchmarks/marble-postfix-subset-2026-06-18-a/`
- 6 paired native-Postgres database tasks.
- `codex-subagents`: 6/6, avg recall 1.000, avg 198.3s, avg total tokens 1,347,910, avg uncached+output 198,790.
- `losangelex`: 6/6, avg recall 1.000, avg 170.9s, avg total tokens 2,468,825, avg uncached+output 447,705.
- Interpretation: Losangelex is modestly faster on this MARBLE slice but costs about 2.3x uncached+output tokens.

## Tracked Research Artifact

- `evals/research/2026-06-18-hollywood-collaboration-postfix/README.md`
- Includes copied reports/results:
  - `HOLLYWOOD_COORDINATION_REPORT.md`
  - `hollywood-coordination-results.json`
  - `SILO_POSTFIX_SUBSET_REPORT.md`
  - `silo-postfix-subset-waitfix-results.json`
  - `SILO_POSTFIX_PRIOR_FAILURES_N5_REPORT.md`
  - `silo-postfix-prior-failures-n5-results.json`
  - `SILO_POSTFIX_PRIOR_FAILURES_N10_REPORT.md`
  - `silo-postfix-prior-failures-n10-results.json`
  - `MARBLE_POSTFIX_SUBSET_REPORT.md`
  - `marble-postfix-subset-results.json`
  - `PLAN.md`

## Full Rerun Decision

- Do not start full SILO/MARBLE reruns yet without explicit acceptance of the current cost profile and hard-case quality regression.
- Reason: subset evidence is enough to identify the current tradeoff: Losangelex latency is better, but uncached+output token cost is still roughly 2.2x to 2.3x Codex subagents, and the targeted historical SILO failure slice did not improve quality.
- The hard-case usage-limit blocker was cleared with targeted reruns after the backend reset; the consolidated n5 hard-case artifact has no invalid rows.
- Next useful engineering step before full reruns: reduce duplicated per-agent context/tool output in Losangelex, make room-state/peer wake handling more selective, and evaluate task-family-specific coordination policy instead of defaulting the same collaboration behavior across SILO Level II/III.

## Candidate Commands

After the runner exists, run a small coordination comparison:

```bash
python3 scripts/run_hollywood_coordination_benchmark.py \
  --campaign-name hollywood-coordination-postfix-2026-06-18-a \
  --system codex \
  --system codex-subagents \
  --system losangelex-baseline \
  --system losangelex \
  --runs-per-scenario 1
```

Implemented runner: `scripts/run_hollywood_coordination_benchmark.py`.
Syntax check passed:

```bash
python3 -m py_compile scripts/run_hollywood_coordination_benchmark.py scripts/eval_collaboration_first_debug.py
python3 scripts/run_hollywood_coordination_benchmark.py --help
```

Run a small SILO subset:

```bash
python3 scripts/run_silo_published_agents.py \
  --campaign-name silo-postfix-subset-2026-06-18-a \
  --system codex-subagents \
  --system losangelex \
  --agent-count 5 \
  --limit 6 \
  --model gpt-5.5 \
  --timeout-seconds 1800 \
  --per-agent-timeout-seconds 600
```

Run a small MARBLE subset:

```bash
python3 scripts/run_marble_database_published_agents.py \
  --campaign-name marble-postfix-subset-2026-06-18-a \
  --system codex-subagents \
  --system losangelex \
  --limit 6 \
  --model gpt-5.5 \
  --evidence-mode native-postgres \
  --timeout-seconds 1200 \
  --per-agent-timeout-seconds 600
```

## Resume Notes

- If compacted, continue from the first unchecked item above.
- Before publishing claims, distinguish:
  - mechanism evidence from the targeted collaboration eval,
  - post-fix subset evidence from the new runs,
  - full benchmark evidence from complete SILO/MARBLE reruns.
