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
inference is definitively interrupted. A stable restart token prevents unchanged
polling from chaining completed inferences. Unknown native turns remain held;
cancelled Work is not resumed. An intentionally stopped service stays stopped
until explicitly activated. This does not establish enterprise boot policy or
automatic recovery from every host/network failure.
