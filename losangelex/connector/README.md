# LAX Hollywood connector candidate

Hollywood owns communication and durable request/delivery identity; this connector owns native LAX execution and its local intent journal. It uses a pinned LAX app-server, not a TUI or a model API replacement. Human requests remain user input; agent requests arrive as native tool-authority room messages. Contexts bind authority, actor, room, audience and workspace. Observation tools do not start contexts.

The initial entrypoint is a finite `lax-connect --config PRIVATE_JSON --claim-id ORIGINAL_ID`. No resident polling or model continuation is enabled. Unsettled native effects refuse replay. PostgreSQL/HTTP restart state, native turn reconciliation, cancellation monitoring, host capability isolation and admin bootstrap have separate acceptance gates. Do not call this candidate a full production connector.

The generic stdio RPC transport was reused from the maintained Hollywood implementation at frozen source190ff331df47eaba8a4a46052cc67f0a0ad6b85d and moved into the LAX-side package. No Hollywood execution runtime is imported.

## Native goals and plans: current integration boundary

The fork retains native persisted thread goals, status/budget/accounting,
goal notifications and structured turn plans. A room/product goal spans multiple
agents and contexts; each admitted work execution must bind to its own native
context/goal without replacing another unfinished context's goal. Native goal
completion is evidence for work review; enterprise acceptance remains a separate
Hollywood decision.

The opt-in native feature goal_external_admission keeps goal persistence and
accounting while suppressing automatic idle goal turns. Ordinary Codex behavior
keeps its default. Set it when starting/cold-resuming the controlled thread;
hot feature changes on an already loaded runtime are not qualified. Explicitly
admitted turns still execute normally. The tools.update_plan.enabled setting
enables the existing structured native checklist tool; update_plan_enabled is an
internal resolved field, not a supported input configuration key.

The actual native protocol integration in tests/integration_native_goals.py
exercised goal activation, cold resume, one explicit turn, a structured plan
and retained usage accounting through a local deterministic Responses fixture.
It observed zero automatic continuations and used no real provider inference.
It does not certify native agent deliverables.

The Hollywood connector does not yet set/verify this mode, bind enterprise
work to native goals, or forward structured goal/plan updates. Those are required
before connecting the new workflow API to resident agents. Further work includes
stable native goal-instance identity/CAS, preserving per-scope history, status
and cancellation reconciliation, and authorized artifact verification. No old
session or schedule is resumed by this candidate.
