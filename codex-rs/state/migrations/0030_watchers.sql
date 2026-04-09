CREATE TABLE IF NOT EXISTS watchers (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    title TEXT NOT NULL,
    prompt TEXT NOT NULL,
    trigger_kind TEXT NOT NULL,
    process_id INTEGER,
    timeout_at INTEGER,
    requires_response INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'armed',
    lease_owner TEXT,
    lease_until INTEGER,
    last_run_turn_id TEXT,
    last_run_status TEXT,
    last_error TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_watchers_claim
    ON watchers (status, lease_until, created_at);

CREATE INDEX IF NOT EXISTS idx_watchers_thread_id
    ON watchers (thread_id, created_at);

CREATE TABLE IF NOT EXISTS watcher_runs (
    id TEXT PRIMARY KEY,
    watcher_id TEXT NOT NULL REFERENCES watchers(id) ON DELETE CASCADE,
    thread_id TEXT NOT NULL,
    turn_id TEXT,
    trigger_fired_at INTEGER NOT NULL,
    status TEXT NOT NULL,
    summary TEXT,
    error TEXT,
    started_at INTEGER NOT NULL,
    finished_at INTEGER
);

CREATE INDEX IF NOT EXISTS idx_watcher_runs_watcher_id
    ON watcher_runs (watcher_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_watcher_runs_status
    ON watcher_runs (status, started_at ASC);
