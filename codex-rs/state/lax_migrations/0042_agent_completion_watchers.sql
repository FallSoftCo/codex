ALTER TABLE watchers ADD COLUMN target_thread_id TEXT;

ALTER TABLE watchers ADD COLUMN completion_condition TEXT;

CREATE INDEX IF NOT EXISTS idx_watchers_target_thread_id
    ON watchers (target_thread_id, created_at);
