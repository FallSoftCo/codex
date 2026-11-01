# Conversational Windows host

The Windows path runs one native app-server and one reusable Global across its
joined Hollywood rooms. Hollywood owns messages and membership; the existing
native server owns threads and execution. Joining a room starts neither another
server nor another model context.

This qualifies the conversational path, not the legacy Linux claimed-work
installer or every administration tool on Windows. Additional-agent provisioning
must retain the enrolled host/profile and use distinct native threads; creating
another OS account/server is not a shared-host implementation.

## Runtime and identity

Use the canonical Windows app-server package, including code-mode-host, command
runner, sandbox setup, ripgrep and package metadata. `native_package` validates
the complete layout under the actual execution identity. Its startup checks do
not execute sandbox setup or prove model/tool execution.

Prepared CPython 3.12 Windows dependencies include pywin32. Run an isolated,
versioned installation, not a copied Linux virtualenv or an ambient source tree.
Keep account/profile, SQLite, room receipts and work outside the code closure.
Use only an explicitly authorized local account; verify account metadata without
starting a thread or turn. Never borrow another host's account or silently fall
back to API-key billing.

`windows_ipc` supplies Windows AF_UNIX address conversion missing from CPython.
Established sockets use ordinary asyncio IOCP/aiohttp. Before sending HTTP bytes,
the client pins the private parent, validates the native socket reparse type,
checks the kernel peer PID, its account SID and enrolled executable. There is no
bearer-only TCP proxy for the native server.

## State and initial preferences

Use `runtime_files.state_directory`, not POSIX `mkdir(mode=0700)`, for room state.
Windows Python can give the latter SYSTEM/Administrators/OWNER RIGHTS entries
instead of the required explicit enrolled-SID-only ACL. Existing unsafe paths
are rejected; startup does not silently rewrite their permissions.

Receipts are flushed and atomically replaced within their original directory.
The Windows replacement uses write-through and verifies private ownership.
Process ownership uses one held Windows byte lock; another process cannot take
the same connector while that lock is held.

Creation-time overrides alone do not establish durable thread preferences.
Before declaring a new context ready, call `room_permissions.persist_new_thread`
with its actual creation response and approved initial policy/model/effort.
It uses the supported native `thread/settings/update` API. Verify a later resume
without supplying those overrides. Ordinary resumes must preserve subsequent
user restrictions rather than reasserting installer defaults.

## Desktop startup

The qualified desktop route uses the existing interactive user in Session 1,
InteractiveToken and LeastPrivilege. It does not execute agents through an
elevated SSH Session 0. Login is required; reboot/force-stop persistence is not
established merely by installing tasks.

Use separate explicit Task Scheduler definitions for PostgreSQL, Hollywood,
the shared native server and Global. IgnoreNew prevents overlapping instances.
Logon triggers and three one-minute crash retries supply bounded event-driven
recovery, without a polling supervisor or recurring model calls. Installation
reconciles existing definitions and never implicitly reenables a disabled task.
Original ambiguous registration/start intents require reconciliation.

`windows_process` assigns a native/database child to its kill-on-close Windows
Job while its initial thread is suspended, then resumes it. A bounded memory
limit and blocking exit wait cover the entire owned child lifetime. Closing the
task cannot leave that child tree running. Python services run in the scheduled
Python process with private logs and a process memory cap.

Task Scheduler normalizes account aliases and XML when operational Enabled state
changes. Compare canonical SIDs, execution arguments, triggers and settings,
separately from enabled/disabled state. Keep original XML hashes as evidence,
not as the sole execution-identity comparison.

## Qualification boundary

The real Windows journey qualified native binaries, private AF_UNIX WebSocket,
fail-before-send peer/ACL rejection, cross-process receipt locking, durable
replacement, local account metadata, limited-token Task Scheduler and Job
ownership, a live PostgreSQL/Hollywood node, NATS discovery, native model/tool
execution and one source-bound room answer through NextComp's human-bound API.
The original failed attempts remain separate evidence, not successful tests.

Linux regression exercised two clients against a real native server using a
local synthetic provider: distinct threads/callbacks, scoped interruption,
disconnect/reconnect and rejection of changed loaded tool declarations. A
separate zero-turn native journey checked permission persistence and preservation
of later owner restrictions. Zero model turns is not a claim of zero transport
initialization or provider prewarming.

These receipts do not qualify unattended reboot, physical phone voice/push,
an elevated Windows agent, transparent room-storage replication, or every
additional-agent factory path. Those remain separate acceptance boundaries.
