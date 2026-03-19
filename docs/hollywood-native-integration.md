# Hollywood Native Integration

## Goal

Integrate Hollywood as a native event source in Codex so agent-to-agent messages are observed by the runtime itself, not by an external terminal tail.

The model is room-wide visibility with attention filtering, not direct-message-first delivery.

## Conclusion

The best integration point is the Rust app-server plus protocol layer, with a small core-protocol extension.

Do not integrate Hollywood at the packaged CLI launcher layer.

Do not treat Hollywood as a sidecar terminal stream.

Do not inject Hollywood traffic by rewriting prompts outside the runtime.

## Why

The current system already has the right architecture for native external events:

- The app-server owns thread lifecycle, subscriptions, and outbound notifications.
- The TUI consumes typed `ServerNotification` values.
- The app-server already distinguishes:
  - starting a new turn: `turn/start`
  - steering an active turn: `turn/steer`
  - interrupting a turn: `turn/interrupt`
- The TUI already has queue and interrupt behavior for incoming runtime events.

What is missing is a first-class runtime concept for "external agent message" and "agent attention policy".

Today, `turn/start` ends up as `Op::UserInput` after optional turn-context overrides, which means Hollywood traffic has no native representation and would have to be smuggled in as ordinary user input. That is the wrong abstraction.

Direct-message-first filtering is also the wrong abstraction for Hollywood. Agents should be able to share a room and maintain common awareness while still focusing their attention primarily through `@mentions`.

## Exact insertion points

### 1. Core protocol

Add a new op and event family in `codex-rs/protocol/src/protocol.rs`.

Recommended new primitives:

- `Op::ExternalMessage`
- `EventMsg::ExternalMessageReceived`
- `EventMsg::ExternalMessageQueued`
- `EventMsg::ExternalMessagePolicyDecision`

Suggested payload fields:

- source kind: `hollywood`
- room
- sender id
- sender alias
- parsed mentions
- raw routing metadata if present
- body
- message id
- created at
- delivery policy used

This avoids pretending that an inter-agent message is a human user turn.

### 2. App-server protocol

Add typed app-server notifications and requests in `codex-rs/app-server-protocol/src/protocol/v2.rs`.

Recommended additions:

- `thread/hollywood/attach`
- `thread/hollywood/detach`
- `thread/hollywood/message`
- `thread/hollywood/presence`
- `thread/hollywood/attention/set`

At minimum, add a notification for inbound Hollywood messages and a request for configuring attachment/attention policy.

The app-server protocol is the correct public boundary because all frontends consume it.

### 3. App-server runtime

Implement the Hollywood bridge inside `codex-rs/app-server/src/codex_message_processor.rs` and `codex-rs/app-server/src/thread_state.rs`.

Recommended shape:

- Per thread, maintain an optional Hollywood subscription task.
- Reuse thread subscription state so only attached threads receive room traffic.
- Feed Hollywood events into the thread listener path, alongside other thread-scoped events.
- Use `ThreadScopedOutgoingMessageSender` so notifications follow existing per-thread routing.

This is the cleanest place because the app-server already owns:

- loaded thread lifetime
- connection subscription management
- thread-scoped notifications
- turn status
- interrupt behavior

### 4. Attention model

Hollywood should be modeled as:

- room-wide ingestion
- mention-driven attention
- policy-controlled broadening when idle or blocked

Agents should not default to direct messages only.

Recommended attention modes:

- `focused`
  - Surface only messages that mention this agent.
  - Optionally include `@all`, `@room`, and system/admin messages.
- `ambient`
  - Surface mentions plus a small nearby context window from the room.
- `broad`
  - Surface the full recent room stream.
- `search`
  - Query older room history by mention target, sender, topic, or text.

Recommended broadening behavior:

- Start in `focused`.
- If there is nothing actionable, broaden to `ambient`.
- If still idle or blocked, broaden to `broad`.
- Collapse back to `focused` when a direct `@mention` or active work item appears.

Mention semantics should be the main obligation signal:

- no mention: ambient awareness only
- `@this-agent`: actionable
- `@all` or `@room`: configurable escalation
- self-authored messages: low priority

This preserves:

- common room awareness
- selective focus
- explicit agent coordination through `@mentions`

### Instruction-level behavior

Runtime attention is only half of the feature. The model also needs explicit instruction-level guidance so it uses Hollywood coherently.

- Treat Hollywood traffic as contextual input to analyze, not as unconditional commands.
- Treat `@mentions` as the standard way to request another agent's attention or response.
- Treat unmentioned room chatter as ambient situational awareness.
- Re-evaluate the current plan when a Hollywood message materially changes the situation.
- Use `@mentions` when asking another agent to notice, respond, or coordinate.
- Use unmentioned room messages for status, discoveries, and broadly useful context that does not require a specific reply.

### 5. TUI behavior

Update `codex-rs/tui_app_server/src/chatwidget.rs` and `codex-rs/tui_app_server/src/app/app_server_adapter.rs` to handle the new Hollywood notification family.

The TUI should not own Hollywood transport. It should only render and apply policy:

- if idle: surface focused items first, optionally broaden attention
- if a turn is running: queue, steer, or interrupt based on configured policy
- show ambient room traffic separately from actionable `@mention` traffic
- show pending Hollywood items distinctly from normal queued user messages

### 6. Delivery policy

Hollywood needs explicit scheduling policy. Recommended policies:

- `notify_only`
- `queue_next_turn`
- `steer_active_turn`
- `interrupt_and_handle`

Policy belongs in the app-server thread/session config, not in the shell wrapper.

Recommended split:

- attention policy decides what the agent meaningfully reads
- delivery policy decides how actionable Hollywood messages affect work

## Best first implementation

Phase 1:

- Add app-server notification for inbound Hollywood messages.
- Add per-thread Hollywood listener task.
- Parse mentions and classify messages as ambient vs actionable.
- Render inbound messages in the TUI.
- Default attention mode: `focused`.
- Default delivery policy: `notify_only`.

Phase 2:

- Add app-server-configured attention policy.
- Add broadening logic for idle or blocked states.
- Add app-server-configured delivery policy.
- Route actionable Hollywood messages to:
  - `turn/steer` if a matching active turn exists and policy allows
  - queued follow-up input if idle or if steering is not allowed

Phase 3:

- Add core-native `Op::ExternalMessage` so Hollywood input is no longer modeled as user input at all.
- Add core-native support for attention-policy decisions and message classification events.

## Files that matter most

- `codex-rs/app-server/src/codex_message_processor.rs`
- `codex-rs/app-server/src/thread_state.rs`
- `codex-rs/app-server/src/outgoing_message.rs`
- `codex-rs/app-server-protocol/src/protocol/v2.rs`
- `codex-rs/tui_app_server/src/app/app_server_adapter.rs`
- `codex-rs/tui_app_server/src/chatwidget.rs`
- `codex-rs/protocol/src/protocol.rs`

## Non-goals

- No terminal `tail` bridge.
- No wrapper that prepends inbox text to prompts.
- No fake "continuous listening" implemented outside the runtime.
- No direct-message-only delivery model as the primary coordination mechanism.
