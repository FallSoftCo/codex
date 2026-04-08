CREATE TABLE testers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    objective TEXT NOT NULL,
    background TEXT,
    skill_level TEXT,
    temperament TEXT,
    starting_knowledge_json TEXT NOT NULL,
    constraints_json TEXT NOT NULL,
    allowed_interfaces_json TEXT NOT NULL,
    controller_thread_id TEXT,
    tester_thread_id TEXT,
    cwd TEXT,
    status TEXT NOT NULL,
    last_observed_thread_status TEXT,
    last_error TEXT,
    lease_owner TEXT,
    lease_until INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY(controller_thread_id) REFERENCES threads(id) ON DELETE SET NULL,
    FOREIGN KEY(tester_thread_id) REFERENCES threads(id) ON DELETE SET NULL
);

CREATE INDEX idx_testers_claimable
    ON testers(status, lease_until, updated_at);

CREATE INDEX idx_testers_thread
    ON testers(tester_thread_id);

CREATE TABLE tester_reports (
    id TEXT PRIMARY KEY,
    tester_id TEXT NOT NULL,
    report_kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    details TEXT,
    created_at INTEGER NOT NULL,
    FOREIGN KEY(tester_id) REFERENCES testers(id) ON DELETE CASCADE
);

CREATE INDEX idx_tester_reports_created
    ON tester_reports(tester_id, created_at DESC, id DESC);
