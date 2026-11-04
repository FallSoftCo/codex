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
creation-only fields are absent. Existing immutable invalid specs are NOT silently
replaced: a completed blocked workflow and its accepted report wire require separate
explicit original-operation, positively-no-thread-start owner reconciliation.

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

Reviewable stages: original HOME continuation/parent-placement fix first; then
canonical reported-enrollment recovery plus real HOME fixture; then initial-child
permission normalization plus full platform boundary. Preserve old13/current14 and
all original platform/host operations during independent release review. No live
selection, API/product service change, signing or publication is performed by tests.

tests/integration_native_administrative_recovery.py exercises actual Global/worker
models and a real artifact. Its private proxy drops accepted principal, role,
room and placement acknowledgements. A qualification-only result-boundary wrapper
hides the actual completed provisioning reply once. The workflow recovers by
reads, independently accepts the artifact and proves stopped-worker inspection,
wrong host/spec rejection and the actual unprivileged CLI boundary. Fault
injection does not replace the model provider.
