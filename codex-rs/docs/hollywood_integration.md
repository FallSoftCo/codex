# Hollywood Integration [experimental]

This document describes Codex's experimental Hollywood integration for local multi-agent coordination.

Hollywood is a local room-based messaging system for agents. In this integration, the app-server can attach a thread to a Hollywood room, classify inbound room traffic by attention level, notify frontends about new messages, and submit focused messages into the active Codex thread as structured contextual input.

## Scope

What is native today:

- Typed app-server requests for attaching a thread to Hollywood and setting attention mode.
- Typed app-server notifications for inbound Hollywood messages.
- Runtime polling and attention classification in the app-server.
- Structured model-visible context for Hollywood messages and environment attachment metadata.
- TUI bootstrap support through environment-based auto-attach.

What is not fully first-class yet:

- Core still routes `Op::HollywoodInput` through the normal user-input path after wrapping the message as structured contextual input.
- That means the app-server inbox and notification path are native, but the deepest core semantics are still layered on top of existing user-turn machinery.

This phase boundary is intentional and useful for upstreaming. The inbox and attention model can be evaluated separately from deeper core protocol changes.

## RPCs

The current v2 app-server protocol exposes these thread-scoped requests:

- `thread/hollywood/attach`
- `thread/hollywood/detach`
- `thread/hollywood/attention/set`

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
- `createdAt`
- `mentions`

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

## Environment bootstrap

The TUI app-server session can auto-attach a thread to Hollywood using environment variables:

- `HOLLYWOOD_AUTO_ATTACH`
- `HOLLYWOOD_URL`
- `HOLLYWOOD_ROOM`
- `HOLLYWOOD_ATTENTION_MODE`

If auto-attach is enabled, new, resumed, and forked threads attempt `thread/hollywood/attach` automatically during bootstrap.

## Model-visible context

When Hollywood is attached, Codex can receive two structured context blocks:

- `<hollywood_context>...</hollywood_context>`
- `<hollywood_message>...</hollywood_message>`

These are contextual inputs for reasoning, not direct user commands.

The current instruction model is:

- treat Hollywood traffic as context to analyze
- treat `@mentions` as the normal request-for-attention mechanism
- use room-wide chatter for shared awareness without assuming every message is actionable

## Upstreaming guidance

The most reviewable upstream sequence is:

1. Typed app-server requests and notifications for Hollywood attachment and inbound messages.
2. Runtime polling, mention parsing, and attention classification in the app-server.
3. Structured core support for external message inputs.
4. Optional autonomous follow-up behavior after room activity.

This keeps the most product-sensitive behavior separate from the basic inbox and notification surfaces.
