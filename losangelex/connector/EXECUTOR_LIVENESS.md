# Independent Linux executor observation

service_observer.register() is an administrator installation primitive. It records
an actual live LAX systemd unit, expected installed Linux UID/home and executable,
protected unit-definition digest, invocation, boot and resident guardian. It never
starts or stops that service. Re-registration cannot silently replace its
definition; an upgrade needs an explicit drain/registration plan.

The enrolled protected host controller reads the exact registered incarnation.
It can establish live ownership, or establish stop from an original drained group,
a settled registered invocation or a changed machine boot. The mere absence of a
heartbeat, a timer expiry or a missing unregistered process is insufficient.

A native exit leaves occupancy held while another actual work process remains in
the group. Only the pinned resident guardian may remain in a drained running unit.
Helper evidence is bounded and carries total process count/digest. The controller
never kills a process to free capacity. Persistent application/render workloads
need their own explicit managed-workload ownership, not hidden orphan cleanup.

Unknown/unregistered observations remain conservative. They are coalesced rather
than waking models, and one registry-verification failure does not prevent other
executor observations. Stopped original effects are not retried or undone.

tests/integration_executor_liveness.py runs the actual native app-server, systemd,
kernel process/group inspection and authenticated PostgreSQL API. It starts no
provider inference: the check is executor liveness. A real helper survives native
closure, holds the slot, then an explicit owned qualification action stops it.
Independent observation releases the slot for another pending peer while the
original delivery remains unknown. Private qualification artifacts/identities are
retained and owned processes stop afterward.

This is a foundation, not the completed Global control journey. Main connector
launch/attestation, durable per-attempt journals, explicit human inspection in the
original context, enforced native tool policy and parent-generation effect fencing
remain required. Existing codex_extension_api::ToolPolicy is a startup ceiling,
must be supplied again on cold resume, and filters construction/dispatch. The
ShellTool feature alone leaves apply_patch registered and is insufficient.

Other execution environments need their own truthful supervisor/capability
backend. This Linux implementation does not imply Android, macOS or Windows
qualification. There is no exactly-once or shared-filesystem claim.

## Registered guardian ticks without manager IPC

Routine restart/purpose reconciliation first verifies an already registered
current guardian with `kernel_incarnation`. This retains the protected
enrollment/approval/config/image and unit hash checks, boot, invocation export,
trusted cgroup invocation ID, PID birth, UID, executable, launch environment and
membership fences. Managed-service transition locks and unsettled-definition /
release checks still precede that shortcut. The result is unchanged registration
metadata with `observationSource: kernel-incarnation` and
`managerStateInspected: false`; it is **not** native idle, completion, execution
readiness, or a claim that `NeedDaemonReload` is `no`.

New registrations and incarnation changes retain manager-based inspection and
the original registry writer. Incomplete kernel evidence retains ordinary
stopped/orphan/restart reconciliation; an identity/approval violation holds
instead of falling back to an older or weaker positive observation. Explicit
enrollment, definition, image/release and administration checks still use the
manager. Existing original receipts and deliberately stopped services are not
restarted, rewritten or admitted by this optimization.

Qualification: `test_registered_kernel_tick.py` covers selection, outage and
fail-closed boundaries with synthetic facts and real private fixture files.
`integration_managed_kernel_incarnation.py` additionally exercises the host-tick
entry point against an existing protected registration and actual live process
while manager failure is injected; it starts no native/model work or service.

Owning activation requires reviewed immutable observer packaging, retention of
the previous closure and receipts, and a quiet observer-only replacement boundary
under its original service owner. Verify the actual loaded source and a single
bounded observation afterwards, including held/unknown behavior and continued
explicit manager checks. This candidate does not authorize that replacement,
daemon-reload, native-client restart, unit/config change or mount/fstab edits.
