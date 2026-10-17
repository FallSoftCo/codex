# Managed native execution ownership

Hollywood records a launch reservation before Connector.once creates a native
process. The reservation binds the original delivery/generation/claim, enrolled
host, boot, systemd unit/invocation, guardian PID/start and actual cgroup.

The independent enrolled host controller registers the actual administrator-owned
service invocation. LAX waits for that protected guardian observation before
process creation. After creation, an immutable attachment receipt supplies the
actual native PID/start. The original reservation descriptor/digest remains
unchanged; the current descriptor includes the attached incarnation.

The native child stays before RPC initialization while the host verifies its
UID, executable inode, service/cgroup and original guardian. Before provider
submission the connector checks current live attestation, current controller
identity and the original delivery again. These metadata observations start no
models. An unconfirmed mutation response is recovered by reading the same
executor identity; it never justifies another process or turn submission.

Managed service ownership is required for the execution connector. Private
native metadata readers use AppServer without an execution callback and cannot
admit provider work. Existing direct native session control is separate.

A reserved launch remains unknown while its guardian is alive, even if no child
is visible. Once a native incarnation is attached, native exit plus an empty
work cgroup can establish physical stop while the resident guardian stays
available. A remaining helper retains occupancy. Stop never establishes the
outcome of external effects or undoes them.

Capacity counts every non-stopped recorded executor, including older generations
and terminal deliveries. Active deliveries lacking a resource record retain
conservative occupancy. A later ordinary claim by the same agent waits for its
recorded physical resources to drain.

The controller coalesces unchanged observations. Known-rejected stale metadata
can be refreshed; uncertain requests retain their original operation/payload.
One observation failure does not abort unrelated rows. Controller status exposes
observation gaps separately from successful capacity sampling.

Fresh Global provisioning installs a root-owned dormant service definition.
Installation orchestration must enroll/start the host controller, verify
placement, then deliberately activate Global. Repeated provisioning returns the
original accepted identity and preserves deliberate stops and existing config.
Workers retain their managed service and scoped Unix identity. Global keeps its
verified installation administrator authority.

Cancellation or failure before native attachment can retain a reserved unknown
resource. Settling that boundary requires matching guardian/invocation drainage;
no empty-group shortcut is accepted while that guardian can still launch.
The protected controller recovery path and full original-Global human control
remain unfinished. Same-context control admission and parent-generation effect
fencing must be qualified before production/physical-phone cutover.

Installed worker receipts can retain a base unit name. Enrollment resolves the
actual canonical systemd Id before matching it to cgroup service identity.
Protected sensor diagnostics retain the exact lookup failure for operators.


## Approved automatic service restart registration

Dev46 adds an idle-service pass to the existing Root host controller. A service
already restarted by systemd can receive a new protected incarnation record even
when no current executor row exists. It never starts a stopped unit, changes a
placement, creates or retries a request, or claims an external effect was undone.
A current already-admitted launch reservation may obtain metadata registration;
it receives no new admission from this pass. Old executors remain independently
subject to the normal controller observations and canonical occupancy fences.

Automatic registration requires a Root-protected restart approval matching the
exact existing enrollment, native image, guardian executable, unit definition,
machine, UID, home and unchanged connector configuration. Initial approval hashes
the image and guardian. Each restart checks their complete protected kernel file
identities, including inode/size/timestamps/ownership, without reading the large
CLI into the controller cgroup page cache again. The new guardian must be alone;
old guardians must be gone, old groups empty except the new guardian in a reused
unit group, and original executor physical stop must be conclusive. Unknowns,
changed pins, pending image/definition transitions and publication races hold.
A conclusive old-incarnation stop can still be reported while the new approval
is held; stop never proves an external effect was undone.

Fresh provisioning records an explicit automatic-registration preference and
uses its protected original configuration digest/package receipt to approve it
at initial explicit registration. Historical installations keep their original
specification and require one reviewed activation approval, not a registry
repair after every crash. With the already-running guardian explicitly registered,
inspect using `lax-service --inspect` and review `restartReview`, native package,
service memory and policy digest. Then use:

```sh
lax-service --authority AUTHORITY --host HOST --agent AGENT --approve-restarts \
  --expected-enrollment ENROLLMENT_SHA --expected-definition UNIT_SHA \
  --expected-image-sha256 NATIVE_CLI_SHA --expected-configuration-sha256 CONFIG_SHA
```

Changing an existing approval also requires `--expected-restart-policy` with its
inspected digest. Approvals and incarnations retain immutable historical records.
A reviewed image/configuration/definition upgrade needs a new explicit approval;
the controller never refreshes those pins automatically. Roll out the matching
controller source, then qualify one idle owned restart and a separately addressed
actual task. These source mechanics do not prove an installed restart or model
outcome. Registration does not restart or recover a failed business request.

## Service memory ceilings

Fresh Global and worker provisioning now explicitly records an 8 GiB hard service
ceiling. The previous source-worker 2 GiB cgroup was actually OOM-killed at a
2.0 GiB peak; Root's temporary 8 GiB cap restored room for the source workload.
This motivates the fresh default and is not evidence of a memory leak fix or a
universal sufficient limit. Admission estimates/reservations remain separate;
the service cgroup ceiling includes the connector and all descendants.

Set `serviceMemoryMaxBytes` in reviewed provisioning configuration, or provide it
to the verified Global `lax_provision_worker` tool. Global's optional
`workerServiceMemoryMaxBytes` config selects its explicit fresh-worker preference.
Model, effort and execution permissions are unchanged. Existing approved specs,
provisioning digests and original unit bytes retain their historical 2 GiB worker
or 4 GiB Global defaults unless a reviewed upgrade changes the definition.
Provisioning retries never overwrite a stopped worker or its limits.

`lax-service --inspect` distinguishes original approved provisioning memory,
current unit directive and effective systemd MemoryMax/MemoryCurrent/MemoryPeak.
A runtime override may differ from the unit and historical spec. To prepare a
reviewable existing-service change without touching its live unit:

```sh
lax-service --authority AUTHORITY --host HOST --agent AGENT \
  --prepare-memory-max-bytes 8589934592 \
  --expected-enrollment ENROLLMENT_SHA --expected-definition UNIT_SHA \
  --output /run/owned-memory-review
```

The output retains exact original bytes, a unit differing only in MemoryMax,
and a manifest with digests and activation requirements. Root independently
pauses/drains and publishes the reviewed definition, reloads it through the
existing explicit definition-upgrade process, and approves matching restart
pins. No live unit/default is rewritten by inspection or preparation. Original
specs, contexts, receipts and unknown effects remain. Root's temporary production
source-worker override is untouched by this source change.

A definition upgrade may return an accepted metadata transition with readiness
held until matching restart pins are explicitly approved. Inspect that result;
do not repeat the accepted upgrade. Dev46 also changes the protected adapter
digest, so Root rolls out the matching controller/connector package and a new
reviewed collaboration preparation through the maintained paused bridge CAS
path. Existing preparations stay immutable. The matching-seed reselection rule
handles known pause invalidation without releasing any original locks/effects.
