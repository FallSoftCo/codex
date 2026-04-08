use super::*;
use crate::model::ClaimedTester;
use crate::model::TesterCreateParams;
use crate::model::TesterReport;
use crate::model::TesterReportKind;
use crate::model::TesterReportRow;
use crate::model::TesterRow;
use crate::model::TesterStatus;

fn serialize_string_vec(values: &[String]) -> anyhow::Result<String> {
    serde_json::to_string(values).map_err(Into::into)
}

impl StateRuntime {
    pub async fn create_tester(&self, params: TesterCreateParams) -> anyhow::Result<()> {
        let now = Utc::now().timestamp();
        let starting_knowledge_json = serialize_string_vec(&params.starting_knowledge)?;
        let constraints_json = serialize_string_vec(&params.constraints)?;
        let allowed_interfaces_json = serialize_string_vec(&params.allowed_interfaces)?;

        sqlx::query(
            r#"
INSERT INTO testers (
    id,
    name,
    objective,
    background,
    skill_level,
    temperament,
    starting_knowledge_json,
    constraints_json,
    allowed_interfaces_json,
    controller_thread_id,
    tester_thread_id,
    cwd,
    status,
    created_at,
    updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
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
        .bind(&params.controller_thread_id)
        .bind(
            params
                .cwd
                .as_ref()
                .map(|cwd| cwd.to_string_lossy().into_owned()),
        )
        .bind(TesterStatus::Pending.as_str())
        .bind(now)
        .bind(now)
        .execute(self.pool.as_ref())
        .await?;

        self.append_tester_report(
            &params.id,
            TesterReportKind::Created,
            format!("tester {} created", params.name),
            Some("tester is pending startup"),
        )
        .await?;
        Ok(())
    }

    pub async fn list_testers(&self) -> anyhow::Result<Vec<crate::Tester>> {
        let rows = sqlx::query_as::<_, TesterRow>(
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
    controller_thread_id,
    tester_thread_id,
    cwd,
    status,
    last_observed_thread_status,
    last_error,
    created_at,
    updated_at
FROM testers
ORDER BY created_at DESC, id DESC
            "#,
        )
        .fetch_all(self.pool.as_ref())
        .await?;
        rows.into_iter().map(TryInto::try_into).collect()
    }

    pub async fn get_tester(&self, id: &str) -> anyhow::Result<Option<crate::Tester>> {
        let row = sqlx::query_as::<_, TesterRow>(
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
    controller_thread_id,
    tester_thread_id,
    cwd,
    status,
    last_observed_thread_status,
    last_error,
    created_at,
    updated_at
FROM testers
WHERE id = ?
            "#,
        )
        .bind(id)
        .fetch_optional(self.pool.as_ref())
        .await?;
        row.map(TryInto::try_into).transpose()
    }

    pub async fn claim_pending_testers(
        &self,
        now: DateTime<Utc>,
        worker_id: &str,
        limit: usize,
        lease_duration: Duration,
    ) -> anyhow::Result<Vec<ClaimedTester>> {
        let rows = sqlx::query_as::<_, TesterRow>(
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
    controller_thread_id,
    tester_thread_id,
    cwd,
    status,
    last_observed_thread_status,
    last_error,
    created_at,
    updated_at
FROM testers
WHERE status = ?
  AND tester_thread_id IS NULL
  AND (lease_until IS NULL OR lease_until < ?)
ORDER BY created_at ASC, id ASC
LIMIT ?
            "#,
        )
        .bind(TesterStatus::Pending.as_str())
        .bind(now.timestamp())
        .bind(i64::try_from(limit).unwrap_or(i64::MAX))
        .fetch_all(self.pool.as_ref())
        .await?;

        let lease_until = now + chrono::Duration::from_std(lease_duration)?;
        let mut claimed = Vec::new();
        for row in rows {
            let result = sqlx::query(
                r#"
UPDATE testers
SET status = ?,
    lease_owner = ?,
    lease_until = ?,
    updated_at = ?
WHERE id = ?
  AND status = ?
  AND tester_thread_id IS NULL
  AND (lease_until IS NULL OR lease_until < ?)
                "#,
            )
            .bind(TesterStatus::Starting.as_str())
            .bind(worker_id)
            .bind(lease_until.timestamp())
            .bind(now.timestamp())
            .bind(&row.id)
            .bind(TesterStatus::Pending.as_str())
            .bind(now.timestamp())
            .execute(self.pool.as_ref())
            .await?;
            if result.rows_affected() == 0 {
                continue;
            }

            let tester: crate::Tester = row.try_into()?;
            claimed.push(ClaimedTester {
                id: tester.id,
                name: tester.name,
                objective: tester.objective,
                background: tester.background,
                skill_level: tester.skill_level,
                temperament: tester.temperament,
                starting_knowledge: tester.starting_knowledge,
                constraints: tester.constraints,
                allowed_interfaces: tester.allowed_interfaces,
                controller_thread_id: tester.controller_thread_id,
                cwd: tester.cwd,
            });
        }
        Ok(claimed)
    }

    pub async fn mark_tester_started(
        &self,
        tester_id: &str,
        tester_thread_id: &str,
        now: DateTime<Utc>,
    ) -> anyhow::Result<()> {
        sqlx::query(
            r#"
UPDATE testers
SET tester_thread_id = ?,
    status = ?,
    last_observed_thread_status = ?,
    last_error = NULL,
    lease_owner = NULL,
    lease_until = NULL,
    updated_at = ?
WHERE id = ?
            "#,
        )
        .bind(tester_thread_id)
        .bind(TesterStatus::Running.as_str())
        .bind("active")
        .bind(now.timestamp())
        .bind(tester_id)
        .execute(self.pool.as_ref())
        .await?;
        Ok(())
    }

    pub async fn mark_tester_start_failed(
        &self,
        tester_id: &str,
        error: &str,
        now: DateTime<Utc>,
    ) -> anyhow::Result<()> {
        sqlx::query(
            r#"
UPDATE testers
SET status = ?,
    last_error = ?,
    lease_owner = NULL,
    lease_until = NULL,
    updated_at = ?
WHERE id = ?
            "#,
        )
        .bind(TesterStatus::Failed.as_str())
        .bind(error)
        .bind(now.timestamp())
        .bind(tester_id)
        .execute(self.pool.as_ref())
        .await?;
        self.append_tester_report(
            tester_id,
            TesterReportKind::Failed,
            "tester failed to start".to_string(),
            Some(error),
        )
        .await?;
        Ok(())
    }

    pub async fn list_monitorable_testers(&self) -> anyhow::Result<Vec<crate::Tester>> {
        let rows = sqlx::query_as::<_, TesterRow>(
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
    controller_thread_id,
    tester_thread_id,
    cwd,
    status,
    last_observed_thread_status,
    last_error,
    created_at,
    updated_at
FROM testers
WHERE tester_thread_id IS NOT NULL
  AND status IN (?, ?, ?)
ORDER BY updated_at ASC, id ASC
            "#,
        )
        .bind(TesterStatus::Running.as_str())
        .bind(TesterStatus::Waiting.as_str())
        .bind(TesterStatus::Paused.as_str())
        .fetch_all(self.pool.as_ref())
        .await?;
        rows.into_iter().map(TryInto::try_into).collect()
    }

    pub async fn update_tester_runtime_status(
        &self,
        tester_id: &str,
        status: TesterStatus,
        observed_thread_status: Option<&str>,
        last_error: Option<&str>,
    ) -> anyhow::Result<()> {
        sqlx::query(
            r#"
UPDATE testers
SET status = ?,
    last_observed_thread_status = ?,
    last_error = ?,
    updated_at = ?
WHERE id = ?
            "#,
        )
        .bind(status.as_str())
        .bind(observed_thread_status)
        .bind(last_error)
        .bind(Utc::now().timestamp())
        .bind(tester_id)
        .execute(self.pool.as_ref())
        .await?;
        Ok(())
    }

    pub async fn stop_tester(&self, tester_id: &str) -> anyhow::Result<bool> {
        let result = sqlx::query(
            r#"
UPDATE testers
SET status = ?,
    lease_owner = NULL,
    lease_until = NULL,
    updated_at = ?
WHERE id = ?
  AND status != ?
            "#,
        )
        .bind(TesterStatus::Stopped.as_str())
        .bind(Utc::now().timestamp())
        .bind(tester_id)
        .bind(TesterStatus::Stopped.as_str())
        .execute(self.pool.as_ref())
        .await?;
        if result.rows_affected() > 0 {
            self.append_tester_report(
                tester_id,
                TesterReportKind::Stopped,
                "tester stopped".to_string(),
                None,
            )
            .await?;
            Ok(true)
        } else {
            Ok(false)
        }
    }

    pub async fn append_tester_report(
        &self,
        tester_id: &str,
        report_kind: TesterReportKind,
        summary: String,
        details: Option<&str>,
    ) -> anyhow::Result<String> {
        let report_id = uuid::Uuid::new_v4().to_string();
        sqlx::query(
            r#"
INSERT INTO tester_reports (
    id,
    tester_id,
    report_kind,
    summary,
    details,
    created_at
) VALUES (?, ?, ?, ?, ?, ?)
            "#,
        )
        .bind(&report_id)
        .bind(tester_id)
        .bind(report_kind.as_str())
        .bind(summary)
        .bind(details)
        .bind(Utc::now().timestamp())
        .execute(self.pool.as_ref())
        .await?;
        Ok(report_id)
    }

    pub async fn list_tester_reports(
        &self,
        tester_id: Option<&str>,
    ) -> anyhow::Result<Vec<TesterReport>> {
        let rows = if let Some(tester_id) = tester_id {
            sqlx::query_as::<_, TesterReportRow>(
                r#"
SELECT id, tester_id, report_kind, summary, details, created_at
FROM tester_reports
WHERE tester_id = ?
ORDER BY created_at DESC, id DESC
                "#,
            )
            .bind(tester_id)
            .fetch_all(self.pool.as_ref())
            .await?
        } else {
            sqlx::query_as::<_, TesterReportRow>(
                r#"
SELECT id, tester_id, report_kind, summary, details, created_at
FROM tester_reports
ORDER BY created_at DESC, id DESC
                "#,
            )
            .fetch_all(self.pool.as_ref())
            .await?
        };
        rows.into_iter().map(TryInto::try_into).collect()
    }
}

#[cfg(test)]
mod tests {
    use super::StateRuntime;
    use crate::TesterCreateParams;
    use crate::TesterReportKind;
    use crate::TesterStatus;
    use crate::runtime::test_support::test_thread_metadata;
    use chrono::Utc;
    use codex_protocol::ThreadId;
    use pretty_assertions::assert_eq;
    use std::time::Duration;

    #[tokio::test]
    async fn tester_create_and_claim_round_trip() {
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
            .create_tester(TesterCreateParams {
                id: "tester-1".to_string(),
                name: "beta".to_string(),
                objective: "Deploy the app and report friction".to_string(),
                background: Some("New to the repo".to_string()),
                skill_level: Some("intermediate".to_string()),
                temperament: Some("persistent".to_string()),
                starting_knowledge: vec!["README only".to_string()],
                constraints: vec!["Do not read source code".to_string()],
                allowed_interfaces: vec!["terminal_harness".to_string()],
                controller_thread_id: Some(controller_thread_id.to_string()),
                cwd: Some(tempdir.path().to_path_buf()),
            })
            .await
            .expect("create tester");

        let testers = runtime.list_testers().await.expect("list testers");
        assert_eq!(testers.len(), 1);
        assert_eq!(testers[0].status, TesterStatus::Pending);
        assert_eq!(
            testers[0].starting_knowledge,
            vec!["README only".to_string()]
        );

        let claimed = runtime
            .claim_pending_testers(Utc::now(), "worker-1", 10, Duration::from_secs(30))
            .await
            .expect("claim testers");
        assert_eq!(claimed.len(), 1);
        assert_eq!(claimed[0].objective, "Deploy the app and report friction");

        let reports = runtime
            .list_tester_reports(Some("tester-1"))
            .await
            .expect("list reports");
        assert_eq!(reports.len(), 1);
        assert_eq!(reports[0].report_kind, TesterReportKind::Created);
    }
}
