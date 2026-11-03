# Shared native turns and per-source response outcomes

One Global/thread remains shared across rooms. Native start-or-steer admission,
original client IDs, additionalContext, busy relevance and receive/handoff/ACK
journals are unchanged. The native queue is not a substitute: its inspected
contract lacks additionalContext and may auto-dispatch an idle thread.

Human input guidance identifies the existing explicit-publication route when
several source scopes share a turn. Reply-eligible input is a response opportunity,
not an exclusive task assignment or a requirement for every member to acknowledge.
Ordinary context-only peer traffic remains history-only and cannot poison scope.

## Durable, safe outcome

An ambiguous normal final stays `output.state=queued` with its original item,
turn, body and phase. A separate `reply_delivery_hold` retains its original reason,
metadata and body digest, and adds an actionable diagnosis. The diagnosis is not
publication, suppression, source selection or historical repair. Diagnosed mixed
finals no longer occupy the publisher's first32 slots and starve later unique
finals. No model is woken and no original input is resubmitted. Missing original
input ACK is distinguished: its later original bind can wake normal delivery.

Explicit original-source answer/blocked receipts record their actual phase in an
additive table. Per-input state distinguishes awaiting response, unbound native
handoff, native ended without a source answer, unknown/rejected publication,
accepted answer availability and a reported blocker. Old accepted phases remain
explicitly unknown unless their exact original publication ledger supplies them.
Native end and accepted answer availability NEVER imply business completion.

Existing `hollywood_context` / `hollywood_room_info` results expose **own** bounded,
room-filtered reply state. Tool declarations are unchanged. Reports contain no
message body, but can contain private source identifiers: they are owner-private,
not a public activity payload. Explicit publications continue to use the original
source/room/audience/counterpart; private-to-room expansion remains rejected.

An operator can inspect without starting a connector, migration or model:

```
python -m lax_connector.inspect_reply_state --config ORIGINAL_PRIVATE_CONFIG \
  --room EXACT_ROOM --after 0 --limit 100
```

The read uses SQLite mode=ro, validates original owner/thread binding and requires
the original private files. Do not point it at another agent's credentials/state.
Live owner inspection does not authorize disposition of retained ambiguous finals.
There is intentionally no automatic source-selection or replay command.

## Native state is a separate axis

`ownNativeState` reports actual shared-thread status separately from room-source
attribution, without exposing another room/source ID. The owner-private saved
shared-status snapshot is event evidence, not a process health/currentness proof.
The old v1 wire projection maps active-elsewhere to unavailable. The companion
Hollywood source advertises `nativeState.capabilities.sharedThreadStatus=1`;
only a CURRENT authenticated catalog advertising that exact capability enables
the source-less `activeElsewhere` status. Its flags are empty, and it identifies
no other room, private source or work claim. Persisted capability is discarded
on restart; an old API/rollback remains legacy-compatible. The companion client
candidate labels it **Shared context busy**, neither Idle nor Running in this
room nor an unavailable native process. The existing75-second expiry still
overrides it. Deploy compatible client support before advertising the capability.

Neither server capability nor client source is deployed by this qualification.
Hollywood177 does not advertise it, and NextComp161 is not claimed repaired by a
local field. Per-source outcomes remain owner-private inspection, not a fabricated
business-completion projection. The HTTP/PG journey uses synthetic completed-turn
evidence and real source/publication/status receipts, not a native/model execution.

No live connector, API, phone app, native process, old output disposition or room
grant is changed by source qualification. Release remains owner-coordinated.
