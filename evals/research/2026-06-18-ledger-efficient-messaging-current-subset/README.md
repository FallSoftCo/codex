# Ledger-Efficient Hollywood Current Subset Evaluation

Generated: 2026-06-18

This is a bounded model-in-the-loop subset evaluation of the ledger-efficient
Hollywood coordination changes after merging current upstream Codex. It is not a
full benchmark rerun. The subset was preregistered before execution: one SILO n5
case from each level and two MARBLE database cases, each run with current
Losangelex and current Codex subagents.

## Runtime Under Test

- Worktree: `/home/ai/Development/losangelex-ledger-efficient-messaging`
- Branch: `hollywood-ledger-efficient-messaging`
- Commit: `07bf3b7d2eb450349b4712ae2f9b493123a9076f`
- Binary: `codex-rs/target/losangelex-ledger-eval/debug/codex`
- Model: `gpt-5.5`
- SILO systems: `losangelex-selector`, `codex-subagents`
- MARBLE systems: `losangelex`, `codex-subagents`
- App-server mode: isolated managed benchmark app-server per runner
- Started: 2026-06-18T05:45:06Z
- Finished: 2026-06-18T06:08:51Z

The published benchmark repositories were copied into this worktree under
`tmp/research/published-agent-benchmarks/repos` before execution so the runner
could hide benchmark repositories without touching live checkout state.

## Results

| Benchmark | System | Tasks | Successes | Avg seconds | Avg total tokens | Avg uncached+output | Coordination errors |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| SILO n5 stratified | losangelex-selector | 3 | 3 | 88.3 | 1,109,471 | 205,194 | 0 |
| SILO n5 stratified | codex-subagents | 3 | 3 | 159.6 | 840,545 | 136,972 | 0 |
| MARBLE database | losangelex | 2 | 2 | 150.8 | 1,924,300 | 387,084 | 0 |
| MARBLE database | codex-subagents | 2 | 2 | 188.8 | 1,353,278 | 248,254 | 0 |

In this subset, Losangelex was faster but used more tokens:

- SILO: Losangelex-selector was 44.7% faster by wall time, with 32.0% more total tokens and 49.8% more uncached+output tokens.
- MARBLE: Losangelex was 20.1% faster by wall time, with 42.2% more total tokens and 55.9% more uncached+output tokens.

All systems achieved full recall/success on the selected tasks. MARBLE exact-set
matches were 0/2 for both systems because both systems predicted the required
root cause plus one extra label on each case.

## Included Files

- `silo-n5-stratified-current-results.json`: raw SILO results.
- `silo-n5-stratified-current-report.md`: generated SILO report.
- `marble-db-current-results.json`: raw MARBLE results.
- `marble-db-current-report.md`: generated MARBLE report.
- `subset.status.txt`: runner start/end/status log.
- `run_2026_06_18_subset.sh.txt`: exact command script used for this subset.
- `SHA256SUMS.txt`: artifact checksums.

## Notes

- This subset is useful as current-build regression evidence, not as a statistically meaningful replacement for the full June 16 benchmark set.
- The result supports the same directional finding as earlier runs: Losangelex/Hollywood buys wall-clock speed through more concurrent model work, while current Codex subagents are more token-efficient on this subset.
- No live user Losangelex session or main-checkout app-server was reused or interrupted.
