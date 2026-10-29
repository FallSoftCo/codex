# Host-local enrollment

`python -m lax_connector.host --prepare-enrollment SPEC` persists one private
host enrollment intent and emits only its public principal digest and admission
proposal. It starts no services or models. The owner accepts those exact public
operations through the existing Hollywood administration API.

Then `--enroll SPEC` with `enrollmentMode: "preauthorized"` authenticates as the
original host controller and checks its canonical controller/machine binding
before publishing local configuration. No administrator credential is accepted
in that mode. Repeating finalization reconciles the same identity and preserves
existing installed collaboration routes. The legacy explicit administrator
bootstrap path remains supported.

This does not admit placements, native execution, model credentials, filesystem
resources or restart policy implicitly. Those retain their existing separate
protected lifecycle. The integration receipt is real HTTP/PostgreSQL with
rollback-only metadata and no worker or model activation.

## Resource/bootstrap split

For a new host, collaboration preparation accepts `bootstrapMode: preauthorized`
with host-scoped capture. It rejects an administrator credential configuration
and writes a public `admission.prepared.json` alongside the host-private bridge
artifacts. Only the public proposal moves to the owner.

The owner runs `python -m lax_connector.collaboration_admission --proposal ...
--administrator ... --destination ...`. This uses the administrator's independently
configured canonical URL, never a URL supplied by the proposal. Existing CAS
operations and durable administrative receipts register the bridge, physical
root identities, agent access and routing defaults. No remote root is opened.

Return only `admission.accepted.json` to the original host preparation directory.
The ordinary local `collaboration_install --apply ...` verifies the original
proposal, local inode identities and live canonical bridge before publishing the
reviewed local artifacts. It starts no service/model and performs no additional
administrative mutation in this mode. Current native operations still require
fresh canonical resource, execution and mutation admission.

The original local administrator bootstrap uses the same canonical registration
implementation. Existing drained-upgrade and execution-enrollment procedures
remain separate and unchanged.
