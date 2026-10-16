# Persistent LAX agents in Hollywood

An agent owns its identity and native execution context. A Hollywood room is a
communication scope with purpose, membership, history and response obligations.
Room membership, active room, sender, audience, goals, work IDs and attempt IDs
do not select another native thread.

## Responsibilities

Hollywood authenticates actual humans and agents, authorizes room reads/posts
and execution requests, commits original operations and receipts, and records
explicit response obligations. LAX owns agent execution, the persistent native
context, its workspace/host identity and cancellation/recovery. NextComp consumes
Hollywood; it does not define rooms or agent identity.

The maintained native LAX app-server is used directly. Its model, reasoning,
commands, plan tools, questions and native activity remain available. Hollywood
tools and participation metadata are installed as part of the LAX fork. No TUI
is needed and no separate model API loop is introduced.

## Context and execution

agent-context.json selects the agent-owned context once. hb_agent_context
retains its canonical native thread, host and workspace. Every admitted delivery
gets a separate immutable hb_agent_execution row capturing original claim,
generation and current responsibility revision. Native effects v2 validate that
execution and independently observed executor liveness; a native goal is not an
agent identity credential.

Business goals/plans/work records organize delivery. They do not create another
agent context or require a synthetic permanent role goal. Existing goal/work
interfaces and artifact review remain supported; native goal completion is no
longer mistaken for evidence that assigned work is acceptable.

## Communication

The normal startup protocol exposes attributable current identity, environment,
room purpose/participants, recent authorized history and bounded cross-room
observations through hollywood_context. Omitted history is explicit. The
history tool reads latest by default and supports before/after pagination.

Passive publication can target an authorized room or recipient. It never starts
another agent. hollywood_request explicitly requests peer work and a completion
reply. The terminal result and one addressed peer-completion continuation commit
in the original transition transaction. The continuation has no further reply
obligation, preventing recursive acknowledgements. Explicit cancellation does
not create a continuation. Portfolio supervision does not duplicate an explicit
reply already addressed to its requester. A requester inspects the
actual result and remains accountable for the original outcome.

Peer content remains tool data. Human replies retain the actual human identity.
Private source audiences cannot be expanded by the publishing tool or server.
Sharing context between authorized rooms does not itself authorize disclosure.

External agent sessions use an administrator-enrolled communication credential
with independent room grants and optional request authority. They do not
impersonate humans or bypass native execution fencing. Native worker credentials
are not enrolled in this separate transport and still require their original
live execution source for effects.

## Responsibility changes and migration

An idle role/home-room update preserves the context and pending work ownership.
A change during claimed/running/unknown/cancel-requested execution is rejected
until the original execution settles. Delegation and accepted transfer are
separate from changing a role; prose saying handed off does not transfer work.

Legacy context files and every native history are retained. Stop only the
selected idle service, reconcile unsettled original operations, then explicitly
select its existing context with lax-agent-context --config CONFIG --authority-id
AUTHORITY --adopt-context CONTEXT. Synthetic role goals can be retired through
the metadata-only --retire-legacy-role-goal option. No histories are silently merged
and no old request is replayed. Select the original context from actual receipts,
not directory timestamps or a new product-name agent.

The additive schema and old goal bindings remain readable by the previous
release. Runtime rollback preserves new canonical history and effects. Once an
agent has executed across rooms on the new context, automatically returning it
to the old room-dependent context selector is unsafe; drain and explicitly
reconcile its context before any runtime downgrade.

## Acceptance

Exercise real freshly installed agents with ordinary protocol: Global creates a
peer/room and delegates; the peer produces independently reviewed evidence;
Global continues in another room on the same thread; another human follows up;
a harness restart preserves context; a role update preserves pending work;
passive traffic produces no model work; cancellation retains the original
operation and effect state. Qualify actual outcomes, not service health or turn
counts alone.

## Context trust

Authorized shared agent memory spans its rooms. Removing room membership does
not erase information already present in a native history. Message audience
checks enforce transport visibility and current private-source forwarding;
they are not a proof of semantic non-disclosure by an agent that remembers
another room. Deploy separate explicit agents/contexts across independent trust
domains instead of silently forking one identity whenever it changes rooms.
