# Original execution attempts and current context projection

Each captured delivery/generation has its own private journal below
state/executions/<delivery>/<generation>/execution.json. Its captured source
request, agent, host and original claim cannot be replaced by later writes.
The current selector and the existing state/execution.json view are projections.
Reconciliation of an older attempt never selects it or overwrites a later view.

Writes persist the canonical attempt before the current selector and projection.
Startup repairs an interrupted projection from the selected canonical record.
Existing full execution records are imported without starting a model or changing
their original scope. Claiming an already captured attempt is rejected.

A write-ahead open directory contains relative symlink references to unresolved
canonical attempts. Admission scans this bounded open set instead of every
historical journal. A dangling reference is a hold. Terminal canonical writes
precede index removal; a surviving terminal reference can be removed after
reading the canonical record. The directory and files are fsynced.

The connector flock remains the single local writer. These records supplement
Hollywood's authoritative delivery and command receipts; they do not establish
that an external effect did or did not happen.

Use --list-attempts for private metadata inspection. Use --reconcile-delivery
<original-id> --generation <original-generation> to read and settle only a
captured original attempt. Neither action admits a model turn. Old-attempt
recovery cannot replace an actively running native transport. Native snapshot,
transition intents/receipts and recovery pacing are stored under that attempt.
A source-matching existing transition intent is preserved during import.

Recovery checks only tool records belonging to the original request and native
thread. Uncertain effects from other attempts remain retained independently.

This change retains the existing semantic hold on ordinary work. It does not yet
authorize Global control while an older effect is unknown. That requires the
independently attested executor lifecycle, Hollywood control authorization,
the enforced native tool ceiling and parent-generation mutation fencing.
