# Protected native collaboration setup

The candidate connector is version `0.1.0.dev46`. Its installer and automatic
capture paths are staged source. Root owns installation, controlled activation
and genuine native qualification. Component tests do not establish that a normal
room task, shared edit or later continuation works end to end.

The enrolled host-controller credential relays native operations. A separate
administrator credential registers physical roots and canonical per-agent access.
Structured assignments additionally retain their existing work grants.
Neither credential enters the native descriptor, model arguments or model
context. The bridge authenticates the exact native process and independently
observed service incarnation before consuming frame bytes, then derives the
running turn and unchanged private context from canonical receipts.

## Native package installation preflight

Global and worker provisioning require the complete Linux CLI package produced by
`scripts/build_codex_package.py`. Configure its `bin/codex` entrypoint and retain
`codex-package.json`, `bin/codex-code-mode-host`, `codex-resources/bwrap` and
`codex-path/rg` in the upstream layout. Copying the CLI alone cannot pass.

Provisioning and registered service readiness run the package preflight through
the installed interpreter in isolated mode as the recorded service UID and home.
The writable work cwd and `PYTHONPATH` cannot select its module. The check verifies
metadata, host target, readable executable assets and their SHA-256 hashes, then
runs four bounded startup diagnostics: CLI version, code-mode-host help, bubblewrap
version and ripgrep version. It never widens private directory permissions. Normal
connector admission and enterprise native startup repeat the check under their
actual execution identity; a missing or inaccessible helper prevents readiness
and startup. Read-only historical recovery modes remain available.

The `nativePackage` receipt proves only these package and startup checks. It does
not prove sandbox/tool execution, model access or a successful ordinary task.
Root must still qualify the installed complete package through the original task
and same-context continuation before accepting the runtime.

## Explicit offline native image transition

`lax-service --approve-image-upgrade` is a separate administrator operation from
`--approve-drained-upgrade`; the latter still forbids image changes. Supply the
original `--expected-enrollment`, reviewed `--expected-definition` and exact
`--expected-image-sha256`, together with authority, host and agent IDs.

Before invoking it, the administrator must disable the agent's canonical
placement, settle all original deliveries/executors, and stop its managed service
with empty original cgroups. The operation never changes admission, starts a
service, registers a guardian or resumes a model. It requires the unchanged
identity, unit, binary path and private home, exclusive connector and registry
locks, read-only settled journals, disabled placement with no busy/pending work,
independently stopped canonical executors, the complete package preflight under
the actual service UID, and a root-protected exact image. Directory/file handles,
SHA-256 and repeated identity checks fence local path replacement and changes.

Original enrollment and transition intent/acceptance records are retained.
An interrupted intent holds registration and readiness for explicit original-effect
reconciliation; repeating the command never recovers or reapplies it. The operation
returns `executionReady: false`. Root separately starts and registers the reviewed
service, qualifies actual tasks/continuations, and only then re-enables placement.
A disabled placement is an administrator-maintained admission boundary, not a
server lease: concurrent privileged re-enablement, transfer or manual registry
writes are outside this local operation. Production requires that coordinated
boundary and independent installed-runtime qualification. Fixtures do not prove it.

## One installation, automatic current-turn capture

Run these commands only from the administrator's reviewed setup environment.
Preparation creates immutable root-owned files and a service definition. It
starts no service and changes no canonical registration.

```sh
lax-collaboration --prepare /run/owned-setup/policy.json --output /run/owned-setup/prepared
```

The policy file and all its ancestors must be protected from other users. Its
administrator config is a root-owned JSON file with `authorityId`, `hostId`,
`hollywoodUrl` and `token`. The enrolled controller config retains its separate
controller credential and existing machine identity. Do not place credentials
in chat or in the policy example below.

```json
{
  "schema": "lax-collaboration-install/v1",
  "controllerConfig": "/protected/host/controller.json",
  "administratorConfig": "/protected/host/administrator.json",
  "interpreter": "/protected/runtime/bin/python",
  "resources": [{"name": "shared", "root": "/absolute/approved-resource", "environmentId": "local"}],
  "agents": {
    "<existing-agent-UUID>": {"resources": ["shared"], "defaultResource": "shared"}
  }
}
```

Resources are an installation policy, not per-turn model input. Their UUIDs are
derived from the actual enrolled host, local environment and opened root inode.
Aliased/nested roots and changed inodes are rejected. Every agent granted the
same physical root uses the same physical namespace while keeping its own
private context, thread and workspace binding. Optional `runtimeDirectory` (public descriptor), `socketDirectory`,
`stateDirectory` and `unitDirectory` permit an isolated owner-controlled setup;
service argument paths must be literal absolute paths. The socket lives in a
separate named `/run` directory managed by the unit's RuntimeDirectory. Service
stop removes that socket directory while retaining descriptor, credentials and
original effect journals. Existing private ancestors are never widened to make
native access work; choose a separate traversable public directory.

Review `setup.json`, the unit, source hashes and protected configuration before
applying that exact prepared cut:

```sh
lax-collaboration --apply /run/owned-setup/prepared
```

Apply uses explicit administrator CAS operations, preserves original receipts
and writes the reviewed unit/configuration. An uncertain registration/grant is
inspected by its original administrative command identity; its PUT is never
repeated. A changed/revoked existing bridge requires explicit drained upgrade
review. Apply never calls systemctl or starts/restarts a model or service. Root
separately arranges controller reload, daemon reload and bridge start only in the
reviewed activation scope, preserving all live contexts and unknown effects.

The standard public descriptor is
`/etc/harness/<authority>/collaboration/<host>/channel.json`. It contains only the
schema, root-owned socket and implemented ports. The candidate connector finds
this descriptor without editing a worker's private configuration. For an
isolated custom descriptor path, an explicitly configured
`nativeCollaborationChannel` remains supported.

The v2 host observer captures current native turns from canonical delivery and
per-agent resource grants. An installer seed is reviewed initial access intent,
not a runtime whitelist: grant/revoke access with `hollywood_grant_resource` using
exact current workspace and grant CAS revisions. New managed workers inherit an
explicit custom descriptor path and need no bridge configuration rewrite.
Root/resource identities, actual local process root view and grant revisions are
checked again on native IPC. A revoked/changed grant holds an existing channel;
it never silently replaces that channel's original authority.

The original actor, delivery, claim, generation, native thread/turn, current role
and persistent context binding must agree. Ordinary source requests have no Work,
Goal or plan. A request actually carrying workId retains the original planned
work grant, consent and integrator checks; a caller cannot switch it to delivery
scope. Closed original channels are archived only after terminal delivery and
stopped executor evidence. Unsettled channels and command journals are retained.

## Normal authorized task path

An admitted ordinary room request can use native apply_patch on absolute paths in
its approved local resource. The captured adapter posts the exported
`canonical-delivery-edits/v1` preflight/begin/settle envelope. It does not create
work or a plan. Git is optional: direct regular-file patches explicitly carry
`sourceRevision: null`, exact before/after hashes and the actual physical target.
The target action digest covers the normalized complete non-target envelope.

Before turn/start, and after an explicit owner briefing read, the actual managed
connector guardian carries that owner-authenticated briefing's exact scope and
asOfSequence into the root-protected `briefings` store through the metadata port
`owner-briefing/v1`. Kernel PID/UID, original managed enrollment/incarnation,
canonical claim/context and role must match. Native children cannot use this
metadata source. The bridge cannot impersonate the owner to fetch its briefing;
v2 never substitutes zero, Work revision, a global head or the owner-writable
briefing cache. The observed watermark freezes with the original permit. This
records authenticated observation, not model understanding or full read coverage.
A metadata gap permits ordinary reads/commands while editing remains held.

A structured assignment still uses typed plan/coordination intent and the
existing planned mutation protocol. Its current resource list comes from the
administrator-authorized bounded agent catalog: the ordinary-only controller
`delivery-targets` route must never be used for a Work request. Current per-work
grant revisions, consent and integrator ownership remain separate from agent
grant/default-pointer revisions. This release does not change Work editing mode.

Relative v2 plan/claim intent resolves the explicit canonical agent/host default
through `collaboration/delivery-resource-default/{delivery}` at that intent call.
It requires `resourceRouting=canonical-agent-resources/v1`, `resourceDefaults=true`
and `resourceMetadata=true`. Missing, cleared, held, incompatible or unsupported
routing holds the relative intent even when cwd happens to lie in an approved
root. There is no first/sole/cwd fallback. Absolute native patch paths retain
their independent approved physical-root checks. Context/thread/cwd stay intact.

The reviewed `defaultResource` seed is now published through the exact canonical
default-selection API after the explicitly reviewed agent access seed. Selection
pins current root and agent-grant revisions and has its own CAS revision. An
existing clear or changed selection is never overwritten by an installer retry;
matching existing held metadata remains held. Accepted metadata receipts are
historical evidence, not fresh routing authority. Original operation IDs and
administrative GET receipt recovery are reused without repeating uncertain PUTs.

Native tools expose one bounded page of registered roots (administrator only),
agent resources (administrator or owner), and the current default. Use
`hollywood_resource_roots`, `hollywood_agent_resources` and
`hollywood_resource_default`; inspect revisions before
`hollywood_select_resource_default`. Clear requires explicit null workspace and
root/grant revisions. Pages default to four rows, cap at eight and 32768 ASCII
bytes; each page reauthorizes and returns its own nextCursor. Oversize responses
hold without truncation. Normal owner agents obtain the capability flags through
the existing protected guardian briefing receipt, since the canonical bridge
capability endpoint itself is restricted to enrolled controllers/administrators.
This changes no backend authorization or model admission.

Both paths share the server's existing physical path/permit conflict domain.
Only the original non-replayed one-shot begin response permits application.
A lost begin is inspected through the original command receipt; a recovered
receipt never supplies a second grant. Cancellation, unknown outcomes and held
permits retain their locks. Direct GET uses effectiveState, never raw permit
state, to judge settlement. Model-facing replies retain the existing 8192-byte
bound. The wire requires explicit deliveryEdits capability and exact schema;
there is no legacy mutation fallback.

## Existing bridge: reviewed drained upgrade

Fresh `--apply` deliberately refuses changed installed artifacts. Use a new
immutable preparation for the reviewed dev46 adapter, then inspect the actual
original files and canonical bridge revision. Keep the original setup receipt.
The upgrade preserves the same authority, host, machine, credential, socket,
state directory and actual physical root inodes. List every affected consumer;
existing channel owners and all protected services on that host must be included.
No unrelated authority or consumer is changed.

Schema29 adds `hollywood_placement_read` and `hollywood_placement_set` for the
published `canonical-placement-control/v1` interface. The setter requires an
inspected revision and the same host, uses current native provenance and original
administrative receipt recovery, and preserves registration/generation. Pause is
not process drainage and cannot withdraw an already-issued apply grant. Resume
admits no work itself; a paused agent cannot bypass the backend's current-source
fence to resume itself. Root uses an independently authorized administrator.

A drained upgrade requires both that placement capability and
`pausedResourceSetup=true` before publishing its bridge transition intent/CAS.
Agent grants and a new default pointer can then be prepared while paused using
unchanged DTOs. The prepared default is held until explicit resume and current
root/access pins match. A selection invalidated when pause occurred stays held. During a reviewed
paused upgrade, an exact matching seed now explicitly CAS-reselects only the
known `participation-invalidated` case with unchanged current root/grant pins.
The successor remains held while paused and can become eligible on explicit
resume. Cleared/different/unknown access is never silently rebound, and unknown
hold reasons remain held. Initial r13 operation identities and uncertain original
receipt recovery are preserved.
The upgraded result records the default views, including held states.

Disable the scoped placements, settle original effects, and stop the scoped
consumers, host controller and bridge through Root's admitted orchestration.
The upgrader requires disabled/no-busy/no-pending agent placements, no nonstopped
canonical host executors, stopped/empty consumer and bridge cgroups, exclusive
connector and protected service registry locks, settled read-only execution/tool
journals and settled bridge permits. It changes no placement or service state.
Privileged concurrent placement/configuration changes must remain excluded by
that orchestration; this local operation is not a server admission lease.

```sh
lax-collaboration --upgrade /run/owned-setup/prepared \
  --expected-bridge-revision 7 \
  --controller-unit <installed-controller.service> \
  --expected-controller-unit-sha256 <SHA256-of-installed-controller-unit-bytes> \
  --expected-config-sha256 <SHA256-of-installed-bridge.json-bytes> \
  --expected-unit-sha256 <SHA256-of-installed-unit-bytes> \
  --expected-descriptor-sha256 <SHA256-of-installed-channel.json-bytes> \
  --scope-agent-id <first-consumer-UUID> \
  --scope-agent-id <second-consumer-UUID>
```

The revision and hashes above are examples/placeholders; use the inspected
original values. Under `state/upgrades/<operation>-before`, it durably archives
original config, unit, descriptor and setup receipt before an immutable intent
and one canonical bridge CAS. That administrative PUT uses original-operation
receipt recovery and is never repeated on an uncertain response. Repeated drain
and artifact checks precede local replacement. Old channel/command/permit and
administrative records are preserved; seed grants have stable original operation
identities. An accepted result requires separate Root-controlled adapter rollout,
daemon reload, controller/bridge start and native qualification. No startup,
reload, model call or native rebuild occurs inside preparation/upgrade.

An interrupted intent holds subsequent upgrades **and bridge startup**, including
an interruption after canonical acceptance but before local publication. Do not
remove it or retry apply to bypass the hold. Inspect its exact archive, original
administration journal and `GET administration/commands/{operationId}`, plus the
current canonical bridge and actual artifacts. Unknown receipts remain held.
Recovery/rollback is an explicitly reviewed original-effect transition: reconcile
the exact accepted original revision first, retain its immutable evidence, and
prepare a new fenced inverse CAS/local restoration if rollback is required. The
upgrader intentionally provides no automatic resume or rollback that might
repeat an unknown effect. A transition interrupted here needs that separately
reviewed recovery before activation; the happy-path fixture is not recovery or
installed-runtime acceptance.

## Continuation and qualification boundaries

The reviewed causal module retains append-only request/delivery/generation
locators and exact accepted delegation edges. Its bounded960-byte agent tool-data
fragment requires deeper original task/result reads and leaves the outcome
unassessed. Both original accepted and lost-reply-recovered requests index their
lineage without resending. Existing legacy delegations need individually named
canonical bootstrap records; no history scan/latest-generation retarget exists.
Private ancestor delegation remains held when the private participant set changes.
Evaluate the public room flow first. This is not a complete private/multi-human
continuation claim.

Runtime acceptance still needs an ordinary authorized room task that edits,
runs and reports through the actual installed candidate, followed by genuine
same-root collaboration and accountable continuation among the existing owners.
Root owns those tests and deployment orchestration. Direct patches support local regular files with no Git requirement. Planned
editing retains its full-checkout Git checks. Linked-worktree external Git
metadata for planned editing, remote/directory mutations and enterprise native
child admission remain unavailable. Arbitrary shell writes remain a cooperative boundary, not a
filesystem transaction guarantee. The service/controller setup does not claim a
durable solution to heavy-command isolation or general enterprise readiness.

## Passive observations on the existing native connection

After ordinary thread loading and canonical context binding, the connector creates
one passive receiver for that persistent context. Its existing guidance pump
checks one bounded inbox page and can append at most one `agent_message`, using
`thread/inject_items` on the already-open RPC connection. The Stop monitor keeps
its independent lane. Native metadata reads and receiver ticks each have a five-second deadline;
unavailable metadata, authority or private journal state records an observation gap and leaves
the ordinary task's native admission unchanged.

The first cursor starts at the current inbox head. It does not scan old messages.
Only eligible agent observations in the current privacy scope enter the native
context, capped at 960 serialized ASCII bytes with an exact original-event read
locator. Human input, requests, results and controls retain their existing paths.
Observation creates no work, model turn, idle wake or second socket reader.

Before an append, the local provider records the actual rollout EOF. Only an
actual fresh native thread/start reply may authorize a zero origin for a not-yet
materialized store. Exact complete raw-item readback from that finite tail must
precede cursor advancement. The tail is capped at 256 KiB, 256 records and 64 KiB
per record. Accepted or uncertain native input is never resent. Replaced,
ambiguous, inaccessible or unsupported stores stay held.

The provider supports a registered local runtime's configured private CODEX_HOME
and native-returned sessions JSONL locator. This trusts the runtime/service UID;
it does not resist root administrators or code running under that same execution
UID, including model commands. Persisted input proof does not prove model
consumption, comprehension or final enterprise acceptance. Root owns the integrated
active-turn qualification.

For a fresh bridge installation, the installer inspects the not-yet-enrolled bridge
with its separate administrator credential. Host-admission reads and runtime relay
continue to use the enrolled controller credential. Preparation must be regenerated
for the new adapter digest; existing changed or revoked installations still require
an explicit drained upgrade. This source change performs no live installation.
