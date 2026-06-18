# Upstream Codex Subagent Messaging Changes

This note covers upstream commits in the catch-up window that specifically
changed Codex multi-agent/subagent messaging behavior.

## Relevant Commits

| Commit | Date | Subject | Messaging significance |
|---|---|---|---|
| `8f2d6416ce41be54551185c640f83e22f061eccd` | 2026-06-12 | `Support plaintext agent messages (#27830)` | Adds typed/plaintext agent-message input/history handling and preserves delivered inter-agent communications as `agent_message` history rather than flattening them into assistant text. |
| `127224cacce1bc08922f21a5ff3e3ddd33246474` | 2026-06-15 | `[codex] update multi-agent v2 prompts (#28283)` | Updates multi-agent v2 prompt guidance around shared workspaces, direct tool calls, and `fork_turns`; this is instruction-layer behavior, not a new message substrate. |
| `5b22a8e5b13bd4bc3b331e7a1392569107b7bccf` | 2026-06-16 | `feat: render typed envelopes for multi-agent v2 messages (#28368)` | Adds model-visible typed envelopes for `NEW_TASK`, `MESSAGE`, and `FINAL_ANSWER`, including sender, recipient task name, and payload. This replaces the older completion shape for multi-agent v2 final answers. |
| `1b24ba912ac4c56ef936364deb1c3e294b0ef9fa` | 2026-06-16 | `core: surface terminal subagent errors to parent agents (#28375)` | Preserves terminal subagent stream errors and forwards bounded error summaries to parent agents instead of losing them behind a trailing empty turn-complete event. |
| `45f603302c45269737db97443612bb4876365798` | 2026-06-17 | `Add join key for MAv2 inter-agent messages (#28561)` | Adds `ResponseItemMetadata.source_call_id` so app-server clients can join raw inter-agent messages to the originating `spawn_agent`, `send_message`, or `followup_task` call. |

## What Changed

The June 12 and June 16 commits are the most important substrate changes.
Together they make inter-agent communication more typed, more durable, and more
visible to the model and clients:

- Delivered inter-agent communications survive in history as typed
  `agent_message` items.
- Plain text agent messages can be represented without losing the typed
  distinction between normal assistant content and inter-agent delivery.
- Multi-agent v2 completions render in consistent envelopes:

  ```text
  Message Type: <NEW_TASK | MESSAGE | FINAL_ANSWER>
  Task name: <recipient agent path>
  Sender: <author agent path>
  Payload:
  <payload text>
  ```

- Terminal subagent errors are surfaced back to the parent with bounded text and
  recovery guidance.
- App-server consumers get a join key to associate raw agent-message items with
  the tool activity that produced them.

## What Did Not Change

These upstream commits do not make Codex a general Hollywood-style room runtime.
They improve Codex multi-agent v2 parent/child messaging, history, and client
correlation. They do not add Losangelex concepts such as durable rooms, shared
board state, path claims, leases, or collaboration-first autonomous team
formation.

## Publication Interpretation

The changes are fundamentally different from simple prompt edits at the
messaging substrate layer, especially `#27830`, `#28368`, `#28375`, and
`#28561`. They are not fundamentally the same as Losangelex/Hollywood's room
coordination model. The safest public wording is:

> Upstream Codex materially improved multi-agent v2 messaging in mid-June 2026,
> adding typed history, typed message envelopes, terminal-error surfacing, and
> app-client join keys. The June 16 SILO appendix therefore compares Losangelex
> against a stronger current Codex subagent baseline, but it remains a different
> coordination architecture rather than a room-runtime clone.
