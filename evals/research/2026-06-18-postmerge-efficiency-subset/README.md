# Post-Merge Ledger-Efficient Hollywood Subset Evaluation

Generated: 2026-06-18

This is a bounded model-in-the-loop subset evaluation of the
ledger-efficient Hollywood coordination changes after merging current upstream
Codex into the Losangelex feature branch. It reruns the same stratified subset
used earlier on 2026-06-18 so the current branch can be compared against Codex
subagents after the upstream catch-up and direct Hollywood tool exposure work.

This is not a full benchmark rerun. It covers one SILO n5 case from each level
and two MARBLE database cases.

## Runtime Under Test

- Worktree: `/home/ai/Development/losangelex-ledger-efficient-messaging`
- Branch: `hollywood-ledger-efficient-messaging`
- Commit: `a89a1e472c75812412241797b66544d633af6626`
- Binary: `codex-rs/target/debug/codex`
- Model: `gpt-5.5`
- SILO systems: `codex-subagents`, `losangelex-selector`
- MARBLE systems: `codex-subagents`, `losangelex`
- App-server mode: isolated managed benchmark app-server per runner
- Finished: 2026-06-18T13:59:17Z

The published benchmark repositories were read from the main checkout fixture
cache under `/home/ai/Development/losangelex/tmp/research/published-agent-benchmarks/repos`
so this run did not touch live user checkout or app-server state.

## Results

| Benchmark | System | Tasks | Successes | Avg seconds | Avg total tokens | Avg uncached+output | Coordination errors |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| SILO n5 stratified | codex-subagents | 3 | 3 | 157.6 | 908,818 | 176,360 | 0 |
| SILO n5 stratified | losangelex-selector | 3 | 3 | 112.8 | 1,449,053 | 227,037 | 0 |
| MARBLE database | codex-subagents | 2 | 2 | 203.7 | 1,426,958 | 220,494 | 0 |
| MARBLE database | losangelex | 2 | 2 | 169.3 | 2,213,849 | 424,665 | 0 |

In this subset, Losangelex kept a wall-clock advantage but did not beat Codex
subagents on token cost:

- SILO: Losangelex-selector was 28.4% faster by wall time, with 59.4% more total tokens and 28.7% more uncached+output tokens.
- MARBLE: Losangelex was 16.9% faster by wall time, with 55.1% more total tokens and 92.6% more uncached+output tokens.

All selected tasks reached full success/recall for both systems. MARBLE exact
set matches were 0/2 for both systems because both systems predicted the
required root cause plus one extra label on each case.

## Interpretation

The post-merge subset confirms the main directional finding from the earlier
June 18 subset: Losangelex/Hollywood is lower latency on these parallelizable
tasks, while current Codex subagents remain more token-efficient on average.

The SILO Level I case is the strongest current signal for a possible path to
cost parity: `losangelex-selector` used `first-finisher`, solved the task in
72.6s, and used fewer tokens than Codex subagents. The Level II/III SILO cases
and MARBLE database cases still launch five peers and pay large aggregate input
costs across all active threads.

The runner-level coordination summaries also matter: the SILO and MARBLE
Losangelex rows in this subset reported zero Hollywood coordination tool calls.
So this subset measures benchmark-room concurrency and selector policy more than
direct model-initiated Hollywood collaboration. Separate debug evaluations in
`tmp/research/collaboration-first-debug` showed direct tool exposure causes real
Hollywood calls, but those are not represented by this published subset.

## Next Efficiency Targets

- Make the topology selector more selective: use first-finisher or one verifier
  for tasks that do not truly need all peers to complete.
- Add an event-driven obligation wake path so waiting/checking does not require
  extra model turns when Hollywood already knows which peer owes a response.
- Keep per-thread context to task-local deltas: peer briefs should receive only
  the shard, claimed paths, direct messages, and changed task state.
- Stop redundant post-final acknowledgements unless another agent still owes
  integration work.
- Add a direct-collaboration benchmark mode only if it is preregistered and run
  beside the published modes; do not replace published benchmark comparisons
  with a mode tuned only for Losangelex.

## Included Files

- `silo-n5-stratified-postmerge-results.json`: raw SILO results.
- `silo-n5-stratified-postmerge-report.md`: generated SILO report.
- `marble-db-postmerge-results.json`: raw MARBLE results.
- `marble-db-postmerge-report.md`: generated MARBLE report.
- `run_2026_06_18_postmerge_subset.sh.txt`: exact commands used for this subset.
- `subset.status.txt`: completion/status note.
- `SHA256SUMS.txt`: artifact checksums.
