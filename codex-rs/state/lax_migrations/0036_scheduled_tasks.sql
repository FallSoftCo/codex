CREATE TABLE scheduled_tasks (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    title TEXT NOT NULL,
    prompt TEXT NOT NULL,
    schedule_kind TEXT NOT NULL,
    next_run_at INTEGER NOT NULL,
    interval_seconds INTEGER,
    enabled INTEGER NOT NULL DEFAULT 1,
    requires_response INTEGER NOT NULL DEFAULT 1,
    last_run_turn_id TEXT,
    last_run_status TEXT,
    last_error TEXT,
    lease_owner TEXT,
    lease_until INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY(thread_id) REFERENCES threads(id) ON DELETE CASCADE
);

CREATE INDEX idx_scheduled_tasks_due
    ON scheduled_tasks(enabled, next_run_at, lease_until);

CREATE TABLE scheduled_task_runs (
    id TEXT PRIMARY KEY,
    scheduled_task_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    turn_id TEXT,
    scheduled_for INTEGER NOT NULL,
    status TEXT NOT NULL,
    summary TEXT,
    error TEXT,
    started_at INTEGER NOT NULL,
    finished_at INTEGER,
    FOREIGN KEY(scheduled_task_id) REFERENCES scheduled_tasks(id) ON DELETE CASCADE,
    FOREIGN KEY(thread_id) REFERENCES threads(id) ON DELETE CASCADE
);

CREATE INDEX idx_scheduled_task_runs_task_started
    ON scheduled_task_runs(scheduled_task_id, started_at DESC, id DESC);

CREATE INDEX idx_scheduled_task_runs_running
    ON scheduled_task_runs(status, started_at ASC, id ASC);
