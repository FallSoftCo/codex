# Windows parent acceptance locator candidate

This is review-only Windows source against SDK commit
`07d1e3c7b421131e8f092c4cb65799af4fe2b0d0`. It has no new Git commit and is
not installed. The original source carrier, real parent policy draft and all
earlier qualification receipts are retained unchanged.

The owned production delta is limited to `room_factory_windows.py` and
`room_factory_windows_state.py`. CPU owns common policy loading, startup
evidence, supervisor recovery and catalogue/reconnect integration. Earlier
`owner-locator-proposal-r01/r02/r03` common-file variants are reference-only,
superseded as handoff source and excluded from this bundle.

## Problem and interface

V1 pins the parent acceptance SHA inside the immutable policy. A normal parent
restart changes its PID/birth and accepted argv. Accepting that incarnation
therefore changes the acceptance hash, then the policy hash selected by the
already-running parent configuration. The original startup emitter cannot
approve its own evidence. Frozen 07d1 provides no supported way to settle this
cycle without changing the selected policy/configuration again.

The new interface is:

```python
read_parent_acceptance(policy, *, expected_policy_sha256) -> dict
```

V1 remains strict: it reads `parentAcceptancePath` with the exact original
`parentAcceptanceSha256`. V1 never follows a mutable locator.

Opt-in `lax-windows-room-parent-policy/v2` keeps the existing host, parent,
account, root, native, model and guide bindings. It removes BOTH V1 acceptance
fields and requires exactly:

```json
{"parentAcceptanceLocator": {"path": "<fixed protected absolute owner-record path>"}}
```

The file and containing directory must satisfy the existing Windows private
path/ACL checks. The containing directory must be the original
`parentRuntimeMetadata` directory. Exact absolute-path checks reject aliases.
V2 with either V1 acceptance field is rejected.

The owner record has schema `lax-windows-parent-runtime-acceptance/v2` and must
bind `policySha256` to the exact selected stable policy and a nonempty bounded
`ownerAcceptanceOperationId`. Its original authority, host, parent agent,
native descriptor digest and parent task name must match the policy.

`inspect_parent` still requires running/open admission plus the actual current
parent PID/birth/image/account/session and shared native kernel-peer identity.
The carrier retains its current-parent PID and argv acceptance checks. The
reader can return a correctly bound CLOSED record; it never turns closure into
admission. `lax-room-parent-startup/v1` evidence is not an owner acceptance.

The Windows helper only reads this record. Issuing acceptance, validating the
original manager policy, preserving append-only owner-operation history and
atomically replacing the locator record are responsibilities of the existing
owning operator. A caller-supplied operation name alone proves no approval.

## Proposed owner sequence: not executed

1. Review the complete successor release and explicit V2 policy; pin its stable
   SHA in the configuration once before the controlled parent transition.
2. Establish genuine quiet across ALL logical sessions, control/bootstrap,
   publications and unknown effects. Use the existing owner manager boundary
   for the single parent; preserve the original native/profile/threads.
3. The new parent emits startup evidence with admission CLOSED. It cannot
   approve itself. Previously accepted child registrations remain deferred;
   no new thread or model is requested.
4. Independently verify original manager/startup/native/account/argv and record
   the new owner acceptance operation, retaining original receipts. Atomically
   update the fixed protected V2 locator record with the new actual incarnation
   and stable policy SHA. Policy and configuration bytes remain unchanged.
5. CPU's common integration may reconcile only registrations previously
   deferred for parent admission on its existing catalogue/reconnect edge.
   Reuse their accepted configurations and original native threads once. No
   new timer, model, thread start, failed/stopped-session resurrection, or
   running-sibling status/quiet mutation is authorized by this reader.
6. Obtain fresh matching native observation and normal owner acceptance.
   Bootstrap acceptance alone is not attached/canonical-ready evidence.

## Qualification and limits

`test_windows_owner_reader.py` is a retained-layout local Windows fixture,
not portable CI. Run it through the existing approved Python3.12/capsule boot.
Its source imports the retained SDK246 baseline plus the verified frozen 07d1
closure; no dependencies are installed. It creates a new protected
`qualification-r01` exactly once and refuses to replay an existing operation.
The original successful result must be inspected rather than rerun in place.

All fixture runtime/native identities and acceptance records are explicitly
synthetic. Process and native-peer reads are stubbed before exercising the
reader. Windows owner/session and private-path/ACL checks are real. No real
parent acceptance, native RPC, OS manager call, process lifecycle, bootstrap,
session, model or business action occurs.

The actual final-byte Windows fixture passed: V1 exact pin remains strict;
synthetic parent A to B works with byte-identical V2 policy/configuration;
wrong policy, missing owner operation, startup evidence, wrong host, stale
parent, closed admission, ambiguous V1 fields and an unsafe/relocated locator
are rejected. This does not qualify CPU's common recovery implementation or a
live owner transition. The real BLD policy remains unused and admission CLOSED.

`SOURCE-PINS.json`, the code-only patch, bundle manifest and public qualification
summary provide exact source/result hashes. Synthetic private fixture files,
real configuration/auth/profile/state/DB and earlier common variants are
excluded from the archive. Root retains version, complete-carrier integration
and controlled deployment ownership.
