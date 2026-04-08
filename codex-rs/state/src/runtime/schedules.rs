use super::*;
use crate::model::ClaimedScheduledTask;
use crate::model::RunningScheduledTaskRun;
use crate::model::ScheduledTaskCreateParams;
use crate::model::ScheduledTaskKind;
use crate::model::ScheduledTaskRow;
use crate::model::ScheduledTaskRun;
use crate::model::ScheduledTaskRunRow;
use crate::model::ScheduledTaskRunStatus;

impl StateRuntime {
    pub async fn create_scheduled_task(
        &self,
        params: ScheduledTaskCreateParams,
    ) -> anyhow::Result<()> {
        let now = Utc::now().timestamp();
        sqlx::query(
            r#"
INSERT INTO scheduled_tasks (
    id,
    thread_id,
    title,
    prompt,
    schedule_kind,
    next_run_at,
    interval_seconds,
    enabled,
    requires_response,
    created_at,
    updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            "#,
        )
        .bind(params.id)
        .bind(params.thread_id)
        .bind(params.title)
        .bind(params.prompt)
        .bind(params.kind.as_str())
        .bind(params.next_run_at.timestamp())
        .bind(params.interval_seconds)
        .bind(i64::from(params.requires_response))
        .bind(now)
        .bind(now)
        .execute(self.pool.as_ref())
        .await?;
        Ok(())
    }

    pub async fn list_scheduled_tasks(
        &self,
        thread_id: Option<ThreadId>,
    ) -> anyhow::Result<Vec<crate::ScheduledTask>> {
        let rows = if let Some(thread_id) = thread_id {
            sqlx::query_as::<_, ScheduledTaskRow>(
                r#"
SELECT
    id,
    thread_id,
    title,
    prompt,
    schedule_kind,
    next_run_at,
    interval_seconds,
    enabled,
    requires_response,
    last_run_turn_id,
    last_run_status,
    last_error,
    created_at,
    updated_at
FROM scheduled_tasks
WHERE thread_id = ?
ORDER BY next_run_at ASC, id ASC
                "#,
            )
            .bind(thread_id.to_string())
            .fetch_all(self.pool.as_ref())
            .await?
        } else {
            sqlx::query_as::<_, ScheduledTaskRow>(
                r#"
SELECT
    id,
    thread_id,
    title,
    prompt,
    schedule_kind,
    next_run_at,
    interval_seconds,
    enabled,
    requires_response,
    last_run_turn_id,
    last_run_status,
    last_error,
    created_at,
    updated_at
FROM scheduled_tasks
ORDER BY next_run_at ASC, id ASC
                "#,
            )
            .fetch_all(self.pool.as_ref())
            .await?
        };
        rows.into_iter().map(TryInto::try_into).collect()
    }

    pub async fn delete_scheduled_task(&self, id: &str) -> anyhow::Result<bool> {
        let result = sqlx::query("DELETE FROM scheduled_tasks WHERE id = ?")
            .bind(id)
            .execute(self.pool.as_ref())
            .await?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn trigger_scheduled_task_now(&self, id: &str) -> anyhow::Result<bool> {
        let now = Utc::now().timestamp();
        let result = sqlx::query(
            "UPDATE scheduled_tasks SET next_run_at = ?, updated_at = ?, enabled = 1 WHERE id = ?",
        )
        .bind(now)
        .bind(now)
        .bind(id)
        .execute(self.pool.as_ref())
        .await?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn claim_due_scheduled_tasks(
        &self,
        now: DateTime<Utc>,
        worker_id: &str,
        limit: usize,
        lease_duration: Duration,
    ) -> anyhow::Result<Vec<ClaimedScheduledTask>> {
        let due_rows = sqlx::query_as::<_, ScheduledTaskRow>(
            r#"
SELECT
    id,
    thread_id,
    title,
    prompt,
    schedule_kind,
    next_run_at,
    interval_seconds,
    enabled,
    requires_response,
    last_run_turn_id,
    last_run_status,
    last_error,
    created_at,
    updated_at
FROM scheduled_tasks
WHERE enabled = 1
  AND next_run_at <= ?
  AND (lease_until IS NULL OR lease_until < ?)
ORDER BY next_run_at ASC, id ASC
LIMIT ?
            "#,
        )
        .bind(now.timestamp())
        .bind(now.timestamp())
        .bind(i64::try_from(limit).unwrap_or(i64::MAX))
        .fetch_all(self.pool.as_ref())
        .await?;

        let mut claimed = Vec::new();
        let lease_until = now + chrono::Duration::from_std(lease_duration)?;
        for row in due_rows {
            let result = sqlx::query(
                r#"
UPDATE scheduled_tasks
SET lease_owner = ?, lease_until = ?, updated_at = ?
WHERE id = ?
  AND enabled = 1
  AND next_run_at = ?
  AND (lease_until IS NULL OR lease_until < ?)
                "#,
            )
            .bind(worker_id)
            .bind(lease_until.timestamp())
            .bind(now.timestamp())
            .bind(&row.id)
            .bind(row.next_run_at)
            .bind(now.timestamp())
            .execute(self.pool.as_ref())
            .await?;
            if result.rows_affected() == 0 {
                continue;
            }
            claimed.push(ClaimedScheduledTask {
                id: row.id,
                thread_id: row.thread_id,
                title: row.title,
                prompt: row.prompt,
                kind: ScheduledTaskKind::parse(row.schedule_kind.as_str())?,
                scheduled_for: DateTime::from_timestamp(row.next_run_at, 0)
                    .ok_or_else(|| anyhow::anyhow!("invalid next_run_at"))?,
                interval_seconds: row.interval_seconds,
                requires_response: row.requires_response != 0,
            });
        }
        Ok(claimed)
    }

    pub async fn release_scheduled_task_claim(
        &self,
        id: &str,
        next_run_at: DateTime<Utc>,
        last_error: Option<&str>,
    ) -> anyhow::Result<()> {
        sqlx::query(
            r#"
UPDATE scheduled_tasks
SET lease_owner = NULL,
    lease_until = NULL,
    next_run_at = ?,
    last_error = ?,
    updated_at = ?
WHERE id = ?
            "#,
        )
        .bind(next_run_at.timestamp())
        .bind(last_error)
        .bind(Utc::now().timestamp())
        .bind(id)
        .execute(self.pool.as_ref())
        .await?;
        Ok(())
    }

    pub async fn start_scheduled_task_run(
        &self,
        task: &ClaimedScheduledTask,
        turn_id: &str,
        started_at: DateTime<Utc>,
    ) -> anyhow::Result<String> {
        let run_id = uuid::Uuid::new_v4().to_string();
        let (enabled, next_run_at) = match task.kind {
            ScheduledTaskKind::Once => (false, Some(task.scheduled_for.timestamp())),
            ScheduledTaskKind::Interval => {
                let interval_seconds = task.interval_seconds.ok_or_else(|| {
                    anyhow::anyhow!("interval scheduled task missing interval_seconds")
                })?;
                let next_run_at =
                    advance_interval_after(task.scheduled_for, started_at, interval_seconds);
                (true, Some(next_run_at.timestamp()))
            }
        };
        sqlx::query(
            r#"
INSERT INTO scheduled_task_runs (
    id,
    scheduled_task_id,
    thread_id,
    turn_id,
    scheduled_for,
    status,
    started_at
) VALUES (?, ?, ?, ?, ?, ?, ?)
            "#,
        )
        .bind(&run_id)
        .bind(&task.id)
        .bind(&task.thread_id)
        .bind(turn_id)
        .bind(task.scheduled_for.timestamp())
        .bind(ScheduledTaskRunStatus::Running.as_str())
        .bind(started_at.timestamp())
        .execute(self.pool.as_ref())
        .await?;

        sqlx::query(
            r#"
UPDATE scheduled_tasks
SET lease_owner = NULL,
    lease_until = NULL,
    next_run_at = ?,
    enabled = ?,
    last_run_turn_id = ?,
    last_run_status = ?,
    last_error = NULL,
    updated_at = ?
WHERE id = ?
            "#,
        )
        .bind(next_run_at)
        .bind(i64::from(enabled))
        .bind(turn_id)
        .bind(ScheduledTaskRunStatus::Running.as_str())
        .bind(started_at.timestamp())
        .bind(&task.id)
        .execute(self.pool.as_ref())
        .await?;

        Ok(run_id)
    }

    pub async fn record_scheduled_task_start_failure(
        &self,
        task: &ClaimedScheduledTask,
        finished_at: DateTime<Utc>,
        retry_at: DateTime<Utc>,
        error: &str,
    ) -> anyhow::Result<String> {
        let run_id = uuid::Uuid::new_v4().to_string();
        sqlx::query(
            r#"
INSERT INTO scheduled_task_runs (
    id,
    scheduled_task_id,
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
        .bind(&task.id)
        .bind(&task.thread_id)
        .bind(task.scheduled_for.timestamp())
        .bind(ScheduledTaskRunStatus::Failed.as_str())
        .bind("scheduled task did not start")
        .bind(error)
        .bind(finished_at.timestamp())
        .bind(finished_at.timestamp())
        .execute(self.pool.as_ref())
        .await?;

        sqlx::query(
            r#"
UPDATE scheduled_tasks
SET lease_owner = NULL,
    lease_until = NULL,
    next_run_at = ?,
    enabled = 1,
    last_run_status = ?,
    last_error = ?,
    updated_at = ?
WHERE id = ?
            "#,
        )
        .bind(retry_at.timestamp())
        .bind(ScheduledTaskRunStatus::Failed.as_str())
        .bind(error)
        .bind(finished_at.timestamp())
        .bind(&task.id)
        .execute(self.pool.as_ref())
        .await?;

        Ok(run_id)
    }

    pub async fn list_running_scheduled_task_runs(
        &self,
    ) -> anyhow::Result<Vec<RunningScheduledTaskRun>> {
        let rows = sqlx::query_as::<_, ScheduledTaskRunRow>(
            r#"
SELECT
    id,
    scheduled_task_id,
    thread_id,
    turn_id,
    scheduled_for,
    status,
    summary,
    error,
    started_at,
    finished_at
FROM scheduled_task_runs
WHERE status = ?
ORDER BY started_at ASC, id ASC
            "#,
        )
        .bind(ScheduledTaskRunStatus::Running.as_str())
        .fetch_all(self.pool.as_ref())
        .await?;

        rows.into_iter()
            .map(|row| {
                let turn_id = row
                    .turn_id
                    .ok_or_else(|| anyhow::anyhow!("running scheduled task run missing turn_id"))?;
                Ok(RunningScheduledTaskRun {
                    id: row.id,
                    scheduled_task_id: row.scheduled_task_id,
                    thread_id: row.thread_id,
                    turn_id,
                    started_at: DateTime::from_timestamp(row.started_at, 0)
                        .ok_or_else(|| anyhow::anyhow!("invalid started_at"))?,
                })
            })
            .collect()
    }

    pub async fn list_scheduled_task_runs(
        &self,
        task_id: Option<&str>,
    ) -> anyhow::Result<Vec<ScheduledTaskRun>> {
        let rows = if let Some(task_id) = task_id {
            sqlx::query_as::<_, ScheduledTaskRunRow>(
                r#"
SELECT
    id,
    scheduled_task_id,
    thread_id,
    turn_id,
    scheduled_for,
    status,
    summary,
    error,
    started_at,
    finished_at
FROM scheduled_task_runs
WHERE scheduled_task_id = ?
ORDER BY started_at DESC, id DESC
                "#,
            )
            .bind(task_id)
            .fetch_all(self.pool.as_ref())
            .await?
        } else {
            sqlx::query_as::<_, ScheduledTaskRunRow>(
                r#"
SELECT
    id,
    scheduled_task_id,
    thread_id,
    turn_id,
    scheduled_for,
    status,
    summary,
    error,
    started_at,
    finished_at
FROM scheduled_task_runs
ORDER BY started_at DESC, id DESC
                "#,
            )
            .fetch_all(self.pool.as_ref())
            .await?
        };

        rows.into_iter().map(TryInto::try_into).collect()
    }

    pub async fn complete_scheduled_task_run(
        &self,
        run_id: &str,
        scheduled_task_id: &str,
        status: ScheduledTaskRunStatus,
        finished_at: DateTime<Utc>,
        summary: Option<&str>,
        error: Option<&str>,
    ) -> anyhow::Result<()> {
        sqlx::query(
            r#"
UPDATE scheduled_task_runs
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
UPDATE scheduled_tasks
SET last_run_status = ?,
    last_error = ?,
    updated_at = ?
WHERE id = ?
            "#,
        )
        .bind(status.as_str())
        .bind(error)
        .bind(finished_at.timestamp())
        .bind(scheduled_task_id)
        .execute(self.pool.as_ref())
        .await?;
        Ok(())
    }
}

fn advance_interval_after(
    scheduled_for: DateTime<Utc>,
    now: DateTime<Utc>,
    interval_seconds: i64,
) -> DateTime<Utc> {
    let mut next = scheduled_for;
    let interval = chrono::Duration::seconds(interval_seconds.max(1));
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
    async fn scheduled_task_once_can_be_claimed_and_started() {
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
            .create_scheduled_task(ScheduledTaskCreateParams {
                id: "task-1".to_string(),
                thread_id: thread_id.to_string(),
                title: "once".to_string(),
                prompt: "ping".to_string(),
                kind: ScheduledTaskKind::Once,
                next_run_at: now,
                interval_seconds: None,
                requires_response: true,
            })
            .await
            .expect("create scheduled task");

        let claimed = runtime
            .claim_due_scheduled_tasks(now, "worker-1", 10, Duration::from_secs(30))
            .await
            .expect("claim due tasks");
        assert_eq!(claimed.len(), 1);

        let _run_id = runtime
            .start_scheduled_task_run(&claimed[0], "turn-1", now)
            .await
            .expect("start run");

        let tasks = runtime
            .list_scheduled_tasks(Some(thread_id))
            .await
            .expect("list tasks");
        assert_eq!(tasks.len(), 1);
        assert!(!tasks[0].enabled);
        assert_eq!(tasks[0].last_run_turn_id.as_deref(), Some("turn-1"));
    }
}
