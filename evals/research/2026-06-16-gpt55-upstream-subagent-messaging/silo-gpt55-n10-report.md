# Published SILO-BENCH Agent Comparison: silo-gpt55-full-n10-all-systems-2026-06-16

This run evaluates the same published SILO-BENCH task files with Codex
agent cohorts and Losangelex Hollywood rooms. Each agent received only its
private benchmark shard prompt; the expected answers were used only after
execution for deterministic scoring.

## Summary

| System | Tasks | Full successes | Avg S | Avg P | Avg S_tol | Avg P_tol | Avg seconds | Avg total tokens | Avg uncached+output | Total tokens/success | Coordination errors |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| codex | 30 | 21 (70.00%) | 0.727 | 0.746 | 0.860 | 0.866 | 1670.0 | 2,555,300 | 601,064 | 3,650,429 | 0 |
| codex-full-context | 30 | 25 (83.33%) | 0.833 | 0.847 | 0.967 | 0.967 | 62.8 | 106,320 | 33,560 | 127,584 | 0 |
| codex-subagents | 30 | 23 (76.67%) | 0.767 | 0.780 | 0.800 | 0.800 | 289.4 | 1,698,260 | 246,053 | 2,215,122 | 0 |
| losangelex | 30 | 23 (76.67%) | 0.793 | 0.813 | 0.927 | 0.933 | 177.6 | 3,737,636 | 650,741 | 4,875,177 | 0 |

## By Level

| Level | System | Tasks | Full successes | Avg S | Avg P | Avg S_tol | Avg P_tol | Avg seconds | Avg total tokens | Avg uncached+output | Total tokens/success | Coordination errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| I | codex | 10 | 10 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 1544.2 | 2,323,580 | 432,662 | 2,323,580 | 0 |
| I | codex-full-context | 10 | 10 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 51.2 | 102,656 | 24,793 | 102,656 | 0 |
| I | codex-subagents | 10 | 9 (90.00%) | 0.900 | 0.900 | 0.900 | 0.900 | 233.6 | 1,608,458 | 183,050 | 1,787,175 | 0 |
| I | losangelex | 10 | 10 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 142.8 | 2,891,380 | 449,524 | 2,891,380 | 0 |
| II | codex | 10 | 6 (60.00%) | 0.670 | 0.729 | 0.770 | 0.788 | 1384.0 | 2,302,373 | 476,069 | 3,837,289 | 0 |
| II | codex-full-context | 10 | 9 (90.00%) | 0.900 | 0.941 | 1.000 | 1.000 | 53.1 | 98,069 | 29,858 | 108,966 | 0 |
| II | codex-subagents | 10 | 9 (90.00%) | 0.900 | 0.941 | 1.000 | 1.000 | 281.1 | 1,863,942 | 251,987 | 2,071,047 | 0 |
| II | losangelex | 10 | 7 (70.00%) | 0.780 | 0.839 | 0.880 | 0.898 | 165.7 | 3,759,638 | 567,791 | 5,370,911 | 0 |
| III | codex | 10 | 5 (50.00%) | 0.510 | 0.510 | 0.810 | 0.810 | 2082.0 | 3,039,947 | 894,462 | 6,079,893 | 0 |
| III | codex-full-context | 10 | 6 (60.00%) | 0.600 | 0.600 | 0.900 | 0.900 | 84.0 | 118,234 | 46,029 | 197,057 | 0 |
| III | codex-subagents | 10 | 5 (50.00%) | 0.500 | 0.500 | 0.500 | 0.500 | 353.6 | 1,622,380 | 303,122 | 3,244,759 | 0 |
| III | losangelex | 10 | 6 (60.00%) | 0.600 | 0.600 | 0.900 | 0.900 | 224.2 | 4,561,889 | 934,906 | 7,603,148 | 0 |

## Tasks

- codex `I-01_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=1825.0 total_tokens=2,433,407 uncached_plus_output_tokens=442,623 coordination_errors=0
- codex-subagents `I-01_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=214.5 total_tokens=1,269,538 uncached_plus_output_tokens=181,282 coordination_errors=0
- codex-full-context `I-01_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=20.5 total_tokens=61,963 uncached_plus_output_tokens=36,747 coordination_errors=0
- losangelex `I-01_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=111.8 total_tokens=2,481,382 uncached_plus_output_tokens=412,518 coordination_errors=0
- codex `I-02_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=1760.4 total_tokens=2,296,105 uncached_plus_output_tokens=479,657 coordination_errors=0
- codex-subagents `I-02_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=226.7 total_tokens=1,601,164 uncached_plus_output_tokens=169,996 coordination_errors=0
- codex-full-context `I-02_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=47.6 total_tokens=111,603 uncached_plus_output_tokens=41,587 coordination_errors=0
- losangelex `I-02_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=110.9 total_tokens=2,577,462 uncached_plus_output_tokens=451,382 coordination_errors=0
- codex `I-03_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=691.8 total_tokens=1,140,733 uncached_plus_output_tokens=187,005 coordination_errors=0
- codex-subagents `I-03_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=204.3 total_tokens=1,720,472 uncached_plus_output_tokens=187,672 coordination_errors=0
- codex-full-context `I-03_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=63.1 total_tokens=136,834 uncached_plus_output_tokens=24,962 coordination_errors=0
- losangelex `I-03_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=156.5 total_tokens=3,122,922 uncached_plus_output_tokens=539,882 coordination_errors=0
- codex `I-04_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=1179.3 total_tokens=1,672,257 uncached_plus_output_tokens=369,089 coordination_errors=0
- codex-subagents `I-04_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=188.5 total_tokens=1,304,332 uncached_plus_output_tokens=135,308 coordination_errors=0
- codex-full-context `I-04_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=17.9 total_tokens=63,692 uncached_plus_output_tokens=13,388 coordination_errors=0
- losangelex `I-04_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=110.7 total_tokens=1,991,820 uncached_plus_output_tokens=330,252 coordination_errors=0
- codex `I-05_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=1115.3 total_tokens=2,132,519 uncached_plus_output_tokens=434,087 coordination_errors=0
- codex-subagents `I-05_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=238.8 total_tokens=1,654,685 uncached_plus_output_tokens=187,933 coordination_errors=0
- codex-full-context `I-05_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=44.8 total_tokens=111,764 uncached_plus_output_tokens=16,148 coordination_errors=0
- losangelex `I-05_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=156.6 total_tokens=2,574,316 uncached_plus_output_tokens=440,172 coordination_errors=0
- codex `I-06_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=1136.1 total_tokens=1,763,106 uncached_plus_output_tokens=365,730 coordination_errors=0
- codex-subagents `I-06_n10.json`: success=False S=0.000 P=0.000 S_tol=0.000 P_tol=0.000 seconds=203.2 total_tokens=1,566,712 uncached_plus_output_tokens=144,120 coordination_errors=0
- codex-full-context `I-06_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=24.4 total_tokens=64,984 uncached_plus_output_tokens=14,168 coordination_errors=0
- losangelex `I-06_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=155.9 total_tokens=2,548,385 uncached_plus_output_tokens=446,753 coordination_errors=0
- codex `I-07_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=1707.6 total_tokens=2,421,865 uncached_plus_output_tokens=389,481 coordination_errors=0
- codex-subagents `I-07_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=240.7 total_tokens=1,601,706 uncached_plus_output_tokens=167,722 coordination_errors=0
- codex-full-context `I-07_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=68.0 total_tokens=149,517 uncached_plus_output_tokens=20,749 coordination_errors=0
- losangelex `I-07_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=110.9 total_tokens=3,158,270 uncached_plus_output_tokens=500,734 coordination_errors=0
- codex `I-08_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=1956.4 total_tokens=3,352,242 uncached_plus_output_tokens=652,466 coordination_errors=0
- codex-subagents `I-08_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=260.7 total_tokens=1,925,999 uncached_plus_output_tokens=248,175 coordination_errors=0
- codex-full-context `I-08_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=37.9 total_tokens=112,511 uncached_plus_output_tokens=29,183 coordination_errors=0
- losangelex `I-08_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=201.7 total_tokens=3,340,073 uncached_plus_output_tokens=451,369 coordination_errors=0
- codex `I-09_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=2114.6 total_tokens=2,472,424 uncached_plus_output_tokens=433,512 coordination_errors=0
- codex-subagents `I-09_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=244.8 total_tokens=1,287,063 uncached_plus_output_tokens=169,367 coordination_errors=0
- codex-full-context `I-09_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=52.1 total_tokens=134,355 uncached_plus_output_tokens=43,475 coordination_errors=0
- losangelex `I-09_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=156.3 total_tokens=2,389,103 uncached_plus_output_tokens=414,959 coordination_errors=0
- codex `I-10_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=1955.1 total_tokens=3,551,141 uncached_plus_output_tokens=572,965 coordination_errors=0
- codex-subagents `I-10_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=313.8 total_tokens=2,152,908 uncached_plus_output_tokens=238,924 coordination_errors=0
- codex-full-context `I-10_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=135.3 total_tokens=79,334 uncached_plus_output_tokens=7,526 coordination_errors=0
- losangelex `I-10_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=156.6 total_tokens=4,730,068 uncached_plus_output_tokens=507,220 coordination_errors=0
- codex `II-11_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=324.2 total_tokens=708,829 uncached_plus_output_tokens=123,357 coordination_errors=0
- codex-subagents `II-11_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=267.8 total_tokens=1,239,166 uncached_plus_output_tokens=186,494 coordination_errors=0
- codex-full-context `II-11_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=38.5 total_tokens=89,910 uncached_plus_output_tokens=29,494 coordination_errors=0
- losangelex `II-11_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=156.8 total_tokens=3,508,867 uncached_plus_output_tokens=563,587 coordination_errors=0
- codex `II-12_n10.json`: success=False S=0.000 P=0.412 S_tol=1.000 P_tol=1.000 seconds=1526.1 total_tokens=2,707,085 uncached_plus_output_tokens=490,893 coordination_errors=0
- codex-subagents `II-12_n10.json`: success=False S=0.000 P=0.412 S_tol=1.000 P_tol=1.000 seconds=255.6 total_tokens=1,928,302 uncached_plus_output_tokens=231,150 coordination_errors=0
- codex-full-context `II-12_n10.json`: success=False S=0.000 P=0.412 S_tol=1.000 P_tol=1.000 seconds=208.9 total_tokens=142,385 uncached_plus_output_tokens=36,017 coordination_errors=0
- losangelex `II-12_n10.json`: success=False S=0.000 P=0.412 S_tol=1.000 P_tol=1.000 seconds=156.2 total_tokens=3,221,633 uncached_plus_output_tokens=483,073 coordination_errors=0
- codex `II-13_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=1813.8 total_tokens=3,028,278 uncached_plus_output_tokens=539,702 coordination_errors=0
- codex-subagents `II-13_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=290.1 total_tokens=2,291,876 uncached_plus_output_tokens=253,348 coordination_errors=0
- codex-full-context `II-13_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=30.3 total_tokens=85,260 uncached_plus_output_tokens=20,748 coordination_errors=0
- losangelex `II-13_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=156.6 total_tokens=3,039,092 uncached_plus_output_tokens=465,396 coordination_errors=0
- codex `II-14_n10.json`: success=False S=0.700 P=0.880 S_tol=0.700 P_tol=0.880 seconds=2593.2 total_tokens=3,406,592 uncached_plus_output_tokens=435,456 coordination_errors=0
- codex-subagents `II-14_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=309.6 total_tokens=2,060,141 uncached_plus_output_tokens=219,629 coordination_errors=0
- codex-full-context `II-14_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=46.3 total_tokens=140,654 uncached_plus_output_tokens=36,974 coordination_errors=0
- losangelex `II-14_n10.json`: success=False S=0.800 P=0.980 S_tol=0.800 P_tol=0.980 seconds=156.4 total_tokens=4,075,705 uncached_plus_output_tokens=492,729 coordination_errors=0
- codex `II-15_n10.json`: success=False S=0.000 P=0.000 S_tol=0.000 P_tol=0.000 seconds=866.3 total_tokens=1,914,009 uncached_plus_output_tokens=342,937 coordination_errors=0
- codex-subagents `II-15_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=225.1 total_tokens=1,624,272 uncached_plus_output_tokens=159,184 coordination_errors=0
- codex-full-context `II-15_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=32.2 total_tokens=86,812 uncached_plus_output_tokens=40,732 coordination_errors=0
- losangelex `II-15_n10.json`: success=False S=0.000 P=0.000 S_tol=0.000 P_tol=0.000 seconds=202.1 total_tokens=4,358,507 uncached_plus_output_tokens=503,531 coordination_errors=0
- codex `II-16_n10.json`: success=False S=0.000 P=0.000 S_tol=0.000 P_tol=0.000 seconds=1779.0 total_tokens=2,776,937 uncached_plus_output_tokens=522,985 coordination_errors=0
- codex-subagents `II-16_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=296.4 total_tokens=1,730,437 uncached_plus_output_tokens=292,613 coordination_errors=0
- codex-full-context `II-16_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=30.8 total_tokens=85,286 uncached_plus_output_tokens=20,774 coordination_errors=0
- losangelex `II-16_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=157.9 total_tokens=4,062,855 uncached_plus_output_tokens=555,783 coordination_errors=0
- codex `II-17_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=1091.6 total_tokens=2,486,328 uncached_plus_output_tokens=734,648 coordination_errors=0
- codex-subagents `II-17_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=328.8 total_tokens=1,986,818 uncached_plus_output_tokens=288,514 coordination_errors=0
- codex-full-context `II-17_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=39.7 total_tokens=88,870 uncached_plus_output_tokens=42,278 coordination_errors=0
- losangelex `II-17_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=156.2 total_tokens=3,514,428 uncached_plus_output_tokens=579,772 coordination_errors=0
- codex `II-18_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=1985.9 total_tokens=2,876,409 uncached_plus_output_tokens=719,737 coordination_errors=0
- codex-subagents `II-18_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=334.6 total_tokens=2,433,549 uncached_plus_output_tokens=257,293 coordination_errors=0
- codex-full-context `II-18_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=19.7 total_tokens=44,679 uncached_plus_output_tokens=21,383 coordination_errors=0
- losangelex `II-18_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=156.5 total_tokens=3,802,841 uncached_plus_output_tokens=725,337 coordination_errors=0
- codex `II-19_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=1556.9 total_tokens=2,282,255 uncached_plus_output_tokens=666,767 coordination_errors=0
- codex-subagents `II-19_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=275.6 total_tokens=1,569,217 uncached_plus_output_tokens=258,881 coordination_errors=0
- codex-full-context `II-19_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=55.8 total_tokens=109,245 uncached_plus_output_tokens=16,189 coordination_errors=0
- losangelex `II-19_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=155.9 total_tokens=3,062,041 uncached_plus_output_tokens=552,857 coordination_errors=0
- codex `II-20_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=302.5 total_tokens=837,011 uncached_plus_output_tokens=184,211 coordination_errors=0
- codex-subagents `II-20_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=227.7 total_tokens=1,775,646 uncached_plus_output_tokens=372,766 coordination_errors=0
- codex-full-context `II-20_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=28.8 total_tokens=107,589 uncached_plus_output_tokens=33,989 coordination_errors=0
- losangelex `II-20_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=201.9 total_tokens=4,950,408 uncached_plus_output_tokens=755,848 coordination_errors=0
- codex `III-21_n10.json`: success=False S=0.100 P=0.100 S_tol=0.100 P_tol=0.100 seconds=2286.8 total_tokens=4,052,324 uncached_plus_output_tokens=1,179,236 coordination_errors=0
- codex-subagents `III-21_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=338.5 total_tokens=1,880,671 uncached_plus_output_tokens=330,719 coordination_errors=0
- codex-full-context `III-21_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=41.9 total_tokens=112,045 uncached_plus_output_tokens=42,541 coordination_errors=0
- losangelex `III-21_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=156.1 total_tokens=2,946,393 uncached_plus_output_tokens=540,377 coordination_errors=0
- codex `III-22_n10.json`: success=False S=0.000 P=0.000 S_tol=0.000 P_tol=0.000 seconds=1898.3 total_tokens=3,681,002 uncached_plus_output_tokens=1,003,242 coordination_errors=0
- codex-subagents `III-22_n10.json`: success=False S=0.000 P=0.000 S_tol=0.000 P_tol=0.000 seconds=370.0 total_tokens=2,562,035 uncached_plus_output_tokens=337,651 coordination_errors=0
- codex-full-context `III-22_n10.json`: success=False S=0.000 P=0.000 S_tol=0.000 P_tol=0.000 seconds=42.7 total_tokens=112,262 uncached_plus_output_tokens=28,934 coordination_errors=0
- losangelex `III-22_n10.json`: success=False S=0.000 P=0.000 S_tol=0.000 P_tol=0.000 seconds=292.7 total_tokens=10,361,771 uncached_plus_output_tokens=1,182,891 coordination_errors=0
- codex `III-23_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=1815.0 total_tokens=2,860,599 uncached_plus_output_tokens=712,503 coordination_errors=0
- codex-subagents `III-23_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=916.0 total_tokens=2,867,010 uncached_plus_output_tokens=388,290 coordination_errors=0
- codex-full-context `III-23_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=39.1 total_tokens=69,576 uncached_plus_output_tokens=41,800 coordination_errors=0
- losangelex `III-23_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=156.5 total_tokens=3,236,640 uncached_plus_output_tokens=597,024 coordination_errors=0
- codex `III-24_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=1622.6 total_tokens=2,785,617 uncached_plus_output_tokens=716,881 coordination_errors=0
- codex-subagents `III-24_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=330.0 total_tokens=1,771,235 uncached_plus_output_tokens=292,963 coordination_errors=0
- codex-full-context `III-24_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=109.9 total_tokens=127,206 uncached_plus_output_tokens=65,382 coordination_errors=0
- losangelex `III-24_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=156.3 total_tokens=3,403,750 uncached_plus_output_tokens=738,278 coordination_errors=0
- codex `III-25_n10.json`: success=False S=0.000 P=0.000 S_tol=1.000 P_tol=1.000 seconds=2193.6 total_tokens=3,415,193 uncached_plus_output_tokens=860,825 coordination_errors=0
- codex-subagents `III-25_n10.json`: success=False S=0.000 P=0.000 S_tol=0.000 P_tol=0.000 seconds=279.6 total_tokens=1,130,103 uncached_plus_output_tokens=224,759 coordination_errors=0
- codex-full-context `III-25_n10.json`: success=False S=0.000 P=0.000 S_tol=1.000 P_tol=1.000 seconds=110.6 total_tokens=146,573 uncached_plus_output_tokens=45,837 coordination_errors=0
- losangelex `III-25_n10.json`: success=False S=0.000 P=0.000 S_tol=1.000 P_tol=1.000 seconds=246.9 total_tokens=4,804,672 uncached_plus_output_tokens=1,079,360 coordination_errors=0
- codex `III-26_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=2493.7 total_tokens=3,062,077 uncached_plus_output_tokens=797,245 coordination_errors=0
- codex-subagents `III-26_n10.json`: success=False S=0.000 P=0.000 S_tol=0.000 P_tol=0.000 seconds=62.7 total_tokens=126,811 uncached_plus_output_tokens=37,339 coordination_errors=0
- codex-full-context `III-26_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=119.8 total_tokens=114,146 uncached_plus_output_tokens=16,482 coordination_errors=0
- losangelex `III-26_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=291.8 total_tokens=4,064,162 uncached_plus_output_tokens=699,810 coordination_errors=0
- codex `III-27_n10.json`: success=False S=0.000 P=0.000 S_tol=1.000 P_tol=1.000 seconds=3199.8 total_tokens=3,423,791 uncached_plus_output_tokens=1,105,455 coordination_errors=0
- codex-subagents `III-27_n10.json`: success=False S=0.000 P=0.000 S_tol=0.000 P_tol=0.000 seconds=62.4 total_tokens=137,421 uncached_plus_output_tokens=68,941 coordination_errors=0
- codex-full-context `III-27_n10.json`: success=False S=0.000 P=0.000 S_tol=1.000 P_tol=1.000 seconds=116.0 total_tokens=139,630 uncached_plus_output_tokens=55,790 coordination_errors=0
- losangelex `III-27_n10.json`: success=False S=0.000 P=0.000 S_tol=1.000 P_tol=1.000 seconds=291.9 total_tokens=5,413,823 uncached_plus_output_tokens=1,356,991 coordination_errors=0
- codex `III-28_n10.json`: success=False S=0.000 P=0.000 S_tol=1.000 P_tol=1.000 seconds=2040.3 total_tokens=3,140,115 uncached_plus_output_tokens=1,127,059 coordination_errors=0
- codex-subagents `III-28_n10.json`: success=False S=0.000 P=0.000 S_tol=0.000 P_tol=0.000 seconds=91.3 total_tokens=177,953 uncached_plus_output_tokens=107,681 coordination_errors=0
- codex-full-context `III-28_n10.json`: success=False S=0.000 P=0.000 S_tol=1.000 P_tol=1.000 seconds=64.9 total_tokens=96,662 uncached_plus_output_tokens=44,438 coordination_errors=0
- losangelex `III-28_n10.json`: success=False S=0.000 P=0.000 S_tol=1.000 P_tol=1.000 seconds=201.5 total_tokens=3,849,716 uncached_plus_output_tokens=1,088,884 coordination_errors=0
- codex `III-29_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=1398.5 total_tokens=1,808,825 uncached_plus_output_tokens=568,377 coordination_errors=0
- codex-subagents `III-29_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=699.2 total_tokens=3,757,442 uncached_plus_output_tokens=853,122 coordination_errors=0
- codex-full-context `III-29_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=117.4 total_tokens=156,582 uncached_plus_output_tokens=77,990 coordination_errors=0
- losangelex `III-29_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=247.1 total_tokens=3,752,080 uncached_plus_output_tokens=1,205,904 coordination_errors=0
- codex `III-30_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=1871.2 total_tokens=2,169,924 uncached_plus_output_tokens=873,796 coordination_errors=0
- codex-subagents `III-30_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=386.4 total_tokens=1,813,114 uncached_plus_output_tokens=389,754 coordination_errors=0
- codex-full-context `III-30_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=77.6 total_tokens=107,660 uncached_plus_output_tokens=41,100 coordination_errors=0
- losangelex `III-30_n10.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=201.6 total_tokens=3,785,880 uncached_plus_output_tokens=859,544 coordination_errors=0
