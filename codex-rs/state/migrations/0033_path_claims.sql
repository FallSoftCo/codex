CREATE TABLE path_claims (
    id TEXT PRIMARY KEY,
    owner_thread_id TEXT NOT NULL,
    claim_kind TEXT NOT NULL,
    path TEXT NOT NULL,
    claimed_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    lease_expires_at INTEGER NOT NULL
);

CREATE UNIQUE INDEX path_claims_kind_path_idx
    ON path_claims (claim_kind, path);

CREATE INDEX path_claims_owner_idx
    ON path_claims (owner_thread_id, lease_expires_at);

CREATE INDEX path_claims_lease_idx
    ON path_claims (lease_expires_at);
