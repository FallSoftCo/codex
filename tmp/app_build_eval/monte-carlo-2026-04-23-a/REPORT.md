# Hollywood App Monte Carlo Evaluation

- Updated at: 2026-04-23 22:40:43 EDT
- App server: `ws://127.0.0.1:46332`
- Challenges: `habit_dashboard`, `incident_console`, `expense_board`
- Policies: `room_message`, `leader_award`, `semantic_market`, `hybrid`
- Repeats per challenge/policy: `1`
- Timeout per run: `240s`
- Poll interval: `40s`
- Completed runs: `12/12`

## Summary

| Challenge | Policy | Pass Rate | Avg Time To Green | Avg Hollywood Messages | Avg Active Threads After Run | Avg Changed Files |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `expense_board` | `hybrid` | 1.00 | 232.0s | 71.0 | 4.0 | 2.0 |
| `expense_board` | `leader_award` | 1.00 | 265.4s | 67.0 | 4.0 | 2.0 |
| `expense_board` | `room_message` | 1.00 | 264.3s | 177.0 | 4.0 | 3.0 |
| `expense_board` | `semantic_market` | 1.00 | 228.8s | 97.0 | 4.0 | 4.0 |
| `habit_dashboard` | `hybrid` | 1.00 | 225.0s | 76.0 | 4.0 | 2.0 |
| `habit_dashboard` | `leader_award` | 1.00 | 264.8s | 36.0 | 2.0 | 1.0 |
| `habit_dashboard` | `room_message` | 1.00 | 222.6s | 64.0 | 4.0 | 3.0 |
| `habit_dashboard` | `semantic_market` | 1.00 | 222.6s | 157.0 | 4.0 | 3.0 |
| `incident_console` | `hybrid` | 1.00 | 182.3s | 52.0 | 4.0 | 2.0 |
| `incident_console` | `leader_award` | 1.00 | 222.4s | 33.0 | 4.0 | 2.0 |
| `incident_console` | `room_message` | 1.00 | 267.6s | 56.0 | 4.0 | 3.0 |
| `incident_console` | `semantic_market` | 1.00 | 183.8s | 54.0 | 4.0 | 2.0 |

## Notes

- `Avg Active Threads After Run` uses the recorded final thread states after the post-pass soak window.
- Lower `Avg Hollywood Messages` is not automatically better; it only becomes a positive signal when pass rate stays high.
- `Avg Changed Files` is a rough proxy for how broad the resulting workspace delta was relative to the scaffold.
