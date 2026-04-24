# Hollywood App Monte Carlo Evaluation (2026-04-23)

This note captures a real model-in-the-loop coordination benchmark for Losangelex/Hollywood using artifact completion rather than proxy metrics.

## Goal

Compare coordination policies on broad app-building tasks where a team is told to finish the app and only stop when the deterministic test gate passes.

This is meant to answer a practical question:

- which policy gets a team to green fastest
- which policy keeps chatter under control
- which policy actually quiesces after success

## Harness

- Runner: [scripts/run_app_monte_carlo.py](/home/ai/Development/losangelex/scripts/run_app_monte_carlo.py:1)
- Per-run evaluator: [scripts/eval_hollywood_app_builds.py](/home/ai/Development/losangelex/scripts/eval_hollywood_app_builds.py:1)
- Raw campaign output: [tmp/app_build_eval/monte-carlo-2026-04-23-a/results.json](/home/ai/Development/losangelex/tmp/app_build_eval/monte-carlo-2026-04-23-a/results.json)
- Generated campaign report: [tmp/app_build_eval/monte-carlo-2026-04-23-a/REPORT.md](/home/ai/Development/losangelex/tmp/app_build_eval/monte-carlo-2026-04-23-a/REPORT.md)

The evaluator:

- creates a disposable workspace from a scaffold
- starts a real Hollywood team against a live local app-server
- gives a broad completion brief
- polls `npm test -- --run`
- records final thread state, room traffic, and changed files

## Challenges

- [habit_dashboard_template](/home/ai/Development/losangelex/evals/app_challenges/habit_dashboard_template/README.md:1)
- [incident_console_template](/home/ai/Development/losangelex/evals/app_challenges/incident_console_template/README.md:1)
- [expense_board_template](/home/ai/Development/losangelex/evals/app_challenges/expense_board_template/README.md:1)

Each challenge starts from a meaningful failing baseline and is judged by deterministic tests.

## Policies

- `room_message`
- `leader_award`
- `semantic_market`
- `hybrid`

## Campaign Shape

- date: 2026-04-23
- app server: `ws://127.0.0.1:46332`
- runs: 12
- matrix: 3 challenges x 4 policies x 1 repeat
- timeout per run: 240s
- poll interval: 40s
- post-pass soak: 20s

## Results

Per-policy aggregate:

| Policy | Pass Rate | Avg Time To Green | Avg Hollywood Messages | Avg Active Threads After Run | Avg Changed Files |
| --- | ---: | ---: | ---: | ---: | ---: |
| `semantic_market` | 1.00 | 211.7s | 102.7 | 4.0 | 3.0 |
| `hybrid` | 1.00 | 213.1s | 66.3 | 4.0 | 2.0 |
| `leader_award` | 1.00 | 250.9s | 45.3 | 3.3 | 1.7 |
| `room_message` | 1.00 | 251.5s | 99.0 | 4.0 | 3.0 |

Per-challenge times:

| Challenge | `room_message` | `leader_award` | `semantic_market` | `hybrid` |
| --- | ---: | ---: | ---: | ---: |
| `habit_dashboard` | 222.6s | 264.8s | 222.6s | 225.0s |
| `incident_console` | 267.6s | 222.4s | 183.8s | 182.3s |
| `expense_board` | 264.3s | 265.4s | 228.8s | 232.0s |

## Conclusions

- `leader_award` is not justified as the default throughput policy. It was only clearly competitive on `incident_console`, and its aggregate time-to-green was effectively tied with `room_message`.
- `semantic_market` and `hybrid` are the strongest current candidates for broad app delivery. They were fastest on the two richer CRUD/data tasks.
- `room_message` is no longer “always fails,” but it remains a weak default. It succeeded on all three tasks here only by taking a relatively slow path, and it produced much more chatter than `leader_award`.
- Completion discipline is still missing across most policies. `leader_award` was the only policy that sometimes left fewer than all four threads active after the post-pass soak window.

## Interpretation

The current evidence supports a distributed coordination kernel plus model-facing semantic policy, not plain teamwork chat and not a pure planner loop.

More specifically:

- the team can finish broad tasks now
- policy choice materially affects time-to-green on richer tasks
- `semantic_market` and `hybrid` currently look better than `leader_award` for broad delivery
- explicit finish and quiescence behavior is still underpowered

## Follow-Up

- Increase repeats beyond one per challenge/policy so these rankings stabilize statistically.
- Add at least one dependency-heavy challenge where late handoff and unblock behavior matter more than CRUD throughput.
- Score quiescence harder. A fast green with all threads still active should not be treated as equally good as a fast green with clean shutdown.
- Keep using real model-in-the-loop artifact tasks, not deterministic semantic mocks, for policy evaluation.
