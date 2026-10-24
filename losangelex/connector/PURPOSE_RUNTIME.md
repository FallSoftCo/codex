# Purpose-native LAX runtime

Hollywood owns rooms, authenticated communication and durable work references.
One LAX agent has three persistent native histories: reader, writer and responder.
A room does not select a history or execution account. Only the responder emits
intentional messages; writer execution activity is a separate attributed stream.

lax-install-agent --spec FILE is a root installation operation. It validates
canonical Hollywood enrollment, creates a Unix account, verifies the complete
native package and model account under that identity, and installs three systemd
units under one aggregate resource slice. --activate starts only that recorded
installation. An existing activation intent is observed rather than replayed.
The installer does not enable historical sessions, infer work completion, or run
a model. The native runtime wakes from newly admitted canonical material.

Global's lax_provision_worker uses this same installer for a new peer. Enrollment
credentials and purpose tokens are stored in protected files, never tool output.
Each peer has independent native histories, state and workspace. The workspace is
an explicit host-local route; another agent or host must not assume it is shared.
Approved model account identity is checked without overwriting independently
refreshed per-context authentication.

A writer admits original work through Hollywood's shared native claim transaction.
An installed guardian captures its actual resident app-server incarnation through
the existing executor API. The enrolled host controller independently checks its
systemd invocation, UID, executable, PID/start time and cgroup. A turn starts only
after that check and an inference permit. Work claims are durable; inference
permits count active inference, not room memberships or resident idle processes.

The runtime protocol is lax-purpose-runtime/v3. An immutable context-begin
receipt binds a writer turn to its original work, claim, generation and actual
executor. Native mutations use hollywood-native-source/v3, validated inside the
same database transaction as the domain change. There is no synthetic native
goal or legacy agent-execution binding. Reader/responder credentials cannot
borrow writer mutation authority. The shared native handlers retain original
effect journals, command receipt reconciliation and actor attribution.

Old v1 scopes remain readable for delayed execution logs. New v2 execution scopes
carry their executor identity. Neither a log nor a closed model turn proves work
completed or an external effect absent. Unknown delivery and process outcomes
remain held for original-state reconciliation; service restarts do not authorize
replaying external effects.

## Qualification boundary

The 2026-10-19 private authority preserves the original three histories and uses
a newly installed matching Unix identity. PostgreSQL tests qualify claims,
turn scopes, writer mutation authority and invalid-source rejection; their
frozen process facts are not actual execution evidence. The live Global-created
peer/operator-tool journey separately qualifies the installed native path.

This stage does not switch production NextComp profiles, publish a phone update,
qualify multi-host shared editing, or migrate historical sessions. Native
collaboration bridge capture and later completed-report reconciliation still
need purpose-aware integration. The ordinary enterprise bootstrap must adopt
this installation path before a default cutover is claimed.


## Native collaboration and causal peer continuations

The purpose-native writer uses the existing protected collaboration bridge. Its
source is the immutable accepted v3 execution scope, including the actual
executor, context, role, host and native turn. The bridge still verifies the
kernel peer UID/PID/start, native image, installed guardian and independently
observed incarnation. An authenticated controller relay is distinct from the
writer credential; neither can substitute an arbitrary model-selected scope.
The server derives a purpose binding from that original receipt. It does not
create a legacy single-context row.

Installed private workspaces are registered as explicit physical resources with
per-agent access and a selected default. Context workspace identity remains
separate from the physical root namespace. Future purpose-peer provisioning
inherits the protected channel and enrolls its actual workspace through those
same resource APIs. Native apply_patch retains preflight/begin/settle receipts;
a stale, replayed or uncertain receipt never becomes a new one-use grant.
coordination_act and collaborative_edit_plan are exposed only with a configured
channel. The writer explicitly enables the native update_plan configuration.

A request back from an actual delegated peer, sourced to that original
delegation, carries peerContinuation/parentWorkId. The reader interprets it on
the original work, even when the authorized review room differs from the
original request room. It cannot create competing work from that causal input.
An older, unadmitted misclassification can be retained as superseded only while
its original delivery remains pending at generation zero with no execution or
child delegation. Original operations and interpretation evidence are retained.

The writer can supply provide_response_material for a reader-interpreted input
on its current work. This makes the existing required response ready for the
responder without declaring the parent work complete. It allows a peer blocked
on a prerequisite answer to progress while the parent still awaits that peer.
It does not publish directly, steer either writer or create another assignment.

Qualification boundaries: the r22 PostgreSQL checks use frozen native facts and
roll back every synthetic change. The private two-agent model continuation is
separate evidence. Neither establishes production/phone replacement readiness,
multi-host editing, compaction, Stop, or complete enterprise installation.


## Native rejection recovery and questions

The protected edit-status metadata port reports original current-work receipts
to the independently verified writer guardian. It uses the same Unix channel,
not another coordinator. The agent can distinguish a confirmed preflight HTTP
400/403/409 rejection from pending/unknown dispatch or a begun mutation. A
proposed permit ID in a rejected preflight is not an accepted permit. Missing
journal entries alone establish no outcome. Inspection is read-only and bounded
with a cursor; it never grants mutation or authorizes automatic replay.

The currently deployed native implementation checks required patch ports before
bridge dispatch and filesystem mutation. Its exact unavailable-preflight-port
diagnostic therefore has no original permit to reconcile. The published native
edit contract explains that specific case, separately from post-dispatch
uncertainty. Native Rust's generic held wording remains a diagnostic debt for
the next binary release; the package supplies the source-grounded contract and
actual protected receipts rather than interpreting all holds as unknown effects.

Nonblocking questions do not block otherwise authorized physical editing.
Pending execution approvals and unresolved native controls still do. A writer
can withdraw its own unanswered nonblocking question when verified facts make it
obsolete. The original question and attributed reason remain; no human response
or approval is invented. Work completion continues to retain unresolved human
questions as prerequisites.


## Inference attempts are not material-set identities

A pending set can recur (A, A+B, then A) after another response is published.
Its hash must not be reused as the identity of a capacity reservation. New
inference attempts use fresh durable operation IDs; an already queued attempt
keeps its own fair-queue ticket and selected material IDs. Other new inputs stay
durable for the subsequent turn.

The original accepted reservation receipt is immutable. Before native start the
runtime reads its currentPermit projection and requires a reserved, unbound
permit. An old reserved receipt cannot make a released permit usable again.
After a prior turn finishes during a pending read, the scheduler takes a fresh
pending snapshot before admitting another turn.

Recovery retains exact native identities. The observed interrupted responder
turn had never been admitted and referenced an older, already released permit.
Its terminal metadata is recorded as not_admitted/capacityReleased=false; the
old permit and old native turn stay unchanged. No unknown journal is deleted.
The actual private runtime observed that exact native turn and recovered its
existing queued answer in the original history.

This qualification does not cover every disconnected/partially submitted
reservation or native-start crash boundary. Those remain explicit daily-operation
gates before production/phone migration; original uncertainty must not be
converted into an automatic replacement turn.

## Scoped reader observations (r31)

Readers have bounded canonical room discovery/history and exact event retrieval. Ordinary room traffic becomes optional attributed observation material, never an addressed execution delivery or required acknowledgement. Fully read relevant observations may update an existing responsibility without changing its objective or steering a running writer. Hollywood owns cursors and current grants; normal inference admission applies even to read-only observation.

Reader hollywood_rooms/hollywood_read_room use the bounded purpose read route; writer tools retain their shared native handlers. Dispatch follows the purpose's declarations rather than a global name collision. Actual HTTP/PG fixture qualification and the live r31 model journey are separate evidence. Production replacement, arbitrary new-work autonomy, full fork work/report parity and general semantic stability remain unqualified.

Purpose services use systemd KillMode=mixed: SIGTERM reaches the supervisor
first, allowing original native interrupt/end receipts to settle while its
app-server child is alive. The observer accepts only child-group cleanup modes
(control-group or mixed), pins the actual mode through the protected unit
definition and observes real PID/cgroup/incarnation facts. A rejected resident
attestation occurs before inference reservation and is reported as held, inactive.

An explicit service restart can continue eligible material after the original
inference is definitively interrupted. The writer first verifies that exact
native terminal through its existing RPC history. It then uses the existing
context operation channel's resume_interrupted action with only the original
native turn. Hollywood derives the released inference permit from the original
context-end receipt and checks the same agent, context, thread and host. Only
still unfinished, nonwaiting, noncancelled material whose last execution matches
that interrupted turn can receive one continuation revision. The original
operation receipt deduplicates recovery; a different operation cannot advance
already eligible material again. A local restart fingerprint alone is
insufficient to make consumed canonical work eligible.

The paired bind contract advertises interruptedContinuation=1. Startup never
repeats the original inference or infers work completion. Normal placement,
capacity, ownership and original-effect checks still govern the next inference.
Unknown, running, failed or completed originals do not trigger this recovery.
A stable restart token prevents unchanged polling from chaining completed
inferences. An intentionally stopped service stays stopped until explicitly
activated. This does not establish enterprise boot policy or automatic recovery
from every host/network failure.


## Native tool-owned inference lifecycle

Purpose profiles opt in to native `inferenceCompletion: "hostTool"` on start
and every cold resume. They verify the native capability and effective response.
Provider tool selection retains the supported automatic behavior. The native
host completion contract is independent of provider request-format controls.
Nonfinal provider continuations remain ordinary sampling; a final response
without authenticated settlement fails this native inference. Successful scoped host settlement ends inference only
after admitted tools drain. A plain/empty final without tools fails that native
inference; it does not finish Work, publish a reply or automatically start again.

Native failure remains visible and held for explicit diagnosis.
A corrected native image advertises host_tool_inference_auto_transport/v1.
Explicit --reconcile-only --acknowledge-provider-rejection purpose:native-turn
verifies an original unsupported-tool-choice400 response, native items, known
effect journals and canonical failed permit/end before acknowledging that
specific rejection. Original failed receipts remain unchanged; normal startup
only reads the accepted acknowledgement. No model or source input is replayed.
 Accepted Work
and original receipts remain durable. Known pre-model failures retain their
separate narrow recovery. An owner may explicitly recover the latest confirmed
completed-but-unsettled writer inference with `--reconcile-only
--resume-unsettled-native-turn <original-id>`. This verifies the exact original
thread/turn, terminal native actions, reconciled journals, released canonical
permit and still-current unfinished Work before advancing the existing Work
continuation revision once. It starts no model, submits no input and replays no
effect. Unknown outcomes, waiting/cancelled/completed Work and other active
inferences remain fenced. Repeated unchanged polling never invokes this action.

## Shared bridge maintenance

A purpose installation pins its own files and the enrolled shared bridge dependencies.
A drained bridge upgrade can legitimately change those shared pins; this does not
authorize changing an agent's config, units, identity, environment or workspace.

Retain the original accepted `collaboration_upgrade` receipt. With all affected
placements paused and purpose services stopped, activate only the accepted bridge.
Use the administrator CLI `lax-reconcile-agent-dependencies` with the authority,
agent, a new operation UUID, exact old readiness SHA256 and the original protected
`*-accepted.json` bridge receipt. It checks the live root socket and canonical
enrollment, accepts only the reviewed bridge-file/revision delta, retains the
exact prior seal and publishes an attributable reconciliation receipt. No model
or service starts, permission changes or task replay occur in that operation.

Then perform the reviewed purpose software upgrade and matching host/API rollout.
The ordinary runtime `require_sealed` and live-peer checks remain mandatory.
Restore only the prior placement choices authorized for this maintenance scope;
restoring a placement does not start a deliberately stopped service.

If a reply is lost, inspect `--status` for the same operation and its original
readiness hashes before any further write. An unsettled reconciliation is not
permission to repeat it or discard its journal. For rollback, use the accepted
reverse bridge transition and the same checked dependency reconciliation; do not
blindly restore an obsolete seal or revert business/native history.

## Explicit context policy for newly provisioned peers

Native peer provisioning inherits the validated explicit context settings from
the provisioning agent: rebuild enablement, automatic refill policy and native
action-retention version. Omitted settings remain omitted. A retained-native
Writer requires both rebuild enablement and canonical refill. Incomplete policy
is refused before writing the provisioning journal or submitting configuration.

This propagation applies to a new peer's original installation intent. It does
not upgrade existing peers, rewrite old provisioning intents, resume stopped
services, or establish all-purpose native retention. Whole retained execution
evidence remains a Writer capability in the current qualified candidate.

## Original bootstrap binding recovery

A new context is ready after its canonical bind and healthy runtime status,
not merely after context.json contains a native thread ID. A lost bootstrap
HTTP callback keeps the original binding journal. On restart the runtime first
reads that exact operation receipt. A paired Hollywood backend reports an
absent own-purpose receipt as HTTP404 / CONTEXT_OPERATION_NOT_FOUND; wrong-purpose
and authorization failures remain HTTP403.

Only action=bind with nativeTurn=bootstrap and the identical original request
may recover by resubmitting that same idempotent metadata transaction. The
journal retains the recovery observation and accepted receipt. It starts no
replacement native thread, inference, Work or tool execution. Unknown non-bind
operations, external effects and permission failures do not use this recovery.


## Retained native tool declarations

Native Writer retention distinguishes the core-owned prefix from canonical
task data. The prefix includes the native tool declarations needed after a
context reset. An atomic AdditionalTools declaration can use the existing
256 KiB aggregate refill budget; ordinary prefix items and retained task items
remain limited to 32 KiB each. The combined decoded budget, item count and
wire bounds remain unchanged. Host fragments cannot supply a prefix or use
this native declaration allowance.

Recorded-prefix reads still verify the original thread/context, complete
ordered groups, exact digests and non-client authorship. Active and idle
replacement apply the same item rules. A size refusal is reported separately
from incomplete or changed provenance. The R320 candidate was prompted by an
actual managed declaration that exceeded the data-item bound; the original
failure and subsequent runtime recovery qualification are retained separately.


## Current resources and installation integrity

A v2 installation seal pins installed code, configuration, identity and private
workspace identity. Its full resource catalog is a historical readiness
observation. Current grants and catalog revisions remain Hollywood authority;
they are verified together with actual Unix access on every readiness check.
Adding an authorized shared workspace does not change installed code or invalidate
the agent. It does not automatically alter the original seal file.

Resource observations and their revisions are excluded only from v2 installation
comparison, including the existing explicit bridge-dependency transition. Native
operation admission still verifies its current work/resource/source bindings.
Private workspace incarnation, configuration and installed dependency hashes
remain pinned. The exact v1 seal comparison remains unchanged.


## Original idle checkpoint acknowledgement recovery

Native core synchronizes its original replacement checkpoint before requesting
Hollywood acknowledgement. If the first SDK callback fails before Hollywood
records it, cold recovery verifies the exact original file identity, prefix,
checkpoint, ordered source groups, digests and scope. The SDK uses the same
typed prefix/data limits as native core.

After that proof, an authenticated HTTP404 / CONTEXT_OPERATION_NOT_FOUND for the
original installed operation may complete only its missing metadata transaction,
under the original operation ID, snapshot and native receipt. Hollywood still
rechecks the current binding, pending rebuild, selection and source revisions.
Existing receipts are read and compared. Other errors remain held. An uncertain
previous metadata submission uses its existing operation journal and is not
blindly submitted again. No native replacement, inference, Work or command is
replayed; original native journals remain unchanged.

For a drained software upgrade, keep owned purpose services stopped during
publication and integrity checks. Restore only the authorized prior placement
while those services are stopped, then explicitly start that same owned set.
Current Hollywood context actions require an enabled placement, including
the pending/read actions and first checkpoint-metadata acknowledgement used by
startup. The own-operation receipt GET remains available while paused. A paused
placement is therefore not a complete healthy-startup qualification boundary. Verify fresh statuses from the new service
incarnations and the original context bindings; stale status files or a
successful systemctl start are insufficient. Do not use installation activation
as a restart command or restart deliberately stopped agents.


## Native shared human decisions

hollywood_ask may declare responseRoomId when teammates need to authenticate a
human decision. The paired backend adds a mandatory audience notice to the
questions and publishes the human's single answer in that room. The original
agent receives its existing same-context continuation from that same event.
Teammates read the native room event rather than the private attention receipt.

The asker and human need current target-room read/post rights. Omit the field
for a private answer. Publication never grants access to private controls,
another agent's context, Work or execution. The new top-level versioned API
field is rejected by unaware backends rather than silently ignored. Ordinary
private questions retain their previous payload and result shape.

The current NextComp question renderer displays the complete question text in
its scrollable dialog, so the enforced audience notice uses that existing
contract. This is source inspection, not physical-phone proof. The separate
known client gate for nonblocking questions after their input delivery completes
still needs qualification; it must follow authoritative canRespond.
