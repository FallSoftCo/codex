# Additional conversational agents on one native account

This is an explicit **same trusted unrestricted account** boundary, not OS
isolation between logical agents. Restricted, unrelated and purpose-separated
profiles are not merged. A room membership never grants this attachment.

## Enrollment contract

The existing13 tool declarations/arguments remain byte-for-byte unchanged. An
operator must separately approve the same-account factory boundary; a role or
tool invocation does not imply this opt-in. The maintained local metadata-only
command (not executed on a live installation by this candidate) is:

```
sudo APPROVED_PYTHON -I -B -m lax_connector.shared_account \
  --authority AUTHORITY_UUID --host HOST_UUID --expected-manifest-sha256 SHA256
```

It creates a protected `shared-account-policy.json` beside the existing manifest,
without changing its service, profile, credentials or native thread bindings.
The room factory requires that policy, captures the current canonical manifest
SHA256 and original owner, and passes this explicit root-installer contract:

```
nativeHostServer: true
nativeHostAttachment:
  ownerAgentId: <original native host owner UUID>
  manifestSha256: <exact original protected manifest digest>
  trustBoundary: same-account-unrestricted/v1
executionProfile: unrestricted
```

Authority, host, profile, actual NSS service identity, private original model-auth
file identity, native image and initial manifest CAS must agree. This is not a
credential-copy or “equivalent account” mechanism. Missing opt-in fails before
account/installation effects; partial old installations require their original
reconciliation, not replacement specs or identities.
The original owner's protected Global sudo-verification or unrestricted worker
policy receipt must also agree; caller opt-in cannot promote a restricted owner.

The additional connector uses the original native service UID, **without creating
a user, CODEX_HOME, model-auth copy, sudo policy or native daemon**. Its canonical
`workers/<agent>/home` contains its own workspace, connector configuration, state,
initial native-thread journal and message receipts. Root records the immutable
account/profile binding in `shared-native-account.json`. It does not modify the
original daemon manifest or its accepted installation receipt. Native bootstrap
creates and names a different thread with that agent's own tools/instructions.

The service UID's NSS home and the logical agent home deliberately differ.
Package startup uses the real NSS home/profile and the agent's own cwd. Observer
registration and physical release guards resolve the protected binding rather
than inventing another `hworker-*` account. Legacy private-worker/global records
retain their original NSS checks and accepted formats. No manifest, socket peer,
image identity, native per-thread callback or foreign-thread RPC check is waived.

## Stops and release boundary

Attaching inspects the original native service; it never starts a stopped daemon.
Additional connector units have `After=`, not `Wants=` for the host daemon. Lost
bootstrap receipts retain original uncertain native thread creation; a retry does
not manufacture another context. Completed provisioning reconciliation remains
read-only and preserves stopped workers. Restricting a shared worker requires a
separate explicit profile migration, not a policy flag on the trusted UID.

Connector-only releases retain the exact accepted shared native image. Preparation
and transition revalidate the protected binding and both logical/shared physical
paths. Connector-only read-only inspection, for owner and additional agents,
checks that agent's idle thread without draining other loaded agents. The
original private-to-shared adoption path still
requires coordinated owner drainage. Reconciliation carries the same binding and
does not replay input or restart the daemon.

**Remaining engine-release gate:** the existing owner-only paired engine/client
upgrader is not an atomic multi-client transaction. Once attachments exist, it
fails closed with their IDs instead of stranding them. A future coordinated
multi-client engine release/retirement workflow must be reviewed before changing
that shared image. The transition rechecks this inventory, and new enrollment
refuses an unsettled owner image intent. This candidate does not silently extend
that authority.

## Qualification and limits

`test_shared_account.py` uses root-owned disposable on-disk metadata, synthetic
NSS facts and intercepted OS/service commands. It covers actual provisioning and
inspection control flow, distinct layouts, observer/release resolution, same
account/CAS rejection and deliberate stops. It does not install a real service.

`integration_shared_agents.py` runs one accepted native binary against an owned
loopback synthetic provider, with two distinct agent IDs, threads and workspaces.
Actual dynamic callbacks enter `RoomTools`; publication receipts use an owned
synthetic Hollywood transport. It checks cancellation, reconnect, message authors,
foreign-thread rejection and existing-client inspection while another thread is
loaded. It uses no account auth or live Hollywood, and is not real-provider,
production-systemd or malicious-same-UID isolation certification. UID-derived legacy
environment helpers still describe the service account, not a new logical agent;
no per-purpose environment identity is inferred or installed by this feature.

Root owns integration/release. Do not apply this source to live instances, restart
workers or replay accepted provisioning operations merely to run these checks.

## Readiness and original factory recovery after an SDK update

Observer/service registry paths remain the logical agent's home and state. Only
the protected `shared-native-account.json` + original manifest/profile evidence
may resolve package preflight to the original NSS service home. The package
probe still enforces exact NSS equality and uses the logical agent's own `work`
directory as cwd. Ordinary private-worker, Global and purpose installations keep
their original NSS guards. Provisioning already made this distinction; service
readiness and legacy image-approval preflight now make the same distinction. Release
probes continue using their protected shared physical-identity binding.

Factory recovery never regenerates or rewrites `spec.private.json` after an SDK,
name, role or manifest change. Its original credential, interpreter, agent, room
and host binding remain intact. Once dispatch might have occurred, subsequent
calls may ONLY inspect that installation, never invoke its installer again.

Cross-SDK inspection selects the CURRENT connector interpreter separately, records a
private immutable `inspection-runtime-<digest>.json` selection, then invokes
`linux_worker --inspect --inspection-owner OWNER --expected-spec-sha256 SHA`.
The privileged helper requires that interpreter and maintenance module to belong
to OWNER's accepted, settled, integrity-verified release on the same host. It
holds that owner's release lock while reading the distinct worker's original
protected receipts; original worker runtime/configuration are not upgraded.
Missing acceptance, foreign scope, changed code or spec CAS fails closed. It
does not accept arbitrary replacement Python paths or source overrides.

Each new inspection attempt/receipt is retained separately, including failed
attempts. A conclusive original accepted dispatch is returned without running
either installer or inspector again. Unchanged same-interpreter recovery keeps
its legacy `--inspect` contract; the new accepted-release gate is required when
selecting a different maintenance interpreter. Legacy `--inspect` also remains
available to the owning explicit operator; no tool declaration changes are needed.

The focused fixtures qualify service-readiness control flow through the strict
package/NSS probe, original admin reconciliation across SDK changes, protected
maintenance-release validation and no duplicate installer dispatch. Process,
service-manager and provider facts remain synthetic; live readiness correction,
the original QA-agent request and cleanup remain the release owner's gates.

SDK238 maintenance inspections take bounded shared registry snapshots using the operating-system flock wait. They do not fail immediately during an ordinary observer write, poll a model, remove a lock or acquire two registries together. The owner release is verified before and after the separate worker inspection; a changed or unsettled release still rejects the result. Existing mutation writers retain exclusive nonblocking locks.

The actual installed Linux/native callback and command/reply journey is recorded in [qualification/shared-native-live-20261101.json](qualification/shared-native-live-20261101.json). Private operator receipts retain exact identities and original failures; this sanitized receipt states the exercised boundaries and remaining limits.
