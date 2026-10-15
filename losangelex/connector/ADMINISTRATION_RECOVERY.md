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

tests/integration_native_administrative_recovery.py exercises actual Global/worker
models and a real artifact. Its private proxy drops accepted principal, role,
room and placement acknowledgements. A qualification-only result-boundary wrapper
hides the actual completed provisioning reply once. The workflow recovers by
reads, independently accepts the artifact and proves stopped-worker inspection,
wrong host/spec rejection and the actual unprivileged CLI boundary. Fault
injection does not replace the model provider.
