# Published SILO-BENCH Agent Comparison: silo-current-losangelex-selector-n5-full-2026-06-14

This run evaluates the same published SILO-BENCH task files with Codex
agent cohorts and Losangelex Hollywood rooms. Each agent received only its
private benchmark shard prompt; the expected answers were used only after
execution for deterministic scoring.

## Summary

| System | Tasks | Full successes | Avg S | Avg P | Avg S_tol | Avg P_tol | Avg seconds | Avg total tokens | Avg uncached+output | Total tokens/success | Coordination errors |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| losangelex | 30 | 23 (76.67%) | 0.820 | 0.834 | 0.920 | 0.954 | 140.4 | 1,487,623 | 196,756 | 1,940,378 | 0 |
| losangelex-selector | 30 | 22 (73.33%) | 0.813 | 0.827 | 0.900 | 0.932 | 153.4 | 1,365,936 | 191,835 | 1,862,640 | 0 |

## By Level

| Level | System | Tasks | Full successes | Avg S | Avg P | Avg S_tol | Avg P_tol | Avg seconds | Avg total tokens | Avg uncached+output | Total tokens/success | Coordination errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| I | losangelex | 10 | 10 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 110.3 | 1,278,262 | 155,690 | 1,278,262 | 0 |
| I | losangelex-selector | 10 | 10 (100.00%) | 1.000 | 1.000 | 1.000 | 1.000 | 141.9 | 1,136,071 | 141,575 | 1,136,071 | 0 |
| II | losangelex | 10 | 7 (70.00%) | 0.780 | 0.821 | 0.780 | 0.883 | 160.0 | 1,573,870 | 200,263 | 2,248,385 | 0 |
| II | losangelex-selector | 10 | 6 (60.00%) | 0.760 | 0.801 | 0.820 | 0.861 | 167.4 | 1,435,281 | 217,553 | 2,392,135 | 0 |
| III | losangelex | 10 | 6 (60.00%) | 0.680 | 0.680 | 0.980 | 0.980 | 150.9 | 1,610,738 | 234,315 | 2,684,563 | 0 |
| III | losangelex-selector | 10 | 6 (60.00%) | 0.680 | 0.680 | 0.880 | 0.936 | 151.0 | 1,526,457 | 216,377 | 2,544,095 | 0 |

## Tasks

- losangelex `I-01_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=101.6 total_tokens=983,445 uncached_plus_output_tokens=111,381 coordination_errors=0
- losangelex-selector `I-01_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=101.1 total_tokens=762,994 uncached_plus_output_tokens=123,250 coordination_errors=0
- losangelex `I-02_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=101.2 total_tokens=1,044,737 uncached_plus_output_tokens=177,025 coordination_errors=0
- losangelex-selector `I-02_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=101.2 total_tokens=866,313 uncached_plus_output_tokens=116,617 coordination_errors=0
- losangelex `I-03_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=101.2 total_tokens=1,132,164 uncached_plus_output_tokens=172,804 coordination_errors=0
- losangelex-selector `I-03_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=101.1 total_tokens=853,293 uncached_plus_output_tokens=128,045 coordination_errors=0
- losangelex `I-04_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=101.2 total_tokens=1,061,483 uncached_plus_output_tokens=150,891 coordination_errors=0
- losangelex-selector `I-04_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=146.8 total_tokens=1,134,629 uncached_plus_output_tokens=161,445 coordination_errors=0
- losangelex `I-05_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=101.1 total_tokens=1,393,560 uncached_plus_output_tokens=145,944 coordination_errors=0
- losangelex-selector `I-05_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=101.3 total_tokens=835,607 uncached_plus_output_tokens=137,879 coordination_errors=0
- losangelex `I-06_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=101.3 total_tokens=1,055,301 uncached_plus_output_tokens=121,029 coordination_errors=0
- losangelex-selector `I-06_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=101.4 total_tokens=872,608 uncached_plus_output_tokens=113,184 coordination_errors=0
- losangelex `I-07_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=101.5 total_tokens=1,138,121 uncached_plus_output_tokens=147,401 coordination_errors=0
- losangelex-selector `I-07_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=146.7 total_tokens=1,123,038 uncached_plus_output_tokens=141,022 coordination_errors=0
- losangelex `I-08_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=146.6 total_tokens=1,355,942 uncached_plus_output_tokens=162,982 coordination_errors=0
- losangelex-selector `I-08_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=101.4 total_tokens=923,344 uncached_plus_output_tokens=92,496 coordination_errors=0
- losangelex `I-09_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=101.2 total_tokens=1,109,549 uncached_plus_output_tokens=164,781 coordination_errors=0
- losangelex-selector `I-09_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=101.3 total_tokens=833,658 uncached_plus_output_tokens=90,362 coordination_errors=0
- losangelex `I-10_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=146.4 total_tokens=2,508,323 uncached_plus_output_tokens=202,659 coordination_errors=0
- losangelex-selector `I-10_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=416.9 total_tokens=3,155,226 uncached_plus_output_tokens=311,450 coordination_errors=0
- losangelex `II-11_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=146.3 total_tokens=1,124,732 uncached_plus_output_tokens=140,924 coordination_errors=0
- losangelex-selector `II-11_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=101.3 total_tokens=1,048,014 uncached_plus_output_tokens=179,150 coordination_errors=0
- losangelex `II-12_n5.json`: success=False S=0.000 P=0.370 S_tol=0.000 P_tol=0.986 seconds=191.6 total_tokens=1,805,804 uncached_plus_output_tokens=265,836 coordination_errors=0
- losangelex-selector `II-12_n5.json`: success=False S=0.000 P=0.367 S_tol=0.600 P_tol=0.973 seconds=236.6 total_tokens=1,899,507 uncached_plus_output_tokens=245,875 coordination_errors=0
- losangelex `II-13_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=146.7 total_tokens=1,414,162 uncached_plus_output_tokens=204,050 coordination_errors=0
- losangelex-selector `II-13_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=146.6 total_tokens=1,525,957 uncached_plus_output_tokens=257,093 coordination_errors=0
- losangelex `II-14_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=236.5 total_tokens=2,504,672 uncached_plus_output_tokens=191,968 coordination_errors=0
- losangelex-selector `II-14_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=146.4 total_tokens=1,352,925 uncached_plus_output_tokens=215,645 coordination_errors=0
- losangelex `II-15_n5.json`: success=False S=0.000 P=0.000 S_tol=0.000 P_tol=0.000 seconds=146.5 total_tokens=1,698,675 uncached_plus_output_tokens=174,323 coordination_errors=0
- losangelex-selector `II-15_n5.json`: success=False S=0.000 P=0.000 S_tol=0.000 P_tol=0.000 seconds=146.5 total_tokens=1,345,420 uncached_plus_output_tokens=225,932 coordination_errors=0
- losangelex `II-16_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=146.3 total_tokens=1,752,647 uncached_plus_output_tokens=253,511 coordination_errors=0
- losangelex-selector `II-16_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=146.5 total_tokens=1,362,465 uncached_plus_output_tokens=180,001 coordination_errors=0
- losangelex `II-17_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=101.3 total_tokens=1,137,442 uncached_plus_output_tokens=180,386 coordination_errors=0
- losangelex-selector `II-17_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=101.4 total_tokens=1,050,294 uncached_plus_output_tokens=215,734 coordination_errors=0
- losangelex `II-18_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=146.6 total_tokens=1,272,619 uncached_plus_output_tokens=180,523 coordination_errors=0
- losangelex-selector `II-18_n5.json`: success=False S=0.800 P=0.800 S_tol=0.800 P_tol=0.800 seconds=311.3 total_tokens=1,276,579 uncached_plus_output_tokens=174,755 coordination_errors=0
- losangelex `II-19_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=101.3 total_tokens=1,118,185 uncached_plus_output_tokens=161,641 coordination_errors=0
- losangelex-selector `II-19_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=146.4 total_tokens=1,369,963 uncached_plus_output_tokens=196,971 coordination_errors=0
- losangelex `II-20_n5.json`: success=False S=0.800 P=0.840 S_tol=0.800 P_tol=0.840 seconds=236.5 total_tokens=1,909,757 uncached_plus_output_tokens=249,469 coordination_errors=0
- losangelex-selector `II-20_n5.json`: success=False S=0.800 P=0.840 S_tol=0.800 P_tol=0.840 seconds=191.3 total_tokens=2,121,686 uncached_plus_output_tokens=284,374 coordination_errors=0
- losangelex `III-21_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=146.4 total_tokens=1,366,054 uncached_plus_output_tokens=170,918 coordination_errors=0
- losangelex-selector `III-21_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=146.5 total_tokens=1,272,333 uncached_plus_output_tokens=216,589 coordination_errors=0
- losangelex `III-22_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=146.3 total_tokens=1,626,390 uncached_plus_output_tokens=299,030 coordination_errors=0
- losangelex-selector `III-22_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=146.3 total_tokens=1,758,558 uncached_plus_output_tokens=258,782 coordination_errors=0
- losangelex `III-23_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=146.4 total_tokens=1,563,577 uncached_plus_output_tokens=236,601 coordination_errors=0
- losangelex-selector `III-23_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=146.5 total_tokens=1,625,111 uncached_plus_output_tokens=267,415 coordination_errors=0
- losangelex `III-24_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=146.4 total_tokens=1,491,776 uncached_plus_output_tokens=269,760 coordination_errors=0
- losangelex-selector `III-24_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=191.5 total_tokens=1,329,070 uncached_plus_output_tokens=241,070 coordination_errors=0
- losangelex `III-25_n5.json`: success=False S=0.000 P=0.000 S_tol=1.000 P_tol=1.000 seconds=146.3 total_tokens=2,123,027 uncached_plus_output_tokens=226,835 coordination_errors=0
- losangelex-selector `III-25_n5.json`: success=False S=0.000 P=0.000 S_tol=1.000 P_tol=1.000 seconds=146.5 total_tokens=1,559,293 uncached_plus_output_tokens=167,677 coordination_errors=0
- losangelex `III-26_n5.json`: success=False S=0.800 P=0.800 S_tol=0.800 P_tol=0.800 seconds=146.4 total_tokens=1,294,216 uncached_plus_output_tokens=216,456 coordination_errors=0
- losangelex-selector `III-26_n5.json`: success=False S=0.800 P=0.800 S_tol=0.800 P_tol=0.800 seconds=101.3 total_tokens=1,117,056 uncached_plus_output_tokens=180,736 coordination_errors=0
- losangelex `III-27_n5.json`: success=False S=0.000 P=0.000 S_tol=1.000 P_tol=1.000 seconds=236.5 total_tokens=2,839,794 uncached_plus_output_tokens=305,906 coordination_errors=0
- losangelex-selector `III-27_n5.json`: success=False S=0.000 P=0.000 S_tol=0.000 P_tol=0.556 seconds=191.6 total_tokens=2,342,126 uncached_plus_output_tokens=275,822 coordination_errors=0
- losangelex `III-28_n5.json`: success=False S=0.000 P=0.000 S_tol=1.000 P_tol=1.000 seconds=146.4 total_tokens=1,215,696 uncached_plus_output_tokens=198,736 coordination_errors=0
- losangelex-selector `III-28_n5.json`: success=False S=0.000 P=0.000 S_tol=1.000 P_tol=1.000 seconds=146.5 total_tokens=1,339,506 uncached_plus_output_tokens=177,906 coordination_errors=0
- losangelex `III-29_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=146.4 total_tokens=1,404,776 uncached_plus_output_tokens=237,032 coordination_errors=0
- losangelex-selector `III-29_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=191.9 total_tokens=1,634,505 uncached_plus_output_tokens=199,625 coordination_errors=0
- losangelex `III-30_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=101.3 total_tokens=1,182,071 uncached_plus_output_tokens=181,879 coordination_errors=0
- losangelex-selector `III-30_n5.json`: success=True S=1.000 P=1.000 S_tol=1.000 P_tol=1.000 seconds=101.4 total_tokens=1,287,012 uncached_plus_output_tokens=178,148 coordination_errors=0
