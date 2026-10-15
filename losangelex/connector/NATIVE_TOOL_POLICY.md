# Native tool policy for externally admitted execution

The LAX app-server accepts experimental `toolPolicy` on `thread/start` and
cold `thread/resume`. The existing native tool router and dispatch registry
enforce it as an additional capability ceiling.

```json
{"toolPolicy":{"allowedTools":[{"name":"hollywood_read_room"},{"name":"hollywood_publish"},{"name":"get_goal"},{"name":"exec"},{"name":"wait"}]}}
```

The supplied list intersects the session's base `ToolPolicy`. It cannot add
a tool removed by that base policy or relax managed-network, unified-execution
or additional-permissions requirements. Native namespace matching treats
omitted, empty and `functions` as the default namespace. An empty list allows
no tools. Entries are ceilings, not promises that a tool is registered.

Code Mode's generated `exec` and `wait` must be allowed when that transport
is required. They expose only tools retained in the registry; allowing them
does not allow `exec_command` or `apply_patch`. Disabling shell alone is
insufficient because patch registration is independent.

Start and resume return the actual captured ceiling when one exists.
Replacing it on a loaded thread is rejected. At an idle ownership boundary,
release the runtime and supply the intended policy again on cold resume.
A loaded resume without a policy retains the existing ceiling.

The connector configuration uses this value as `nativeToolPolicy`. When
configured, effective readback must be valid and no broader than requested
before goal binding or provider admission. Missing readback fails before
inference and retains the native context and verification receipt. A matching
CLI display version alone does not establish support.

This primitive does not yet admit human control while older work is unknown.
That requires Hollywood control authorization/admission, independent executor
drain evidence, per-attempt journals and source-generation fencing. It does
not reduce Global's Linux administrator authority, grant room membership,
undo effects or settle unknown delivery.

Integration checks use the real native protocol and real Global provider
turns through Hollywood. Metadata protocol checks submit zero model turns.
Original uncertain work is inspected by identity and never replayed.
