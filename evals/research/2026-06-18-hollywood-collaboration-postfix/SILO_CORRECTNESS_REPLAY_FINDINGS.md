# SILO Correctness Replay Findings - 2026-06-19

This note records the targeted replay work after the initial hard-case analysis
showed three Losangelex failure modes: strict formatting mismatches, peer
outliers, and true global-computation errors.

## Candidate Profiles

- `losangelex-contract`: the standard Losangelex room prompt plus a
  final-answer contract checklist for output type, precision, ordering, and the
  prompt's stated algorithm/protocol.
- `losangelex-peer-review`: the contract checklist plus peer contradiction
  checks through the Hollywood room or `shared/` blackboard.

These are benchmark runner profiles, not a change to normal Losangelex session
behavior.

## Results

Hard-smoke replay:

- Artifact: `SILO_CORRECTNESS_REPLAY_HARD_SMOKE_REPORT.md`
- Scope: `II-12_n5`, `II-14_n5`, `II-15_n5`
- Baseline `losangelex`: 1/3 full successes, avg S 0.333, avg P 0.457.
- Initial `losangelex-contract`: 2/3 full successes, avg S 0.667, avg P 0.790.
- Initial `losangelex-peer-review`: 1/3 full successes, avg S 0.333, avg P 0.457.
- Finding: the first contract checklist helped `II-15_n5` but did not fix
  `II-12_n5` formatting. The first peer-review profile made `II-15_n5` worse by
  letting agents override the task's explicit state-machine protocol with a
  generic subsequence-DP interpretation.

Refined two-case replay:

- Artifact: `SILO_CORRECTNESS_REPLAY_REFINED_REPORT.md`
- Scope: `II-12_n5`, `II-15_n5`
- Refined `losangelex-contract`: 2/2 full successes, avg 149.1s, avg
  3,237,582 total tokens, avg 434,574 uncached+output.
- Refined `losangelex-peer-review`: 2/2 full successes, avg 148.9s, avg
  2,861,734 total tokens, avg 380,774 uncached+output.
- Finding: adding explicit guidance to avoid binary floating-point artifacts and
  to treat the prompt's algorithm/protocol as binding fixed both targeted
  failure families in this small live replay.

## Broad-Suite Status

A broader prior-failure replay was started for:

- `II-12_n10`, `II-12_n5`, `II-14_n10`, `II-14_n5`, `II-15_n10`, `II-15_n5`,
  `II-20_n5`, `III-25_n5`, `III-27_n5`, `III-28_n5`

It was stopped after the backend hit the Codex usage limit. The captured error
payload says to retry at **June 19, 2026 12:37 AM EDT**.

During the partial broad run, `II-12_n10` exposed a runner timing issue:
submissions could be scored after all files existed but before active agents
finished refining those files. The workspace rescore for `losangelex-contract`
was 10/10 after the agents settled, while the original record captured 9/10.
The runner now waits for a stable submission snapshot before scoring.

Because of that timing bug and the usage-limit interruption, the partial broad
run is diagnostic only and should not be published as a final score.

## Resume Command

After the usage-limit reset, rerun the broad suite with the stable-submission
runner:

```bash
python3 scripts/run_silo_correctness_replay.py \
  --suite all \
  --system losangelex-contract \
  --system losangelex-peer-review \
  --campaign-name silo-correctness-replay-all-stable-2026-06-19-a \
  --timeout-seconds 1800 \
  --round-timeout-seconds 300 \
  --per-agent-timeout-seconds 600 \
  --max-rounds 3 \
  --submission-settle-seconds 5
```

