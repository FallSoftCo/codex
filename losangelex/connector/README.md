# Native LAX agents in Hollywood

LAX agents retain their own native execution context across Hollywood rooms,
human participants, work assignments and retries. Hollywood owns communication,
room membership, durable requests and receipts. NextComp is a Hollywood client.
The installed agent can create rooms/peers and delegate using ordinary tools.

See [PERSISTENT_AGENTS.md](PERSISTENT_AGENTS.md) for the operating model,
authentication, context migration and end-state acceptance. Native LAX remains
the execution engine: model, commands, plans, questions, approvals and activity
use the maintained upstream runtime without requiring its TUI.

The LAX package provides:
- lax-connect: deterministic resident agent or original-operation reconciliation.
- lax-provision-global and lax-provision-worker: actual Linux identities,
  approved model authentication, runtime, workspace and service enrollment.
- lax-agent-context: explicit adoption of retained context and metadata-only
  retirement of a legacy synthetic role goal.
- lax-host and lax-service: independent execution observations and protected
  service enrollment/readiness.

Global installation optionally accepts environmentProfileFile. This declares
approved non-secret repository, GitHub, SSH and build routes for its authority.
Normal hollywood_context reads those installation facts. Missing declarations
remain explicit; configuration does not by itself prove account/build readiness.

The persistent agent execution binding is independent of native goal IDs.
Business goals and plans remain available. Artifact submission and independent
acceptance establish work delivery; completing a model turn or native goal alone
does not establish an accepted outcome.

Staged completed-original reporting is documented in
[COMPLETED_REPORT_RECONCILIATION.md](COMPLETED_REPORT_RECONCILIATION.md). Its explicit
later-participation tool preserves ordinary captured reporting and still requires
matching server qualification and independent acceptance; no work is restarted.

Cancellation retains desired stop and observed execution separately.
Recovery reads original delivery/claim/generation, native thread/turn and tool
receipts. It never repeats an unsettled model turn or external mutation.
Optional room observations do not start models or acknowledge themselves.

Current real-provider journey: two installed agents, six native turns, exactly
two persistent contexts. Global creates/provisions a peer and room, delegates,
independently accepts artifacts, continues in another room, survives a harness
restart and handles another human. The peer retains pending work/context across
an idle responsibility change. Active changes are held; passive traffic admits
no turns; original cancellation settles. Retained-context adoption and HTTP
isolation are qualified separately without provider inference.

The former room/work/attempt context and synthetic role-goal architecture and
its historical proofs remain in Git at c8e264cfe5adb27aca6c7fa6134a000fdb59faec.
They are historical evidence, not the current operating contract. The six-turn
journey is a bounded one-host proof; it is not physical-phone voice/push,
second-host migration or autonomous business/revenue qualification.
