# Losangelex SOTA-Without-Overfit Protocol

Last updated: 2026-05-21

This protocol defines the bar for a publishable SOTA-style claim without
benchmark overfitting. It applies to all future Losangelex improvements made
after the baseline commit `debbe3a9ba604b16d8a5a929954d437081f3b32b`.

## Claim Target

The target claim is not "multi-agent systems always beat single agents." The
target claim is:

> A durable multi-agent runtime can reach frontier published-benchmark
> performance without benchmark-specific tuning, while improving latency and
> coordination reliability against same-model agent baselines.

## Non-Overfit Rules

- Treat all tasks already run before this protocol as observed development or
  evidence tasks, not as final held-out proof after future tuning.
- Use `evals/losangelex_benchmark_manifest.json` as the locked task manifest.
- Losangelex changes may be motivated by development-set failure taxonomies,
  but must be benchmark-general runtime changes: coordination, aggregation,
  wake policy, leases, durable state, worker reliability, evidence collection,
  or generic prompt/interface shape.
- Do not add benchmark-label heuristics, task-ID exceptions, answer-format
  shortcuts, or MARBLE/Silo-specific semantic rules.
- Run all final-held-out comparisons once per frozen candidate unless a
  harness/infrastructure failure is documented before scoring.
- Include negative controls and ceiling controls: serial Codex cohort, true
  Codex subagents where available, and single-agent full-context oracle where
  possible.
- Report auxiliary metrics and failures even when the benchmark-aligned metric
  is favorable.

## Minimum Publishable Evidence

1. Native MARBLE PostgreSQL:
   - current 20 observed tasks remain as evidence/dev;
   - run the locked 30-task final-primary holdout after any Losangelex changes;
   - report recall, exact set, precision, F1, runtime, coordination errors, and
     worker-submission completeness.
2. Silo-Bench:
   - keep n=5/n=10 observed matrices as evidence/dev;
   - add true Codex-subagent orchestration baselines;
   - use n=50 as the primary held-out scale target, with n=100 as the stretch
     final scale if cost permits;
   - report S, P, strict success, runtime, coordination errors, and parent
     visibility caveats for Codex-subagent orchestration.
3. SWE-bench:
   - expand beyond the existing three-instance negative control;
   - include multi-file, dependency-chain, and verifier-heavy tasks;
   - report official resolved/not-resolved plus runtime and coordination
     overhead.
4. Analysis:
   - paired deltas for every task;
   - bootstrap or exact paired intervals for runtime and score deltas;
   - failure taxonomy for Losangelex and Codex-subagents;
   - ablation or at least controlled comparisons for the Losangelex runtime
     mechanisms being claimed.

## Enhancement Gate

Do not enhance Losangelex for SOTA until these are complete:

- true Codex-subagent Silo runner smoke passes;
- development-set failures are categorized across at least MARBLE and Silo;
- the candidate improvement is written as a benchmark-general hypothesis.

After an enhancement, rerun development tasks first. Only when the candidate is
frozen should the final-primary holdouts be run.
