# Hollywood Collaboration Postfix Evaluation - 2026-06-18

This artifact captures post-fix evidence for default-on Losangelex/Hollywood collaboration behavior after the peer wake path was moved from the debug flag to the default collaboration policy.

## What Changed

- Prompt/context policy: agents are now instructed by default to decide whether collaboration would help, ask peers directly with required responses when collaboration is useful, and avoid peer churn for tiny work.
- Runtime wake path: Hollywood polling now follows the default collaboration policy instead of only `LOSANGELEX_COLLABORATION_FIRST_DEBUG`.
- Benchmark harness: the SILO Losangelex wait loop now stops once all expected submission files exist after initial turns complete. This removed a benchmark wait/poll tail that was not useful task work.

## Artifacts

- `HOLLYWOOD_COORDINATION_REPORT.md` and `hollywood-coordination-results.json`: live coordination benchmark across Codex single, Codex subagents, Losangelex collaboration disabled, and Losangelex collaboration enabled.
- `SILO_POSTFIX_SUBSET_REPORT.md` and `silo-postfix-subset-waitfix-results.json`: 6 paired SILO Level I five-agent tasks, Codex subagents vs Losangelex.
- `SILO_POSTFIX_PRIOR_FAILURES_N5_REPORT.md` and `silo-postfix-prior-failures-n5-results.json`: targeted SILO five-agent cases that were partial/failing before the June 16 snapshot.
- `SILO_POSTFIX_PRIOR_FAILURES_N10_REPORT.md` and `silo-postfix-prior-failures-n10-results.json`: targeted SILO ten-agent cases that were partial/failing before the June 16 snapshot.
- `MARBLE_POSTFIX_SUBSET_REPORT.md` and `marble-postfix-subset-results.json`: 6 paired native-Postgres MARBLE database tasks, Codex subagents vs Losangelex.
- `PLAN.md`: compaction-safe execution plan and notes.

## Results

| Evaluation | System | Valid tasks | Invalid | Success | Avg seconds | Avg total tokens | Avg uncached+output |
|---|---|---:|---:|---:|---:|---:|---:|
| Coordination | codex | 3 | 0 | 3/3 | 56.8 | 86,745 | 19,119 |
| Coordination | codex-subagents | 3 | 0 | 3/3 | 107.9 | 271,828 | 57,641 |
| Coordination | losangelex-baseline | 3 | 0 | 1/3 | 110.1 | 341,854 | 60,424 |
| Coordination | losangelex | 3 | 0 | 3/3 | 136.3 | 587,980 | 103,884 |
| SILO Level I subset | codex-subagents | 6 | 0 | 6/6 | 147.2 | 790,865 | 119,739 |
| SILO Level I subset | losangelex | 6 | 0 | 6/6 | 81.0 | 1,471,166 | 265,257 |
| SILO prior hard n5 | codex-subagents | 9 | 0 | 5/9 | 203.5 | 977,628 | 160,604 |
| SILO prior hard n5 | losangelex | 9 | 0 | 2/9 | 135.0 | 2,413,434 | 380,993 |
| SILO prior hard n10 | codex-subagents | 3 | 0 | 2/3 | 467.6 | 1,715,535 | 273,828 |
| SILO prior hard n10 | losangelex | 3 | 0 | 0/3 | 175.5 | 6,876,753 | 1,044,902 |
| MARBLE subset | codex-subagents | 6 | 0 | 6/6 | 198.3 | 1,347,910 | 198,790 |
| MARBLE subset | losangelex | 6 | 0 | 6/6 | 170.9 | 2,468,825 | 447,705 |

## Interpretation

- The live coordination benchmark confirms the fixed Losangelex path actually wakes peers: enabled Losangelex passed 3/3 with required peer requests and peer responses; disabled Losangelex solved files but failed coordination on collaborative cases.
- Codex subagents solved the small coordination fixtures, but did not spawn workers on the two collaborative fixtures in this run.
- On the SILO subset, Losangelex is materially faster than Codex subagents while preserving 100% success, but uses about 2.2x uncached+output tokens.
- On the targeted pre-June-16 SILO hard-case slice, Losangelex did not show a broad quality lift: it solved 2/9 versus Codex subagents at 5/9, while remaining faster and about 2.4x token-heavier on uncached+output. A quota-limited intermediate run was completed with targeted reruns; the consolidated artifact has no invalid rows.
- The targeted n10 hard-case slice reinforces this: Losangelex solved 0/3 versus Codex subagents at 2/3, while remaining 2.7x faster and about 3.8x token-heavier on uncached+output.
- On the MARBLE subset, Losangelex is modestly faster while preserving 100% success/recall, but uses about 2.3x uncached+output tokens.
- Full SILO/MARBLE reruns are not recommended until the remaining token-efficiency and hard-case quality gaps are addressed or explicitly accepted. The subset evidence is stable enough to identify the current tradeoff: latency improved, cost still loses, and default collaboration does not automatically rescue historical SILO failures.

## Caveats

- These are subset results, not full benchmark reruns.
- The targeted hard-case SILO run originally hit usage limits at 4:52 PM EDT; targeted reruns after the 7:25 PM reset replaced the invalid rows in the consolidated artifact.
- The coordination benchmark is deliberately Hollywood-native; it is useful for measuring peer wake/response behavior but should not replace SILO/MARBLE.
- The pre-fix June 15/16 full benchmark artifacts remain the latest full comparable runs.
