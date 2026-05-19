use super::*;
use crate::model::ClaimedWatcher;
use crate::model::RunningWatcherRun;
use crate::model::WatcherCreateParams;
use crate::model::WatcherRow;
use crate::model::WatcherRun;
use crate::model::WatcherRunRow;
use crate::model::WatcherRunStatus;
use crate::model::WatcherStatus;
use crate::model::WatcherTriggerKind;

impl StateRuntime {
    pub async fn create_watcher(&self, params: WatcherCreateParams) -> anyhow::Result<()> {
        self.ensure_state_schema_current().await?;
        let now = Utc::now().timestamp();
        sqlx::query(
            r#"
INSERT INTO watchers (
    id,
    thread_id,
    title,
    prompt,
    trigger_kind,
    process_id,
    target_thread_id,
    completion_condition,
    timeout_at,
    requires_response,
    status,
    created_at,
    updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            "#,
        )
        .bind(params.id)
        .bind(params.thread_id)
        .bind(params.title)
        .bind(params.prompt)
        .bind(params.trigger_kind.as_str())
        .bind(params.process_id)
        .bind(params.target_thread_id)
        .bind(
            params
                .agent_completion_condition
                .map(crate::WatcherAgentCompletionCondition::as_str),
        )
        .bind(params.timeout_at.map(|value| value.timestamp()))
        .bind(i64::from(params.requires_response))
        .bind(WatcherStatus::Armed.as_str())
        .bind(now)
        .bind(now)
        .execute(self.pool.as_ref())
        .await?;
        Ok(())
    }

    pub async fn list_watchers(
        &self,
        thread_id: Option<ThreadId>,
    ) -> anyhow::Result<Vec<crate::Watcher>> {
        self.ensure_state_schema_current().await?;
        let rows = if let Some(thread_id) = thread_id {
            sqlx::query_as::<_, WatcherRow>(
                r#"
SELECT
    id,
    thread_id,
    title,
    prompt,
    trigger_kind,
    process_id,
    target_thread_id,
    completion_condition,
    timeout_at,
    requires_response,
    status,
    last_run_turn_id,
    last_run_status,
    last_error,
    created_at,
    updated_at
FROM watchers
WHERE thread_id = ?
ORDER BY created_at DESC, id DESC
                "#,
            )
            .bind(thread_id.to_string())
            .fetch_all(self.pool.as_ref())
            .await?
        } else {
            sqlx::query_as::<_, WatcherRow>(
                r#"
SELECT
    id,
    thread_id,
    title,
    prompt,
    trigger_kind,
    process_id,
    target_thread_id,
    completion_condition,
    timeout_at,
    requires_response,
    status,
    last_run_turn_id,
    last_run_status,
    last_error,
    created_at,
    updated_at
FROM watchers
ORDER BY created_at DESC, id DESC
                "#,
            )
            .fetch_all(self.pool.as_ref())
            .await?
        };
        rows.into_iter().map(TryInto::try_into).collect()
    }

    pub async fn cancel_watcher(&self, id: &str) -> anyhow::Result<bool> {
        self.ensure_state_schema_current().await?;
        let result = sqlx::query(
            r#"
UPDATE watchers
SET status = ?,
    lease_owner = NULL,
    lease_until = NULL,
    updated_at = ?
WHERE id = ?
  AND status = ?
            "#,
        )
        .bind(WatcherStatus::Stopped.as_str())
        .bind(Utc::now().timestamp())
        .bind(id)
        .bind(WatcherStatus::Armed.as_str())
        .execute(self.pool.as_ref())
        .await?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn claim_armed_watchers(
        &self,
        now: DateTime<Utc>,
        worker_id: &str,
        limit: usize,
        lease_duration: Duration,
    ) -> anyhow::Result<Vec<ClaimedWatcher>> {
        self.ensure_state_schema_current().await?;
        let rows = sqlx::query_as::<_, WatcherRow>(
            r#"
SELECT
    id,
    thread_id,
    title,
    prompt,
    trigger_kind,
    process_id,
    target_thread_id,
    completion_condition,
    timeout_at,
    requires_response,
    status,
    last_run_turn_id,
    last_run_status,
    last_error,
    created_at,
    updated_at
FROM watchers
WHERE status = ?
  AND (lease_until IS NULL OR lease_until < ?)
ORDER BY created_at ASC, id ASC
LIMIT ?
            "#,
        )
        .bind(WatcherStatus::Armed.as_str())
        .bind(now.timestamp())
        .bind(i64::try_from(limit).unwrap_or(i64::MAX))
        .fetch_all(self.pool.as_ref())
        .await?;

        let lease_until = now + chrono::Duration::from_std(lease_duration)?;
        let mut claimed = Vec::new();
        for row in rows {
            let result = sqlx::query(
                r#"
UPDATE watchers
SET lease_owner = ?, lease_until = ?, updated_at = ?
WHERE id = ?
  AND status = ?
  AND (lease_until IS NULL OR lease_until < ?)
                "#,
            )
            .bind(worker_id)
            .bind(lease_until.timestamp())
            .bind(now.timestamp())
            .bind(&row.id)
            .bind(WatcherStatus::Armed.as_str())
            .bind(now.timestamp())
            .execute(self.pool.as_ref())
            .await?;
            if result.rows_affected() == 0 {
                continue;
            }
            claimed.push(ClaimedWatcher {
                id: row.id,
                thread_id: row.thread_id,
                title: row.title,
                prompt: row.prompt,
                trigger_kind: WatcherTriggerKind::parse(row.trigger_kind.as_str())?,
                process_id: row.process_id,
                target_thread_id: row.target_thread_id,
                agent_completion_condition: row
                    .completion_condition
                    .as_deref()
                    .map(crate::WatcherAgentCompletionCondition::parse)
                    .transpose()?,
                timeout_at: row.timeout_at.map(epoch_seconds_to_datetime).transpose()?,
                requires_response: row.requires_response != 0,
                created_at: epoch_seconds_to_datetime(row.created_at)?,
            });
        }
        Ok(claimed)
    }

    pub async fn release_watcher_claim(&self, id: &str) -> anyhow::Result<()> {
        self.ensure_state_schema_current().await?;
        sqlx::query(
            r#"
UPDATE watchers
SET lease_owner = NULL,
    lease_until = NULL,
    updated_at = ?
WHERE id = ?
            "#,
        )
        .bind(Utc::now().timestamp())
        .bind(id)
        .execute(self.pool.as_ref())
        .await?;
        Ok(())
    }

    pub async fn start_watcher_run(
        &self,
        watcher: &ClaimedWatcher,
        turn_id: Option<&str>,
        trigger_fired_at: DateTime<Utc>,
    ) -> anyhow::Result<String> {
        self.ensure_state_schema_current().await?;
        let run_id = uuid::Uuid::new_v4().to_string();
        sqlx::query(
            r#"
INSERT INTO watcher_runs (
    id,
    watcher_id,
    thread_id,
    turn_id,
    trigger_fired_at,
    status,
    started_at
) VALUES (?, ?, ?, ?, ?, ?, ?)
            "#,
        )
        .bind(&run_id)
        .bind(&watcher.id)
        .bind(&watcher.thread_id)
        .bind(turn_id)
        .bind(trigger_fired_at.timestamp())
        .bind(WatcherRunStatus::Running.as_str())
        .bind(trigger_fired_at.timestamp())
        .execute(self.pool.as_ref())
        .await?;

        sqlx::query(
            r#"
UPDATE watchers
SET status = ?,
    lease_owner = NULL,
    lease_until = NULL,
    last_run_turn_id = ?,
    last_run_status = ?,
    last_error = NULL,
    updated_at = ?
WHERE id = ?
            "#,
        )
        .bind(WatcherStatus::Triggered.as_str())
        .bind(turn_id)
        .bind(WatcherRunStatus::Running.as_str())
        .bind(trigger_fired_at.timestamp())
        .bind(&watcher.id)
        .execute(self.pool.as_ref())
        .await?;

        Ok(run_id)
    }

    pub async fn fail_watcher(
        &self,
        watcher_id: &str,
        status: WatcherStatus,
        error: &str,
        now: DateTime<Utc>,
    ) -> anyhow::Result<()> {
        self.ensure_state_schema_current().await?;
        sqlx::query(
            r#"
UPDATE watchers
SET status = ?,
    lease_owner = NULL,
    lease_until = NULL,
    last_run_status = ?,
    last_error = ?,
    updated_at = ?
WHERE id = ?
            "#,
        )
        .bind(status.as_str())
        .bind(WatcherRunStatus::Failed.as_str())
        .bind(error)
        .bind(now.timestamp())
        .bind(watcher_id)
        .execute(self.pool.as_ref())
        .await?;
        Ok(())
    }

    pub async fn list_running_watcher_runs(&self) -> anyhow::Result<Vec<RunningWatcherRun>> {
        self.ensure_state_schema_current().await?;
        let rows = sqlx::query_as::<_, WatcherRunRow>(
            r#"
SELECT
    id,
    watcher_id,
    thread_id,
    turn_id,
    trigger_fired_at,
    status,
    summary,
    error,
    started_at,
    finished_at
FROM watcher_runs
WHERE status = ?
ORDER BY started_at ASC
            "#,
        )
        .bind(WatcherRunStatus::Running.as_str())
        .fetch_all(self.pool.as_ref())
        .await?;

        let mut runs = Vec::new();
        for row in rows {
            let Some(turn_id) = row.turn_id else {
                continue;
            };
            runs.push(RunningWatcherRun {
                id: row.id,
                watcher_id: row.watcher_id,
                thread_id: row.thread_id,
                turn_id,
                started_at: epoch_seconds_to_datetime(row.started_at)?,
            });
        }
        Ok(runs)
    }

    pub async fn list_watcher_runs(
        &self,
        watcher_id: Option<&str>,
    ) -> anyhow::Result<Vec<WatcherRun>> {
        self.ensure_state_schema_current().await?;
        let rows = if let Some(watcher_id) = watcher_id {
            sqlx::query_as::<_, WatcherRunRow>(
                r#"
SELECT
    id,
    watcher_id,
    thread_id,
    turn_id,
    trigger_fired_at,
    status,
    summary,
    error,
    started_at,
    finished_at
FROM watcher_runs
WHERE watcher_id = ?
ORDER BY started_at DESC
                "#,
            )
            .bind(watcher_id)
            .fetch_all(self.pool.as_ref())
            .await?
        } else {
            sqlx::query_as::<_, WatcherRunRow>(
                r#"
SELECT
    id,
    watcher_id,
    thread_id,
    turn_id,
    trigger_fired_at,
    status,
    summary,
    error,
    started_at,
    finished_at
FROM watcher_runs
ORDER BY started_at DESC
                "#,
            )
            .fetch_all(self.pool.as_ref())
            .await?
        };
        rows.into_iter().map(TryInto::try_into).collect()
    }

    pub async fn complete_watcher_run(
        &self,
        run_id: &str,
        watcher_id: &str,
        status: WatcherRunStatus,
        finished_at: DateTime<Utc>,
        summary: Option<&str>,
        error: Option<&str>,
    ) -> anyhow::Result<()> {
        self.ensure_state_schema_current().await?;
        sqlx::query(
            r#"
UPDATE watcher_runs
SET status = ?,
    summary = ?,
    error = ?,
    finished_at = ?
WHERE id = ?
            "#,
        )
        .bind(status.as_str())
        .bind(summary)
        .bind(error)
        .bind(finished_at.timestamp())
        .bind(run_id)
        .execute(self.pool.as_ref())
        .await?;

        sqlx::query(
            r#"
UPDATE watchers
SET last_run_status = ?,
    last_error = ?,
    updated_at = ?
WHERE id = ?
            "#,
        )
        .bind(status.as_str())
        .bind(error)
        .bind(finished_at.timestamp())
        .bind(watcher_id)
        .execute(self.pool.as_ref())
        .await?;
        Ok(())
    }
}

fn epoch_seconds_to_datetime(value: i64) -> anyhow::Result<DateTime<Utc>> {
    DateTime::from_timestamp(value, 0)
        .ok_or_else(|| anyhow::anyhow!("invalid epoch seconds: {value}"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::WatcherCreateParams;
    use pretty_assertions::assert_eq;

    #[tokio::test]
    async fn process_exit_watcher_can_be_claimed_and_started() {
        let tempdir = tempfile::tempdir().expect("tempdir");
        let db = StateRuntime::init(tempdir.path().to_path_buf(), "openai".to_string())
            .await
            .expect("init");
        let thread_id = "thread-1".to_string();

        db.create_watcher(WatcherCreateParams {
            id: "watch-1".to_string(),
            thread_id: thread_id.clone(),
            title: "wait for build".to_string(),
            prompt: "Inspect the completed build and summarize failures.".to_string(),
            trigger_kind: WatcherTriggerKind::ProcessExit,
            process_id: Some(1234),
            target_thread_id: None,
            agent_completion_condition: None,
            timeout_at: None,
            requires_response: true,
        })
        .await
        .expect("create watcher");

        let claimed = db
            .claim_armed_watchers(Utc::now(), "worker-1", 10, Duration::from_secs(30))
            .await
            .expect("claim");
        assert_eq!(claimed.len(), 1);
        assert_eq!(claimed[0].process_id, Some(1234));

        let run_id = db
            .start_watcher_run(&claimed[0], Some("turn-1"), Utc::now())
            .await
            .expect("start watcher run");
        assert!(!run_id.is_empty());

        let watchers = db.list_watchers(None).await.expect("list watchers");
        assert_eq!(watchers.len(), 1);
        assert_eq!(watchers[0].status, WatcherStatus::Triggered);
        assert_eq!(watchers[0].last_run_turn_id.as_deref(), Some("turn-1"));
    }

    #[tokio::test]
    async fn agent_completion_watcher_persists_target_and_condition() {
        let tempdir = tempfile::tempdir().expect("tempdir");
        let db = StateRuntime::init(tempdir.path().to_path_buf(), "openai".to_string())
            .await
            .expect("init");

        db.create_watcher(WatcherCreateParams {
            id: "watch-2".to_string(),
            thread_id: "thread-1".to_string(),
            title: "wait for reviewer".to_string(),
            prompt: "Inspect the reviewer result.".to_string(),
            trigger_kind: WatcherTriggerKind::AgentCompletion,
            process_id: None,
            target_thread_id: Some("thread-2".to_string()),
            agent_completion_condition: Some(crate::WatcherAgentCompletionCondition::Completed),
            timeout_at: None,
            requires_response: true,
        })
        .await
        .expect("create watcher");

        let watchers = db.list_watchers(None).await.expect("list watchers");
        assert_eq!(watchers.len(), 1);
        assert_eq!(
            watchers[0].trigger_kind,
            WatcherTriggerKind::AgentCompletion
        );
        assert_eq!(watchers[0].target_thread_id.as_deref(), Some("thread-2"));
        assert_eq!(
            watchers[0].agent_completion_condition,
            Some(crate::WatcherAgentCompletionCondition::Completed)
        );
    }

    #[tokio::test]
    async fn watcher_run_can_be_recorded_without_turn_id() {
        let tempdir = tempfile::tempdir().expect("tempdir");
        let db = StateRuntime::init(tempdir.path().to_path_buf(), "openai".to_string())
            .await
            .expect("init");

        db.create_watcher(WatcherCreateParams {
            id: "watch-3".to_string(),
            thread_id: "thread-1".to_string(),
            title: "wait for build".to_string(),
            prompt: "Summarize the build result.".to_string(),
            trigger_kind: WatcherTriggerKind::ProcessExit,
            process_id: Some(42),
            target_thread_id: None,
            agent_completion_condition: None,
            timeout_at: None,
            requires_response: true,
        })
        .await
        .expect("create watcher");

        let claimed = db
            .claim_armed_watchers(Utc::now(), "worker-1", 10, Duration::from_secs(30))
            .await
            .expect("claim");
        let run_id = db
            .start_watcher_run(&claimed[0], None, Utc::now())
            .await
            .expect("start watcher run");

        let runs = db
            .list_watcher_runs(Some("watch-3"))
            .await
            .expect("list watcher runs");
        assert_eq!(runs.len(), 1);
        assert_eq!(runs[0].id, run_id);
        assert_eq!(runs[0].turn_id, None);
        assert_eq!(runs[0].status, WatcherRunStatus::Running);
    }

    #[tokio::test]
    async fn list_watchers_recreates_missing_watcher_schema() {
        let tempdir = tempfile::tempdir().expect("tempdir");
        let db = StateRuntime::init(tempdir.path().to_path_buf(), "openai".to_string())
            .await
            .expect("init");

        sqlx::query("DROP TABLE watcher_runs")
            .execute(db.pool.as_ref())
            .await
            .expect("drop watcher_runs");
        sqlx::query("DROP TABLE watchers")
            .execute(db.pool.as_ref())
            .await
            .expect("drop watchers");
        sqlx::query("DELETE FROM _sqlx_migrations WHERE version IN (40, 41)")
            .execute(db.pool.as_ref())
            .await
            .expect("delete watcher migrations");

        let watchers = db.list_watchers(None).await.expect("list watchers");
        assert_eq!(watchers, Vec::<crate::Watcher>::new());
    }
}
