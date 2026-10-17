# Published SILO-BENCH Agent Comparison: silo-postfix-prior-failures-n5-consolidated-2026-06-18-a

This run evaluates the same published SILO-BENCH task files with Codex
agent cohorts and Losangelex Hollywood rooms. Each agent received only its
private benchmark shard prompt; the expected answers were used only after
execution for deterministic scoring.

## Summary

| System | Valid tasks | Invalid | Full successes | Avg S | Avg P | Avg S_tol | Avg P_tol | Avg seconds | Avg total tokens | Avg uncached+output | Total tokens/success | Coordination errors |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| codex-subagents | 9 | 0 | 5 (55.56%) | 0.556 | 0.597 | 1.000 | 1.000 | 203.5 | 977,628 | 160,604 | 1,759,730 | 0 |
| losangelex | 9 | 0 | 2 (22.22%) | 0.400 | 0.461 | 0.844 | 0.864 | 135.0 | 2,413,434 | 380,993 | 10,860,454 | 0 |

## By Level

| Level | System | Valid tasks | Invalid | Full successes | Avg S | Avg P | Avg S_tol | Avg P_tol | Avg seconds | Avg total tokens | Avg uncached+output | Total tokens/success | Coordination errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| II | codex-subagents | 5 | 0 | 4 (80.00%) | 0.800 | 0.874 | 1.000 | 1.000 | 173.4 | 920,877 | 148,935 | 1,151,096 | 0 |
| II | losangelex | 5 | 0 | 1 (20.00%) | 0.520 | 0.630 | 0.720 | 0.756 | 119.6 | 2,036,737 | 351,668 | 10,183,685 | 0 |
| III | codex-subagents | 4 | 0 | 1 (25.00%) | 0.250 | 0.250 | 1.000 | 1.000 | 241.2 | 1,048,566 | 175,190 | 4,194,265 | 0 |
| III | losangelex | 4 | 0 | 1 (25.00%) | 0.250 | 0.250 | 1.000 | 1.000 | 154.3 | 2,884,306 | 417,650 | 11,537,223 | 0 |

## Tasks

- codex-subagents `II-12_n5.json`: valid success=False S=0.000 P=0.370 S_tol=1.000 P_tol=1.000 seconds=200.7 total_tokens=1,190,036 uncached_plus_output_tokens=174,612 coordination_errors=0
- losangelex `II-12_n5.json`: valid success=False S=0.000 P=0.370 S_tol=1.000 P_tol=1.000 seconds=118.6 total_tokens=1,686,723 uncached_plus_output_tokens=326,467 coordination_errors=0
- codex-subagents `II-14_n5.json`: valid success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=172.1 total_tokens=926,288 uncached_plus_output_tokens=122,576 coordination_errors=0
- losangelex `II-14_n5.json`: valid success=False S=0.800 P=0.980 S_tol=0.800 P_tol=0.980 seconds=119.2 total_tokens=2,148,378 uncached_plus_output_tokens=345,882 coordination_errors=0
- codex-subagents `II-15_n5.json`: valid success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=143.8 total_tokens=831,183 uncached_plus_output_tokens=200,143 coordination_errors=0
- losangelex `II-15_n5.json`: valid success=False S=0.000 P=0.000 S_tol=0.000 P_tol=0.000 seconds=119.7 total_tokens=2,296,468 uncached_plus_output_tokens=390,036 coordination_errors=0
- codex-subagents `II-17_n5.json`: valid success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=189.1 total_tokens=803,244 uncached_plus_output_tokens=133,676 coordination_errors=0
- losangelex `II-17_n5.json`: valid success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=120.4 total_tokens=2,048,653 uncached_plus_output_tokens=370,061 coordination_errors=0
- codex-subagents `II-20_n5.json`: valid success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=161.2 total_tokens=853,634 uncached_plus_output_tokens=113,666 coordination_errors=0
- losangelex `II-20_n5.json`: valid success=False S=0.800 P=0.800 S_tol=0.800 P_tol=0.800 seconds=120.2 total_tokens=2,003,463 uncached_plus_output_tokens=325,895 coordination_errors=0
- codex-subagents `III-25_n5.json`: valid success=False S=0.000 P=0.000 S_tol=1.000 P_tol=1.000 seconds=245.8 total_tokens=1,181,342 uncached_plus_output_tokens=256,158 coordination_errors=0
- losangelex `III-25_n5.json`: valid success=False S=0.000 P=0.000 S_tol=1.000 P_tol=1.000 seconds=120.6 total_tokens=1,913,317 uncached_plus_output_tokens=350,565 coordination_errors=0
- codex-subagents `III-26_n5.json`: valid success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=198.2 total_tokens=1,053,822 uncached_plus_output_tokens=140,158 coordination_errors=0
- losangelex `III-26_n5.json`: valid success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=104.8 total_tokens=2,034,899 uncached_plus_output_tokens=351,571 coordination_errors=0
- codex-subagents `III-27_n5.json`: valid success=False S=0.000 P=0.000 S_tol=1.000 P_tol=1.000 seconds=315.2 total_tokens=1,006,890 uncached_plus_output_tokens=181,802 coordination_errors=0
- losangelex `III-27_n5.json`: valid success=False S=0.000 P=0.000 S_tol=1.000 P_tol=1.000 seconds=210.3 total_tokens=4,018,013 uncached_plus_output_tokens=473,821 coordination_errors=0
- codex-subagents `III-28_n5.json`: valid success=False S=0.000 P=0.000 S_tol=1.000 P_tol=1.000 seconds=205.7 total_tokens=952,211 uncached_plus_output_tokens=122,643 coordination_errors=0
- losangelex `III-28_n5.json`: valid success=False S=0.000 P=0.000 S_tol=1.000 P_tol=1.000 seconds=181.4 total_tokens=3,570,994 uncached_plus_output_tokens=494,642 coordination_errors=0
