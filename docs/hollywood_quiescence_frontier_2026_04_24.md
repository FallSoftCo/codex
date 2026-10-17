# Hollywood Quiescence Frontier Notes (2026-04-24)

This note captures the next stability finding after the earlier app-build policy comparisons.

The short version:

- prompt-level policy search still changes throughput
- it no longer meaningfully improves shutdown / settling
- explicit quiescence instructions alone are not enough

That means the next frontier is runtime support for termination detection and durable obligation state, not more freeform prompt variation.

## Inputs

### Partial long-soak comparison

Campaign artifact:

- [tmp/app_build_eval/monte-carlo-2026-04-24-e/results.json](/home/ai/Development/losangelex/tmp/app_build_eval/monte-carlo-2026-04-24-e/results.json)
- [tmp/app_build_eval/monte-carlo-2026-04-24-e/REPORT.md](/home/ai/Development/losangelex/tmp/app_build_eval/monte-carlo-2026-04-24-e/REPORT.md)

Configuration:

- app server: `ws://127.0.0.1:46422`
- timeout: `240s`
- poll interval: `40s`
- post-pass soak: `30s`
- policies attempted: `leader_award`, `kanban_pull`, `dual_command`, `org_layered`, `gpgp_blackboard`

The broader run was intentionally stopped after the first challenge once the evidence was decisive enough.

Observed `habit_dashboard` results:

| Policy | Pass Rate | Time To Green | Hollywood Messages | Active Threads After Soak |
| --- | ---: | ---: | ---: | ---: |
| `kanban_pull` | 1.00 | 223.9s | 43 | 4 |
| `leader_award` | 1.00 | 263.8s | 99 | 4 |
| `org_layered` | 1.00 | 264.6s | 82 | 4 |
| `dual_command` | 1.00 | 265.3s | 54 | 3 |

Interpretation:

- `kanban_pull` was the best throughput policy in this slice and the quietest of the fully green runs.
- `dual_command` modestly improved quiescence, but not enough to count as a real settlement solution.
- `org_layered`, despite being directly research-shaped, did not improve settling at all on this task.

The fifth candidate, `gpgp_blackboard`, was rejected before continuing the full matrix because its `habit_dashboard` workspace was still failing 4/5 tests when inspected externally, while the other four policies were already green.

### Targeted `quiescence_token` follow-up

Policy intent:

- keep leader-style execution
- add an explicit distributed quiescence round
- require `IDLE-ACK` / `STILL-OWN <exact-scope>` responses before shutdown

Observed `habit_dashboard` result:

| Policy | Pass Rate | Time To Green | Hollywood Messages | Active Threads After Soak |
| --- | ---: | ---: | ---: | ---: |
| `quiescence_token` | 1.00 | 265.5s | 109 | 4 |

Interpretation:

- The prompt-level termination protocol did not improve settlement.
- It actually increased coordination traffic.
- The room transcript showed the right idea semantically: Ray started a quiescence round, teammates replied with `IDLE-ACK`, and the test gate was green.
- Despite that, all threads still remained active in final thread state after the soak window.

That is the key result.

## What This Means

Prompt-only quiescence is not enough.

The system can now:

- solve the app
- run green tests
- even speak an explicit shutdown protocol in room language

But the runtime still does not interpret that as durable global termination.

So the next stable-systems step should be in the kernel:

1. **Durable per-agent obligation state**
   Each agent needs explicit outstanding-obligation tracking, not just room messages and active turns.

2. **Runtime quiescence barrier**
   A first-class barrier where the system records:
   - all agents passive
   - no unacknowledged obligations
   - no in-flight wake-worthy deltas
   - last deterministic gate still green

3. **Termination detection semantics**
   Shutdown should be a state transition, not a social consensus pattern.

4. **Reason-for-active diagnostics**
   If a thread is still active after green, the runtime should say why:
   - pending wake
   - unresolved obligation
   - in-flight turn
   - stale Hollywood delta
   - waiting on barrier / missing idle ack

## Current Best Read

For prompt-level policy:

- `kanban_pull` remains the best throughput candidate
- `dual_command` remains the best slight-quiescence candidate
- `org_layered` did not move the frontier enough
- `quiescence_token` disproved the idea that “just add explicit shutdown instructions” solves the problem

For architecture:

- exact claims and durable coordination state were necessary
- synthetic briefs were necessary
- hardening the runtime was necessary
- the next irreducible requirement is **runtime-level termination detection**
