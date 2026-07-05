CREATE TABLE collaborative_edit_plans (
    id TEXT PRIMARY KEY,
    actor_thread_id TEXT NOT NULL,
    room TEXT,
    file_path TEXT NOT NULL,
    edit_slice TEXT NOT NULL,
    intent TEXT NOT NULL,
    peers_json TEXT NOT NULL,
    handoff TEXT,
    integrator TEXT,
    report_back TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    lease_expires_at INTEGER NOT NULL
);

CREATE INDEX collaborative_edit_plans_file_lease_idx
    ON collaborative_edit_plans (file_path, lease_expires_at);

CREATE INDEX collaborative_edit_plans_actor_lease_idx
    ON collaborative_edit_plans (actor_thread_id, lease_expires_at);
