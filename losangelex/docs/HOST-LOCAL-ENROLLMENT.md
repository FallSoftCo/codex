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
