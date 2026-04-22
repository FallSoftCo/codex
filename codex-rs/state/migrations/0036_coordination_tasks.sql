CREATE TABLE coordination_tasks (
    id TEXT PRIMARY KEY,
    creator_thread_id TEXT NOT NULL,
    owner_thread_id TEXT,
    team_id TEXT,
    room TEXT,
    task_kind TEXT NOT NULL,
    status TEXT NOT NULL,
    summary TEXT NOT NULL,
    details TEXT NOT NULL,
    requested_capability TEXT,
    blocked_reason TEXT,
    lease_expires_at INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    completed_at INTEGER
);

CREATE INDEX coordination_tasks_owner_status_idx
    ON coordination_tasks (owner_thread_id, status, updated_at);

CREATE INDEX coordination_tasks_creator_status_idx
    ON coordination_tasks (creator_thread_id, status, updated_at);

CREATE INDEX coordination_tasks_lease_idx
    ON coordination_tasks (lease_expires_at);

CREATE TABLE coordination_task_dependencies (
    task_id TEXT NOT NULL REFERENCES coordination_tasks(id) ON DELETE CASCADE,
    depends_on_task_id TEXT NOT NULL REFERENCES coordination_tasks(id) ON DELETE CASCADE,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (task_id, depends_on_task_id)
);

CREATE INDEX coordination_task_dependencies_depends_on_idx
    ON coordination_task_dependencies (depends_on_task_id, task_id);

CREATE TABLE coordination_acts (
    id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES coordination_tasks(id) ON DELETE CASCADE,
    actor_thread_id TEXT NOT NULL,
    act_kind TEXT NOT NULL,
    summary TEXT,
    payload_json TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE INDEX coordination_acts_task_created_idx
    ON coordination_acts (task_id, created_at DESC, id DESC);
