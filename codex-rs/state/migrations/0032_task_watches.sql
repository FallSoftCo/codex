CREATE TABLE IF NOT EXISTS task_watches (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    title TEXT NOT NULL,
    objective TEXT NOT NULL,
    prompt TEXT NOT NULL,
    cadence_seconds INTEGER NOT NULL,
    next_check_at INTEGER NOT NULL,
    max_checks INTEGER,
    check_count INTEGER NOT NULL DEFAULT 0,
    requires_response INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'active',
    lease_owner TEXT,
    lease_until INTEGER,
    last_decision TEXT,
    last_observation TEXT,
    last_run_turn_id TEXT,
    last_run_status TEXT,
    last_error TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    stopped_at INTEGER
);

CREATE INDEX IF NOT EXISTS idx_task_watches_claim
    ON task_watches (status, next_check_at, lease_until);

CREATE INDEX IF NOT EXISTS idx_task_watches_thread_id
    ON task_watches (thread_id, next_check_at, id);

CREATE TABLE IF NOT EXISTS task_watch_runs (
    id TEXT PRIMARY KEY,
    task_watch_id TEXT NOT NULL REFERENCES task_watches(id) ON DELETE CASCADE,
    thread_id TEXT NOT NULL,
    turn_id TEXT,
    scheduled_for INTEGER NOT NULL,
    status TEXT NOT NULL,
    summary TEXT,
    error TEXT,
    started_at INTEGER NOT NULL,
    finished_at INTEGER
);

CREATE INDEX IF NOT EXISTS idx_task_watch_runs_watch_id
    ON task_watch_runs (task_watch_id, started_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_task_watch_runs_status
    ON task_watch_runs (status, started_at ASC, id ASC);
