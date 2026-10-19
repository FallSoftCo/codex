# Purpose-native LAX runtime

Hollywood owns rooms, authenticated communication and durable work references.
One LAX agent has three persistent native histories: reader, writer and responder.
A room does not select a history or execution account. Only the responder emits
intentional messages; writer execution activity is a separate attributed stream.

lax-install-agent --spec FILE is a root installation operation. It validates
canonical Hollywood enrollment, creates a Unix account, verifies the complete
native package and model account under that identity, and installs three systemd
units under one aggregate resource slice. --activate starts only that recorded
installation. An existing activation intent is observed rather than replayed.
The installer does not enable historical sessions, infer work completion, or run
a model. The native runtime wakes from newly admitted canonical material.

Global's lax_provision_worker uses this same installer for a new peer. Enrollment
credentials and purpose tokens are stored in protected files, never tool output.
Each peer has independent native histories, state and workspace. The workspace is
an explicit host-local route; another agent or host must not assume it is shared.
Approved model account identity is checked without overwriting independently
refreshed per-context authentication.

A writer admits original work through Hollywood's shared native claim transaction.
An installed guardian captures its actual resident app-server incarnation through
the existing executor API. The enrolled host controller independently checks its
systemd invocation, UID, executable, PID/start time and cgroup. A turn starts only
after that check and an inference permit. Work claims are durable; inference
permits count active inference, not room memberships or resident idle processes.

The runtime protocol is lax-purpose-runtime/v3. An immutable context-begin
receipt binds a writer turn to its original work, claim, generation and actual
executor. Native mutations use hollywood-native-source/v3, validated inside the
same database transaction as the domain change. There is no synthetic native
goal or legacy agent-execution binding. Reader/responder credentials cannot
borrow writer mutation authority. The shared native handlers retain original
effect journals, command receipt reconciliation and actor attribution.

Old v1 scopes remain readable for delayed execution logs. New v2 execution scopes
carry their executor identity. Neither a log nor a closed model turn proves work
completed or an external effect absent. Unknown delivery and process outcomes
remain held for original-state reconciliation; service restarts do not authorize
replaying external effects.

## Qualification boundary

The 2026-10-19 private authority preserves the original three histories and uses
a newly installed matching Unix identity. PostgreSQL tests qualify claims,
turn scopes, writer mutation authority and invalid-source rejection; their
frozen process facts are not actual execution evidence. The live Global-created
peer/operator-tool journey separately qualifies the installed native path.

This stage does not switch production NextComp profiles, publish a phone update,
qualify multi-host shared editing, or migrate historical sessions. Native
collaboration bridge capture and later completed-report reconciliation still
need purpose-aware integration. The ordinary enterprise bootstrap must adopt
this installation path before a default cutover is claimed.
