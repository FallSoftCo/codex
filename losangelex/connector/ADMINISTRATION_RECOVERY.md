# Administrative child receipts and provisioning inspection

An administrative native callback is a parent workflow. Its ordered HTTP steps
are journaled before submission, scoped to the captured authority, agent, host,
request, delivery claim/generation and native callback. Child operation IDs append
an explicit stage to the original callback operation. Enrollment bodies are never
copied into generic effect journals; only their exact wire digests are retained.

While the original callback is live, a lost child reply can be resolved by an
authenticated original administrative command read. LAX checks issuer, authority,
operation, method, route and digest before continuing the remaining stages. It
does not resend that child or restart the parent workflow. A completed local
parent journal remains recoverable through the existing original-tool mechanism.

Linux worker setup records root-protected intent and original completion evidence:
spec digest, configuration digest, service-definition digest and stable Linux
identity. The spec is pinned to actual machine identity. The separate command

    python -m lax_connector.linux_worker --spec <protected-spec> --inspect

requires verified root administration. It checks original evidence, account/home,
current configuration and the administrator-owned service definition, then reports
original acceptance separately from current ActiveState, UnitFileState and
MainPID. It never creates directories, copies credentials, enables or restarts a
service. The provisioner and inspector share configuration/service constructors.

If the original setup process settles without a usable returned result, the live
callback invokes only this inspector. A deliberately stopped worker remains
stopped. A missing/incomplete receipt, changed specification/host/configuration or
wrong privilege remains rejected for recovery; matching mutable state is not
substituted for acceptance evidence.

Limits: this does not automatically complete a halfway workflow after its native
callback/process ended, infer rejection from a missing receipt, repair arbitrary
partial Linux effects, reconcile external shell/MCP effects or transfer ownership
across hosts. Such state stays partial/unknown until explicitly reconciled.
Old provisioning receipts without the new evidence are not silently backfilled.
Current model credential copying is unchanged; runtime/tool credential separation
remains an enterprise release gate.

## SDK250: original HOME attachment preparation, not unknown-write replay

An authenticated command inspection can positively report HTTP503 with structured
`error=ORIGINAL_HOME_ATTACHMENT_NOT_DISPATCHED` and strict `mayApply=false`.
This is the existing HOME preparing/prepared metadata phase, before its durable
dispatch-intent CAS; it is not absence of a receipt or an unknown native action.
Only the original room-origin factory enrollment step may then re-enter that
HOME's existing idempotent preparation with the same payload and operation key.

The client verifies the retained actor/thread workflow, configured home node,
exact original accepted allocate/GET prefix, room/coordinator/desired identity,
step position and wire digest. Generic administrative tools, other hosts,
changed credentials/wires, untyped error text, 404s and dispatch/reply-unknown
outcomes remain held. One inspection permits at most one continuation request;
a lost continuation reply requires another original command inspection. No new
operation or accepted receipt is manufactured. Original per-step facts and
bounded structured error observations survive acceptance. Credentials/error-body
text are not copied into these observations.

Automatic setup also reads the existing parent placement on the existing catalog
edge. A paused, revoked, mismatched or unreadable enrollment defers before factory
allocation/enrollment; six pending rooms share one paused-placement read. Eligible
queued work rechecks placement before setup, including after diagnostic I/O. An
enable/revision change can continue the same original safe workflow without a
new timer, model wake or permission flag. This metadata check is not a distributed
lock: the server's actual authorization and original effect receipts still rule.
Existing native/session/user-stop and platform owner-admission fences are intact.

An earlier controller `reported` diagnostic is not acceptance of a still-sending
enrollment. A stable canonical identity/origin/member/coordinator change can
resume ONLY that same bound, unconfirmed step-2 workflow with its original pending
pointer and credential, before any spec/platform dispatch. Slot revision may stay
blocked while HOME attachment changes these canonical facts. Timestamps and
diagnostic freshness are not recovery edges. Completed/rejected workflows,
existing specs and unknown native operations do not qualify. Prior diagnostic
observations are archived, not erased or converted into accepted effects.

Fresh NEW child creation now receives explicit initial permissions from reviewed
normalized Linux/Windows/macOS host policy (or an explicit matching accepted parent
configuration). Missing defaults fail closed; a current explicit parent restriction
is never widened. Warm parent/native settings and byte-exact tool declarations are
not rewritten. This prevents invalid fresh Mac children when the warm parent's
creation-only fields are absent.

### Source-bound failed PRELAUNCH configuration successor

`room_initial_configuration.py` recognizes ONLY the reviewed Mac r03 validator
source SHA256 `aeef4b5170312bf1e1f95a623664249c89f43261080db9f229c30565ce9c9f8b`.
Its exact `Fresh declared initial room configuration required` Hold occurs through
`verify_input` BEFORE component lock/materialization/native-intent/thread start.
Its retained BLOCKED host result, exact original spec/dispatch binding and all
eight accepted HTTP wire/result receipts are required, including the old blocked
report's reconstructed wire. The old missing-permissions config must reproduce
that SAME guard. A reason string or absent files alone is NOT sufficient evidence.
Any existing claim/child home/platform/native intent or accepted/context evidence
blocks initial selection; unknown results never qualify.

The SAME original workflow can then record ONE explicit immutable successor spec
and source-bound proof `initial-configuration-successor.json`. Only new-child
creation permissions and independently approved current parent-incarnation/policy
evidence change. Model/effort, tools, identity/origin, credential, paths, native
server and original operation remain pinned. Full current protected host policy,
Mac validator and guides are revalidated; a dead old parent PID is NOT copied or
treated as present. No parent/native user restriction is rewritten.

The old completed workflow/spec/blocked dispatch/host result/steps remain byte-exact.
A distinct `configuration-recovery-<original-id>.json` journals the successor stage
under the SAME actor/thread/operation, and the pending pointer identifies this
journal rather than treating the old completed record as no outstanding work.
Original accepted steps0..4 are read by reference, never resent/copied as new ACKs;
fresh steps5..7 have their own successor directory. A new deterministic
`<original-operation>:initial-config:<successor-sha>:report` metadata stage reports
the actual new outcome without changing/reusing the accepted old `:report` wire.
This is not a new child/native identity or replay of a completed business action.

Catalog recovery recognizes only this positively eligible failed-prelaunch case;
other completed workflows remain cached. `hollywood_admin_reconcile` on the SAME
original operation can inspect/continue the same successor journal. Unknown native
dispatch/lost replies retain intent and are NEVER started again. A completed
unknown successor remains held; there is no repeated correction loop. A later
parent/policy/receipt drift holds for owner review, not spec rewriting. Maintained
owner selection/review of SDK250 supplies this bounded repair, not a new service,
permission flag, model wake or user approval system.

Qualification stages (none establishes affected-host/native/model readiness):

* `tests/test_room_initialization_continuation.py`: real loopback HTTP/private
  journals; synthetic HOME phases and parent facts; scope/wire/unknown/re-pause
  rejection and narrow reported-observation recovery.
* `tests/integration_initialization_continuation.py`: reuses the reviewed existing
  API HOME fixture via `SDK250_HOME_FIXTURE`; isolated two PostgreSQL stores, two
  authenticated loopback NATS nodes and actual HTTP/prepare/dispatch CAS. Interrupted
  prepare, lost attach ACK, blocked-revision canonical change and real placement
  pause/enable use the same original workflows/credentials. Native adapter/host
  policy are synthetic. `ROOM_HOME_NATS_QA/database.json` must name ONLY disposable
  owned databases; this fixture creates a second database and must never use live
  configuration. Retire only its exact owned broker/container/volume after closure.
* `tests/integration_initial_permissions.py`: full common factory to actual Mac
  policy normalization, validator, private-file/IPC and platform-bootstrap boundary.
  Only Darwin process/NSS and native RPC facts are synthetic on CPU. Omitted warm
  creation overrides succeed for NEW child; old invalid child is rejected before
  native; parent/auth bytes and restrictions survive. `SDK250_MAC_QA` must be a
  short owner-private disk directory (UDS path limit); `SDK250_MAC_RESULT` names the
  owned qualification result. No real Darwin native/model claim.
* `tests/integration_prelaunch_configuration.py`: actual common factory/unchanged
  Mac guard first produces a COMPLETED blocked workflow/revision3 with the omitted
  SDK249 creation-field shape. A maintained parent-incarnation change is modeled
  through independently pinned current policy. The same original operation then
  initializes once via the explicit successor, preserving all13 original proof
  files. Lost successor report ACK resolves by original receipt GET; a separate
  lost native thread/start reply remains unknown without second start. Unknown
  intents, existing child state, accepted-wire drift and explicit restrictions
  are rejected. Only catalog/process/NSS/native RPC facts are synthetic on CPU.

Reviewable stages: original HOME continuation/parent-placement fix first; then
canonical reported-enrollment recovery plus real HOME fixture; then initial-child
permission normalization plus full platform boundary; finally the source-bound
prelaunch successor and original completed-workflow recovery. Preserve old13/current14 and
all original platform/host operations during independent release review. No live
selection, API/product service change, signing or publication is performed by tests.

tests/integration_native_administrative_recovery.py exercises actual Global/worker
models and a real artifact. Its private proxy drops accepted principal, role,
room and placement acknowledgements. A qualification-only result-boundary wrapper
hides the actual completed provisioning reply once. The workflow recovers by
reads, independently accepts the artifact and proves stopped-worker inspection,
wrong host/spec rejection and the actual unprivileged CLI boundary. Fault
injection does not replace the model provider.

## SDK251: bounded report identity and report-only input successor

SDK250's native-admin UUID plus full initial-config digest produced a136-character
report key. Actual maintained API180 `server.RoomAgentReport` inherits a128-character
operationId limit and validates BEFORE `invoke`, NATS/domain or administrative
transaction admission. Source SHA256 is pinned in `room_initial_report.CONTRACT`.
An absent/403 command read is NOT evidence of non-admission. This correction relies
on the specific reconstructed invalid136 wire and independently qualified API180
input contract, not a generic HTTP400/error-string/unknown-write retry rule.

Existing report keys <=128 remain byte-exact. Oversized newly generated keys become
`room-report:v1:<sha256(full-original-key)>` (79 characters), retaining full original
stage identity without truncation/collision-prone suffix removal. All prior
HOME-known-not-dispatched, initial-permission and prelaunch safeguards remain.

For already initialized SDK250 children, a report-only successor validates the
original actor/thread/operation/selected spec, frozen step5 plus sending step6 wire,
ready dispatch/host result, matching native-intent/accepted/context/session config,
and CURRENT protected parent/native policy. Ambiguous native state or any binding,
wire or receipt drift holds. It never calls factory/bootstrap/native RPC/session
attach. Old workflow, sending report (including its403 inspection), specs, positive
prelaunch/native receipts and all original accepted reports stay immutable.

`report-recovery-<original-id>.json` and `report-successor-v1/` retain a distinct
bounded metadata stage. The pending pointer follows that journal; an unknown
bounded send blocks other administration and is inspected, NEVER blindly resent.
A FRESH matching canonical receipt can conclusively finish by READ even when the
command receipt is unavailable; it does not forge an ACK for either old sending
record. A different canonical receipt is never overwritten. Without a matching
canonical receipt or exact bounded-command receipt, lost/uncertain sends remain
held. Fresh report uses current canonical revision, then reports provisioning,
not fabricated Ready. New child/thread identities are never allocated here.

`tests/integration_initial_report.py` runs production native-admin UUID-shaped keys
through actual API180 HTTP, two isolated PostgreSQL/HOME stores and authenticated
NATS. It asserts invalid136/129 never reach invoke/NATS or command rows, valid128
and bounded79 succeed; full actual Mac file/validator/bootstrap boundary produces
the original initialized-but-unsent report. Darwin NSS/process/native RPC are
synthetic on CPU, zero real native/model calls. Lost ACK plus403 receipt and an
ambiguous pre-wire send prove no duplicate; positive canonical read settles only
after actual metadata acceptance. Original blocked+ready proof files remain exact.

### Minimal independent Root owner contract

1. Keep actual reviewed API180 validation contract pinned during this repair;
   source/fixture proof is not permission to assume a changed API's boundary.
2. Select SDK251 through existing maintained owner transition after genuine
   all-context/output quiet, preserving original native daemon, threads, tools,
   permissions, credentials and queued work. Rebind CURRENT parent policy through
   its existing protected owner mechanism, not a copied old PID or side daemon.
3. Existing catalog/reconciliation edge resumes original work. For initialized Mac
   originals inspect the new report-only journal: NO enrollment/native/factory call.
   For never-initialized homes the retained prelaunch path creates once with bounded
   new report key. Do not replay original apply/init operations or delete journals.
4. Old SDK250 unconfirmed workflow/oversized sending row remains historical. Only
   a completed report-successor binding their EXACT hashes plus positive canonical
   receipt/command proof closes that specific metadata obligation for accounting;
   never blanket-ignore unconfirmed/native unknown records. Verify actual distinct
   original native/canonical freshness/Ready separately. Root owns all deployment,
   publication and live acceptance; this source task performs none.

### SDK251 Windows original five-step pre-resident successor

`room_windows_initial_configuration.py` handles ONLY the source-pinned original
Windows `_load`→`_scope` failure `Explicit NEW full native policy required`, before
resident seal/file preparation/native intent. It requires five exact accepted
HTTP steps, retained dispatching spec/credential/operation binding, and an ACCEPTED
original blocked diagnostic with exact actor/control-operation/guard witness.
The exact original pure `_scope` must reproduce that guard under protected current
parent evidence; absent files or a generic Held/error string alone do not qualify.
Any resident seal/state preparation/child root/native intent/host result holds.

Only an independently REAL accepted V2 current parent can select the immutable
Windows successor spec. Full maintained current `_load` validates that candidate
before plan selection, preserving scope/tools/model/profile/credential and native
incarnation; only missing initial permissions and CURRENT approved parent witness
change. No old parent PID is spoofed/reused, no V2 acceptance is issued by the SDK,
and a current explicit restriction is never widened. Original unconfirmed workflow,
five HTTP records, spec, dispatch and credential remain byte-exact. The explicit
`windows-configuration-recovery-<original-id>.json`/pending marker references those
originals, reuses steps0..4, and allows exactly the SAME fixed native operation to
enter the actual platform once. New reporting uses the bounded identity above.
Ambiguous native receipts remain unknown and cannot cause another thread/start.

`tests/integration_windows_prelaunch.py` executes the ACTUAL unchanged Windows
validators and resident/file/bootstrap phase machines on CPU, replacing ONLY
Windows kernel SID/ACL/process/pipe facts and native RPC with explicit shims.
Ready/unknown-reply cases preserve ten original proof files, bind current parent102
instead of101, reject unknown intent/missing positive diagnostic/closed V2/current
restriction, and attempt one thread/start. This is NOT actual Win32 ACL/OS/native
qualification. The separately retained real BLD-owner six-original pure-guard/
source/diagnostic packet supplies original-phase evidence, not child readiness.
Root still owns actual Windows owner selection, separate fresh V2 acceptance,
same-operation platform qualification and canonical freshness after true quiet.
