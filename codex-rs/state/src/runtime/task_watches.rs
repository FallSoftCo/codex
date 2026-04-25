use super::*;
use crate::model::ClaimedTaskWatch;
use crate::model::RunningTaskWatchRun;
use crate::model::TaskWatchCreateParams;
use crate::model::TaskWatchRow;
use crate::model::TaskWatchRun;
use crate::model::TaskWatchRunRow;
use crate::model::TaskWatchRunStatus;
use crate::model::TaskWatchStatus;
use crate::model::TaskWatchUpdateParams;

impl StateRuntime {
    pub async fn create_task_watch(&self, params: TaskWatchCreateParams) -> anyhow::Result<()> {
        let now = Utc::now().timestamp();
        sqlx::query(
            r#"
INSERT INTO task_watches (
    id,
    thread_id,
    title,
    objective,
    prompt,
    cadence_seconds,
    next_check_at,
    max_checks,
    requires_response,
    status,
    created_at,
    updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            "#,
        )
        .bind(params.id)
        .bind(params.thread_id)
        .bind(params.title)
        .bind(params.objective)
        .bind(params.prompt)
        .bind(params.cadence_seconds)
        .bind(params.next_check_at.timestamp())
        .bind(params.max_checks)
        .bind(i64::from(params.requires_response))
        .bind(TaskWatchStatus::Active.as_str())
        .bind(now)
        .bind(now)
        .execute(self.pool.as_ref())
        .await?;
        Ok(())
    }

    pub async fn list_task_watches(
        &self,
        thread_id: Option<ThreadId>,
    ) -> anyhow::Result<Vec<crate::TaskWatch>> {
        let rows = if let Some(thread_id) = thread_id {
            sqlx::query_as::<_, TaskWatchRow>(
                r#"
SELECT
    id,
    thread_id,
    title,
    objective,
    prompt,
    cadence_seconds,
    next_check_at,
    max_checks,
    check_count,
    requires_response,
    status,
    last_decision,
    last_observation,
    last_run_turn_id,
    last_run_status,
    last_error,
    created_at,
    updated_at,
    stopped_at
FROM task_watches
WHERE thread_id = ?
ORDER BY next_check_at ASC, id ASC
                "#,
            )
            .bind(thread_id.to_string())
            .fetch_all(self.pool.as_ref())
            .await?
        } else {
            sqlx::query_as::<_, TaskWatchRow>(
                r#"
SELECT
    id,
    thread_id,
    title,
    objective,
    prompt,
    cadence_seconds,
    next_check_at,
    max_checks,
    check_count,
    requires_response,
    status,
    last_decision,
    last_observation,
    last_run_turn_id,
    last_run_status,
    last_error,
    created_at,
    updated_at,
    stopped_at
FROM task_watches
ORDER BY next_check_at ASC, id ASC
                "#,
            )
            .fetch_all(self.pool.as_ref())
            .await?
        };
        rows.into_iter().map(TryInto::try_into).collect()
    }

    pub async fn update_task_watch(&self, params: TaskWatchUpdateParams) -> anyhow::Result<bool> {
        let now = Utc::now();
        let status = params.status.map(TaskWatchStatus::as_str);
        let stopped_at = params.status.and_then(|value| {
            matches!(value, TaskWatchStatus::Completed | TaskWatchStatus::Stopped).then_some(now)
        });
        let result = sqlx::query(
            r#"
UPDATE task_watches
SET cadence_seconds = COALESCE(?, cadence_seconds),
    next_check_at = COALESCE(?, next_check_at),
    max_checks = COALESCE(?, max_checks),
    last_decision = COALESCE(?, last_decision),
    last_observation = COALESCE(?, last_observation),
    status = COALESCE(?, status),
    stopped_at = COALESCE(?, stopped_at),
    lease_owner = NULL,
    lease_until = NULL,
    updated_at = ?
WHERE id = ?
  AND status NOT IN (?, ?)
            "#,
        )
        .bind(params.cadence_seconds)
        .bind(params.next_check_at.map(|value| value.timestamp()))
        .bind(params.max_checks)
        .bind(params.last_decision)
        .bind(params.last_observation)
        .bind(status)
        .bind(stopped_at.map(|value| value.timestamp()))
        .bind(now.timestamp())
        .bind(params.id)
        .bind(TaskWatchStatus::Completed.as_str())
        .bind(TaskWatchStatus::Stopped.as_str())
        .execute(self.pool.as_ref())
        .await?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn cancel_task_watch(
        &self,
        id: &str,
        status: TaskWatchStatus,
    ) -> anyhow::Result<bool> {
        let now = Utc::now().timestamp();
        let result = sqlx::query(
            r#"
UPDATE task_watches
SET status = ?,
    stopped_at = ?,
    lease_owner = NULL,
    lease_until = NULL,
    updated_at = ?
WHERE id = ?
  AND status NOT IN (?, ?)
            "#,
        )
        .bind(status.as_str())
        .bind(now)
        .bind(now)
        .bind(id)
        .bind(TaskWatchStatus::Completed.as_str())
        .bind(TaskWatchStatus::Stopped.as_str())
        .execute(self.pool.as_ref())
        .await?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn claim_due_task_watches(
        &self,
        now: DateTime<Utc>,
        worker_id: &str,
        limit: usize,
        lease_duration: Duration,
    ) -> anyhow::Result<Vec<ClaimedTaskWatch>> {
        let due_rows = sqlx::query_as::<_, TaskWatchRow>(
            r#"
SELECT
    id,
    thread_id,
    title,
    objective,
    prompt,
    cadence_seconds,
    next_check_at,
    max_checks,
    check_count,
    requires_response,
    status,
    last_decision,
    last_observation,
    last_run_turn_id,
    last_run_status,
    last_error,
    created_at,
    updated_at,
    stopped_at
FROM task_watches
WHERE status = ?
  AND next_check_at <= ?
  AND (lease_until IS NULL OR lease_until < ?)
  AND NOT EXISTS (
      SELECT 1
      FROM task_watch_runs
      WHERE task_watch_runs.task_watch_id = task_watches.id
        AND task_watch_runs.status = ?
  )
ORDER BY next_check_at ASC, id ASC
LIMIT ?
            "#,
        )
        .bind(TaskWatchStatus::Active.as_str())
        .bind(now.timestamp())
        .bind(now.timestamp())
        .bind(TaskWatchRunStatus::Running.as_str())
        .bind(i64::try_from(limit).unwrap_or(i64::MAX))
        .fetch_all(self.pool.as_ref())
        .await?;

        let lease_until = now + chrono::Duration::from_std(lease_duration)?;
        let mut claimed = Vec::new();
        for row in due_rows {
            let result = sqlx::query(
                r#"
UPDATE task_watches
SET lease_owner = ?, lease_until = ?, updated_at = ?
WHERE id = ?
  AND status = ?
  AND next_check_at = ?
  AND (lease_until IS NULL OR lease_until < ?)
                "#,
            )
            .bind(worker_id)
            .bind(lease_until.timestamp())
            .bind(now.timestamp())
            .bind(&row.id)
            .bind(TaskWatchStatus::Active.as_str())
            .bind(row.next_check_at)
            .bind(now.timestamp())
            .execute(self.pool.as_ref())
            .await?;
            if result.rows_affected() == 0 {
                continue;
            }
            claimed.push(ClaimedTaskWatch {
                id: row.id,
                thread_id: row.thread_id,
                title: row.title,
                objective: row.objective,
                prompt: row.prompt,
                cadence_seconds: row.cadence_seconds,
                scheduled_for: DateTime::from_timestamp(row.next_check_at, 0)
                    .ok_or_else(|| anyhow::anyhow!("invalid next_check_at"))?,
                max_checks: row.max_checks,
                check_count: row.check_count,
                requires_response: row.requires_response != 0,
            });
        }
        Ok(claimed)
    }

    pub async fn record_task_watch_start_failure(
        &self,
        task_watch: &ClaimedTaskWatch,
        finished_at: DateTime<Utc>,
        retry_at: DateTime<Utc>,
        error: &str,
    ) -> anyhow::Result<String> {
        let run_id = uuid::Uuid::new_v4().to_string();
        sqlx::query(
            r#"
INSERT INTO task_watch_runs (
    id,
    task_watch_id,
    thread_id,
    turn_id,
    scheduled_for,
    status,
    summary,
    error,
    started_at,
    finished_at
) VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?)
            "#,
        )
        .bind(&run_id)
        .bind(&task_watch.id)
        .bind(&task_watch.thread_id)
        .bind(task_watch.scheduled_for.timestamp())
        .bind(TaskWatchRunStatus::Failed.as_str())
        .bind("task watch did not start")
        .bind(error)
        .bind(finished_at.timestamp())
        .bind(finished_at.timestamp())
        .execute(self.pool.as_ref())
        .await?;

        sqlx::query(
            r#"
UPDATE task_watches
SET lease_owner = NULL,
    lease_until = NULL,
    next_check_at = ?,
    last_run_status = ?,
    last_error = ?,
    updated_at = ?
WHERE id = ?
            "#,
        )
        .bind(retry_at.timestamp())
        .bind(TaskWatchRunStatus::Failed.as_str())
        .bind(error)
        .bind(finished_at.timestamp())
        .bind(&task_watch.id)
        .execute(self.pool.as_ref())
        .await?;

        Ok(run_id)
    }

    pub async fn start_task_watch_run(
        &self,
        task_watch: &ClaimedTaskWatch,
        turn_id: &str,
        started_at: DateTime<Utc>,
    ) -> anyhow::Result<String> {
        let run_id = uuid::Uuid::new_v4().to_string();
        sqlx::query(
            r#"
INSERT INTO task_watch_runs (
    id,
    task_watch_id,
    thread_id,
    turn_id,
    scheduled_for,
    status,
    started_at
) VALUES (?, ?, ?, ?, ?, ?, ?)
            "#,
        )
        .bind(&run_id)
        .bind(&task_watch.id)
        .bind(&task_watch.thread_id)
        .bind(turn_id)
        .bind(task_watch.scheduled_for.timestamp())
        .bind(TaskWatchRunStatus::Running.as_str())
        .bind(started_at.timestamp())
        .execute(self.pool.as_ref())
        .await?;

        sqlx::query(
            r#"
UPDATE task_watches
SET lease_owner = NULL,
    lease_until = NULL,
    last_run_turn_id = ?,
    last_run_status = ?,
    last_error = NULL,
    updated_at = ?
WHERE id = ?
            "#,
        )
        .bind(turn_id)
        .bind(TaskWatchRunStatus::Running.as_str())
        .bind(started_at.timestamp())
        .bind(&task_watch.id)
        .execute(self.pool.as_ref())
        .await?;

        Ok(run_id)
    }

    pub async fn list_running_task_watch_runs(&self) -> anyhow::Result<Vec<RunningTaskWatchRun>> {
        let rows = sqlx::query_as::<_, TaskWatchRunRow>(
            r#"
SELECT
    id,
    task_watch_id,
    thread_id,
    turn_id,
    scheduled_for,
    status,
    summary,
    error,
    started_at,
    finished_at
FROM task_watch_runs
WHERE status = ?
ORDER BY started_at ASC, id ASC
            "#,
        )
        .bind(TaskWatchRunStatus::Running.as_str())
        .fetch_all(self.pool.as_ref())
        .await?;

        rows.into_iter()
            .map(|row| {
                let turn_id = row
                    .turn_id
                    .ok_or_else(|| anyhow::anyhow!("running task watch run missing turn_id"))?;
                Ok(RunningTaskWatchRun {
                    id: row.id,
                    task_watch_id: row.task_watch_id,
                    thread_id: row.thread_id,
                    turn_id,
                    started_at: DateTime::from_timestamp(row.started_at, 0)
                        .ok_or_else(|| anyhow::anyhow!("invalid started_at"))?,
                })
            })
            .collect()
    }

    pub async fn list_task_watch_runs(
        &self,
        task_watch_id: Option<&str>,
    ) -> anyhow::Result<Vec<TaskWatchRun>> {
        let rows = if let Some(task_watch_id) = task_watch_id {
            sqlx::query_as::<_, TaskWatchRunRow>(
                r#"
SELECT
    id,
    task_watch_id,
    thread_id,
    turn_id,
    scheduled_for,
    status,
    summary,
    error,
    started_at,
    finished_at
FROM task_watch_runs
WHERE task_watch_id = ?
ORDER BY started_at DESC, id DESC
                "#,
            )
            .bind(task_watch_id)
            .fetch_all(self.pool.as_ref())
            .await?
        } else {
            sqlx::query_as::<_, TaskWatchRunRow>(
                r#"
SELECT
    id,
    task_watch_id,
    thread_id,
    turn_id,
    scheduled_for,
    status,
    summary,
    error,
    started_at,
    finished_at
FROM task_watch_runs
ORDER BY started_at DESC, id DESC
                "#,
            )
            .fetch_all(self.pool.as_ref())
            .await?
        };
        rows.into_iter().map(TryInto::try_into).collect()
    }

    pub async fn complete_task_watch_run(
        &self,
        run_id: &str,
        task_watch_id: &str,
        status: TaskWatchRunStatus,
        finished_at: DateTime<Utc>,
        summary: Option<&str>,
        error: Option<&str>,
    ) -> anyhow::Result<()> {
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await?;

        sqlx::query(
            r#"
UPDATE task_watch_runs
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
        .execute(&mut *tx)
        .await?;

        let task_watch = sqlx::query_as::<_, TaskWatchRow>(
            r#"
SELECT
    id,
    thread_id,
    title,
    objective,
    prompt,
    cadence_seconds,
    next_check_at,
    max_checks,
    check_count,
    requires_response,
    status,
    last_decision,
    last_observation,
    last_run_turn_id,
    last_run_status,
    last_error,
    created_at,
    updated_at,
    stopped_at
FROM task_watches
WHERE id = ?
            "#,
        )
        .bind(task_watch_id)
        .fetch_optional(&mut *tx)
        .await?;

        let (next_check_at, check_count, task_watch_status, stopped_at) = match task_watch {
            Some(task_watch) => {
                let check_count = task_watch.check_count + 1;
                let task_watch_status = TaskWatchStatus::parse(task_watch.status.as_str())?;
                let max_checks_reached = task_watch
                    .max_checks
                    .is_some_and(|max_checks| check_count >= max_checks);
                let next_check_at = if task_watch_status == TaskWatchStatus::Active {
                    Some(
                        advance_interval_after(
                            finished_at,
                            finished_at,
                            task_watch.cadence_seconds,
                        )
                        .timestamp(),
                    )
                } else {
                    None
                };
                let task_watch_status =
                    if task_watch_status == TaskWatchStatus::Active && max_checks_reached {
                        TaskWatchStatus::Stopped
                    } else {
                        task_watch_status
                    };
                let stopped_at = matches!(
                    task_watch_status,
                    TaskWatchStatus::Completed | TaskWatchStatus::Stopped
                )
                .then_some(finished_at.timestamp());
                (next_check_at, check_count, task_watch_status, stopped_at)
            }
            None => return Ok(()),
        };

        sqlx::query(
            r#"
UPDATE task_watches
SET next_check_at = COALESCE(?, next_check_at),
    check_count = ?,
    status = ?,
    stopped_at = COALESCE(?, stopped_at),
    last_run_status = ?,
    last_error = ?,
    updated_at = ?
WHERE id = ?
            "#,
        )
        .bind(next_check_at)
        .bind(check_count)
        .bind(task_watch_status.as_str())
        .bind(stopped_at)
        .bind(status.as_str())
        .bind(error)
        .bind(finished_at.timestamp())
        .bind(task_watch_id)
        .execute(&mut *tx)
        .await?;
        tx.commit().await?;
        Ok(())
    }

    pub async fn deliver_task_watch_to_active_thread(
        &self,
        task_watch: &ClaimedTaskWatch,
        turn_id: Option<&str>,
        delivered_at: DateTime<Utc>,
        summary: &str,
    ) -> anyhow::Result<String> {
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        let run_id = uuid::Uuid::new_v4().to_string();
        sqlx::query(
            r#"
INSERT INTO task_watch_runs (
    id,
    task_watch_id,
    thread_id,
    turn_id,
    scheduled_for,
    status,
    summary,
    started_at,
    finished_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            "#,
        )
        .bind(&run_id)
        .bind(&task_watch.id)
        .bind(&task_watch.thread_id)
        .bind(turn_id)
        .bind(task_watch.scheduled_for.timestamp())
        .bind(TaskWatchRunStatus::Completed.as_str())
        .bind(summary)
        .bind(delivered_at.timestamp())
        .bind(delivered_at.timestamp())
        .execute(&mut *tx)
        .await?;

        let task_watch_row = sqlx::query_as::<_, TaskWatchRow>(
            r#"
SELECT
    id,
    thread_id,
    title,
    objective,
    prompt,
    cadence_seconds,
    next_check_at,
    max_checks,
    check_count,
    requires_response,
    status,
    last_decision,
    last_observation,
    last_run_turn_id,
    last_run_status,
    last_error,
    created_at,
    updated_at,
    stopped_at
FROM task_watches
WHERE id = ?
            "#,
        )
        .bind(&task_watch.id)
        .fetch_optional(&mut *tx)
        .await?;

        let Some(task_watch_row) = task_watch_row else {
            return Ok(run_id);
        };

        let check_count = task_watch_row.check_count + 1;
        let current_status = TaskWatchStatus::parse(task_watch_row.status.as_str())?;
        let max_checks_reached = task_watch_row
            .max_checks
            .is_some_and(|max_checks| check_count >= max_checks);
        let next_check_at = if current_status == TaskWatchStatus::Active {
            Some(
                advance_interval_after(delivered_at, delivered_at, task_watch_row.cadence_seconds)
                    .timestamp(),
            )
        } else {
            None
        };
        let status = if current_status == TaskWatchStatus::Active && max_checks_reached {
            TaskWatchStatus::Stopped
        } else {
            current_status
        };
        let stopped_at = matches!(
            status,
            TaskWatchStatus::Completed | TaskWatchStatus::Stopped
        )
        .then_some(delivered_at.timestamp());

        sqlx::query(
            r#"
UPDATE task_watches
SET lease_owner = NULL,
    lease_until = NULL,
    next_check_at = COALESCE(?, next_check_at),
    check_count = ?,
    status = ?,
    stopped_at = COALESCE(?, stopped_at),
    last_run_turn_id = COALESCE(?, last_run_turn_id),
    last_run_status = ?,
    last_error = NULL,
    updated_at = ?
WHERE id = ?
            "#,
        )
        .bind(next_check_at)
        .bind(check_count)
        .bind(status.as_str())
        .bind(stopped_at)
        .bind(turn_id)
        .bind(TaskWatchRunStatus::Completed.as_str())
        .bind(delivered_at.timestamp())
        .bind(&task_watch.id)
        .execute(&mut *tx)
        .await?;
        tx.commit().await?;

        Ok(run_id)
    }

    pub async fn fail_task_watch(
        &self,
        task_watch_id: &str,
        status: TaskWatchStatus,
        error: &str,
        now: DateTime<Utc>,
    ) -> anyhow::Result<()> {
        sqlx::query(
            r#"
UPDATE task_watches
SET status = ?,
    stopped_at = ?,
    lease_owner = NULL,
    lease_until = NULL,
    last_run_status = ?,
    last_error = ?,
    updated_at = ?
WHERE id = ?
            "#,
        )
        .bind(status.as_str())
        .bind(now.timestamp())
        .bind(TaskWatchRunStatus::Failed.as_str())
        .bind(error)
        .bind(now.timestamp())
        .bind(task_watch_id)
        .execute(self.pool.as_ref())
        .await?;
        Ok(())
    }
}

fn advance_interval_after(
    scheduled_for: DateTime<Utc>,
    now: DateTime<Utc>,
    cadence_seconds: i64,
) -> DateTime<Utc> {
    let mut next = scheduled_for;
    let interval = chrono::Duration::seconds(cadence_seconds.max(1));
    while next <= now {
        next += interval;
    }
    next
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::StateRuntime;

    #[tokio::test]
    async fn task_watch_can_be_claimed_and_started() {
        let tempdir = tempfile::tempdir().expect("tempdir");
        let runtime = StateRuntime::init(tempdir.path().to_path_buf(), "test-provider".to_string())
            .await
            .expect("state runtime");
        let thread_id = ThreadId::new();
        let metadata = crate::runtime::test_support::test_thread_metadata(
            tempdir.path(),
            thread_id,
            tempdir.path().to_path_buf(),
        );
        runtime
            .upsert_thread(&metadata)
            .await
            .expect("upsert thread");

        let now = Utc::now();
        runtime
            .create_task_watch(crate::TaskWatchCreateParams {
                id: "watch-1".to_string(),
                thread_id: thread_id.to_string(),
                title: "watch deploy".to_string(),
                objective: "keep checking deploy".to_string(),
                prompt: "inspect deploy".to_string(),
                cadence_seconds: 60,
                next_check_at: now,
                max_checks: Some(3),
                requires_response: true,
            })
            .await
            .expect("create task watch");

        let claimed = runtime
            .claim_due_task_watches(now, "worker-1", 10, Duration::from_secs(30))
            .await
            .expect("claim due task watches");
        assert_eq!(claimed.len(), 1);

        runtime
            .start_task_watch_run(&claimed[0], "turn-1", now)
            .await
            .expect("start task watch run");

        let watches = runtime
            .list_task_watches(Some(thread_id))
            .await
            .expect("list task watches");
        assert_eq!(watches.len(), 1);
        assert_eq!(watches[0].check_count, 0);
        assert_eq!(watches[0].status, TaskWatchStatus::Active);
        assert_eq!(watches[0].last_run_turn_id.as_deref(), Some("turn-1"));
        assert_eq!(
            watches[0].last_run_status,
            Some(TaskWatchRunStatus::Running)
        );
    }

    #[tokio::test]
    async fn running_task_watch_cannot_be_claimed_twice() {
        let tempdir = tempfile::tempdir().expect("tempdir");
        let runtime = StateRuntime::init(tempdir.path().to_path_buf(), "test-provider".to_string())
            .await
            .expect("state runtime");
        let thread_id = ThreadId::new();
        let metadata = crate::runtime::test_support::test_thread_metadata(
            tempdir.path(),
            thread_id,
            tempdir.path().to_path_buf(),
        );
        runtime
            .upsert_thread(&metadata)
            .await
            .expect("upsert thread");

        let now = Utc::now();
        runtime
            .create_task_watch(crate::TaskWatchCreateParams {
                id: "watch-running".to_string(),
                thread_id: thread_id.to_string(),
                title: "watch deploy".to_string(),
                objective: "keep checking deploy".to_string(),
                prompt: "inspect deploy".to_string(),
                cadence_seconds: 30,
                next_check_at: now,
                max_checks: Some(3),
                requires_response: true,
            })
            .await
            .expect("create task watch");

        let claimed = runtime
            .claim_due_task_watches(now, "worker-1", 10, Duration::from_secs(30))
            .await
            .expect("claim due task watches");
        assert_eq!(claimed.len(), 1);
        runtime
            .start_task_watch_run(&claimed[0], "turn-running", now)
            .await
            .expect("start task watch run");

        let claimed_again = runtime
            .claim_due_task_watches(
                now + chrono::Duration::seconds(31),
                "worker-2",
                10,
                Duration::from_secs(30),
            )
            .await
            .expect("claim due task watches again");
        assert!(claimed_again.is_empty());
    }

    #[tokio::test]
    async fn completing_task_watch_run_advances_next_check_and_count() {
        let tempdir = tempfile::tempdir().expect("tempdir");
        let runtime = StateRuntime::init(tempdir.path().to_path_buf(), "test-provider".to_string())
            .await
            .expect("state runtime");
        let thread_id = ThreadId::new();
        let metadata = crate::runtime::test_support::test_thread_metadata(
            tempdir.path(),
            thread_id,
            tempdir.path().to_path_buf(),
        );
        runtime
            .upsert_thread(&metadata)
            .await
            .expect("upsert thread");

        let started_at = Utc::now();
        runtime
            .create_task_watch(crate::TaskWatchCreateParams {
                id: "watch-complete".to_string(),
                thread_id: thread_id.to_string(),
                title: "watch deploy".to_string(),
                objective: "keep checking deploy".to_string(),
                prompt: "inspect deploy".to_string(),
                cadence_seconds: 30,
                next_check_at: started_at,
                max_checks: Some(3),
                requires_response: true,
            })
            .await
            .expect("create task watch");

        let claimed = runtime
            .claim_due_task_watches(started_at, "worker-1", 10, Duration::from_secs(30))
            .await
            .expect("claim due task watches");
        let run_id = runtime
            .start_task_watch_run(&claimed[0], "turn-complete", started_at)
            .await
            .expect("start task watch run");

        let finished_at = started_at + chrono::Duration::seconds(90);
        runtime
            .complete_task_watch_run(
                &run_id,
                "watch-complete",
                TaskWatchRunStatus::Completed,
                finished_at,
                Some("done"),
                None,
            )
            .await
            .expect("complete task watch run");

        let watches = runtime
            .list_task_watches(Some(thread_id))
            .await
            .expect("list task watches");
        assert_eq!(watches.len(), 1);
        assert_eq!(watches[0].check_count, 1);
        assert_eq!(watches[0].status, TaskWatchStatus::Active);
        assert_eq!(
            watches[0].next_check_at.timestamp(),
            (finished_at + chrono::Duration::seconds(30)).timestamp()
        );
        assert_eq!(
            watches[0].last_run_status,
            Some(TaskWatchRunStatus::Completed)
        );

        let claimed_again = runtime
            .claim_due_task_watches(finished_at, "worker-2", 10, Duration::from_secs(30))
            .await
            .expect("claim due task watches again");
        assert!(claimed_again.is_empty());
    }

    #[tokio::test]
    async fn completing_task_watch_run_preserves_completed_status() {
        let tempdir = tempfile::tempdir().expect("tempdir");
        let runtime = StateRuntime::init(tempdir.path().to_path_buf(), "test-provider".to_string())
            .await
            .expect("state runtime");
        let thread_id = ThreadId::new();
        let metadata = crate::runtime::test_support::test_thread_metadata(
            tempdir.path(),
            thread_id,
            tempdir.path().to_path_buf(),
        );
        runtime
            .upsert_thread(&metadata)
            .await
            .expect("upsert thread");

        let started_at = Utc::now();
        runtime
            .create_task_watch(crate::TaskWatchCreateParams {
                id: "watch-preserve".to_string(),
                thread_id: thread_id.to_string(),
                title: "watch deploy".to_string(),
                objective: "keep checking deploy".to_string(),
                prompt: "inspect deploy".to_string(),
                cadence_seconds: 30,
                next_check_at: started_at,
                max_checks: Some(3),
                requires_response: true,
            })
            .await
            .expect("create task watch");

        let claimed = runtime
            .claim_due_task_watches(started_at, "worker-1", 10, Duration::from_secs(30))
            .await
            .expect("claim due task watches");
        let run_id = runtime
            .start_task_watch_run(&claimed[0], "turn-complete", started_at)
            .await
            .expect("start task watch run");

        let accepted = runtime
            .update_task_watch(crate::TaskWatchUpdateParams {
                id: "watch-preserve".to_string(),
                cadence_seconds: None,
                next_check_at: None,
                max_checks: None,
                last_decision: Some("complete".to_string()),
                last_observation: Some("lane assigned".to_string()),
                status: Some(TaskWatchStatus::Completed),
            })
            .await
            .expect("update task watch");
        assert!(accepted);

        let finished_at = started_at + chrono::Duration::seconds(5);
        runtime
            .complete_task_watch_run(
                &run_id,
                "watch-preserve",
                TaskWatchRunStatus::Completed,
                finished_at,
                Some("done"),
                None,
            )
            .await
            .expect("complete task watch run");

        let watches = runtime
            .list_task_watches(Some(thread_id))
            .await
            .expect("list task watches");
        assert_eq!(watches.len(), 1);
        assert_eq!(watches[0].status, TaskWatchStatus::Completed);
        assert_eq!(watches[0].check_count, 1);
    }

    #[tokio::test]
    async fn delivering_task_watch_to_active_thread_advances_without_failure() {
        let tempdir = tempfile::tempdir().expect("tempdir");
        let runtime = StateRuntime::init(tempdir.path().to_path_buf(), "test-provider".to_string())
            .await
            .expect("state runtime");
        let thread_id = ThreadId::new();
        let metadata = crate::runtime::test_support::test_thread_metadata(
            tempdir.path(),
            thread_id,
            tempdir.path().to_path_buf(),
        );
        runtime
            .upsert_thread(&metadata)
            .await
            .expect("upsert thread");

        let now = Utc::now();
        runtime
            .create_task_watch(crate::TaskWatchCreateParams {
                id: "watch-deliver".to_string(),
                thread_id: thread_id.to_string(),
                title: "watch deploy".to_string(),
                objective: "keep checking deploy".to_string(),
                prompt: "inspect deploy".to_string(),
                cadence_seconds: 30,
                next_check_at: now,
                max_checks: Some(3),
                requires_response: true,
            })
            .await
            .expect("create task watch");

        let claimed = runtime
            .claim_due_task_watches(now, "worker-1", 10, Duration::from_secs(30))
            .await
            .expect("claim due task watches");
        assert_eq!(claimed.len(), 1);

        runtime
            .deliver_task_watch_to_active_thread(
                &claimed[0],
                Some("turn-active"),
                now,
                "task watch wake was appended to an already-active thread",
            )
            .await
            .expect("deliver task watch");

        let watches = runtime
            .list_task_watches(Some(thread_id))
            .await
            .expect("list task watches");
        assert_eq!(watches.len(), 1);
        assert_eq!(watches[0].check_count, 1);
        assert_eq!(watches[0].status, TaskWatchStatus::Active);
        assert_eq!(watches[0].last_run_turn_id.as_deref(), Some("turn-active"));
        assert_eq!(
            watches[0].last_run_status,
            Some(TaskWatchRunStatus::Completed)
        );
        assert_eq!(
            watches[0].next_check_at.timestamp(),
            (now + chrono::Duration::seconds(30)).timestamp()
        );

        let claimed_again = runtime
            .claim_due_task_watches(now, "worker-2", 10, Duration::from_secs(30))
            .await
            .expect("claim due task watches again");
        assert!(claimed_again.is_empty());
    }

    #[tokio::test]
    async fn update_task_watch_mutates_same_row_in_place() {
        let tempdir = tempfile::tempdir().expect("tempdir");
        let runtime = StateRuntime::init(tempdir.path().to_path_buf(), "test-provider".to_string())
            .await
            .expect("state runtime");
        let thread_id = ThreadId::new();
        let metadata = crate::runtime::test_support::test_thread_metadata(
            tempdir.path(),
            thread_id,
            tempdir.path().to_path_buf(),
        );
        runtime
            .upsert_thread(&metadata)
            .await
            .expect("upsert thread");

        runtime
            .create_task_watch(crate::TaskWatchCreateParams {
                id: "watch-2".to_string(),
                thread_id: thread_id.to_string(),
                title: "watch ci".to_string(),
                objective: "keep checking ci".to_string(),
                prompt: "inspect ci".to_string(),
                cadence_seconds: 60,
                next_check_at: Utc::now(),
                max_checks: None,
                requires_response: true,
            })
            .await
            .expect("create task watch");

        let accepted = runtime
            .update_task_watch(crate::TaskWatchUpdateParams {
                id: "watch-2".to_string(),
                cadence_seconds: Some(300),
                next_check_at: None,
                max_checks: Some(10),
                last_decision: Some("continue_with_backoff".to_string()),
                last_observation: Some("still pending".to_string()),
                status: None,
            })
            .await
            .expect("update task watch");
        assert!(accepted);

        let watches = runtime
            .list_task_watches(Some(thread_id))
            .await
            .expect("list task watches");
        assert_eq!(watches.len(), 1);
        assert_eq!(watches[0].cadence_seconds, 300);
        assert_eq!(watches[0].max_checks, Some(10));
        assert_eq!(
            watches[0].last_decision.as_deref(),
            Some("continue_with_backoff")
        );
        assert_eq!(
            watches[0].last_observation.as_deref(),
            Some("still pending")
        );
    }
}
