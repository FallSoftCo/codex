# Native room agent initialization

All host launchers provision a new room agent through `lax_connector.room_bootstrap.initialize` (or its `--config` CLI), including a host Global. Host-specific code prepares local paths, the shared native listener and the OS service; it must not call `thread/start` itself.

Initialization defaults to `danger-full-access` and `never`. An explicitly configured restricted policy is preserved. The initializer creates the context once, persists the initial permission/model settings with the native settings API, names it and then returns its ready receipt. Service installation uses that original native thread ID. No model turn, synthetic message or separate approval step is part of provisioning.

A service restart resumes the original context without reapplying defaults. Later owner permission changes remain authoritative. An uncertain original creation is reconciled using its retained receipt, never replaced by a second thread. Old one-off installation scripts are historical receipts, not alternative supported enrollment commands.

The metadata-only native lifecycle qualification in `tests/integration_room_permissions_native.py` covers default initialization, cold resume and preserving a later explicit restriction without using a model. This is release testing, not periodic runtime permission polling.
