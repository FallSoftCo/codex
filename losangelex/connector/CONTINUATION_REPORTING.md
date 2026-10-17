# Explicit reporting from a private continuation

A private continuation keeps its default direct reply to the captured author.
It does not become a public request, create human input, replace the persistent
agent context or grant a new execution obligation.

The pre-native causal hook may return a bounded replyScope for a newly authored
public status summary. The transport accepts this only for hollywood_publish
with explicit audience=room and roomId, no recipient, and a verified scope bound
to the exact current delivery/claim/request. sourceEventId may be omitted; when
provided it must equal the selected verified public source. A caller-supplied
source reference, a copied JSON context, or data.type alone cannot establish
authority. Requests and private-origin exchanges keep their existing boundary.

For a peer completion, existing canonical child/result/locator checks prove the
original public request. For a portfolio Goal review, the hook separately verifies
the canonical enabled policy and exact recorded review delivery/digest, current
Goal source, and original addressed request locator. Cross-room Goal reports also
require the existing explicit-planning-intent/v1 source event. The original
request room and its explicitly selected Goal room are the only report scopes.
Private delivery-incident reviews have no Goal reporting exception.

The serialized fragment stays within the existing 960-byte bound and remains
tool data. It includes the public reply scope and canonical inspection references.
Full proof stays in the connector's in-memory VerifiedContext object; private
audits retain original attribution. A public summary never receives a private
request/result body automatically. Its body comes only from the intentional
publish call; access to private evidence still does not authorize copying it.

The existing message POST transaction must still authorize current room posting
rights, current native source and readable source event. Canonical delivery/claim
headers remain the private current execution while the message's source points
to its verified public causal origin. No backend or DTO change is required by
the inspected policy/item/Goal/source contracts.

Existing connector.py call sites remain unchanged: retain prepare_context's
returned object on c.causal_task_context and call participation.message normally.
Do not flatten that in-memory object into plain JSON before dispatch: doing so
safely loses the reporting proof. Scope checks occur before the existing effect
journal's POST; operation IDs, wire digests and original lost-reply receipt
recovery remain unchanged. An already refused original tool call stays refused;
a later intentional summary uses a new call identity. Unknown effects are never
retried.

The dedicated fixture records filtered real QA failure metadata with its source
hash and omits the private outcome body. Canonical GET rows in loopback HTTP
tests are explicitly synthetic. These tests qualify transport/privacy/receipt
boundaries, not model behavior. Root must separately qualify the actual Global
continuation in its original Goal on the integrated installed candidate.
