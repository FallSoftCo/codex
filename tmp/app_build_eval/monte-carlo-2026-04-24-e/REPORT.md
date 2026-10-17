# Hollywood App Monte Carlo Evaluation

- Updated at: 2026-04-24 13:32:38 EDT
- App server: `ws://127.0.0.1:46422`
- Challenges: `habit_dashboard`, `incident_console`, `expense_board`
- Policies: `leader_award`, `kanban_pull`, `dual_command`, `org_layered`, `gpgp_blackboard`
- Repeats per challenge/policy: `1`
- Timeout per run: `240s`
- Poll interval: `40s`
- Completed runs: `4/15`

## Overall Leaderboard

| Policy | Pass Rate | Avg Time To Green | Avg Hollywood Messages | Avg Active Threads After Run | Avg Changed Files |
| --- | ---: | ---: | ---: | ---: | ---: |
| `kanban_pull` | 1.00 | 223.9s | 43.0 | 4.0 | 2.0 |
| `leader_award` | 1.00 | 263.8s | 99.0 | 4.0 | 2.0 |
| `org_layered` | 1.00 | 264.6s | 82.0 | 4.0 | 1.0 |
| `dual_command` | 1.00 | 265.3s | 54.0 | 3.0 | 1.0 |

## Per-Challenge Summary

| Challenge | Policy | Pass Rate | Avg Time To Green | Avg Hollywood Messages | Avg Active Threads After Run | Avg Changed Files |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `habit_dashboard` | `dual_command` | 1.00 | 265.3s | 54.0 | 3.0 | 1.0 |
| `habit_dashboard` | `kanban_pull` | 1.00 | 223.9s | 43.0 | 4.0 | 2.0 |
| `habit_dashboard` | `leader_award` | 1.00 | 263.8s | 99.0 | 4.0 | 2.0 |
| `habit_dashboard` | `org_layered` | 1.00 | 264.6s | 82.0 | 4.0 | 1.0 |

## Notes

- `Avg Active Threads After Run` uses the recorded final thread states after the post-pass soak window.
- Lower `Avg Hollywood Messages` is not automatically better; it only becomes a positive signal when pass rate stays high.
- `Avg Changed Files` is a rough proxy for how broad the resulting workspace delta was relative to the scaffold.
