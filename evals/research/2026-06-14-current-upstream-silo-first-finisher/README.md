# Current-Upstream SILO First-Finisher Pilot, 2026-06-14

This directory contains a small current-upstream SILO-BENCH refresh run after
merging the FallSoftCo Losangelex fork with upstream Codex changes through
June 2026.

The run is a matched four-task pilot, not a replacement for the June 2 full
30-task token-cost study. Its purpose is to check how the current upstream
Codex subagent implementation compares with normal Losangelex/Hollywood rooms
and an experimental first-finisher Hollywood coordination pattern.

## Files

- `results.json` - path-masked combined result data for 12 records: four task
  files times three systems.
- `SILO_PUBLISHED_REPORT.md` - generated aggregate report for the same records.
- `SHA256SUMS.txt` - checksums for the tracked files in this bundle.

## Systems

| System | Meaning |
| --- | --- |
| `codex-subagents` | Current upstream Codex parent process with five subagents. |
| `losangelex` | Normal Losangelex/Hollywood room execution with five agents. |
| `losangelex-first-finisher` | Experimental Hollywood pattern where workers publish compact notes and the first worker to acquire a lock becomes the final aggregator. |

## Result

| System | Tasks | Strict successes | Mean time | Avg total tokens | Avg uncached+output |
| --- | ---: | ---: | ---: | ---: | ---: |
| `codex-subagents` | 4 | 4/4 | 154.3s | 827,710 | 118,558 |
| `losangelex` | 4 | 4/4 | 113.6s | 1,104,493 | 166,893 |
| `losangelex-first-finisher` | 4 | 4/4 | 157.9s | 912,785 | 120,209 |

On this sample, normal Hollywood remains the latency leader, upstream Codex
subagents are the total-token leader, and the first-finisher pattern reduces
Hollywood token usage materially while giving up the latency advantage.

## Interpretation

This is evidence for a coordination-design tradeoff, not a broad benchmark
win. The first-finisher pattern is useful when the system wants a bounded fan-in
phase and compact shared notes, but it can add wait time and should not replace
normal Hollywood room coordination purely to improve a benchmark aggregate.

The primary public evidence remains the June 2 30-task SILO and MARBLE
token-cost study. This bundle is a current-upstream check and a design probe for
team-coordination semantics.
