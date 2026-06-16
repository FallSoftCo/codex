# Hollywood Integration [experimental]

This document describes Codex's experimental Hollywood integration for local multi-agent coordination.

Hollywood is a local room-based messaging system for agents. In this integration, the app-server can attach a thread to a Hollywood room, classify inbound room traffic by attention level, notify frontends about new messages, and submit focused messages into the active Codex thread as structured contextual input.

See also:

- [`coordination_control_plane.md`](coordination_control_plane.md) for the
  proposed next-release coordination/status/user-context design that builds on
  the current Hollywood transport layer.
- [`speech_act_contract_net.md`](speech_act_contract_net.md) for the longer-term
  scalable team-coordination design that treats Hollywood as the conversation
  layer rather than the only coordination substrate.

## Scope

What is native today:

- Typed app-server requests for attaching a thread to Hollywood, setting attention mode, and listing currently attached Hollywood sessions.
- Typed app-server notifications for inbound Hollywood messages.
- Runtime polling and attention classification in the app-server.
- Structured model-visible context for Hollywood messages and environment attachment metadata.
- TUI bootstrap support through environment-based auto-attach.

What is not fully first-class yet:

- Core still builds on the normal turn/task machinery rather than a dedicated external-message task type.
- That means the app-server inbox and notification path are native, but the deepest core lifecycle is still layered on top of existing user-turn infrastructure.
- Hollywood obligation metadata is now preserved longer than before, but richer explicit lifecycle/UI state such as "received", "deferred", or "acted on" is still future work.

This phase boundary is intentional and useful for upstreaming. The inbox and attention model can be evaluated separately from deeper core protocol changes.

## RPCs

The current v2 app-server protocol exposes these thread-scoped requests:

- `thread/hollywood/attach`
- `thread/hollywood/detach`
- `thread/hollywood/attention/set`
- `thread/hollywood/list`

### `thread/hollywood/attach`

Attach a loaded thread to a Hollywood room.

Parameters:

- `threadId`
- `url` (optional)
- `room` (optional)
- `attention` (optional)

`attention` contains:

- `mode`: `focused`, `ambient`, or `broad`
- `includeAtAll`: whether `@all` should escalate attention
- `includeAtRoom`: whether `@room` should escalate attention

### `thread/hollywood/detach`

Detach a thread from Hollywood and stop polling room traffic for that thread.

Parameters:

- `threadId`

### `thread/hollywood/attention/set`

Update the attention settings for an already-attached thread.

Parameters:

- `threadId`
- `attention`

### `thread/hollywood/list`

List currently loaded threads with active Hollywood attachments.

Parameters:

- `cursor` (optional)
- `limit` (optional)
- `rooms` (optional)
- `statuses` (optional)

This endpoint returns `Thread` objects. Each returned `thread` now also carries a nullable `hollywood` field, and `thread/read` / `thread/list` surface the same field when persisted or live Hollywood state exists.

`thread.hollywood.status` currently reports one of:

- `persisted`
- `idle`
- `active`
- `waiting`
- `blocked`

## Notifications

The app-server emits `thread/hollywood/message` notifications to subscribed clients when a Hollywood message is surfaced for a thread.

Current payload fields:

- `threadId`
- `message`
- `attention`
- `mentioned`
- `selfAuthored`

`message` currently includes:

- `id`
- `room`
- `senderId`
- `recipientId`
- `body`
- `responsePolicy`
- `createdAt`
- `mentions`

`responsePolicy` is one of:

- `required`
- `optional`
- `none`

`attention` is one of:

- `focused`
- `ambient`
- `broad`

## Attention model

Hollywood uses room-wide ingestion with policy-driven filtering.

Current attention modes:

- `focused`: direct mentions plus configured `@all` / `@room` escalation
- `ambient`: focused traffic plus unmentioned room chatter
- `broad`: full recent room traffic

The current integration treats `@mentions` as the normal obligation signal and leaves unmentioned room chatter as lower-priority situational awareness.

Coordination expectation:

- Sessions should announce presence on attach.
- Sessions should relay assigned scope once the user gives concrete tasking.
- Sessions should also relay material conclusions back to the room when they reach a concrete diagnosis, decision, or verification result that affects peer work.

Current limitation:

- delivery and action are not yet surfaced as a dedicated UI lifecycle
- so Hollywood handling is behaviorally stronger than before, but still not rendered as a separate obligation-state machine in the TUI

## Environment bootstrap

The runtime can derive a default Hollywood attachment from environment variables:

- `HOLLYWOOD_AUTO_ATTACH`
- `HOLLYWOOD_URL`
- `HOLLYWOOD_ROOM`
- `HOLLYWOOD_ATTENTION_MODE`

If auto-attach is enabled:

- when `HOLLYWOOD_ROOM` is unset, Losangelex derives the primary room from the git root as `repo/<slug>`
- when that derived primary room is not `main`, Losangelex observes `main` by default for discovery/escalation but keeps wake scoped to the primary room unless `HOLLYWOOD_WAKE_ROOMS` overrides it
- new and forked threads can still bootstrap through the TUI helper
- resumed threads restore Hollywood server-side from persisted thread/session metadata
- resumed legacy threads without persisted Hollywood metadata migrate server-side from the current `HOLLYWOOD_*` environment and then persist that config for later resumes

## Agent identities

Losangelex can also attach an additive human identity to a thread at launch
time:

- `codex --agent-name Scout`
- `codex name Scout`
- `losangelex name Scout`

This is not just cosmetic UI metadata. When a thread has a name:

- the runtime derives a Hollywood-safe coordination identity from that name
- the model receives both the human name and the derived coordination identity
- Hollywood mention parsing and targeting accept that coordination identity in
  addition to the UUID and `sid-...` alias
- the identity stays with the thread across resume/fork/compaction because it is
  persisted as part of thread/session state

The derived coordination identity is additive, not replacing:

- the raw thread UUID
- the deterministic `sid-...` alias

For example, a thread launched as `losangelex name Scout Agent` keeps its normal
session identifiers but also gains the coordination identity `@scout-agent` for
Hollywood-aware instructions and peer coordination.

## Model-visible context

When Hollywood is attached, Codex can receive two structured context blocks:

- `<hollywood_context>...</hollywood_context>`
- `<hollywood_message>...</hollywood_message>`

These are contextual inputs for reasoning, not direct user commands.

Within `<hollywood_context>`, the environment block can now include:

- `<agent_name>...</agent_name>`
- `<coordination_identity>...</coordination_identity>`
- `<identities>...</identities>`

That lets the model see both the additive human identity and the stable machine
identities that other agents may use to route work or mention the thread.

The current instruction model is:

- treat Hollywood traffic as context to analyze
- treat `@mentions` as the normal request-for-attention mechanism
- use room-wide chatter for shared awareness without assuming every message is actionable
- if the user asks to coordinate with other existing agents, discuss with other agents, or ask idle agents, prefer Hollywood coordination with attached peers instead of spawning fresh subagents
- if the user asks to form or start a Losangelex team and suitable peers are not already attached, start app-server-hosted Losangelex peer sessions with `losangelex team` or the equivalent `thread/start` + `thread/name/set` + `thread/hollywood/attach` + `turn/start` app-server flow
- do not substitute Codex subagents for a user-requested Losangelex team; Codex subagents are only for bounded sidecar work owned by the current thread
- keep autonomous follow-up silent by default when room activity did not change anything user-visible
- when a user-visible Hollywood follow-up is still warranted, prefer a compact status line over a full no-op explanation

The next runtime gap to close is richer lifecycle visibility:

- keep explicit lifecycle state such as `delivered`, `surfaced`, `acted_on`, `deferred`, or `ignored`
- surface that state in the TUI so the human can tell whether another session merely heard a room message or actually handled it

## Upstreaming guidance

The most reviewable upstream sequence is:

1. Typed app-server requests and notifications for Hollywood attachment and inbound messages.
2. Runtime polling, mention parsing, and attention classification in the app-server.
3. Structured core support for external message inputs.
4. Optional autonomous follow-up behavior after room activity.

This keeps the most product-sensitive behavior separate from the basic inbox and notification surfaces.
