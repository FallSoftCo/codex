# Native room input durability

This candidate keeps Hollywood communication separate from native execution.
The receive journal records canonical input identity and original handoff only;
it never owns a task, claims an executor, selects a model or restarts work.

## Current proven boundary

Hollywood persists canonical publications and immutable send-time recipients.
The connector preserves each event ID and content fingerprint before calling
native start-or-steer. Concurrent receive connections can reserve only one
original handoff. Acknowledgements survive connector restart. A lost response
leaves the original handoff unresolved and prohibits automatic resubmission.

The real publication lost-ACK qualification separately proves one POST, one
canonical event and lookup of its original command after transport loss.

## Native gap that must close before production migration

Current turn/start acknowledges an in-memory Started/Steered decision before
input recording. thread/items/list reads storage; it does not flush a live writer.
The user-message UI item has clientId, but the earlier response-item persistence
stores input acceptance order without that correlation. Passive typed agent
items are not part of that UI projection. Missing UI history therefore cannot
prove that input or external actions never happened.

Native must own a durable input receipt keyed by thread + canonical input ID,
with immutable actor, input type and content fingerprint. Commit before exposing
acceptance or allowing model/tool effects. Retain duplicate receipts across
restart and compaction. Same identity/content returns the original receipt;
changed contents conflict. Native input acceptance order controls dispatch.

Reuse the native storage and input serialization boundaries. The existing user
queue cannot be called exactly-once: it allocates random IDs and removes rows
when Core accepts an in-memory submission. Do not relabel peer messages as user
input or function-call outputs to reuse that queue. Do not add a Hollywood job
or executor protocol to compensate for native persistence.

Required fault cases: process death before commit, after commit/before ACK,
after dispatch/before UI history, and during compaction; human start/steer and
passive/explicit peer input; duplicate transport and content mismatch. Recovery
must retain the original input and external effects, never replay unknown work.

The connector journal is not the native fix. Its acknowledged rows remain
pending native durability reconciliation; it must not be advertised as complete
unattended recovery or used to migrate the user's production room yet.
