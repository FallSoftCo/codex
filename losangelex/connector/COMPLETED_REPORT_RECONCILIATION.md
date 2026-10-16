# Completed assignment report reconciliation

This is a staged connector contract for `hollywood_work_report_reconcile`, not a
live migration, work restart or acceptance of an earlier deliverable. Ordinary
`hollywood_work_report` keeps its captured-work and native-goal checks.

An owner may discover during a later, normally admitted participation that its
original assignment completed without a report. It inspects the original request,
execution, artifact bytes and effects before explicitly submitting evidence. It
uses `blocked` when criteria/effects remain uncertain. The note is an accountable
effect/acceptance attestation, not an automatic inference from completion or stop.
The connector cannot determine semantic business success from artifact hashes.

## Wire contract for joint server review

The native tool takes exactly `workId`, `revision`, `priorDeliveryId`, `state`
(`submitted` or `blocked`), explicit `effectDisposition` (`reviewed` or `unknown`),
`note` (nonblank, at most4000 characters), and at most16
relative `artifactPaths`. It does not accept caller-supplied hashes, credentials,
workspace roots or participation claims. Its operation ID is the existing durable
`lax-tool:<SHA256(nativeThread + callId)>` identity.

The connector reads `GET work/{workId}` and `GET deliveries/{priorDeliveryId}`.
It requires the original owner, latest assigned/unreported work, exact revision,
completed original delivery/result, original request/work linkage, same authority,
host, persistent thread/context and workspace identity. The current captured
participation must have its own valid persistent-agent binding, current role
revision and uncancelled active delivery. It may be in another authorized room;
the original room's rights must still be checked by the server.

The single mutation is `POST work/{workId}/report-reconcile`:

```json
{
  "operationId": "lax-tool:<current native call digest>",
  "revision": 7,
  "priorDeliveryId": "<original completed delivery>",
  "state": "submitted",
  "effectDisposition": "reviewed",
  "note": "<original receipt, effect and acceptance review>",
  "evidence": [{"hostId":"<original/current host>","workspaceId":"<original/current workspace>","relativePath":"result.txt","size":16,"sha256":"<connector digest>"}],
  "briefingSequence": 123
}
```

The existing `X-Hollywood-Native-Source: hollywood-native-source/v2` header carries
the CURRENT authenticated request/delivery/claim/generation, native thread/turn,
context, actor, host, role revision and exact tool argument digest. No original
claim is presented as active. `briefingSequence` describes current participation;
the server must retain the original attempt's briefing and immutable history and
separately record reconciliation provenance/current decision checks.

These body names and the hyphenated route are selected by the pinned
shared/review-gate-r02.json. No current identity hints are sent in the body;
the current v2 source header supplies those identities. `effectDisposition` is
required with no default or inference from note text/completion/stop. Submitted
requires explicit reviewed disposition; blocked may preserve unknown. Exact model
compatibility is checked separately from domain/SQL/native qualification.

## Evidence and mutation fences

The configured workspace must equal both authoritative execution bindings. One
`O_DIRECTORY | O_NOFOLLOW` root descriptor pins the directory across all artifact
reads; caller paths cannot choose another root. Each path component is opened
without following symlinks. Only bounded regular files are hashed; nonblocking
leaf opens reject FIFOs without hanging, and device/inode/size/mtime/ctime must
remain stable during each read. The payload contains hashes of actual current
bytes in the original pinned workspace. An unchanged historical byte identity
requires the owner's original evidence/receipt comparison; the tool does not
invent a missing historical hash or silently restore files.

The server must recheck current principal/placement/context/claim, original-room
posting rights, ownership, goal/cooperation, relevant decisions and cancellation
atomically at mutation time. Client GET checks cannot close a revocation or
report/cancel race. The proposed paused-goal semantics permit evidence-only
reporting of an already completed original, without admitting work or resuming the
goal; cancel_requested/cancelled must deny. The selected server cut agrees with
this pause policy; its independently qualified implementation is still required
before native proof or activation.

The new tool is a mutation under the existing uncertainty gate and exact native
tool allowlist. It is an atomic effect: lost replies reconcile only the original
canonical command's identical wire digest/event/accepted result. Same-call native
retries return the durable cached result; changed arguments are held. The server
must implement same-operation replay and changed-payload/CAS conflicts. There is
no fallback to ordinary reporting, reassignment, recovery, new execution or model
loop. A missing endpoint fails closed and can remain unconfirmed under the
existing generic404 policy; do not retry it on an older backend.

The connector advertises `completed-work-report-reconciliation/v1` and package
version0.1.0.dev39. Deploy only with its matching independently reviewed server;
an older native tool ceiling must be explicitly reconciled to expose the new tool.
No Rust/native runtime change is required. Submission remains separate from
independent review/acceptance against the original completed execution.

## Focused component check

Run with existing dependencies, `PYTHONDONTWRITEBYTECODE=1`, an owned RAM `TMPDIR`,
and this worktree's connector directory on `PYTHONPATH`:

```sh
python -m unittest discover -s losangelex/connector/tests -p test_completed_report_reconcile.py -v
```

These are explicitly synthetic receipt/HTTP fixtures and actual RAM file-boundary
checks. They cover client original/current identity fences, captured-report
compatibility, tool dispatch/caching/policy, actual local hashes and file races,
native-source header attribution and original lost-reply receipt recovery. They
do not replace authoritative server authorization/race tests or a real native run.

For the selected server wire, run `tests/check_completed_report_wire.py` with
`--server-source` pointing to the exact reviewed committed server.py snapshot.
It extracts only the actual Pydantic model classes, validates the connector's
captured body and rejects the superseded identity hints/missing attestation.
This check starts no HTTP server, PostgreSQL or native runtime and reports the
reviewed source hash. It does not execute the server's SQL or prove authority.

## One later staged integration and activation

After both component commits complete and are independently cross-reviewed, the
designated Hollywood owner should run ONE newly created isolated RAM-backed stack
using existing dependencies/native binary. Do not restart a retained fixture.
An assigned native worker writes an artifact and effect receipt, then completes
without reporting. Later ordinary native participation in the same agent context
inspects its original receipts and calls this new tool. Preserve original/current
request, delivery, result, context, thread, turn, action and artifact hashes. Verify
one original effect, no original re-execution, no extra attempt/admission, original
work.delivery unchanged and explicit report provenance. A distinct authorized
native manager/verifier independently inspects and reviews that exact evidence.

The matching server component must separately establish stale claim/generation,
revocation, cross-owner/context/host/workspace, missing/changed evidence, stale
decision, failed/unknown/nonterminal/superseded original, exact replay/conflict and
report/cancel races. Retain failures and their effects, without substituting a
passing synthetic fixture for native acceptance.

Activation is Global's separate decision after both reviews and original native
receipts pass: package the two pinned commits, qualify the exact installed cuts,
drain/CAS-upgrade and register only explicitly authorized idle runtimes while
preserving contexts, journals, original obligations and current production state.
No activation is authorized by this staged implementation. Rollback removes new
tool exposure only at verified idle boundaries and retains every new report,
command receipt and original attempt; never restore an older database over newly
accepted evidence or replay an uncertain operation. A schema-changing server cut
needs its own forward/backward data-compatibility review.
