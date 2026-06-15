# SILO Hollywood Topology Selector v1 Full Run, 2026-06-14

This directory contains a full n=5 SILO-BENCH model-in-the-loop evaluation of a
frozen Losangelex/Hollywood topology selector against normal Hollywood room
coordination.

The selector was frozen before the run in
`evals/research/2026-06-14-silo-topology-selector-protocol/README.md` as
`silo-topology-v1-2026-06-14`.

## Files

- `results.json` - path-masked result data for 60 records: 30 task files times
  two systems.
- `SILO_PUBLISHED_REPORT.md` - generated aggregate report for the same records.
- `SHA256SUMS.txt` - checksums for the tracked files in this bundle.

## Systems

| System | Meaning |
| --- | --- |
| `losangelex` | Normal Losangelex/Hollywood room execution with five agents. |
| `losangelex-selector` | Frozen selector: first-finisher for Level I global reductions and normal room coordination for Levels II and III. |

## Result

| System | Tasks | Strict successes | Mean time | Avg total tokens | Avg uncached+output |
| --- | ---: | ---: | ---: | ---: | ---: |
| `losangelex` | 30 | 23/30 | 140.4s | 1,487,623 | 196,756 |
| `losangelex-selector` | 30 | 22/30 | 153.4s | 1,365,936 | 191,835 |

The selector reduced average total tokens by 8.2% and average uncached+output
tokens by 2.5%, but lost one strict success and added 13.1 seconds of mean
latency. Under the protocol's interpretation rules, this means selector v1 is
not ready as a default policy.

## Important Finding

The broad Level I rule is too coarse. Level I first-finisher stayed correct on
all ten tasks and saved tokens on most of them, but `I-10_n5.json` Standard
Deviation regressed sharply: 416.9s and 3,155,226 total tokens under the
selector versus 146.4s and 2,508,323 total tokens under normal room
coordination.

Levels II and III were routed to normal room coordination, so differences there
should be treated as stochastic run-to-run variation rather than evidence about
the foreman pattern. The one strict-success loss was `II-18_n5.json`, which was
room-routed in both systems.

## Interpretation

This run supports a narrower selector, not a global foreman default. A v2 rule
should target simple single-pass bounded aggregations and exclude multi-phase
numeric reductions such as standard deviation unless a different specialized
coordination protocol is designed for them.
