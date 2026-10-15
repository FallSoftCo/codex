# LAX Hollywood connector candidate

Hollywood owns communication and durable request/delivery identity; this connector owns native LAX execution and its local intent journal. It uses a pinned LAX app-server, not a TUI or a model API replacement. Human requests remain user input; agent requests arrive as native tool-authority room messages. Contexts bind authority, actor, room, audience and workspace. Observation tools do not start contexts.

The finite entrypoint is `lax-connect --config PRIVATE_JSON --claim-id ORIGINAL_ID`. Its opt-in resident mode observes authenticated metadata and admits addressed deliveries; metadata polling is not model polling. Explicit goal policy may authorize a bounded, deduplicated material-work review. Unsettled native effects refuse replay. PostgreSQL/HTTP restart state, native turn reconciliation, cancellation monitoring, host capability isolation and admin bootstrap have separate acceptance gates. Do not call this candidate a full production connector.

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

The connector verifies external-admission capability before loading a context,
binds captured work or coordination requests to stable native goal instances,
and publishes structured native plans and verified goal/accounting observations.
Native goal/set supports an optional expectedGoalId fence: null requires absence;
an ID requires that exact instance. Replacing a completed coordination objective
creates a fresh instance and resets its accounting. Unbound or replaced goals are
held for explicit reconciliation. Ordinary unfenced Codex clients retain their
previous behavior.

A real packaged one-host enterprise scenario completed three native turns:
Global created an Engineering room/worker, delegated a goal-backed assignment,
the separate worker UID received an attributable human clarification, wrote an
artifact and reported connector-hashed evidence; Global independently verified
its bytes with sudo and explicitly accepted work and goal in its original
context. Exactly one material review was authorized. An explicit fourth human
read-only follow-up projected a native structured plan. These are finite actual
provider proofs, not continuous supervision or physical-phone delivery.

Native goal instance/CAS and cold-resume accounting were also exercised through
two actual app-server processes with a deterministic provider. A second context
writer was rejected, stale goal IDs could not replace a newer instance and no
idle model continuation occurred. Immutable package executables/directories use
0755 and descriptors 0644 even under installer umask 0077; actual Global and
worker UIDs both executed the packaged binary. Credential/state directories keep
their separate private permissions.

Business pause/cancellation and stopped native-goal reconciliation, process-crash
recovery, plan editing/retries, second-host artifact retrieval, physical Android
voice/push and production migration remain release gates. No old session or
schedule is resumed by this candidate.
