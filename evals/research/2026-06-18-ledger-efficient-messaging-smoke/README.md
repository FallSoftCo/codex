# Ledger-Efficient Hollywood Messaging Smoke Evaluation

Generated: 2026-06-18

This is a bounded model-in-the-loop smoke evaluation for the ledger-efficient
Hollywood coordination changes. It is not a full benchmark rerun.

## Runtime Under Test

- Worktree: `/home/ai/Development/losangelex-ledger-efficient-messaging`
- Branch: `hollywood-ledger-efficient-messaging`
- Binary: `codex-rs/target/losangelex-ledger-bench/debug/codex`
- Model: `gpt-5.5`
- App-server mode: isolated managed benchmark app-server per runner

The published benchmark repositories were copied into this worktree under
`tmp/research/published-agent-benchmarks/repos` before execution so the runner
could hide benchmark repositories without touching any live checkout state.

## Results

| Benchmark | System | Task | Result | Seconds | Total tokens | Uncached+output |
| --- | --- | --- | --- | ---: | ---: | ---: |
| SILO-BENCH | losangelex-selector | `I-01_n2` | success, S=1.000, P=1.000 | 43.9 | 212,600 | 68,856 |
| MARBLE database | losangelex | `database-001`, native-postgres | success, recall=1.000, precision=0.500, F1=0.667 | 135.6 | 1,731,339 | 327,179 |

The MARBLE prediction was `['INSERT_LARGE_DATA', 'VACUUM']`; gold was
`['INSERT_LARGE_DATA']`, so recall passed but exact-set precision did not.

## Commands

```sh
python3 scripts/run_silo_published_agents.py \
  --system losangelex-selector \
  --silo-root /home/ai/Development/losangelex-ledger-efficient-messaging/tmp/research/published-agent-benchmarks/repos/acl26-silo-bench \
  --out-root /home/ai/Development/losangelex-ledger-efficient-messaging/tmp/research/published-agent-benchmarks \
  --campaign-name 2026-06-18-ledger-efficient-silo-smoke \
  --codex /home/ai/Development/losangelex-ledger-efficient-messaging/codex-rs/target/losangelex-ledger-bench/debug/codex \
  --model gpt-5.5 \
  --level I \
  --agent-count 2 \
  --limit 1 \
  --max-rounds 2 \
  --per-agent-timeout-seconds 300 \
  --timeout-seconds 900 \
  --round-timeout-seconds 300 \
  --poll-seconds 2 \
  --app-server-start-timeout-seconds 60

python3 scripts/run_marble_database_published_agents.py \
  --system losangelex \
  --marble-root /home/ai/Development/losangelex-ledger-efficient-messaging/tmp/research/published-agent-benchmarks/repos/MARBLE \
  --out-root /home/ai/Development/losangelex-ledger-efficient-messaging/tmp/research/published-agent-benchmarks \
  --campaign-name 2026-06-18-ledger-efficient-marble-smoke \
  --codex /home/ai/Development/losangelex-ledger-efficient-messaging/codex-rs/target/losangelex-ledger-bench/debug/codex \
  --model gpt-5.5 \
  --task-id database-001 \
  --max-rounds 1 \
  --per-agent-timeout-seconds 300 \
  --timeout-seconds 1200 \
  --round-timeout-seconds 300 \
  --poll-seconds 2 \
  --app-server-start-timeout-seconds 60 \
  --evidence-mode native-postgres
```

## Notes

- An initial SILO attempt using relative `--out-root`/fixture paths was invalid:
  the runner changes cwd for the managed app-server, causing doubled relative
  workspace paths. That invalid temp artifact was deleted and rerun with
  absolute paths.
- The isolated app-server logged a project-trust warning for the worktree-local
  `.codex` directory, but command execution and benchmark scoring succeeded.
- These smoke runs are useful regression evidence for runtime viability, but
  they are not statistically meaningful benchmark comparisons.
