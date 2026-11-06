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

## Autonomous obligation lifecycle

Every admitted request retains its original work ID, source, owning lead and
completion contract. A native turn finishing is not a project finishing. The
runtime owns continuation; conversational phrasing cannot create or settle an
execution dependency.

Current waits have typed, durable bindings. Peer waits name current assignment,
question or original-send receipts. Human waits bind a delivered need-input
intent to its work revision; they are not a count of historical blocked messages.
An acknowledged old question cannot override a newer independent-work decision.
Releasing a wait does not fabricate an answer or erase its original record.

The existing project event loop reconciles these obligations on startup and
relevant events. While unfinished work exists, a bounded one-minute metadata
audit covers a missed native end callback. It reads native turn metadata only;
it does not ask a model whether to continue. No audit runs for completed/stopped
work alone. Missing or contradictory evidence remains unavailable, not success.

When a peer wait loses its last actual dependency after a completed native turn,
reconciliation enters the same durable recovery path. The original thread,
background commands, pending callbacks, input/output and delivery identities must
settle before exactly one readiness event is released. Stops and real current
human-input waits remain stopped. Completed, blocked and failed worker results
are retained for the lead's next decision; none is misrepresented as an active
worker.

`lead_work.obligation` exposes current reference identities and a persisted
coverage snapshot. Evidence-backed completion and bounded no-progress recovery
remain separate requirements. This contract does not promise that models can
solve every task or that disconnected hardware is available. Its purpose is
accountability and recoverable continuation, without duplicate external actions
or perpetual model polling. Host availability, provider availability, sufficient
resources and actual human decisions remain explicit operating dependencies.
