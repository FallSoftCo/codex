# Host execution and provider access

Workers default to the unrestricted execution profile: native danger-full-access,
NoNewPrivileges=no, and verified passwordless sudo. Linux identities, workspaces,
captured responsibilities and execution receipts remain individual. Addressed
work remains the execution trigger. Full host access does not create tasks or
resume historical schedules. The restricted profile is an explicit choice.

Historical provisioning receipts remain immutable. Administrator-owned execution
policy upgrade receipts link new configuration/unit hashes to the original spec.
Apply changes after the current native execution ends; preserve active work and
unknown outcomes. Service ordering must not couple agent process lifetime to a
Hollywood HTTP restart.

The GitHub client provider preserves caller UID and working directory and reads
installation-authorized credentials privately into only its CLI child environment.
It stores no persistent credential copy in worker homes. The host deploys the same
lax_connector.github_client module at /usr/local/lib/harness/github_client.py,
a /usr/local/bin/gh entrypoint and a root-owned, authority-specific provider record
at /etc/harness/<authority>/github-provider.json. Other identities retain their own
normal GitHub authentication. The host-specific Git credential helper uses this
provider; existing user configuration takes precedence.

Provider setup needs legitimate operator authorization. Model login and service
health do not prove provider, Git, SSH or build access. Verify actual operations
under agent identities; a dry-run push can test write negotiation without making
a remote branch. Complete enterprise credential enrollment and install/upgrade
orchestration remain separate installer work.

Managed-service upgrades must finish protected execution registration before
being called ready. A healthy systemd process is insufficient. The administrator
uses lax-service --authority <id> --host <id> --agent <id> --inspect to compare
the actual unit/native image/invocation with its root-owned enrollment. It makes
no changes and reports a stopped service without enabling it. After a deliberate
drain and upgrade, use --approve-drained-upgrade with the two digests returned by
inspection; old invocation manifests and upgrade receipts remain preserved.
Unchanged service restarts use --register. None of these commands repairs,
replays, cancels or claims an uncertain delivery.

Worker provisioning now registers its actual service before returning execution
readiness, and repeated inspection exposes registration drift separately from
configuration and systemd health. For a launch denied before native birth, retain
the failed attempt, establish independent stop evidence, and use the existing
explicit work recover/assign lifecycle. Do not reset an unknown request to pending
or delete its journal. Permission policy changes and execution enrollment belong
to one upgrade procedure, even when the native binary did not change.

Fresh Global installation enables the existing portfolio supervision policy from
its activation sequence. It coalesces typed material reports/incidents, retains
one outstanding review and deduplicates unchanged snapshots. The default allows
four material reviews per minute; excess material stays pending. Passive chat
and a clock tick do not create model work. Existing policies, deliberate disabled
supervision and stopped services are preserved during setup reconciliation.
Previously returned reports need an explicit bounded handoff; installation never
backfills historical work or replays it. A business goal's finite reviewBudget
does not replace ongoing Global portfolio supervision.
