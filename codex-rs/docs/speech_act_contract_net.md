# Speech-Act Contract Net Coordination [proposal]

This document extends
[`coordination_control_plane.md`](./coordination_control_plane.md) with the
long-term Losangelex design for scalable team work.

The target is not a pure workflow engine and not pure room chat. The target is
a backend coordination substrate that:

- lets models negotiate and sequence work in natural language over Hollywood
- records only durable commitments as structured state
- wakes the right agent when work actually becomes actionable
- survives restart, resume, idle gaps, and rolling deploys

## Problem

The current Hollywood-based model is useful for awareness, but it breaks down
as a durable coordination system:

- idle peers often stay idle unless a message happens to use the right wake
  shape
- room scrollback is doing too much semantic work
- ownership, dependency, and completion state live partly in prose and partly
  in unrelated runtime mechanisms
- restart and rolling-deploy recovery depend on reconstructing intent from
  messages rather than from durable coordination state

At the same time, a rigid task-board-only design would underuse the models.
Agents are good at:

- decomposing work after inspecting the code
- negotiating patch order in natural language
- revising the plan when reality changes
- deciding which peer is best suited for a slice

The runtime should not replace that reasoning. It should make the resulting
commitments durable and enforceable.

## Design Goals

- Preserve Hollywood as the shared model-visible collaboration surface.
- Move durable coordination truth into app-server and state, not chat
  scrollback.
- Make assignment, blocking, handoff, review, and completion restart-safe.
- Let idle agents be woken by durable work state, not only by message wording.
- Support directed assignments and scalable open-task claiming.
- Keep most of the new machinery out of `codex-core`; core should mostly
  consume pending work plus contextual coordination input.
- Support future backend-scale deployment where many Losangelex sessions may be
  active across several app-server generations.

## Non-Goals

This design should not:

- force all collaboration through rigid forms instead of natural language
- make arbitrary natural-language parsing the source of truth
- turn Losangelex into a general-purpose workflow or BPM engine
- require a permanent manager agent for all multi-agent work
- use Hollywood room membership as the durable source of task ownership

## Core Principle

Use two layers at once:

- `conversation layer`
  Hollywood remains the place where agents reason together in natural
  language.
- `commitment layer`
  Only accepted coordination commitments become durable structured state.

That means an agent can still say:

- "I need to land the protocol shape first."
- "@peer take the TUI once I unblock you."
- "Hold off on `foo.rs` until I finish the migration."
- "Review is ready now."

But the runtime only treats those statements as coordination truth when the
agent also emits a structured act for the commitment.

## Architecture

### Three Planes

The durable design has three planes:

- `collaboration plane`
  Hollywood room messages, presence, natural-language negotiation, and shared
  awareness.
- `coordination plane`
  Durable contracts, bids, awards, dependencies, leases, and completion state
  stored in app-server/state.
- `execution plane`
  Existing Codex thread execution, pending-work wake paths, ownership
  enforcement, and tool calls.

The planes interact, but they should not collapse into one another.

### Dual Write For Commitments

Whenever an agent makes a durable coordination move, Losangelex should do two
things:

1. persist a structured coordination act
2. emit a concise Hollywood summary for model and human awareness

The Hollywood message is for collaboration visibility.

The structured act is the source of truth for:

- wake routing
- task ownership
- dependency tracking
- lease expiry
- completion propagation
- restart and rolling-deploy recovery

## Speech-Act Model

The durable layer should be based on a small, explicit set of coordination
acts. These are not inferred from arbitrary room text by default. They are
emitted by model-visible tools when an agent decides that a commitment is real.

Suggested initial acts:

- `announce`
  Publish intended work without taking ownership.
- `open_task`
  Create a task/contract that may be directed or open for bids.
- `bid`
  Offer to take a task or review.
- `award`
  Assign a task to a specific thread.
- `accept`
  Accept an awarded task and start the lease.
- `decline`
  Reject an award or open invitation.
- `claim_scope`
  Claim file/path/module scope for the awarded work.
- `release_scope`
  Release a previously claimed scope.
- `depends_on`
  Record that a task is blocked by another task or handoff.
- `blocked`
  Mark the task as blocked and provide unblock conditions.
- `review_request`
  Ask another thread to review a slice or result.
- `handoff`
  Transfer ownership or shift the next active step to another thread.
- `done`
  Mark the task complete and optionally unblock dependents.
- `yield`
  Yield or abandon the lease without claiming completion.
- `availability`
  Update runtime-level willingness to take open work.

These acts are intentionally narrow. They capture commitments, not all
discussion.

## Contract Graph

The durable source of truth should be a coordination graph rather than a flat
task list.

Suggested durable entities:

- `coordination_tasks`
  The unit of owned or reviewable work.
- `coordination_acts`
  Append-only record of commitments and transitions.
- `coordination_bids`
  Candidate ownership offers for open work.
- `coordination_dependencies`
  Directed blockers and unblock relationships.
- `coordination_leases`
  Active ownership leases and expiry state.
- `coordination_reviews`
  Review obligations and review completion.

Existing ownership state should remain the source of truth for concrete
file/path claims. The coordination layer should attach to it rather than
duplicate it.

### Task Shape

Each task should carry:

- `task_id`
- `team_id`
- `room`
- `creator_thread_id`
- `owner_thread_id`
- `state`
- `kind`
  such as `implementation`, `review`, `investigation`, `handoff`, or `qa`
- `summary`
- `details`
- `wake_policy`
- `priority`
- `requested_capability`
- `created_at`
- `updated_at`

Suggested states:

- `open`
- `bidding`
- `awarded`
- `accepted`
- `active`
- `blocked`
- `review_pending`
- `handoff_pending`
- `done`
- `yielded`
- `expired`
- `cancelled`

### Lease Rules

Awards should not imply permanent ownership. They should create renewable
leases.

Lease behavior:

- `award` starts a pending lease candidate
- `accept` activates the lease
- heartbeats and progress updates renew the lease
- lease expiry returns the task to `open` or `handoff_pending`
- expiry may preserve prior owner metadata for audit and takeover context

This gives backend-safe recovery when a process dies, a daemon rolls, or a
session disappears.

## Ownership Integration

The coordination layer should not invent a second notion of file ownership.

Instead:

- `award` and `accept` may create required ownership claims
- `claim_scope` should map onto existing thread ownership APIs
- `handoff`, `done`, `yield`, and expiry should release or narrow claims
- conflicts between a task award and an existing ownership claim should block
  activation until resolved

This keeps the coordination graph durable while still using the existing path
claim enforcement machinery.

## Wake Routing

Wake routing should be driven by structured state transitions first and room
chat second.

### Wakeworthy transitions

These transitions should be able to wake an idle thread directly:

- a directed `award`
- acceptance required for a newly awarded task
- a dependency becoming unblocked
- a `review_request` for a specific reviewer
- a `handoff` to a specific owner
- lease expiry on work the current thread created or depends on
- completion of a dependency the current thread is waiting on

### Non-wakeworthy transitions

These should usually remain `annotate` or `queue`:

- presence announcements
- ambient room discussion without a durable act
- repeated progress updates with no new action required
- acknowledgments without assignment or unblock effect

### Relationship To Hollywood Classification

The control-plane design in
[`coordination_control_plane.md`](./coordination_control_plane.md) already
proposes `interrupt|annotate|queue` routing for Hollywood traffic. The durable
contract layer should sit above that:

- free-form Hollywood messages still flow through `interrupt|annotate|queue`
- structured coordination acts may trigger direct durable wake semantics even
  when the paired Hollywood summary is only ambient text

That split is important. Models should be free to discuss a plan in room text
without that discussion alone becoming the wake mechanism.

## Contract-Net Policies

The runtime should support several policy variants so Losangelex can benchmark
and evolve defaults instead of baking in one brittle coordination style.

### `leader_award`

One lead agent decomposes the work, peers bid or are directly assigned, and the
lead awards ownership.

Pros:

- clear accountability
- good for high-context feature work

Costs:

- leader can become a bottleneck
- large-context lead threads can drift

### `first_claim`

Open work is announced, eligible peers claim it, and the first valid claimant
gets the lease.

Pros:

- simple and decentralized
- good for homogeneous peers

Costs:

- can create noisy races
- weaker capability matching

### `auto_match`

The backend proposes or directly awards based on capability, load, room,
ownership overlap, and recent activity.

Pros:

- scalable backend behavior
- efficient when many agents are active

Costs:

- harder to explain and tune
- more risk of surprising assignments

### `hybrid`

Use `leader_award` for directed feature decomposition, `first_claim` or
`auto_match` for broad review/help/QA work, and keep directed handoffs explicit.

This is the recommended default target because it preserves model judgment for
high-context sequencing while still supporting scalable open-work routing.

## Example Flow

Patch-sequencing example:

1. Agent A inspects the code and decides the protocol must land first.
2. Agent A discusses that plan in Hollywood with a concise room message.
3. Agent A opens a task for the protocol slice and claims the relevant scope.
4. Agent A opens a second dependent TUI task for Agent B and records
   `depends_on(protocol_task -> tui_task)`.
5. The TUI task stays blocked and does not wake B yet.
6. Agent A finishes the protocol task and emits `done`.
7. The runtime unblocks the dependent TUI task and wakes B.
8. Agent B accepts, claims UI scope, executes, and eventually requests review.
9. Reviewer C receives a directed `review_request`, completes review, and the
   lead thread is woken only when there is a real result to synthesize.

Natural language still carries the reasoning. The contract graph carries the
commitments.

## Model-Facing Tooling

The model should not have to speak only in RPC payloads. It should keep using
Hollywood naturally. But the runtime does need structured acts.

The right tool surface is a small family of explicit commitment tools, or one
generic coordination-act tool with a self-documenting act enum, that:

- records the structured act
- optionally posts the paired Hollywood summary
- returns any new task ids, lease ids, or ownership conflicts

Whatever tool shape is chosen, the design requirement is:

- discussion stays free-form
- commitments become explicit
- explicit commitments are easy for the model to use correctly

## Runtime Placement

Most of this feature should live outside `codex-core`.

Primary home:

- `codex-state`
  durable graph, migrations, and repo methods
- `codex-app-server`
  policy evaluation, wake routing, lease management, and room/runtime
  integration
- `codex-app-server-protocol`
  typed APIs and notifications for the coordination plane

Core should remain responsible for:

- consuming wake prompts and contextual coordination input
- surfacing model-visible tools
- respecting ownership conflicts and pending work

This keeps the scalable coordination backend where it belongs and avoids
turning core into a scheduler.

## Suggested API Shape

The exact v2 surface can evolve, but it should likely include:

- coordination task create/read/list/update APIs
- coordination act creation APIs
- coordination runtime status listing APIs
- coordination team membership/runtime APIs
- coordination notifications for task state changes and directed work

The API should distinguish:

- transport visibility (`thread/hollywood/*`)
- runtime availability (`thread/coordination/runtime/*`)
- durable coordination truth (task/act/lease/dependency APIs)

Those should not be collapsed into the same resource.

## Evaluation Matrix

This architecture should be validated with repeatable scenarios rather than
intuition alone.

### Scenarios

- directed review request to one idle peer
- broad "someone take QA" request
- sequential backend-then-UI patch chain
- overlapping file ownership claims
- owner crash while holding a lease
- rolling deploy during active team work
- stale room chatter with unrelated ambient traffic
- leader disappearance with open awarded tasks

### Metrics

- time from task creation to first claim or award
- time from dependency unblock to resumed work
- percentage of eligible idle peers left idle while actionable work exists
- duplicate work rate
- ownership conflict rate
- review turnaround time
- task recovery success after restart or rolling deploy
- token overhead for coordination
- number of user interventions required per completed multi-agent task

### Harness

The comparison harness should be built around app-server integration tests and
synthetic Hollywood rooms, not prompt-only evaluation.

Compare at least:

- current room-message coordination
- `leader_award`
- `first_claim`
- `auto_match`
- `hybrid`

The goal is to pick policy defaults from measured behavior, not from taste.

## Rollout

Phase 1:

- land the durable coordination graph schema and repo/runtime helpers
- expose read/list/debug views before automatic wake behavior

Phase 2:

- add explicit coordination act tools and paired Hollywood summaries
- keep the first execution path human/model-driven rather than auto-matched

Phase 3:

- route directed awards, review requests, dependency unblocks, and handoffs
  through durable wake behavior
- integrate with existing ownership enforcement

Phase 4:

- benchmark `leader_award`, `first_claim`, `auto_match`, and `hybrid`
- choose defaults based on recovery, latency, and duplicate-work metrics

Phase 5:

- harden for backend-scale deployment:
  - lease recovery across app-server generations
  - rolling-deploy-safe handoff
  - durable observability and audit trails

## Recommendation

Losangelex should build toward a speech-act contract net:

- Hollywood remains the place where models think together
- the coordination graph becomes the durable source of truth
- wake semantics follow assignment and dependency state, not only room wording
- ownership stays enforced through the existing path-claim system
- scalable backend behavior comes from leases, directed wake rules, and policy
  benchmarking rather than from a single manager agent

That architecture preserves model strengths while giving Losangelex the durable
backend coordination layer it needs to scale.
