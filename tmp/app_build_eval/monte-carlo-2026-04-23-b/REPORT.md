# Hollywood App Monte Carlo Evaluation

- Updated at: 2026-04-24 00:31:39 EDT
- App server: `ws://127.0.0.1:46333`
- Challenges: `habit_dashboard`, `incident_console`, `expense_board`
- Policies: `room_message`, `leader_award`, `semantic_market`, `hybrid`, `market_with_finisher`, `leader_market`, `critic_executor`
- Repeats per challenge/policy: `1`
- Timeout per run: `240s`
- Poll interval: `40s`
- Completed runs: `21/21`

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

## Per-Challenge Summary

| Challenge | Policy | Pass Rate | Avg Time To Green | Avg Hollywood Messages | Avg Active Threads After Run | Avg Changed Files |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `expense_board` | `critic_executor` | 1.00 | 182.3s | 48.0 | 4.0 | 3.0 |
| `expense_board` | `hybrid` | 1.00 | 224.4s | 125.0 | 4.0 | 3.0 |
| `expense_board` | `leader_award` | 1.00 | 181.7s | 16.0 | 1.0 | 2.0 |
| `expense_board` | `leader_market` | 1.00 | 226.1s | 33.0 | 4.0 | 4.0 |
| `expense_board` | `market_with_finisher` | 0.00 | - | 129.0 | 4.0 | 2.0 |
| `expense_board` | `room_message` | 1.00 | 184.3s | 43.0 | 4.0 | 1.0 |
| `expense_board` | `semantic_market` | 1.00 | 268.5s | 198.0 | 4.0 | 3.0 |
| `habit_dashboard` | `critic_executor` | 1.00 | 265.4s | 37.0 | 4.0 | 1.0 |
| `habit_dashboard` | `hybrid` | 0.00 | - | 78.0 | 4.0 | 0.0 |
| `habit_dashboard` | `leader_award` | 1.00 | 268.0s | 43.0 | 2.0 | 2.0 |
| `habit_dashboard` | `leader_market` | 1.00 | 267.6s | 82.0 | 3.0 | 3.0 |
| `habit_dashboard` | `market_with_finisher` | 1.00 | 182.4s | 89.0 | 4.0 | 1.0 |
| `habit_dashboard` | `room_message` | 1.00 | 264.3s | 164.0 | 4.0 | 1.0 |
| `habit_dashboard` | `semantic_market` | 1.00 | 224.5s | 75.0 | 4.0 | 1.0 |
| `incident_console` | `critic_executor` | 1.00 | 189.7s | 33.0 | 4.0 | 3.0 |
| `incident_console` | `hybrid` | 1.00 | 268.4s | 71.0 | 3.0 | 2.0 |
| `incident_console` | `leader_award` | 1.00 | 181.3s | 21.0 | 1.0 | 1.0 |
| `incident_console` | `leader_market` | 1.00 | 142.0s | 41.0 | 4.0 | 1.0 |
| `incident_console` | `market_with_finisher` | 0.00 | - | 107.0 | 4.0 | 2.0 |
| `incident_console` | `room_message` | 1.00 | 223.4s | 68.0 | 4.0 | 1.0 |
| `incident_console` | `semantic_market` | 1.00 | 224.7s | 86.0 | 4.0 | 3.0 |

## Notes

- `Avg Active Threads After Run` uses the recorded final thread states after the post-pass soak window.
- Lower `Avg Hollywood Messages` is not automatically better; it only becomes a positive signal when pass rate stays high.
- `Avg Changed Files` is a rough proxy for how broad the resulting workspace delta was relative to the scaffold.
