# Hollywood App Policy Comparison (2026-04-24)

This note records the larger follow-up comparison after the initial 4-policy Hollywood app Monte Carlo run.

It uses the same real model-in-the-loop artifact harness, but expands the policy set to include newer candidates so they can be compared against the earlier anchors in one global leaderboard.

## Harness

- Campaign runner: [scripts/run_app_monte_carlo.py](/home/ai/Development/losangelex/scripts/run_app_monte_carlo.py:1)
- Per-run evaluator: [scripts/eval_hollywood_app_builds.py](/home/ai/Development/losangelex/scripts/eval_hollywood_app_builds.py:1)
- Raw output: [tmp/app_build_eval/monte-carlo-2026-04-23-b/results.json](/home/ai/Development/losangelex/tmp/app_build_eval/monte-carlo-2026-04-23-b/results.json)
- Generated report: [tmp/app_build_eval/monte-carlo-2026-04-23-b/REPORT.md](/home/ai/Development/losangelex/tmp/app_build_eval/monte-carlo-2026-04-23-b/REPORT.md)

## Challenges

- [habit_dashboard_template](/home/ai/Development/losangelex/evals/app_challenges/habit_dashboard_template/README.md:1)
- [incident_console_template](/home/ai/Development/losangelex/evals/app_challenges/incident_console_template/README.md:1)
- [expense_board_template](/home/ai/Development/losangelex/evals/app_challenges/expense_board_template/README.md:1)

## Policies Compared

Existing anchors:

- `room_message`
- `leader_award`
- `semantic_market`
- `hybrid`

New candidates:

- `market_with_finisher`
- `leader_market`
- `critic_executor`

## Campaign Shape

- app server: `ws://127.0.0.1:46333`
- runs: 21
- matrix: 3 challenges x 7 policies x 1 repeat
- timeout per run: 240s
- poll interval: 40s
- post-pass soak: 20s

## Overall Leaderboard

| Policy | Pass Rate | Avg Time To Green | Avg Hollywood Messages | Avg Active Threads After Run | Avg Changed Files |
| --- | ---: | ---: | ---: | ---: | ---: |
| `leader_award` | 1.00 | 210.3s | 26.7 | 1.3 | 1.7 |
| `leader_market` | 1.00 | 211.9s | 52.0 | 3.7 | 2.7 |
| `critic_executor` | 1.00 | 212.5s | 39.3 | 4.0 | 2.3 |
| `room_message` | 1.00 | 224.0s | 91.7 | 4.0 | 1.0 |
| `semantic_market` | 1.00 | 239.2s | 119.7 | 4.0 | 2.3 |
| `hybrid` | 0.67 | 246.4s | 91.3 | 3.7 | 1.7 |
| `market_with_finisher` | 0.33 | 182.4s | 108.3 | 4.0 | 1.7 |

## Main Conclusions

- `leader_award` is the current best global default in this corpus.
  It tied for the best reliability, had the best average time to green, had the lowest room traffic, and was the only policy that repeatedly left fewer than all threads active after the soak window.

- `leader_market` is the strongest pure speed competitor to `leader_award`.
  It nearly matched `leader_award` on average time, and it won `incident_console`, but it did not improve quiescence and stayed much chattier.

- `critic_executor` is real.
  It was globally competitive, reliable, and quieter than most of the field. It looks like a serious frontier candidate rather than a dead-end experiment.

- `market_with_finisher` is not production-ready as a default.
  It had the fastest single successful run in the whole comparison, but only passed 1 out of 3 tasks. That makes it a high-upside, low-reliability policy in its current form.

- `semantic_market` underperformed the expanded field.
  It looked promising in the smaller corpus, but against the larger comparison it was slower, noisier, and never meaningfully improved quiescence.

- `hybrid` is unstable.
  It failed one task and was slow on the others. It should not be treated as the leading general solution anymore.

## Interpretation

The strongest current evidence favors policies that give one agent explicit coordination authority while still letting the rest of the team execute concrete work.

That does not mean the final answer is a single static planner loop. It means the next serious frontier is narrower:

- `leader_award`
- `leader_market`
- `critic_executor`

Those are the policies that deserve the next round of harder evaluation.

## What This Rules Out

- It is no longer justified to treat `hybrid` as the obvious forward path.
- It is no longer justified to treat `semantic_market` as the likely global winner.
- It is no longer justified to assume a finisher-only improvement fixes the system by itself.

## Next Evaluation Targets

The next comparison should focus on the narrowed frontier and harder workloads:

- dependency-heavy tasks with real unblock events
- backend + frontend split work
- broad diagnosis/refactor tasks with shared-file contention
- stronger quiescence scoring so “fast but still active” is penalized more directly
- more repeats per challenge so the ranking becomes statistically steadier
