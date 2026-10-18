# LAX fork contract and upstream integration

## Authority and scope

LAX is the FallSoftCo agent harness. Hollywood is its primary communication
system for humans and agents; NextComp is a human client. Upstream Codex is a
source of reusable implementation and fixes. Its product assumptions do not
define LAX behavior.

LAX may replace, remove or restructure upstream code wherever the product
requires it. Architectural compatibility with upstream is optional. Preserving
LAX behavior, security and recoverability is mandatory. This policy follows the
user's explicit architecture direction of 2026-10-17.

The following is the target contract and the acceptance boundary for future
changes. Recording this contract does not assert that the current runtime
already implements or has qualified every requirement.

## Product contract

- Hollywood owns authenticated rooms, membership, communication provenance,
  durable messages and receipts. Human and agent authors remain distinct.
- LAX owns agent execution, model inputs, tool definitions and implementations,
  context, continuation, cancellation and lifecycle. Hollywood startup
  initializes or recovers Global through LAX without requiring a TUI.
- Each agent has a durable identity, individual context and responsibilities
  independent of room membership. An agent can join many rooms; a room can
  contain many agents.
- Authorized peer requests and replies are primary actionable inputs. Observing
  room traffic does not automatically accept every assignment or require a
  response from every observer.
- The model receives a coherent LAX tool and instruction set. Agent lifecycle
  and communication use LAX/Hollywood implementations; competing upstream
  backends must not remain executable through hidden, deferred, dynamic or
  restored tool paths. Useful execution and editing tools can be retained.
- Base instructions, roles, namespace guidance, tool descriptions and incoming
  message envelopes agree with the actual runtime. Model changes, peer launch,
  resume and compaction must preserve that agreement.
- Existing native cooperation modes and collaborative editing are capabilities
  to reconcile and qualify, not silently discard during upstream updates.
- Model response completion, message acceptance, peer response and work
  completion are separate events. Waiting preserves pending work and resumes
  on relevant events without recurring model polling.
- Intentional conversation messages and execution activity are separate
  attributable event streams. Both can be presented in NextComp.
- Host, workspace and artifact references are explicit. A shared filesystem,
  common current directory or common permissions cannot be assumed across
  agents or hosts.
- Recovery preserves original operation identities and uncertain outcomes.
  Durable receipts and deduplication do not imply exactly-once external effects.
- User stops, cancellations, permissions, existing pairings, drafts and queued
  work survive upgrades. An upstream import must not activate paused work.

## Purpose-separated agent contexts

One durable agent may use independent reader, writer and responder histories.
The reader interprets attributable communication and maintains relevant work
material. The writer executes accepted responsibilities. The responder owns
outward communication, including proactive communication; internal model final
text is not automatically a room reply.

Changing input is retrieved through bounded, versioned tools. The responder
does not receive a duplicate automatic room inbox. Reading or publishing against
material must preserve its source, purpose, revision and authorized audience.
Observation timeouts do not establish execution failure or authorize a replacement
turn. Recovery observes the exact original native turn and operation receipts.

Purpose separation must reuse the native execution, administration, work/review
and cooperation mechanisms. Internal context material is a handoff, not another
authoritative work acceptance ledger. Do not silently lose these capabilities
by substituting a reduced tool set. The three-context candidate qualification
records distinguish actual-model evidence from remaining integration work;
they do not establish production replacement readiness.

## Upstream intake and release

1. Fetch current upstream source separately and record the exact inspected
   commit. A source receipt records provenance; it is not an instruction to
   freeze future intake at that revision.
2. Integrate in a reviewable candidate. Preserve the maintained fork and current
   release before resolving changes. Never replace a deployed fork with an
   upstream checkout, installer or binary as an update shortcut.
3. Review semantic changes as well as merge conflicts. Inspect model catalog
   defaults, prompts and roles, tool planning and discovery, registered
   handlers, incoming message handling, history/resume/compaction, lifecycle,
   authentication and host/workspace routing. A conflict-free merge is not
   evidence of product compatibility.
4. Keep or rewrite the implementation that satisfies this contract. Upstream
   deletion, renaming or restructuring is not authority to delete a LAX
   capability. Avoid blanket file-level merge strategies that silently discard
   useful upstream fixes.
5. Qualify the resulting LAX behavior through its actual human API and model
   route. The core journey is headless Global bootstrap, an ordinary human
   request without prescribed tool names, peer creation, room communication,
   cooperative execution, a peer reply and a later human turn. Inspect actual
   model-visible tools and attributed events. Continue the same work across
   reconnect/resume and verify the relevant cancellation and isolation
   boundaries. Deterministic mocks alone do not establish model behavior.
6. Release an identified LAX artifact with the source/review receipt and bounded
   integration evidence. Preserve the previous artifact and durable state
   compatibility so rollback does not replay work or discard accepted input.

## Enforcement status

This document and AGENTS.md establish repository policy. They do not themselves
install CI checks, remote branch protection or a production release gate.
Implement and qualify the executable native journey before claiming automated
protection. Keep implementation status and observed evidence explicit.
