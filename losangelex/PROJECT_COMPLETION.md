# Evidence-backed completion and unattended recovery

LAX owns these records in the existing per-agent `project-work.sqlite`. Hollywood
continues to own messages and identity; this adds no execution scheduler to it.

A lead defines `lead_work.acceptance` for the original work: an exact subject
revision, concise testable criteria, and the scope rationale. The original human
source and intent digest are retained. Changing the subject invalidates prior
verification. Existing requirements cannot silently disappear or weaken.

`lead_work.verification` names a criterion, verdict, summary, evidence files with
expected SHA256, and an actual native command's turn/item IDs. `lead_work` lists
recent command receipts. A successful command must print the supplied artifact
hashes. The runtime checks the original work/turn binding, successful exit, file
identity and bounded regular-file contents, then retains the bytes and command
receipt in SQLite. Local source-file deletion does not erase accepted evidence.
The lead must review what the evidence means; checksum/execution verification
cannot mechanically establish every product-quality claim. Choose criteria and
verification proportional to the original request, including delivery where
requested. Worker `done` reports require evidence references but remain claims
until the lead verifies their results.

Both `lead_work(state=complete)` and `lead_reply(disposition=complete)` require
all current criteria to pass. The latter checks before publishing, so unsupported
completion claims never become human room messages. Completion seals an immutable
receipt; repeated accepted replies retain their original identity. Historical
completed work is not reopened or retroactively certified.

Native terminal failures retain their typed error. Confirmed transient capacity,
rate-limit, connection and server failures enter durable recovery with capped
exponential backoff. Cheap metadata checks reconcile the original terminal turn,
background commands, callbacks, I/O and worker dependencies before creating one
source-bound readiness event. Unknown delivery never means retry permission.
Schedules and observations survive restart; pending communications reconcile
through the existing same-ID outbox. Usage/permission stops, cancellations and
interruptions do not become automatic retries.

Two completed turns without progress get one diagnostic continuation per material
progress frontier. Repeated unchanged diagnostic ends stay faulted and inspectable;
they do not create a model-polling loop. New material selected-worker results or
explicit authorized repair can make work useful again. Recovery is not a promise
to solve every blocker automatically. `lead_work` exposes the durable diagnosis,
retry time, acceptance criteria, verification verdicts and completion receipt.

Qualification covers actual SQLite reopen, hours-long metadata backoff, unknown
publication reconciliation, no-progress bounds and a real isolated native two-turn
journey. The native journey rejects unsupported completion, executes verification,
continues after a private final, and publishes one evidence-backed human result.
Production release requires matching lead tool declarations and instructions at
the existing idle role-handover boundary; source tests do not establish activation.
