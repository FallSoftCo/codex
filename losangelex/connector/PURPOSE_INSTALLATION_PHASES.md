# Purpose-agent setup phases

The native installer uses prepare, seal and first activation. This is LAX
installation work; Hollywood remains the communication authority.

Use lax-install-agent --spec /protected/spec.json --prepare to persist the
canonical Unix identity, private state, original contexts, package/account
configuration and service definitions without starting or sealing them. The
existing collaboration installer can then use that real UID and workspace to
install its controller, protected bridge, canonical roots, grants and defaults.
This resolves the first-Global setup dependency cycle.

Run the same original spec without --prepare after those dependencies exist.
The installer reconciles the original identity, installs its environment and
resources, and seals readiness. Sealing checks the canonical context, exact
protected config/service files, real local bridge peer and API enrollment,
workspace inode/access, selected local model-account identity, approved
environment clients, actual service UID and sudo. It starts no model or service.
Current installed account identity is compared without resetting refreshed
tokens. Provider reachability and genuine execution are separate qualifications.

The first --activate requires a fresh matching seal before recording the start
intent. An existing activation intent remains status-only: repeating setup does
not restart a deliberately stopped service. Metadata preparation is not readiness,
nor proof that an ordinary human task was completed.

The r43 receipt verifies dependencies for the three actual QA identities and
preserves their existing activation intents and process IDs. No readiness seal
was written during that read-only check. This source is not the completed paired
enterprise bootstrap: first-Global factory wiring, deliberate boot desired state,
clean installation and first-user integration remain required before release.
