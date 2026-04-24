# Hollywood App Monte Carlo Evaluation

- Updated at: 2026-04-24 09:36:12 EDT
- App server: `ws://127.0.0.1:46335`
- Challenges: `habit_dashboard`, `incident_console`, `expense_board`
- Policies: `leader_award`, `leader_market`, `critic_executor`, `dual_command`, `kanban_pull`, `relay_foreman`, `review_gated`
- Repeats per challenge/policy: `1`
- Timeout per run: `240s`
- Poll interval: `40s`
- Completed runs: `21/21`

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

## Per-Challenge Summary

| Challenge | Policy | Pass Rate | Avg Time To Green | Avg Hollywood Messages | Avg Active Threads After Run | Avg Changed Files |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `expense_board` | `critic_executor` | 0.00 | - | 118.0 | 4.0 | 0.0 |
| `expense_board` | `dual_command` | 1.00 | 181.5s | 85.0 | 4.0 | 2.0 |
| `expense_board` | `kanban_pull` | 1.00 | 224.1s | 56.0 | 4.0 | 2.0 |
| `expense_board` | `leader_award` | 1.00 | 227.1s | 33.0 | 1.0 | 3.0 |
| `expense_board` | `leader_market` | 1.00 | 225.3s | 50.0 | 3.0 | 2.0 |
| `expense_board` | `relay_foreman` | 1.00 | 224.3s | 32.0 | 4.0 | 3.0 |
| `expense_board` | `review_gated` | 1.00 | 221.7s | 46.0 | 4.0 | 1.0 |
| `habit_dashboard` | `critic_executor` | 1.00 | 264.9s | 33.0 | 2.0 | 3.0 |
| `habit_dashboard` | `dual_command` | 1.00 | 220.8s | 90.0 | 4.0 | 2.0 |
| `habit_dashboard` | `kanban_pull` | 1.00 | 265.9s | 102.0 | 4.0 | 3.0 |
| `habit_dashboard` | `leader_award` | 1.00 | 262.5s | 85.0 | 3.0 | 3.0 |
| `habit_dashboard` | `leader_market` | 1.00 | 262.7s | 60.0 | 4.0 | 1.0 |
| `habit_dashboard` | `relay_foreman` | 0.00 | - | 84.0 | 4.0 | 1.0 |
| `habit_dashboard` | `review_gated` | 0.00 | - | 120.0 | 4.0 | 0.0 |
| `incident_console` | `critic_executor` | 1.00 | 180.8s | 61.0 | 4.0 | 3.0 |
| `incident_console` | `dual_command` | 0.00 | - | 108.0 | 4.0 | 0.0 |
| `incident_console` | `kanban_pull` | 1.00 | 181.4s | 33.0 | 4.0 | 3.0 |
| `incident_console` | `leader_award` | 1.00 | 181.2s | 18.0 | 3.0 | 1.0 |
| `incident_console` | `leader_market` | 0.00 | - | 73.0 | 4.0 | 1.0 |
| `incident_console` | `relay_foreman` | 1.00 | 181.8s | 28.0 | 4.0 | 3.0 |
| `incident_console` | `review_gated` | 1.00 | 223.0s | 116.0 | 3.0 | 1.0 |

## Notes

- `Avg Active Threads After Run` uses the recorded final thread states after the post-pass soak window.
- Lower `Avg Hollywood Messages` is not automatically better; it only becomes a positive signal when pass rate stays high.
- `Avg Changed Files` is a rough proxy for how broad the resulting workspace delta was relative to the scaffold.
