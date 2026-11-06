# Lead-owned projects

A project has one human-facing lead and addressed room-origin workers. Hollywood
retains communication, audience, membership and original acceptance. The shared
host connector owns native execution and a private SQLite work journal. A room
membership or stored note is not a model admission or an execution assignment.

New human input reaches the canonical lead. `lead_assign` creates one stable
assignment; only its recipient receives native input. Workers use concise
`team_report`, `team_question` and `team_answer` calls. Routine progress is
retained without waking the lead. A selected terminal result, real question or
changed dependency lets the lead decide what to do next. Human answers use
`lead_reply` with the original work ID and audience. Normal worker/lead finals
remain in native history rather than being copied into room chat.

The active work ledger is separate from native context. `lead_work(workId)`
retrieves the accepted original request and its addressed assignments. Reading
stored history, listing participants and fetching status do not wake models.
Native turn end is not task completion. Explicit completion, pause and cancellation
are retained. An unaccounted native end gets one bounded repair opportunity;
repeated unchanged/no-progress ends become an inspectable fault rather than an
unlimited model-polling loop. Native failures still require scoped runtime
recovery; this change does not claim that every failure class is automatically
recoverable.

## Existing logical agents

An existing room is adopted at an independently observed quiet boundary. Preserve
its identity, thread, credentials, original immutable initialization/configuration,
full raw history and uncertain receipts. Do not restart the shared native server.
Install the role-aware parent runtime through the existing host-owner enrollment
upgrade first. Its logical-session snapshot advertises `project-role-handover/v1`.

`lax-adopt-room-role --plan OWNER_PRIVATE_JSON --receipt OWNER_PRIVATE_JSON` applies
one reviewed original-binding plan. Required fields are `parentPath`, `agent`,
`expectedConfigSha256`, `expectedRecordSha256`, `policy`, `seed`, `operation`, and
`work`. Policy must match the authenticated canonical room. Each work entry names
an original accepted human `eventId`, `canonicalSha256`, reviewed `state` and
`reason`. Only explicitly unfinished, reconciled `ready` work is runnable. Paused,
cancelled, completed and uncertain (`fault`) obligations stay non-running. Do not
infer ready work from every historical request or from a synthetic forwarded
message. Preserve original external-action state before deciding to resume.

The operator holds the original parent/child locks, writes an immutable successor
configuration and a write-ahead registry hold, performs a no-model native
checkpoint/refill on the SAME thread, imports reviewed original obligations, then
publishes one accepted registry pointer. Neither incomplete pointer form can
start an old or partially adopted context. Unknown checkpoint outcomes remain
held for original-receipt reconciliation. An accepted retry returns the original
receipt; it cannot fork a context or reset later work.

The retained original human event is imported as evidence with zero native human
admissions. Ready work queues one deduplicated agent-authored work-ready event
referencing that same original. It is not another human POST or permission to
replay external actions. Ordinary subsequent input uses the independent `inputs`
view cursor; the old room conversation cursor is never reused for native input.

The native cache boundary uses existing idle resume/unsubscribe and zero idle
retention during the mechanical checkpoint only. It never archives a business
thread, fabricates a setting change, calls a model to summarize, creates another
app-server or changes model, effort or permissions. Original pending input,
output, publication, native callbacks or background commands must settle first.

## Qualification boundaries

Real isolated PostgreSQL/HTTP and shared-native journeys cover addressed work,
worker-to-worker questions, an untouched observer, lost-ACK reconciliation,
privacy, stops and a same-thread role handover completing its original accepted
request without resending it. Logical NATS-node qualification is distinct from
physical multi-host activation. A root-approved QA host policy does not qualify
production host enrollment upgrades. The release owner must verify those actual
upgrades and each adopted room before reporting deployment.

Legacy acknowledged receive rows are checked against their independent original
input-to-turn binding and persisted native terminal event before a context
handover. ACK alone is insufficient; old receipt rows are never rewritten to
fabricate a committed state. Accepted context-only injection has no execution
claim. Original uncertain explicit publications remain held for same-ID reads.

Project worker room reads default to twelve internal coordination events, with
explicit cursors for further evidence. Lead reads default to its human lane.
Accepted role receipts pin the configuration originally reviewed; later SDK
template/tool changes cannot regenerate or silently rewrite that acceptance.
Exact previous tool-schema hashes remain supported for retained contexts.

## Local lead progress

Delegation is optional. A lead doing local work records a material milestone with
`lead_work(workId, checkpoint={key, summary, evidence})`. The exact current native
work must be bound to that turn. Stable keys preserve retries; the same versioned
evidence cannot add progress again under another key or reworded summary. These
are attributable lead assertions, not independent artifact verification. Tool
counts, elapsed time, unchanged checks and status paraphrases are not milestones.
The journal survives connector restart; a material milestone permits continued
useful work after native turn end without a new user command. The existing
no-progress bound, original-output settlement, stops and unknown-action guards
remain in force. A checkpoint never creates a human message or model timer.

SDK-only native-client upgrades use their existing managed-service enrollment
and unchanged native dependency. They pin the actual physical host, original
principal and complete reviewed software, preserve semantic configuration and
require the existing quiet-context/I/O boundary. Legacy execution controllers
and historical optional node annotations are unrelated to this client update.
The upgrade neither queries execution slots nor changes placement or deliveries.
Engine, route and instruction changes retain their existing owning release path;
accepted historical records remain unchanged.
