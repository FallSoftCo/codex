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

Finite native cancellation and original-turn recovery now have integration
evidence; the ongoing-role qualification below supersedes the legacy Global
coordination-goal lifecycle. Broader crash/fault cases, plan editing/retries,
second-host artifact retrieval, physical Android voice/push and production
migration remain release gates. No old session or schedule is resumed.


## Cancellation and recovery candidate

Cancellation intent is separate from observed execution state. Hollywood retains
that intent even while execution is unknown; only an attributable stop
acknowledgement cancels the associated work. LAX interrupts the captured turn and
conditionally pauses its matching unfinished native goal, preserving instance
identity and accounting. A completed native objective is retained as a fact;
neither stop nor local completion means external effects were undone.

Recovery reads the original delivery/claim/generation/host, native binding,
thread/turn and persisted tool outcomes. It enables external admission before
native reads and never starts or resumes a model turn. Two actual stopped native
contexts (Global and worker) reconciled their original interrupted turns to failed
execution without another model turn. Unresolved tool effects remain held.

Resident native metadata reads use a persisted bounded backoff. Three unchanged
reads park recovery by default until an authoritative delivery change or explicit
`--reconcile`; a resident restart does not reset that budget. Ordinary HTTP queue
observation remains deterministic and cannot admit unknown execution again.

Administrative discovery exposes current room membership and role revisions.
Known rejection of one atomic command remains rejected and can be corrected after
a fresh authorized read. Unconfirmed multi-step effects remain fenced. Shared
errors and durable journals live in canonical modules so console and `python -m`
entrypoints classify the same exception identities.

Source-bound human follow-ups retain an unambiguous goal reference. Multiple goals
from one source do not manufacture a reference. Bounded work attaches only its
original matching native instance; old coordination contexts require explicit
reconciliation before conversion to ongoing responsibility.


The installed dev6 native cancellation probe now passes: one Global created and
provisioned a worker, recovered a deliberate membership 409 through authoritative
inspection, delegated a real helper/question, then handled a source-bound human
stop in its existing context. The helper stopped before its deferred write;
work/execution and business goal closed, native objectives paused and the stale
human answer was denied. Three explicit provider turns ran, with no model polling.
Owned services were stopped/disabled afterwards. The earlier namespace-PID guard
failure and administrative classification failures remain in protected evidence;
none of their original requests was resubmitted.

Goal cancellation is a durable Hollywood operation, not a request for Global to
poll workers. It can return cancel_requested while the service propagates stop
and reconciles original acknowledgements. CLI/callback errors now share one
canonical type; a known 409 cannot become an unknown effect merely because the
connector was launched with `python -m`.


## Ongoing roles and bounded work

Hollywood role policy now declares nativeGoalScope: role or work. Bootstrap
Global has role scope; other agents default to work, and an administrator may
explicitly give an ongoing primary responsibility to another agent. This field
does not grant communication or operating-system permissions.

A role context owns one native responsibility goal, independently of any business
goal. Its objective comes from authenticated role metadata, without copying a
human task or peer message into privileged role context. Hollywood records the
native goal instance, role revision, context, host, workspace and audience.
Subsequent deliveries must match; silent instance replacement, role changes,
host migration and workspace substitution require explicit reconciliation.
Different room/private audiences retain separate native contexts.

The opt-in native goal_external_lifecycle feature exposes get_goal but excludes
model create_goal/update_goal. Trusted metadata APIs keep their fenced control;
native accounting and structured turn plans remain available. The separate
goal_external_admission feature continues to prevent idle model turns. Bounded
work retains get_goal/update_goal and its existing completion/evidence contract.

Accepting or cancelling a business goal does not alter the ongoing responsibility.
Stopping/failing one delivery also does not stop the role or imply effects were
undone. Its assigned bounded worker execution still receives actual cancellation
and its unfinished native goal is paused after acknowledgement. Stopped native
role objectives refuse further execution until an explicit operator decision;
a general enterprise role pause/resume interface is a remaining release gate.
A role/definition change is deliberately held rather than silently overwriting
the existing objective.

This is an additive candidate protocol, not a production migration. Legacy
coordination bindings remain readable and retain their original receipt digests.
Converting existing live contexts needs a reviewed migration with preserved
native identity/accounting and explicit operator intent.


Role protocol upgrade and rollback: schema 7 moves role/binding metadata into a
separate table, retaining the original ten-column binding row shape and every
recorded digest. Claims and automatic review dispatch for role-scoped actors
require the native-role-goals/v1 connector capability. A missing capability
rejects admission without consuming work/review policy; original receipts remain
readable through their authenticated read routes.

An older server can read legacy binding records, but cannot execute new role
semantics safely. Rollback therefore requires draining/stopping role writers and
disabling their placements before switching the authority runtime. Preserve the
database and new history; do not restore an old dump over accepted new work or
start an old coordinator against a role context. Use the coupled current package
to reconcile original receipts. Production migration remains held.


## Qualification of ongoing responsibility

A fresh installed enterprise completed six actual native provider turns: Global
provisioned one separate worker UID and two business goals, delegated an exact
artifact, performed one explicitly budgeted material review and independently
verified/accepted that work and goal, assigned the second goal, cancelled its
running helper/pending human question, then answered a third human request with
a structured native plan. Four Global turns retained the same native context
and role goal; the worker's two assignments used distinct bounded contexts.
The role remained active, accepted work stayed accepted, the cancelled work goal
paused, the helper stopped before its deferred write and a stale answer was
denied. This is one-host evidence, not general autonomous enterprise completion.

The actual native protocol fixture separately verifies role get-only versus
bounded work get/update tools, stable goal IDs, accounting, cold resume and no
automatic continuation. PostgreSQL/HTTP qualification covers role revision,
instance/workspace substitution, legacy connector rejection, preserved receipts,
and changed-role admission/review holds.

After schema/transport changes, the installed dev9 stack read the original six
deliveries and all three native goal instances/accounting without another model
turn. Its authenticated cold connector found no pending work. No agent service
was resumed. Qualification services were stopped; production and physical phone
were unchanged. The first empty-plan acceptance scenario and an overly strict
metadata-notification verifier failed and remain recorded; their original native
requests were not replayed. These checks do not qualify native push/voice or
production migration.
