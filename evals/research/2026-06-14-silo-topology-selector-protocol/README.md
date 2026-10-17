# SILO Hollywood Topology Selector Protocol, 2026-06-14

This protocol freezes the first Losangelex/Hollywood coordination selector to
test whether a foreman-style first-finisher pattern should be used selectively
rather than globally.

## Selector

Selector id: `silo-topology-v1-2026-06-14`

The selector uses only task topology visible before execution. It must not use
expected outputs, previous benchmark outcomes, task-specific score history, or
post-run observations.

| SILO task topology | Hollywood strategy | Rationale |
| --- | --- | --- |
| Level I global reductions | `first-finisher` | Each worker can publish a compact local fact and one finisher can write the same final aggregate for all agents. |
| Level II or III tasks | `room` | These tasks are order-dependent, iterative, graph-like, or require per-agent distinct output; normal room coordination is safer. |

## Test

The intended evaluation is model-in-the-loop, using the same frozen SILO task
files and the existing runner/scorer:

```bash
python3 scripts/run_silo_published_agents.py \
  --system losangelex \
  --system losangelex-selector \
  --agent-count 5 \
  --campaign-name silo-current-losangelex-selector-n5-2026-06-14
```

`losangelex` is the normal-room control. `losangelex-selector` applies the
frozen topology selector per task and records the selected strategy in each
result row.

## Interpretation Rules

- Treat `losangelex-first-finisher` as an ablation, not a deployment default.
- Treat `losangelex-selector` as the product-relevant candidate.
- If the selector improves token usage but loses strict success or materially
  worsens latency, it is not ready as a default policy.
- If the selector helps only a narrow task family, keep it as an explicit
  coordination primitive that agents or task routers can request.
