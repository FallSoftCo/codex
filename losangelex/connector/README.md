# Native LAX agents in Hollywood

LAX agents retain their own native execution context across Hollywood rooms,
human participants, work assignments and retries. Hollywood owns communication,
room membership, durable requests and receipts. NextComp is a Hollywood client.
The installed agent can create rooms/peers and delegate using ordinary tools.

See [PERSISTENT_AGENTS.md](PERSISTENT_AGENTS.md) for the operating model,
authentication, context migration and end-state acceptance. Native LAX remains
the execution engine: model, commands, plans, questions, approvals and activity
use the LAX-owned native runtime without requiring a TUI.

Peer deliveries use the native hollywood/agentMessage API and remain
agent-authored model input. Human deliveries retain human provenance. The
installed LAX contract and Hollywood tools are selected together; upstream local
subagent backends are disabled for this runtime. Canonical packaging supports the
standalone headless app-server entrypoint as well as retained CLI packages.
The focused native integration checks the actual mock-provider input, tool
inventory and model-switch behavior; it does not establish live model cooperation
or complete enterprise readiness.

The LAX package provides:

- lax-agent: independent durable reader, writer and responder runtime contexts.
- lax-provision-global (also lax-provision-native-global): native first-Global
  preparation, host/collaboration enrollment, readiness sealing and explicit
  first activation. Both names use the same implementation.
- lax-install-agent: the same native purpose installation for peers.
- lax-connect and lax-provision-worker: retained single-context installations
  and original-operation inspection; these are not the first-Global default.
- lax-agent-context: explicit adoption of retained context and metadata-only
  retirement of a legacy synthetic role goal.
- lax-host and lax-service: independent execution observations and protected
  service enrollment/readiness.

First-Global installation requires an explicit
`lax-first-global-install/v1` profile passed with `--spec`; use `--activate`
for the first activation after readiness seals. The profile references the
Hollywood bootstrap's protected original installation intent, explicit host and
private endpoint, approved native binary/interpreter, model/account, host policy
and optional environment profile. Provisioning prepares the Unix identity and
three purpose bindings before installing shared host infrastructure, then seals
the actual installed channel, resource and account facts. It starts no model
turn. Accepted human or peer work is the source of inference.

Re-running setup reconciles the same identities and original receipts. Once
initial activation is recorded, `--activate` reads service status and preserves
a deliberate stop. An existing single-context Global requires explicit adoption;
the native factory refuses to replace it. The retained
`python -m lax_connector.linux_admin` primitive is not the default setup path.

The factory prepares a disabled systemd startup target for this Global's three
purpose services, host observer and native collaboration bridge. Additional
already-installed API/client service units can be declared with repeated
`--startup-service UNIT` arguments. Later reconciliation retains that exact
membership and the operator's current enabled/disabled state. It does not
automatically enroll peers or historical installations at boot.

Use `--enable-startup` or `--disable-startup` for an explicit boot-policy change.
These commands never use `--now` and do not start, stop or restart current
execution. Native first activation remains `--activate`; subsequent setup
preserves deliberate service stops. The target is an ordinary systemd boot
dependency group, not a work scheduler. Current execution and boot policy remain
separate operator actions.

The packaged SDK102 installer passed an actual owned seven-service cold restart:
the same three native histories, six inference permits and original completed
request/answer receipts remained unchanged. Default setup preserved a disabled
target and deliberately stopped responder. This is installation restart
evidence, not a host reboot, shared database restart, phone, voice or push proof.
See `qualification/native-startup-20261019.json` and the explicit
`tests/integration_native_boot.py` integration runner.

This factory still does not provision the Hollywood API/database or NextComp
gateway. Those dependencies must already be installed, their own boot/database
dependencies configured, and the actual private API available for sealing.
Do not describe factory readiness as a complete enterprise installation.

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

The connector consumes canonical bounded resource discovery, revisioned
agent/host defaults and placement pause/resume. Relative intent uses an explicit
current default while ordinary absolute native patches remain independent.
Reviewed installer seeds now publish routing metadata through supported APIs,
including held setup for paused placements. See
[NATIVE_COLLABORATION_SETUP.md](NATIVE_COLLABORATION_SETUP.md) for exact gates,
protected capture and the maintained drained bridge transition. Root owns actual
installed/native acceptance and rollout; this source package performs no deployment.

Dev46 adds approved same-image guardian registration through the existing host
controller after genuine service restarts, explicit fresh service memory ceilings
and reviewed memory previews. See [NATIVE_LAUNCH.md](NATIVE_LAUNCH.md) for one-time
activation pins and existing-service upgrade requirements. The controller starts
no stopped service or task, and a higher ceiling is not a memory leak fix.


Connector dev47 consumes the published canonical-work-delivery-edits/v1
capability. An original assigned business Work can use native delivery edits
under its independent writable resource grant. The backend derives Work
authority; the consumer pins its additive permit proof without changing the
delivery DTO or dropping original identifiers. Explicit native plan callbacks
retain consent/integrator checks, and claims, ready scopes and unsettled permits
continue to share the physical conflict domain. See NATIVE_COLLABORATION_SETUP.md
for the maintained drained upgrade; include Global and all three team consumers
in the explicit scope before activating a four-agent installation.

### Approved service runtime

Release approval reloads the reviewed unit metadata into systemd before publishing
its accepted software pointer; it does not start a service or admit a model turn.
Registration and readiness also verify the live guardian's configured interpreter,
connector module and configuration path. Matching files on disk alone do not
establish which installed release is running. A pending manager reload or mismatched
launcher stays unavailable until the approved lifecycle completes. A busy inspection
lock is reported separately from an unsettled image transition; it grants no execution.

Release transitions pin predecessor receipts by operation identity and canonical
digest; they do not recursively embed the entire previous release. Original
accepted/interrupt records remain immutable and readable. A bounded 32 MiB
compatibility budget covers the captured legacy 18 MiB interrupted record; both
writes and reads enforce the same ceiling. Reconciliation still requires the
original operation/digest and the unchanged offline scope.

## Native human questions

In the Hollywood-native runtime, hollywood_ask returns a durable pending
Attention receipt without holding the inference turn. Hollywood retains a
question with request.isBlocking=false after that input is handled and queues
the attributable human's authenticated answer into the same agent context.
The native runtime excludes the competing upstream single-user UI tools.
The server's canRespond and responseMode fields describe current actionability;
an accepted answer and completed semantic work remain separate. Command and
file approvals retain their original callback and permission scope.
This requires the matching Hollywood human-continuation implementation; older
servers cannot silently supply the native continuation contract.

Native terminal output uses the same projection for live execution and original
receipt recovery. Commentary stays in the activity stream. Only a completed
inference may publish its final (or unphased) model reply; cancellation and
failure publish the observed lifecycle outcome instead of an earlier model plan.
This does not equate inference completion with Goal or Work acceptance. Metadata
readback also keeps native mode enabled and never starts or resumes a model turn.
