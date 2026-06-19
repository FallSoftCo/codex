# Hollywood Coordination Benchmark

Generated: 2026-06-18T18:06:11Z

Live model-in-the-loop comparison using frozen scratch coordination scenarios.

## Summary

| System | Runs | Passed | Content matches | Coord met | Avg seconds | Avg total tokens | Avg uncached+output | Spawn calls | Required peer requests | Peer responses | Tool errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| codex | 3 | 3 (100.0%) | 3 | 3 | 56.8 | 86,745 | 19,119 | 0 | 0 | 0 | 0 |
| codex-subagents | 3 | 3 (100.0%) | 3 | 1 | 107.9 | 271,828 | 57,641 | 0 | 0 | 0 | 0 |
| losangelex | 3 | 3 (100.0%) | 3 | 3 | 136.3 | 587,980 | 103,884 | 0 | 3 | 9 | 0 |
| losangelex-baseline | 3 | 1 (33.3%) | 3 | 1 | 110.1 | 341,854 | 60,424 | 0 | 2 | 0 | 0 |

## Runs

### codex / review_heavy_permissions / 69ce6695

- Passed: `True`
- Expected collaboration: `True`
- Coordination requirement met: `True`
- Expected content matches: `True`
- Workspace changed: `True`
- Seconds: `50.0`
- Total tokens: `103115`
- Uncached+output tokens: `30283`
- Spawn calls: `0`
- Required peer requests: `0`
- Peer responses: `0`
- Tool errors: `0`
- Workspace: `/home/ai/Development/losangelex/tmp/research/hollywood-coordination-benchmark/hollywood-coordination-postfix-2026-06-18-c/codex/review_heavy_permissions/69ce6695/workspace`

### codex-subagents / review_heavy_permissions / 543b5d6d

- Passed: `True`
- Expected collaboration: `True`
- Coordination requirement met: `False`
- Expected content matches: `True`
- Workspace changed: `True`
- Seconds: `101.2`
- Total tokens: `299570`
- Uncached+output tokens: `51506`
- Spawn calls: `0`
- Required peer requests: `0`
- Peer responses: `0`
- Tool errors: `0`
- Workspace: `/home/ai/Development/losangelex/tmp/research/hollywood-coordination-benchmark/hollywood-coordination-postfix-2026-06-18-c/codex-subagents/review_heavy_permissions/543b5d6d/workspace`

### losangelex-baseline / review_heavy_permissions / 4d9eecef

- Passed: `False`
- Expected collaboration: `True`
- Coordination requirement met: `False`
- Expected content matches: `True`
- Workspace changed: `True`
- Seconds: `155.0`
- Total tokens: `615362`
- Uncached+output tokens: `103362`
- Spawn calls: `0`
- Required peer requests: `2`
- Peer responses: `0`
- Tool errors: `0`
- Workspace: `/home/ai/Development/losangelex/tmp/research/hollywood-coordination-benchmark/hollywood-coordination-postfix-2026-06-18-c/baseline/review_heavy_permissions/4d9eecef/workspace`

### losangelex / review_heavy_permissions / 09c196fe

- Passed: `True`
- Expected collaboration: `True`
- Coordination requirement met: `True`
- Expected content matches: `True`
- Workspace changed: `True`
- Seconds: `196.8`
- Total tokens: `912571`
- Uncached+output tokens: `134203`
- Spawn calls: `0`
- Required peer requests: `2`
- Peer responses: `6`
- Tool errors: `0`
- Workspace: `/home/ai/Development/losangelex/tmp/research/hollywood-coordination-benchmark/hollywood-coordination-postfix-2026-06-18-c/candidate/review_heavy_permissions/09c196fe/workspace`

### codex / splittable_reconnect / 36378464

- Passed: `True`
- Expected collaboration: `True`
- Coordination requirement met: `True`
- Expected content matches: `True`
- Workspace changed: `True`
- Seconds: `59.4`
- Total tokens: `95960`
- Uncached+output tokens: `14936`
- Spawn calls: `0`
- Required peer requests: `0`
- Peer responses: `0`
- Tool errors: `0`
- Workspace: `/home/ai/Development/losangelex/tmp/research/hollywood-coordination-benchmark/hollywood-coordination-postfix-2026-06-18-c/codex/splittable_reconnect/36378464/workspace`

### codex-subagents / splittable_reconnect / 341cd80d

- Passed: `True`
- Expected collaboration: `True`
- Coordination requirement met: `False`
- Expected content matches: `True`
- Workspace changed: `True`
- Seconds: `196.4`
- Total tokens: `456118`
- Uncached+output tokens: `95926`
- Spawn calls: `0`
- Required peer requests: `0`
- Peer responses: `0`
- Tool errors: `0`
- Workspace: `/home/ai/Development/losangelex/tmp/research/hollywood-coordination-benchmark/hollywood-coordination-postfix-2026-06-18-c/codex-subagents/splittable_reconnect/341cd80d/workspace`

### losangelex-baseline / splittable_reconnect / b91cd003

- Passed: `False`
- Expected collaboration: `True`
- Coordination requirement met: `False`
- Expected content matches: `True`
- Workspace changed: `True`
- Seconds: `127.9`
- Total tokens: `305794`
- Uncached+output tokens: `36098`
- Spawn calls: `0`
- Required peer requests: `0`
- Peer responses: `0`
- Tool errors: `0`
- Workspace: `/home/ai/Development/losangelex/tmp/research/hollywood-coordination-benchmark/hollywood-coordination-postfix-2026-06-18-c/baseline/splittable_reconnect/b91cd003/workspace`

### losangelex / splittable_reconnect / 40a29fe3

- Passed: `True`
- Expected collaboration: `True`
- Coordination requirement met: `True`
- Expected content matches: `True`
- Workspace changed: `True`
- Seconds: `156.9`
- Total tokens: `711418`
- Uncached+output tokens: `144378`
- Spawn calls: `0`
- Required peer requests: `1`
- Peer responses: `3`
- Tool errors: `0`
- Workspace: `/home/ai/Development/losangelex/tmp/research/hollywood-coordination-benchmark/hollywood-coordination-postfix-2026-06-18-c/candidate/splittable_reconnect/40a29fe3/workspace`

### codex / tiny_readme / ee1772eb

- Passed: `True`
- Expected collaboration: `False`
- Coordination requirement met: `True`
- Expected content matches: `True`
- Workspace changed: `True`
- Seconds: `60.9`
- Total tokens: `61161`
- Uncached+output tokens: `12137`
- Spawn calls: `0`
- Required peer requests: `0`
- Peer responses: `0`
- Tool errors: `0`
- Workspace: `/home/ai/Development/losangelex/tmp/research/hollywood-coordination-benchmark/hollywood-coordination-postfix-2026-06-18-c/codex/tiny_readme/ee1772eb/workspace`

### codex-subagents / tiny_readme / 6f858510

- Passed: `True`
- Expected collaboration: `False`
- Coordination requirement met: `True`
- Expected content matches: `True`
- Workspace changed: `True`
- Seconds: `26.2`
- Total tokens: `59795`
- Uncached+output tokens: `25491`
- Spawn calls: `0`
- Required peer requests: `0`
- Peer responses: `0`
- Tool errors: `0`
- Workspace: `/home/ai/Development/losangelex/tmp/research/hollywood-coordination-benchmark/hollywood-coordination-postfix-2026-06-18-c/codex-subagents/tiny_readme/6f858510/workspace`

### losangelex-baseline / tiny_readme / 2055bc3b

- Passed: `True`
- Expected collaboration: `False`
- Coordination requirement met: `True`
- Expected content matches: `True`
- Workspace changed: `True`
- Seconds: `47.4`
- Total tokens: `104405`
- Uncached+output tokens: `41813`
- Spawn calls: `0`
- Required peer requests: `0`
- Peer responses: `0`
- Tool errors: `0`
- Workspace: `/home/ai/Development/losangelex/tmp/research/hollywood-coordination-benchmark/hollywood-coordination-postfix-2026-06-18-c/baseline/tiny_readme/2055bc3b/workspace`

### losangelex / tiny_readme / 98b23104

- Passed: `True`
- Expected collaboration: `False`
- Coordination requirement met: `True`
- Expected content matches: `True`
- Workspace changed: `True`
- Seconds: `55.2`
- Total tokens: `139952`
- Uncached+output tokens: `33072`
- Spawn calls: `0`
- Required peer requests: `0`
- Peer responses: `0`
- Tool errors: `0`
- Workspace: `/home/ai/Development/losangelex/tmp/research/hollywood-coordination-benchmark/hollywood-coordination-postfix-2026-06-18-c/candidate/tiny_readme/98b23104/workspace`

