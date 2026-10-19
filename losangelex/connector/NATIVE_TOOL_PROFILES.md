# Approved native writer tools

Hollywood remains the primary communication authority. Each LAX identity retains
three durable native histories. An administrator may provide a protected JSON
tool profile at first Global installation or explicit native worker provisioning.
It adds execution tools to the writer only; reader and responder ceilings remain
unchanged. Workers do not implicitly inherit the administrator's providers.

The native fork already supplies MCP configuration and namespaced tool policies.
LAX passes the approved server configuration through thread/start or thread/resume
and selects exact namespace/name pairs through that policy. It does not introduce
a second provider transport or copy a user's ambient MCP configuration.

The profile has exactly these fields:

```json
{
  "schema": "lax-native-tool-profile/v1",
  "builtins": [],
  "mcpServers": {},
  "allowedTools": [
    {"namespace": "mcp__example", "name": "read"}
  ],
  "webSearchMode": "disabled"
}
```

The example selects an already managed native account connector. An explicitly
configured MCP provider belongs in mcpServers using the native server declaration
schema. Select its exact tools in allowedTools as well. Native tool discovery is
exposed when external tools are selected; discovery does not widen their execution
ceiling. Configured server inventory may include additional account-managed
connectors; inventory presence alone does not prove model execution access.

Supported builtin selections are view_image and web_search. Search exposure must
agree with disabled/cached/live mode. Their general provider behavior has not
been qualified by the MCP integration receipt below.

toolProfileFile must be an absolute, administrator-owned regular file, at most
64 KiB, without group/world write permission. Installation copies it into the
protected identity record and pins its exact SHA256. A changed installed profile
requires an explicit upgrade; normal reconciliation must not overwrite it.
MCP provider configuration can contain secrets: do not print profiles, tokens or
full native tool results in rooms. Native execution journals remain private.

Actual qualification: qualification/native-approved-tools-20261019.json records
one disposable native agent's three histories, an agent-authored Hollywood request,
a real writer MCP run and original-job status observation across the existing
OZZZ-to-system76 SSH route, a verified filesystem artifact and terminal response.
Only read-only provider metadata was requested. The provider retained its
completed_unverified flag; no exactly-once or external-effect claim follows.

This is not qualification of all account connectors, browser input, physical
Android use, voice, push or an enterprise-wide migration.
