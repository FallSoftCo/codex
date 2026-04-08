use super::*;
use crate::model::ClaimedTesterRun;
use crate::model::TesterRunArtifact;
use crate::model::TesterRunArtifactKind;
use crate::model::TesterRunArtifactRow;
use crate::model::TesterRunCreateParams;
use crate::model::TesterRunReport;
use crate::model::TesterRunReportKind;
use crate::model::TesterRunReportRow;
use crate::model::TesterRunRow;
use crate::model::TesterRunStatus;

fn serialize_string_vec(values: &[String]) -> anyhow::Result<String> {
    serde_json::to_string(values).map_err(Into::into)
}

impl StateRuntime {
    pub async fn create_tester_run(&self, params: TesterRunCreateParams) -> anyhow::Result<()> {
        let now = Utc::now().timestamp();
        let starting_knowledge_json = serialize_string_vec(&params.starting_knowledge)?;
        let constraints_json = serialize_string_vec(&params.constraints)?;
        let allowed_interfaces_json = serialize_string_vec(&params.allowed_interfaces)?;

        sqlx::query(
            r#"
INSERT INTO tester_runs (
    id,
    name,
    objective,
    background,
    skill_level,
    temperament,
    starting_knowledge_json,
    constraints_json,
    allowed_interfaces_json,
    execution_class,
    controller_thread_id,
    runtime_thread_id,
    rollout_path,
    cwd,
    status,
    last_observed_thread_status,
    last_error,
    last_parsed_rollout_index,
    created_at,
    updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, NULL, NULL, 0, ?, ?)
            "#,
        )
        .bind(&params.id)
        .bind(&params.name)
        .bind(&params.objective)
        .bind(&params.background)
        .bind(&params.skill_level)
        .bind(&params.temperament)
        .bind(starting_knowledge_json)
        .bind(constraints_json)
        .bind(allowed_interfaces_json)
        .bind(params.execution_class.as_str())
        .bind(&params.controller_thread_id)
        .bind(
            params
                .cwd
                .as_ref()
                .map(|cwd| cwd.to_string_lossy().into_owned()),
        )
        .bind(TesterRunStatus::Queued.as_str())
        .bind(now)
        .bind(now)
        .execute(self.pool.as_ref())
        .await?;

        self.append_tester_run_report(
            &params.id,
            TesterRunReportKind::Created,
            format!("tester run {} created", params.name),
            Some(format!(
                "execution_class={} allowed_interfaces={}",
                params.execution_class.as_str(),
                params.allowed_interfaces.join(",")
            )),
        )
        .await?;
        Ok(())
    }

    pub async fn list_tester_runs(&self) -> anyhow::Result<Vec<crate::TesterRun>> {
        let rows = sqlx::query_as::<_, TesterRunRow>(
            r#"
SELECT
    id,
    name,
    objective,
    background,
    skill_level,
    temperament,
    starting_knowledge_json,
    constraints_json,
    allowed_interfaces_json,
    execution_class,
    controller_thread_id,
    runtime_thread_id,
    rollout_path,
    cwd,
    status,
    last_observed_thread_status,
    last_error,
    last_parsed_rollout_index,
    created_at,
    updated_at
FROM tester_runs
ORDER BY created_at DESC, id DESC
            "#,
        )
        .fetch_all(self.pool.as_ref())
        .await?;
        rows.into_iter().map(TryInto::try_into).collect()
    }

    pub async fn get_tester_run(&self, id: &str) -> anyhow::Result<Option<crate::TesterRun>> {
        let row = sqlx::query_as::<_, TesterRunRow>(
            r#"
SELECT
    id,
    name,
    objective,
    background,
    skill_level,
    temperament,
    starting_knowledge_json,
    constraints_json,
    allowed_interfaces_json,
    execution_class,
    controller_thread_id,
    runtime_thread_id,
    rollout_path,
    cwd,
    status,
    last_observed_thread_status,
    last_error,
    last_parsed_rollout_index,
    created_at,
    updated_at
FROM tester_runs
WHERE id = ?
            "#,
        )
        .bind(id)
        .fetch_optional(self.pool.as_ref())
        .await?;
        row.map(TryInto::try_into).transpose()
    }

    pub async fn claim_queued_tester_runs(
        &self,
        now: DateTime<Utc>,
        worker_id: &str,
        limit: usize,
        lease_duration: Duration,
    ) -> anyhow::Result<Vec<ClaimedTesterRun>> {
        let rows = sqlx::query_as::<_, TesterRunRow>(
            r#"
SELECT
    id,
    name,
    objective,
    background,
    skill_level,
    temperament,
    starting_knowledge_json,
    constraints_json,
    allowed_interfaces_json,
    execution_class,
    controller_thread_id,
    runtime_thread_id,
    rollout_path,
    cwd,
    status,
    last_observed_thread_status,
    last_error,
    last_parsed_rollout_index,
    created_at,
    updated_at
FROM tester_runs
WHERE status = ?
  AND runtime_thread_id IS NULL
  AND (lease_until IS NULL OR lease_until < ?)
ORDER BY created_at ASC, id ASC
LIMIT ?
            "#,
        )
        .bind(TesterRunStatus::Queued.as_str())
        .bind(now.timestamp())
        .bind(i64::try_from(limit).unwrap_or(i64::MAX))
        .fetch_all(self.pool.as_ref())
        .await?;

        let lease_until = now + chrono::Duration::from_std(lease_duration)?;
        let mut claimed = Vec::new();
        for row in rows {
            let result = sqlx::query(
                r#"
UPDATE tester_runs
SET status = ?,
    lease_owner = ?,
    lease_until = ?,
    updated_at = ?
WHERE id = ?
  AND status = ?
  AND runtime_thread_id IS NULL
  AND (lease_until IS NULL OR lease_until < ?)
                "#,
            )
            .bind(TesterRunStatus::Starting.as_str())
            .bind(worker_id)
            .bind(lease_until.timestamp())
            .bind(now.timestamp())
            .bind(&row.id)
            .bind(TesterRunStatus::Queued.as_str())
            .bind(now.timestamp())
            .execute(self.pool.as_ref())
            .await?;
            if result.rows_affected() == 0 {
                continue;
            }

            let tester_run: crate::TesterRun = row.try_into()?;
            claimed.push(ClaimedTesterRun {
                id: tester_run.id,
                name: tester_run.name,
                objective: tester_run.objective,
                background: tester_run.background,
                skill_level: tester_run.skill_level,
                temperament: tester_run.temperament,
                starting_knowledge: tester_run.starting_knowledge,
                constraints: tester_run.constraints,
                allowed_interfaces: tester_run.allowed_interfaces,
                execution_class: tester_run.execution_class,
                controller_thread_id: tester_run.controller_thread_id,
                cwd: tester_run.cwd,
            });
        }
        Ok(claimed)
    }

    pub async fn mark_tester_run_started(
        &self,
        tester_run_id: &str,
        runtime_thread_id: &str,
        rollout_path: Option<&Path>,
        now: DateTime<Utc>,
    ) -> anyhow::Result<()> {
        sqlx::query(
            r#"
UPDATE tester_runs
SET runtime_thread_id = ?,
    rollout_path = ?,
    status = ?,
    last_observed_thread_status = ?,
    last_error = NULL,
    lease_owner = NULL,
    lease_until = NULL,
    updated_at = ?
WHERE id = ?
            "#,
        )
        .bind(runtime_thread_id)
        .bind(rollout_path.map(|path| path.to_string_lossy().into_owned()))
        .bind(TesterRunStatus::Running.as_str())
        .bind("active")
        .bind(now.timestamp())
        .bind(tester_run_id)
        .execute(self.pool.as_ref())
        .await?;
        Ok(())
    }

    pub async fn mark_tester_run_start_failed(
        &self,
        tester_run_id: &str,
        error: &str,
        now: DateTime<Utc>,
    ) -> anyhow::Result<()> {
        sqlx::query(
            r#"
UPDATE tester_runs
SET status = ?,
    last_error = ?,
    lease_owner = NULL,
    lease_until = NULL,
    updated_at = ?
WHERE id = ?
            "#,
        )
        .bind(TesterRunStatus::BlockedEnvironment.as_str())
        .bind(error)
        .bind(now.timestamp())
        .bind(tester_run_id)
        .execute(self.pool.as_ref())
        .await?;
        self.append_tester_run_report(
            tester_run_id,
            TesterRunReportKind::BlockedEnvironment,
            "tester run failed to start".to_string(),
            Some(error.to_string()),
        )
        .await?;
        Ok(())
    }

    pub async fn list_supervised_tester_runs(&self) -> anyhow::Result<Vec<crate::TesterRun>> {
        let rows = sqlx::query_as::<_, TesterRunRow>(
            r#"
SELECT
    id,
    name,
    objective,
    background,
    skill_level,
    temperament,
    starting_knowledge_json,
    constraints_json,
    allowed_interfaces_json,
    execution_class,
    controller_thread_id,
    runtime_thread_id,
    rollout_path,
    cwd,
    status,
    last_observed_thread_status,
    last_error,
    last_parsed_rollout_index,
    created_at,
    updated_at
FROM tester_runs
WHERE runtime_thread_id IS NOT NULL
  AND status IN (?, ?, ?)
ORDER BY updated_at ASC, id ASC
            "#,
        )
        .bind(TesterRunStatus::Running.as_str())
        .bind(TesterRunStatus::Starting.as_str())
        .bind(TesterRunStatus::BlockedProduct.as_str())
        .fetch_all(self.pool.as_ref())
        .await?;
        rows.into_iter().map(TryInto::try_into).collect()
    }

    pub async fn update_tester_run_supervisor_state(
        &self,
        tester_run_id: &str,
        status: TesterRunStatus,
        observed_thread_status: Option<&str>,
        last_error: Option<&str>,
        last_parsed_rollout_index: i64,
    ) -> anyhow::Result<()> {
        sqlx::query(
            r#"
UPDATE tester_runs
SET status = ?,
    last_observed_thread_status = ?,
    last_error = ?,
    last_parsed_rollout_index = ?,
    updated_at = ?
WHERE id = ?
            "#,
        )
        .bind(status.as_str())
        .bind(observed_thread_status)
        .bind(last_error)
        .bind(last_parsed_rollout_index)
        .bind(Utc::now().timestamp())
        .bind(tester_run_id)
        .execute(self.pool.as_ref())
        .await?;
        Ok(())
    }

    pub async fn stop_tester_run(&self, tester_run_id: &str) -> anyhow::Result<bool> {
        let result = sqlx::query(
            r#"
UPDATE tester_runs
SET status = ?,
    lease_owner = NULL,
    lease_until = NULL,
    updated_at = ?
WHERE id = ?
  AND status != ?
            "#,
        )
        .bind(TesterRunStatus::Stopped.as_str())
        .bind(Utc::now().timestamp())
        .bind(tester_run_id)
        .bind(TesterRunStatus::Stopped.as_str())
        .execute(self.pool.as_ref())
        .await?;
        if result.rows_affected() > 0 {
            self.append_tester_run_report(
                tester_run_id,
                TesterRunReportKind::Stopped,
                "tester run stopped".to_string(),
                None,
            )
            .await?;
            Ok(true)
        } else {
            Ok(false)
        }
    }

    pub async fn append_tester_run_report(
        &self,
        tester_run_id: &str,
        report_kind: TesterRunReportKind,
        summary: String,
        details: Option<String>,
    ) -> anyhow::Result<String> {
        let report_id = uuid::Uuid::new_v4().to_string();
        sqlx::query(
            r#"
INSERT INTO tester_run_reports (
    id,
    tester_run_id,
    report_kind,
    summary,
    details,
    created_at
) VALUES (?, ?, ?, ?, ?, ?)
            "#,
        )
        .bind(&report_id)
        .bind(tester_run_id)
        .bind(report_kind.as_str())
        .bind(summary)
        .bind(details)
        .bind(Utc::now().timestamp())
        .execute(self.pool.as_ref())
        .await?;
        Ok(report_id)
    }

    pub async fn list_tester_run_reports(
        &self,
        tester_run_id: Option<&str>,
    ) -> anyhow::Result<Vec<TesterRunReport>> {
        let rows = if let Some(tester_run_id) = tester_run_id {
            sqlx::query_as::<_, TesterRunReportRow>(
                r#"
SELECT id, tester_run_id, report_kind, summary, details, created_at
FROM tester_run_reports
WHERE tester_run_id = ?
ORDER BY created_at DESC, id DESC
                "#,
            )
            .bind(tester_run_id)
            .fetch_all(self.pool.as_ref())
            .await?
        } else {
            sqlx::query_as::<_, TesterRunReportRow>(
                r#"
SELECT id, tester_run_id, report_kind, summary, details, created_at
FROM tester_run_reports
ORDER BY created_at DESC, id DESC
                "#,
            )
            .fetch_all(self.pool.as_ref())
            .await?
        };
        rows.into_iter().map(TryInto::try_into).collect()
    }

    pub async fn append_tester_run_artifact(
        &self,
        tester_run_id: &str,
        artifact_kind: TesterRunArtifactKind,
        label: &str,
        path: &Path,
    ) -> anyhow::Result<String> {
        let artifact_id = uuid::Uuid::new_v4().to_string();
        sqlx::query(
            r#"
INSERT INTO tester_run_artifacts (
    id,
    tester_run_id,
    artifact_kind,
    label,
    path,
    created_at
) VALUES (?, ?, ?, ?, ?, ?)
            "#,
        )
        .bind(&artifact_id)
        .bind(tester_run_id)
        .bind(artifact_kind.as_str())
        .bind(label)
        .bind(path.to_string_lossy().into_owned())
        .bind(Utc::now().timestamp())
        .execute(self.pool.as_ref())
        .await?;
        Ok(artifact_id)
    }

    pub async fn list_tester_run_artifacts(
        &self,
        tester_run_id: &str,
    ) -> anyhow::Result<Vec<TesterRunArtifact>> {
        let rows = sqlx::query_as::<_, TesterRunArtifactRow>(
            r#"
SELECT id, tester_run_id, artifact_kind, label, path, created_at
FROM tester_run_artifacts
WHERE tester_run_id = ?
ORDER BY created_at DESC, id DESC
            "#,
        )
        .bind(tester_run_id)
        .fetch_all(self.pool.as_ref())
        .await?;
        rows.into_iter().map(TryInto::try_into).collect()
    }
}

#[cfg(test)]
mod tests {
    use super::StateRuntime;
    use crate::TesterExecutionClass;
    use crate::TesterRunCreateParams;
    use crate::TesterRunReportKind;
    use crate::TesterRunStatus;
    use crate::runtime::test_support::test_thread_metadata;
    use chrono::Utc;
    use codex_protocol::ThreadId;
    use pretty_assertions::assert_eq;
    use std::time::Duration;

    #[tokio::test]
    async fn tester_run_create_and_claim_round_trip() {
        let tempdir = tempfile::tempdir().expect("tempdir");
        let runtime = StateRuntime::init(tempdir.path().to_path_buf(), "test-provider".to_string())
            .await
            .expect("state runtime");
        let controller_thread_id = ThreadId::new();
        let metadata = test_thread_metadata(
            tempdir.path(),
            controller_thread_id,
            tempdir.path().to_path_buf(),
        );
        runtime
            .upsert_thread(&metadata)
            .await
            .expect("upsert controller thread");

        runtime
            .create_tester_run(TesterRunCreateParams {
                id: "tester-run-1".to_string(),
                name: "intent-check".to_string(),
                objective: "Evaluate the product from the outside".to_string(),
                background: Some("New to the repo".to_string()),
                skill_level: Some("intermediate".to_string()),
                temperament: Some("persistent".to_string()),
                starting_knowledge: vec!["README only".to_string()],
                constraints: vec!["Do not read source code".to_string()],
                allowed_interfaces: vec!["terminal_harness".to_string()],
                execution_class: TesterExecutionClass::TerminalFullAccess,
                controller_thread_id: Some(controller_thread_id.to_string()),
                cwd: Some(tempdir.path().to_path_buf()),
            })
            .await
            .expect("create tester run");

        let tester_runs = runtime.list_tester_runs().await.expect("list tester runs");
        assert_eq!(tester_runs.len(), 1);
        assert_eq!(tester_runs[0].status, TesterRunStatus::Queued);
        assert_eq!(
            tester_runs[0].starting_knowledge,
            vec!["README only".to_string()]
        );

        let claimed = runtime
            .claim_queued_tester_runs(Utc::now(), "worker-1", 10, Duration::from_secs(30))
            .await
            .expect("claim tester runs");
        assert_eq!(claimed.len(), 1);
        assert_eq!(
            claimed[0].objective,
            "Evaluate the product from the outside"
        );
        assert_eq!(
            claimed[0].execution_class,
            TesterExecutionClass::TerminalFullAccess
        );

        let reports = runtime
            .list_tester_run_reports(Some("tester-run-1"))
            .await
            .expect("list reports");
        assert_eq!(reports.len(), 1);
        assert_eq!(reports[0].report_kind, TesterRunReportKind::Created);
    }
}
