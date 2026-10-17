# Published SILO-BENCH Agent Comparison: silo-gpt55-full-n5-all-systems-2026-06-16

This run evaluates the same published SILO-BENCH task files with Codex
agent cohorts and Losangelex Hollywood rooms. Each agent received only its
private benchmark shard prompt; the expected answers were used only after
execution for deterministic scoring.

## Summary

| System | Tasks | Full successes | Avg S | Avg P | Avg S_tol | Avg P_tol | Avg seconds | Avg total tokens | Avg uncached+output | Total tokens/success | Coordination errors |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| codex | 30 | 23 (76.67%) | 0.800 | 0.818 | 0.933 | 0.939 | 841.0 | 1,173,682 | 301,098 | 1,530,890 | 0 |
| codex-full-context | 30 | 25 (83.33%) | 0.833 | 0.846 | 0.967 | 0.967 | 41.4 | 84,428 | 26,402 | 101,314 | 0 |
| codex-subagents | 30 | 24 (80.00%) | 0.800 | 0.812 | 0.933 | 0.933 | 220.8 | 954,987 | 161,852 | 1,193,734 | 0 |
| losangelex | 30 | 25 (83.33%) | 0.833 | 0.846 | 0.967 | 0.967 | 170.9 | 1,679,657 | 317,729 | 2,015,589 | 0 |

## By Level

| Level | System | Tasks | Full successes | Avg S | Avg P | Avg S_tol | Avg P_tol | Avg seconds | Avg total tokens | Avg uncached+output | Total tokens/success | Coordination errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| I | codex | 10 | 10 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 751.5 | 1,138,702 | 267,560 | 1,138,702 | 0 |
| I | codex-full-context | 10 | 10 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 27.6 | 68,370 | 23,020 | 68,370 | 0 |
| I | codex-subagents | 10 | 9 (90.00%) | 0.900 | 0.900 | 0.900 | 0.900 | 158.2 | 824,530 | 128,120 | 916,144 | 0 |
| I | losangelex | 10 | 10 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 121.2 | 1,374,751 | 253,688 | 1,374,751 | 0 |
| II | codex | 10 | 7 (70.00%) | 0.780 | 0.833 | 0.880 | 0.896 | 648.1 | 1,031,133 | 291,613 | 1,473,047 | 0 |
| II | codex-full-context | 10 | 8 (80.00%) | 0.800 | 0.837 | 0.900 | 0.900 | 45.1 | 91,294 | 29,137 | 114,117 | 0 |
| II | codex-subagents | 10 | 8 (80.00%) | 0.800 | 0.837 | 0.900 | 0.900 | 246.7 | 911,541 | 172,392 | 1,139,426 | 0 |
| II | losangelex | 10 | 8 (80.00%) | 0.800 | 0.837 | 0.900 | 0.900 | 202.4 | 1,959,541 | 402,178 | 2,449,426 | 0 |
| III | codex | 10 | 6 (60.00%) | 0.620 | 0.620 | 0.920 | 0.920 | 1123.3 | 1,351,211 | 344,120 | 2,252,018 | 0 |
| III | codex-full-context | 10 | 7 (70.00%) | 0.700 | 0.700 | 1.000 | 1.000 | 51.5 | 93,621 | 27,048 | 133,744 | 0 |
| III | codex-subagents | 10 | 7 (70.00%) | 0.700 | 0.700 | 1.000 | 1.000 | 257.4 | 1,128,890 | 185,044 | 1,612,701 | 0 |
| III | losangelex | 10 | 7 (70.00%) | 0.700 | 0.700 | 1.000 | 1.000 | 189.2 | 1,704,680 | 297,320 | 2,435,258 | 0 |

## Tasks

- codex `I-01_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=538.4 total_tokens=1,023,922 uncached_plus_output_tokens=223,026 coordination_errors=0
- codex-subagents `I-01_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=129.4 total_tokens=785,587 uncached_plus_output_tokens=91,443 coordination_errors=0
- codex-full-context `I-01_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=11.3 total_tokens=39,186 uncached_plus_output_tokens=11,282 coordination_errors=0
- losangelex `I-01_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=103.3 total_tokens=1,195,648 uncached_plus_output_tokens=209,792 coordination_errors=0
- codex `I-02_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=605.3 total_tokens=826,467 uncached_plus_output_tokens=161,507 coordination_errors=0
- codex-subagents `I-02_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=124.0 total_tokens=799,075 uncached_plus_output_tokens=95,203 coordination_errors=0
- codex-full-context `I-02_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=18.4 total_tokens=60,000 uncached_plus_output_tokens=11,744 coordination_errors=0
- losangelex `I-02_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=103.2 total_tokens=1,193,266 uncached_plus_output_tokens=208,434 coordination_errors=0
- codex `I-03_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=527.4 total_tokens=974,335 uncached_plus_output_tokens=163,711 coordination_errors=0
- codex-subagents `I-03_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=167.4 total_tokens=858,526 uncached_plus_output_tokens=83,358 coordination_errors=0
- codex-full-context `I-03_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=30.8 total_tokens=40,776 uncached_plus_output_tokens=12,360 coordination_errors=0
- losangelex `I-03_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=103.1 total_tokens=1,034,107 uncached_plus_output_tokens=208,251 coordination_errors=0
- codex `I-04_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=482.1 total_tokens=813,279 uncached_plus_output_tokens=214,623 coordination_errors=0
- codex-subagents `I-04_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=131.6 total_tokens=632,175 uncached_plus_output_tokens=76,783 coordination_errors=0
- codex-full-context `I-04_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=21.0 total_tokens=80,489 uncached_plus_output_tokens=53,353 coordination_errors=0
- losangelex `I-04_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=103.0 total_tokens=1,176,616 uncached_plus_output_tokens=194,216 coordination_errors=0
- codex `I-05_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=798.3 total_tokens=985,710 uncached_plus_output_tokens=246,126 coordination_errors=0
- codex-subagents `I-05_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=148.3 total_tokens=748,920 uncached_plus_output_tokens=95,480 coordination_errors=0
- codex-full-context `I-05_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=35.7 total_tokens=104,570 uncached_plus_output_tokens=21,242 coordination_errors=0
- losangelex `I-05_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=103.2 total_tokens=1,150,458 uncached_plus_output_tokens=230,266 coordination_errors=0
- codex `I-06_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=655.9 total_tokens=1,150,502 uncached_plus_output_tokens=319,654 coordination_errors=0
- codex-subagents `I-06_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=145.3 total_tokens=762,914 uncached_plus_output_tokens=100,002 coordination_errors=0
- codex-full-context `I-06_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=19.0 total_tokens=60,291 uncached_plus_output_tokens=18,691 coordination_errors=0
- losangelex `I-06_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=148.7 total_tokens=1,475,700 uncached_plus_output_tokens=272,244 coordination_errors=0
- codex `I-07_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=766.8 total_tokens=1,368,640 uncached_plus_output_tokens=314,176 coordination_errors=0
- codex-subagents `I-07_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=160.2 total_tokens=951,757 uncached_plus_output_tokens=141,133 coordination_errors=0
- codex-full-context `I-07_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=36.8 total_tokens=65,435 uncached_plus_output_tokens=21,787 coordination_errors=0
- losangelex `I-07_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=148.1 total_tokens=1,433,433 uncached_plus_output_tokens=237,657 coordination_errors=0
- codex `I-08_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=1240.2 total_tokens=1,539,540 uncached_plus_output_tokens=346,964 coordination_errors=0
- codex-subagents `I-08_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=167.9 total_tokens=864,461 uncached_plus_output_tokens=155,725 coordination_errors=0
- codex-full-context `I-08_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=32.7 total_tokens=82,405 uncached_plus_output_tokens=24,549 coordination_errors=0
- losangelex `I-08_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=148.5 total_tokens=1,887,648 uncached_plus_output_tokens=347,680 coordination_errors=0
- codex `I-09_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=950.4 total_tokens=1,241,741 uncached_plus_output_tokens=323,085 coordination_errors=0
- codex-subagents `I-09_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=175.9 total_tokens=962,425 uncached_plus_output_tokens=184,697 coordination_errors=0
- codex-full-context `I-09_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=26.1 total_tokens=60,499 uncached_plus_output_tokens=18,899 coordination_errors=0
- losangelex `I-09_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=102.9 total_tokens=1,056,980 uncached_plus_output_tokens=301,780 coordination_errors=0
- codex `I-10_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=950.6 total_tokens=1,462,887 uncached_plus_output_tokens=362,727 coordination_errors=0
- codex-subagents `I-10_n5.json`: success=False S=0.000 P=0.000 S_tol=0.000 P_tol=0.000 seconds=231.9 total_tokens=879,456 uncached_plus_output_tokens=257,376 coordination_errors=0
- codex-full-context `I-10_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=44.5 total_tokens=90,049 uncached_plus_output_tokens=36,289 coordination_errors=0
- losangelex `I-10_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=148.3 total_tokens=2,143,651 uncached_plus_output_tokens=326,563 coordination_errors=0
- codex `II-11_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=187.7 total_tokens=497,479 uncached_plus_output_tokens=130,503 coordination_errors=0
- codex-subagents `II-11_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=164.7 total_tokens=858,974 uncached_plus_output_tokens=192,606 coordination_errors=0
- codex-full-context `II-11_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=34.6 total_tokens=102,891 uncached_plus_output_tokens=50,283 coordination_errors=0
- losangelex `II-11_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=193.5 total_tokens=2,382,866 uncached_plus_output_tokens=414,994 coordination_errors=0
- codex `II-12_n5.json`: success=False S=0.000 P=0.370 S_tol=1.000 P_tol=1.000 seconds=739.9 total_tokens=1,268,385 uncached_plus_output_tokens=363,937 coordination_errors=0
- codex-subagents `II-12_n5.json`: success=False S=0.000 P=0.370 S_tol=1.000 P_tol=1.000 seconds=206.1 total_tokens=769,611 uncached_plus_output_tokens=178,379 coordination_errors=0
- codex-full-context `II-12_n5.json`: success=False S=0.000 P=0.370 S_tol=1.000 P_tol=1.000 seconds=71.7 total_tokens=110,678 uncached_plus_output_tokens=32,470 coordination_errors=0
- losangelex `II-12_n5.json`: success=False S=0.000 P=0.370 S_tol=1.000 P_tol=1.000 seconds=193.3 total_tokens=1,947,033 uncached_plus_output_tokens=553,881 coordination_errors=0
- codex `II-13_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=757.2 total_tokens=1,280,157 uncached_plus_output_tokens=455,581 coordination_errors=0
- codex-subagents `II-13_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=166.6 total_tokens=1,312,242 uncached_plus_output_tokens=203,762 coordination_errors=0
- codex-full-context `II-13_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=25.3 total_tokens=79,517 uncached_plus_output_tokens=29,341 coordination_errors=0
- losangelex `II-13_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=193.3 total_tokens=1,774,631 uncached_plus_output_tokens=447,015 coordination_errors=0
- codex `II-14_n5.json`: success=False S=0.800 P=0.960 S_tol=0.800 P_tol=0.960 seconds=769.0 total_tokens=1,427,480 uncached_plus_output_tokens=343,704 coordination_errors=0
- codex-subagents `II-14_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=203.7 total_tokens=1,121,803 uncached_plus_output_tokens=210,315 coordination_errors=0
- codex-full-context `II-14_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=38.9 total_tokens=105,766 uncached_plus_output_tokens=56,230 coordination_errors=0
- losangelex `II-14_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=238.4 total_tokens=2,335,530 uncached_plus_output_tokens=542,506 coordination_errors=0
- codex `II-15_n5.json`: success=False S=0.000 P=0.000 S_tol=0.000 P_tol=0.000 seconds=720.4 total_tokens=970,472 uncached_plus_output_tokens=372,456 coordination_errors=0
- codex-subagents `II-15_n5.json`: success=False S=0.000 P=0.000 S_tol=0.000 P_tol=0.000 seconds=201.4 total_tokens=839,330 uncached_plus_output_tokens=195,362 coordination_errors=0
- codex-full-context `II-15_n5.json`: success=False S=0.000 P=0.000 S_tol=0.000 P_tol=0.000 seconds=44.7 total_tokens=80,643 uncached_plus_output_tokens=36,611 coordination_errors=0
- losangelex `II-15_n5.json`: success=False S=0.000 P=0.000 S_tol=0.000 P_tol=0.000 seconds=283.7 total_tokens=2,271,105 uncached_plus_output_tokens=528,513 coordination_errors=0
- codex `II-16_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=501.0 total_tokens=995,819 uncached_plus_output_tokens=403,947 coordination_errors=0
- codex-subagents `II-16_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=820.2 total_tokens=830,244 uncached_plus_output_tokens=249,764 coordination_errors=0
- codex-full-context `II-16_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=19.4 total_tokens=59,748 uncached_plus_output_tokens=12,004 coordination_errors=0
- losangelex `II-16_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=148.3 total_tokens=1,552,025 uncached_plus_output_tokens=246,937 coordination_errors=0
- codex `II-17_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=578.0 total_tokens=966,344 uncached_plus_output_tokens=298,824 coordination_errors=0
- codex-subagents `II-17_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=173.5 total_tokens=799,151 uncached_plus_output_tokens=91,183 coordination_errors=0
- codex-full-context `II-17_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=75.8 total_tokens=103,837 uncached_plus_output_tokens=21,533 coordination_errors=0
- losangelex `II-17_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=193.5 total_tokens=2,029,473 uncached_plus_output_tokens=395,681 coordination_errors=0
- codex `II-18_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=1294.2 total_tokens=1,426,216 uncached_plus_output_tokens=283,944 coordination_errors=0
- codex-subagents `II-18_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=211.8 total_tokens=944,817 uncached_plus_output_tokens=131,505 coordination_errors=0
- codex-full-context `II-18_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=71.4 total_tokens=107,069 uncached_plus_output_tokens=16,061 coordination_errors=0
- losangelex `II-18_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=193.4 total_tokens=1,875,697 uncached_plus_output_tokens=260,721 coordination_errors=0
- codex `II-19_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=772.8 total_tokens=970,749 uncached_plus_output_tokens=193,533 coordination_errors=0
- codex-subagents `II-19_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=153.3 total_tokens=783,573 uncached_plus_output_tokens=138,965 coordination_errors=0
- codex-full-context `II-19_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=41.9 total_tokens=60,960 uncached_plus_output_tokens=23,456 coordination_errors=0
- losangelex `II-19_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=193.4 total_tokens=1,494,318 uncached_plus_output_tokens=275,630 coordination_errors=0
- codex `II-20_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=160.9 total_tokens=508,226 uncached_plus_output_tokens=69,698 coordination_errors=0
- codex-subagents `II-20_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=165.3 total_tokens=855,663 uncached_plus_output_tokens=132,079 coordination_errors=0
- codex-full-context `II-20_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=27.7 total_tokens=101,828 uncached_plus_output_tokens=13,380 coordination_errors=0
- losangelex `II-20_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=193.3 total_tokens=1,932,731 uncached_plus_output_tokens=355,899 coordination_errors=0
- codex `III-21_n5.json`: success=False S=0.200 P=0.200 S_tol=0.200 P_tol=0.200 seconds=1912.3 total_tokens=1,872,626 uncached_plus_output_tokens=538,482 coordination_errors=0
- codex-subagents `III-21_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=271.0 total_tokens=1,099,006 uncached_plus_output_tokens=166,526 coordination_errors=0
- codex-full-context `III-21_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=58.3 total_tokens=102,892 uncached_plus_output_tokens=42,092 coordination_errors=0
- losangelex `III-21_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=193.6 total_tokens=1,568,839 uncached_plus_output_tokens=350,535 coordination_errors=0
- codex `III-22_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=1605.9 total_tokens=1,353,567 uncached_plus_output_tokens=364,255 coordination_errors=0
- codex-subagents `III-22_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=313.9 total_tokens=1,601,950 uncached_plus_output_tokens=252,446 coordination_errors=0
- codex-full-context `III-22_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=23.9 total_tokens=61,137 uncached_plus_output_tokens=12,881 coordination_errors=0
- losangelex `III-22_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=238.7 total_tokens=2,328,515 uncached_plus_output_tokens=297,539 coordination_errors=0
- codex `III-23_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=1053.2 total_tokens=1,180,894 uncached_plus_output_tokens=213,214 coordination_errors=0
- codex-subagents `III-23_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=374.6 total_tokens=1,130,142 uncached_plus_output_tokens=75,934 coordination_errors=0
- codex-full-context `III-23_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=65.6 total_tokens=105,809 uncached_plus_output_tokens=21,969 coordination_errors=0
- losangelex `III-23_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=193.6 total_tokens=1,524,266 uncached_plus_output_tokens=251,946 coordination_errors=0
- codex `III-24_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=1278.2 total_tokens=1,245,965 uncached_plus_output_tokens=220,301 coordination_errors=0
- codex-subagents `III-24_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=372.2 total_tokens=910,997 uncached_plus_output_tokens=122,901 coordination_errors=0
- codex-full-context `III-24_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=70.0 total_tokens=105,830 uncached_plus_output_tokens=21,990 coordination_errors=0
- losangelex `III-24_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=284.0 total_tokens=1,796,229 uncached_plus_output_tokens=258,053 coordination_errors=0
- codex `III-25_n5.json`: success=False S=0.000 P=0.000 S_tol=1.000 P_tol=1.000 seconds=1015.2 total_tokens=1,205,560 uncached_plus_output_tokens=430,136 coordination_errors=0
- codex-subagents `III-25_n5.json`: success=False S=0.000 P=0.000 S_tol=1.000 P_tol=1.000 seconds=217.0 total_tokens=1,186,476 uncached_plus_output_tokens=233,516 coordination_errors=0
- codex-full-context `III-25_n5.json`: success=False S=0.000 P=0.000 S_tol=1.000 P_tol=1.000 seconds=63.8 total_tokens=120,594 uncached_plus_output_tokens=48,530 coordination_errors=0
- losangelex `III-25_n5.json`: success=False S=0.000 P=0.000 S_tol=1.000 P_tol=1.000 seconds=148.5 total_tokens=1,845,023 uncached_plus_output_tokens=277,407 coordination_errors=0
- codex `III-26_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=813.2 total_tokens=1,120,282 uncached_plus_output_tokens=361,370 coordination_errors=0
- codex-subagents `III-26_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=157.4 total_tokens=884,256 uncached_plus_output_tokens=240,416 coordination_errors=0
- codex-full-context `III-26_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=32.2 total_tokens=82,758 uncached_plus_output_tokens=38,214 coordination_errors=0
- losangelex `III-26_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=148.4 total_tokens=1,657,884 uncached_plus_output_tokens=388,636 coordination_errors=0
- codex `III-27_n5.json`: success=False S=0.000 P=0.000 S_tol=1.000 P_tol=1.000 seconds=1306.9 total_tokens=1,731,561 uncached_plus_output_tokens=384,361 coordination_errors=0
- codex-subagents `III-27_n5.json`: success=False S=0.000 P=0.000 S_tol=1.000 P_tol=1.000 seconds=245.3 total_tokens=1,337,862 uncached_plus_output_tokens=194,822 coordination_errors=0
- codex-full-context `III-27_n5.json`: success=False S=0.000 P=0.000 S_tol=1.000 P_tol=1.000 seconds=49.5 total_tokens=69,585 uncached_plus_output_tokens=16,721 coordination_errors=0
- losangelex `III-27_n5.json`: success=False S=0.000 P=0.000 S_tol=1.000 P_tol=1.000 seconds=239.1 total_tokens=2,248,532 uncached_plus_output_tokens=409,812 coordination_errors=0
- codex `III-28_n5.json`: success=False S=0.000 P=0.000 S_tol=1.000 P_tol=1.000 seconds=798.6 total_tokens=1,521,556 uncached_plus_output_tokens=378,516 coordination_errors=0
- codex-subagents `III-28_n5.json`: success=False S=0.000 P=0.000 S_tol=1.000 P_tol=1.000 seconds=228.6 total_tokens=1,110,046 uncached_plus_output_tokens=169,502 coordination_errors=0
- codex-full-context `III-28_n5.json`: success=False S=0.000 P=0.000 S_tol=1.000 P_tol=1.000 seconds=74.6 total_tokens=110,713 uncached_plus_output_tokens=30,457 coordination_errors=0
- losangelex `III-28_n5.json`: success=False S=0.000 P=0.000 S_tol=1.000 P_tol=1.000 seconds=193.7 total_tokens=1,377,892 uncached_plus_output_tokens=272,228 coordination_errors=0
- codex `III-29_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=863.4 total_tokens=1,237,802 uncached_plus_output_tokens=299,818 coordination_errors=0
- codex-subagents `III-29_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=234.3 total_tokens=1,160,889 uncached_plus_output_tokens=252,857 coordination_errors=0
- codex-full-context `III-29_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=50.4 total_tokens=94,647 uncached_plus_output_tokens=17,847 coordination_errors=0
- losangelex `III-29_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=148.4 total_tokens=1,563,163 uncached_plus_output_tokens=248,219 coordination_errors=0
- codex `III-30_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=585.9 total_tokens=1,042,298 uncached_plus_output_tokens=250,746 coordination_errors=0
- codex-subagents `III-30_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=160.2 total_tokens=867,281 uncached_plus_output_tokens=141,521 coordination_errors=0
- codex-full-context `III-30_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=27.0 total_tokens=82,244 uncached_plus_output_tokens=19,780 coordination_errors=0
- losangelex `III-30_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=103.6 total_tokens=1,136,460 uncached_plus_output_tokens=218,828 coordination_errors=0
