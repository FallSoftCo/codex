# Hollywood Long-Horizon Policy Comparison (2026-04-24)

This note records the next comparative policy search after the 7-policy app-build run in [hollywood_app_policy_compare_2026_04_24.md](/home/ai/Development/losangelex/docs/hollywood_app_policy_compare_2026_04_24.md:1).

The goal here was not to add more prompt variants for their own sake, but to try architectures that more directly target long-running and continuously-fed multi-agent work:

- explicit dual-command control
- pull-based kanban flow
- rolling foreman relay
- review-gated execution

## Harness

- Evaluator: [scripts/eval_hollywood_app_builds.py](/home/ai/Development/losangelex/scripts/eval_hollywood_app_builds.py:1)
- Campaign runner: [scripts/run_app_monte_carlo.py](/home/ai/Development/losangelex/scripts/run_app_monte_carlo.py:1)
- Raw output: [tmp/app_build_eval/monte-carlo-2026-04-24-d/results.json](/home/ai/Development/losangelex/tmp/app_build_eval/monte-carlo-2026-04-24-d/results.json)
- Generated report: [tmp/app_build_eval/monte-carlo-2026-04-24-d/REPORT.md](/home/ai/Development/losangelex/tmp/app_build_eval/monte-carlo-2026-04-24-d/REPORT.md)

## Policies Compared

Frontier carried forward from the previous run:

- `leader_award`
- `leader_market`
- `critic_executor`

New long-horizon candidates:

- `dual_command`
- `kanban_pull`
- `relay_foreman`
- `review_gated`

## Campaign Shape

- app server: `ws://127.0.0.1:46335`
- runs: 21
- matrix: 3 challenges x 7 policies x 1 repeat
- timeout per run: 240s
- poll interval: 40s
- post-pass soak: 20s

## Overall Leaderboard

| Policy | Pass Rate | Avg Time To Green | Avg Hollywood Messages | Avg Active Threads After Run | Avg Changed Files |
| --- | ---: | ---: | ---: | ---: | ---: |
| `leader_award` | 1.00 | 223.6s | 45.3 | 2.3 | 2.3 |
| `kanban_pull` | 1.00 | 223.8s | 63.7 | 4.0 | 2.7 |
| `dual_command` | 0.67 | 201.2s | 94.3 | 4.0 | 1.3 |
| `relay_foreman` | 0.67 | 203.1s | 48.0 | 4.0 | 2.3 |
| `review_gated` | 0.67 | 222.3s | 94.0 | 3.7 | 0.7 |
| `critic_executor` | 0.67 | 222.8s | 70.7 | 3.3 | 2.0 |
| `leader_market` | 0.67 | 244.0s | 61.0 | 3.7 | 1.3 |

## Main Findings

- `leader_award` remains the best current global default.
  It is still the only policy in this comparison that combined full reliability with better-than-average quiescence.

- `kanban_pull` is the strongest new architecture from this round.
  It matched `leader_award` almost exactly on average time while staying fully reliable across all three tasks. Its weakness is finish discipline: all threads remained active after the soak window.

- `dual_command` has real upside but is not yet reliable enough.
  It won `habit_dashboard` and `expense_board` on raw speed, but failed `incident_console`.

- `relay_foreman` is interesting but unstable.
  It failed `habit_dashboard`, then behaved competitively on the other two tasks.

- `review_gated` improves some control properties but is too fragile and too noisy in its current form.

- `critic_executor` and `leader_market` did not survive this harder round as clean frontier leaders.
  Both dropped to 0.67 pass rate.

## Interpretation

This run narrows the next serious frontier to:

- `leader_award`
- `kanban_pull`
- `dual_command`

These three represent three different architecture families:

- lead-driven allocation
- decentralized pull-based workflow
- split control-plane command

That is a more useful frontier than the previous one because it is structurally diverse.

## What This Suggests About The Long-Running Vision

For long-running or continuous work, the best candidate may not be a single static policy.

The evidence now suggests:

- `leader_award` is strongest when reliability and quiescence matter most
- `kanban_pull` is strongest as a reliable continuous-work-feed architecture
- `dual_command` has the best raw upside when the split between planning and verification aligns with the task shape

## Next Step

The next evaluation round should focus on those three policies plus harder continuous-work workloads:

- dependency-heavy tasks with real unblock events
- multi-phase backend + frontend work
- shared-file contention and reassignment
- longer soak windows with explicit idle/quiescence scoring
- restart/recovery scenarios
