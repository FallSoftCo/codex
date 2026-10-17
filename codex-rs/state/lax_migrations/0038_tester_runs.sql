CREATE TABLE tester_runs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    objective TEXT NOT NULL,
    background TEXT,
    skill_level TEXT,
    temperament TEXT,
    starting_knowledge_json TEXT NOT NULL,
    constraints_json TEXT NOT NULL,
    allowed_interfaces_json TEXT NOT NULL,
    execution_class TEXT NOT NULL,
    controller_thread_id TEXT,
    runtime_thread_id TEXT,
    rollout_path TEXT,
    cwd TEXT,
    status TEXT NOT NULL,
    last_observed_thread_status TEXT,
    last_error TEXT,
    last_parsed_rollout_index INTEGER NOT NULL DEFAULT 0,
    lease_owner TEXT,
    lease_until INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY(controller_thread_id) REFERENCES threads(id) ON DELETE SET NULL,
    FOREIGN KEY(runtime_thread_id) REFERENCES threads(id) ON DELETE SET NULL
);

CREATE INDEX idx_tester_runs_claimable
    ON tester_runs(status, lease_until, updated_at);

CREATE INDEX idx_tester_runs_runtime_thread
    ON tester_runs(runtime_thread_id);

CREATE TABLE tester_run_reports (
    id TEXT PRIMARY KEY,
    tester_run_id TEXT NOT NULL,
    report_kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    details TEXT,
    created_at INTEGER NOT NULL,
    FOREIGN KEY(tester_run_id) REFERENCES tester_runs(id) ON DELETE CASCADE
);

CREATE INDEX idx_tester_run_reports_created
    ON tester_run_reports(tester_run_id, created_at DESC, id DESC);

CREATE TABLE tester_run_artifacts (
    id TEXT PRIMARY KEY,
    tester_run_id TEXT NOT NULL,
    artifact_kind TEXT NOT NULL,
    label TEXT NOT NULL,
    path TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    FOREIGN KEY(tester_run_id) REFERENCES tester_runs(id) ON DELETE CASCADE
);

CREATE INDEX idx_tester_run_artifacts_created
    ON tester_run_artifacts(tester_run_id, created_at DESC, id DESC);
