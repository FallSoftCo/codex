# Hollywood App Monte Carlo Evaluation

- Updated at: 2026-04-24 00:53:26 EDT
- App server: `ws://127.0.0.1:46334`
- Challenges: `habit_dashboard`, `incident_console`, `expense_board`
- Policies: `leader_award`, `leader_market`, `critic_executor`, `dual_command`, `kanban_pull`, `relay_foreman`, `review_gated`
- Repeats per challenge/policy: `1`
- Timeout per run: `240s`
- Poll interval: `40s`
- Completed runs: `3/21`

## Overall Leaderboard

| Policy | Pass Rate | Avg Time To Green | Avg Hollywood Messages | Avg Active Threads After Run | Avg Changed Files |
| --- | ---: | ---: | ---: | ---: | ---: |
| `leader_award` | 1.00 | 222.1s | 27.0 | 2.0 | 1.0 |
| `critic_executor` | 1.00 | 226.1s | 57.0 | 4.0 | 2.0 |
| `leader_market` | 1.00 | 263.2s | 66.0 | 4.0 | 1.0 |

## Per-Challenge Summary

| Challenge | Policy | Pass Rate | Avg Time To Green | Avg Hollywood Messages | Avg Active Threads After Run | Avg Changed Files |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `habit_dashboard` | `critic_executor` | 1.00 | 226.1s | 57.0 | 4.0 | 2.0 |
| `habit_dashboard` | `leader_award` | 1.00 | 222.1s | 27.0 | 2.0 | 1.0 |
| `habit_dashboard` | `leader_market` | 1.00 | 263.2s | 66.0 | 4.0 | 1.0 |

## Notes

- `Avg Active Threads After Run` uses the recorded final thread states after the post-pass soak window.
- Lower `Avg Hollywood Messages` is not automatically better; it only becomes a positive signal when pass rate stays high.
- `Avg Changed Files` is a rough proxy for how broad the resulting workspace delta was relative to the scaffold.
