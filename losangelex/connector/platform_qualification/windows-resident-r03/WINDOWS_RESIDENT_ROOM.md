# Windows resident room adapter, pinned common r03

Contract lax-room-origin-platform-adapter/v2, raw SHA
dc525199f336aaabd604026251fec65caf9bfdbf984c1eaca8e9ce1b27db7a2e.
Base SDK246 acc4e932c0fb988e47acfa566981a40da2a56247 unchanged.
New files only; no fabricated source Git commit.

Exact async provision_local(spec_path, operation_dir, *, inspect,
expected_spec_sha256) entry point. This is ONE existing parent host process and
ONE original shared app-server with MANY in-process logical sessions. There
are NO per-agent manager/service/account/process/daemon calls. No Task Scheduler
or WMI calls occur in adapter code; common bootstrap uses original native IPC.
The previous task-based candidate and the earlier state helper with per-agent
manager reads are superseded for integration; retain them only as history.

Windows platform wire fields (within the pinned parentRuntime/nativeIdentity):
parentRuntime={agentId: original parent agent UUID, pid: actual existing parent
PID, roomOriginPolicy:{path: original protected policy, sha256: exact raw SHA}}.
nativeIdentity needs pid, created (Windows platform creation/birth string), image;
optional ownerSidSha256/sessionId also bind exactly. Use this platform's measured
identity representation; PID alone is explicitly rejected.

The protected host policy schema is lax-windows-room-parent-policy/v1. Fields:
authorityId, hostId, parentAgentId, ownerSidSha256, agentRoot,
nativeHostManifest/nativeHostManifestSha256, parentTaskName (label only),
parentRuntimeMetadata (original python.json), parentConfigPath (original private
Global config), approved model/effort defaults when absent from parent config,
parentAcceptancePath/parentAcceptanceSha256.

Root provisions this host-owned policy/agentRoot ONCE at deployment. The existing
host runtime owns its protected startup/admission acceptance descriptor:
schema=lax-windows-parent-runtime-acceptance/v1; same authority/host/parentAgent/
native descriptor SHA/parentTaskName; state=running; admissionAllowed=true;
runtimeIdentity and nativeIdentity with pid,created,image,ownerSidSha256,sessionId;
parentArgvSha256 from the ORIGINAL parent command (normalized first path).
Host manager verification belongs to that single host boundary, never each room.
Stop/drain must close admission; future host-incarnation upgrades refresh this
acceptance/policy through owning review. Per-agent code never invents counters,
starts the parent, or converts an unconfirmed parent into ready.

Actual kernel PID/birth/image/owner/Session1 and original native AF_UNIX peer
are checked against those protected records. Full provision_local additionally
requires os.getpid()==the accepted existing parent PID and sys.orig_argv digest;
an external operator/child is rejected before preparation or bootstrap.

Fresh config keeps origin room only/from0, initial and resume role instructions,
SDK246 exact tools, existing model/effort/profile/native manifest and explicit
initial full-access/never. Every operatingInstructions path+SHA is verified as a
real non-reparse file and appears in BOTH initial and resume instructions. Old
thread/adoption/profile inputs and parent Global thread reuse are held. Agent
paths derive from host agentRoot and canonical reserved identity. Protected
state, original op/config SHA and kernel lock remain immutable across retries.
No auth file is copied and no old room input/output database is imported.

Existing room_bootstrap initializes/persists/name once. Inspect returns original
ready receipt without RPC. Proven connecting/transport-unavailable phases with
threadStartAttempted=false may resume the SAME original operation. Any uncertain
thread/start, created or naming phase holds without a replacement/start replay.
Safe local failures retain original phase/intent and do not expose config/token.
Existing unknown outbox/receipt files are neither cleared nor resubmitted.

Return is LOCAL ONLY. sessionConfigPath/sessionConfigSha256 point to the accepted
owner-private config containing its original NEW nativeThreadId. Common MUST
strip the local path and never transmit private contents in canonical receipts.
Platform state ready means bootstrap/config accepted for attachment, NOT a live
logical session or canonical ready. The result explicitly marks logicalSession-
Attached=false and canonicalObservationRequired=true. RoomSessionSupervisor in
the SAME parent process owns register/attach and later fresh observation. A
restart loads the accepted config/thread, never creates another thread. Parent
upgrade quiet must cover ALL logical sessions/control/bootstrap and unknown IO.

Final actual Windows qualification: original Global2556 and Native31396 remained,
actual owner/Session1/NTFS ACL/native kernel peer and process identities passed;
unmodified out-of-parent guard rejected the standalone fixture. Only afterward
the test stubbed CURRENT-parent PID/own-argv affinity and native RPC responses
to exercise REAL SDK246 bootstrap. No code injected into live parent; no actual
new thread/model/identity/session. The fixture checked full initial settings/name,
distinct synthetic thread, fresh resume/guide preservation, repeat inspect with
zero RPC, retained unknown record, safe unstarted same-op transport recovery,
uncertain thread/start no replay, wrong native birth and host-guide rejection.
Parent task set/auth/config/process identities remained unchanged. Source call
inventory excludes OS manager/WMI/process creation from per-agent code.

Attempts retained: resident-r01 passed then was tightened to eliminate manager
reads entirely. resident-r02 qualification stopped on a TEST closure variable
shadowing bug (no real effects). Final r03 retains IDENTICAL production bytes
to r02 and fixes only that fixture closure; full journey exit0. The manual
driver is dated BLD/retained-layout evidence, not portable CI or live attach.

Remaining owning integrated gates: map/install the protected parent admission
policy in CPU's actual host runtime; merge common supervisor/private-result
filter; first authorized actual canonical agent bootstrap/attachment; fresh
matching observation with original native/Global contexts and sibling isolation.
No per-room scheduler/job or alternative runtime should be added to close those
gates. No AppStore/ASC/business/game/desktop/model/auth changes were performed.
