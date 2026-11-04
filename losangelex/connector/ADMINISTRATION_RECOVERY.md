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

`tests/test_room_initialization_continuation.py` exercises real loopback HTTP and
private journals with synthetic HOME/parent/native facts, including lost replies,
scope/wire rejection and pause-enable/re-pause edges. It is not live rollout,
PostgreSQL dispatch-CAS or model qualification. Preserve old13/current14 native
declarations and all original platform/host operations during owner review.

tests/integration_native_administrative_recovery.py exercises actual Global/worker
models and a real artifact. Its private proxy drops accepted principal, role,
room and placement acknowledgements. A qualification-only result-boundary wrapper
hides the actual completed provisioning reply once. The workflow recovers by
reads, independently accepts the artifact and proves stopped-worker inspection,
wrong host/spec rejection and the actual unprivileged CLI boundary. Fault
injection does not replace the model provider.
