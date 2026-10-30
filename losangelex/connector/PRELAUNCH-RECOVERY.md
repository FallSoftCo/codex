# Pre-launch admission and uncertain execution

## Incident and invariant

Human request947 was durably accepted once. The host controller could not inspect
systemd while the manager was stalled. ExecutionLifecycle.require_registered
converted a45-second observation deadline into a generic RuntimeError; Connector
then marked the delivery unknown, exactly as for an uncertain model/tool effect.
That is an incorrect state classification. No message loss was observed.

Message identity, execution attempt identity and physical executor identity are
separate. Accepted means stored, not running or complete. Missing liveness
observation is not proof of uncertain business effects or proof of a dead process.

## Candidate correction

The original reserved executor remains claimed while awaiting positive independent
host observation. Read-only checks back off from0.5 to30seconds; no replacement
claim, model wake, process birth, room post or notification is generated. The
local launch-admission-status journal records the actual waiting reason. Transport
timeouts and selected transient HTTP failures do not imply dispatch. Authentication,
identity and canonical cancellation/state changes still stop admission. A verified
current controller is required before returning permission to create a process.

## Remaining release requirements

This candidate is not a complete crash-recovery redesign or a deployed release.
A process restart after reservation still uses the existing independent stop proof
and canonical recover-before-native protocol. Autonomous recovery must use that
protocol and an explicit durable pre-dispatch boundary, not delete journals or
infer safety from a missing nativePid alone. Lost replies after birth/submission
must retain original operations and reconcile effects; never replay business work.

Before rollout: qualify a real isolated gateway/controller with delayed host
observation, outage beyond45seconds, cancellation, controller/worker restart, and
uncertain launch acknowledgement. Confirm one accepted message, one eventual
model turn, preserved evidence and no model calls while waiting. Surface waiting
for host verification through the room projection rather than generic unknown.
The host manager stall is a separate infrastructure issue; do not bypass service
identity inspection or restart unrelated host workloads to mask it.
