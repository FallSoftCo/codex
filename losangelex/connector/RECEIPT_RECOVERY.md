# Original tool effects and recovery

A native callback is identified by its thread and call ID. Before its HTTP
mutation, LAX persists an effects journal scoped to authority, agent, host,
delivery claim/generation, source request, native thread/turn and argument digest.
The ContextVar scope follows the callback task, including concurrent callbacks.

Supported atomic Hollywood operations retain their exact wire request and digest.
On a lost response, LAX reads the same authenticated original command and validates
its authority, actor, operation, wire evidence and event. It returns the original
accepted response to a still-live callback when safe. After a native callback
failed and its original turn ended, reconciliation records the known effect and
the failed callback separately; it never replays the callback or the native turn.
A later file modification is not used to reconstruct an earlier report result.

Completed administrative workflows can recover their protected local result.
Mid-workflow administrative uncertainty, incomplete original command evidence and
unsupported native metadata changes remain held. Unsupported administrative
bodies/results are not copied into the generic effect journal, because they can
contain protected enrollment credentials.

Reads and authorized monotonic work/goal/execution cancellation remain available
while another callback is uncertain. New work and resume stay held. Cancellation
does not erase the prior unknown effect. Multi-step failures are not labelled
atomic rejections after an earlier possible or confirmed effect.

This does not reconcile arbitrary shell/MCP effects, provide cross-host ownership
transfer, separate all execution-resource and semantic-effect fences, or grant
exactly-once execution. Those remain deployment gates.

Actual integration drivers:
- tests/integration_native_command_recovery.py: real Global/worker provisioning,
  lost goal/report acknowledgements, original receipt recovery and independent
  artifact/business acceptance, three real native turns.
- tests/integration_native_uncertain_control.py: real Global cancels live work
  while its publication receipt is unavailable; two real native turns, original
  publication readback, interrupted worker and no deferred file effect.

These finite drivers require explicit qualification credentials and private
disposable state. They are not production migration or phone qualification.

## Purpose-native SDK recovery

Purpose writers use the same Effects receipt reconciler at terminal native turns
and on restart. Restart recovery reads the original callback through the owned
native RPC with its exact thread/turn/item IDs; it submits no replacement callback.
Old journals without turn identity use the captured trace only to locate the
turn, then verify the callback against native persisted history. Unavailable or
conflicting evidence remains held. A held tool belongs to its original Work;
independent responsibilities do not inherit that uncertainty. Native terminality
releases inference capacity independently of unresolved Work effects.

Artifact reporting reads explicit canonical resource grants through the captured
participant, without a legacy mutable active-context field. Failed preparation
before the sole mutating report POST can be distinguished from uncertain dispatch:
the transport always durably records write intent before sending. Recovery of a
verified failed report with no write group clears only that callback as having
no dispatched report. A write-intent journal retains its original receipt checks
and never becomes absent merely because a command is missing. New tool results
include originalOperationId; recovery does not automatically submit a new report.

The r55 integration reproduced the original native failure, read all eleven
settled artifacts using authenticated metadata, and exercised the exact failed
callback on copied journals. An unconfirmed write fixture remained held. Actual
post-upgrade native reports and acceptance remain separate end-state evidence.
