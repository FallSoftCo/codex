# Reviewed native preparation: adapter stage

The SDK now separates native preparation from installation:

- `await idle.prepare_for_review(request_id, pending)` prepares and preflights
  an existing idle Writer window, saves the exact packet and returns a sealed
  operation with `approvalDigest`. It performs no replacement RPC.
- `await idle.apply_prepared(operation, approved_digest=...)` checks the seal,
  current configuration/native artifact and exact native cut/preflight again,
  then records dispatch intent and uses the existing strict native installation.
- `await idle.cancel_prepared(operation)` cancels only a known prepared review
  with no dispatch or outcome fields. It retains the cancelled journal and
  leaves the original window intact.
- Existing `await idle.rebuild(request_id, pending)` continues through the
  immediate preparation/install path.

The seal includes original agent/context/thread/request identities, source
snapshot, native history prefix, packet, preflight, retained budget, SDK config,
native capability names, native executable hash and home config hash. This
binding is for exact reviewed content, not a new execution permission.

This is an internal, opt-in SDK API. There is no new model tool, production flag
or public human approval route in this stage. A caller-provided digest is not
proof of human authorization. The next stage must connect the authenticated
Hollywood human review/control state to this API, preserve separate initiating
human and executing-agent provenance, and fence purpose inference while review
is open. Do not expose this method directly as a human authority bypass.

Prepared reviews are durable without a pending native callback or model
inference. Cold startup restores a valid prepared operation and independently
reconciles older installed receipts. If the native cut changed during restart,
application refuses before dispatch; it does not silently rebase an approval.
The known prepared operation can be explicitly cancelled and a new review
prepared. A dispatched/unknown operation is handled through its original
installation receipts, never through prepared-only cancellation.

The native installed callback now requires an actual dispatch state.
Native history replacement, file verification, host metadata recording and
native acknowledgement retain their original meanings. Source/canonical
permission revalidation remains the communication authority's responsibility.

Qualification `tests/integration_native_review_lifecycle.py` uses the actual
packaged native app-server, JSON-RPC, native recorder and WebSocket Responses
transport, with declared scripted provider output and H metadata. It verifies
no pre-approval history/provider changes, refused changed approval/config/data,
explicit strict installation, the next request's selected fact and omitted
canary, cancellation, original immediate rebuild and cold-owner recovery.
The fixture starts no real model and proves no Hollywood human authorization,
semantic continuity, active-turn quiescing, reader/responder atomic support,
whole-window selection or NextComp UI behavior.

Canonical content/native replacement byte counts remain separate from full
provider input and tokenizer-accurate size. The native preflight does not
automatically measure external tool declarations or authoritative account
input usage. Those remain required by the complete manual-context contract.
