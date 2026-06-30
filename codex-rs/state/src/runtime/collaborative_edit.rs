use super::*;
use crate::model::CollaborativeEditPlan;
use crate::model::CollaborativeEditPlanCreateParams;
use crate::model::CollaborativeEditPlanRow;
use std::collections::BTreeSet;
use std::path::PathBuf;

impl StateRuntime {
    pub async fn record_collaborative_edit_plan(
        &self,
        params: CollaborativeEditPlanCreateParams,
    ) -> anyhow::Result<CollaborativeEditPlan> {
        self.ensure_state_schema_current().await?;
        validate_collaborative_edit_plan(&params)?;

        let now = Utc::now().timestamp();
        let lease_seconds = params.lease_seconds.max(1);
        let lease_expires_at = now.saturating_add(lease_seconds);
        let peers_json = serde_json::to_string(&params.peers)?;

        sqlx::query(
            r#"
INSERT INTO collaborative_edit_plans (
    id,
    actor_thread_id,
    room,
    file_path,
    edit_slice,
    intent,
    peers_json,
    handoff,
    integrator,
    report_back,
    created_at,
    updated_at,
    lease_expires_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            "#,
        )
        .bind(params.id.as_str())
        .bind(params.actor_thread_id.to_string())
        .bind(params.room.as_deref())
        .bind(params.file_path.to_string_lossy().as_ref())
        .bind(params.edit_slice.as_str())
        .bind(params.intent.as_str())
        .bind(peers_json.as_str())
        .bind(params.handoff.as_deref())
        .bind(params.integrator.as_deref())
        .bind(params.report_back.as_deref())
        .bind(now)
        .bind(now)
        .bind(lease_expires_at)
        .execute(self.pool.as_ref())
        .await?;

        let row = load_collaborative_edit_plan(self, params.id.as_str())
            .await?
            .ok_or_else(|| anyhow::anyhow!("collaborative edit plan {} disappeared", params.id))?;
        Ok(row)
    }

    pub async fn list_collaborative_edit_plans_for_files(
        &self,
        file_paths: &[PathBuf],
    ) -> anyhow::Result<Vec<CollaborativeEditPlan>> {
        self.ensure_state_schema_current().await?;
        let now = Utc::now().timestamp();
        let mut seen = BTreeSet::new();
        let mut plans = Vec::new();

        for file_path in file_paths {
            if !seen.insert(file_path.clone()) {
                continue;
            }
            let rows = sqlx::query_as::<_, CollaborativeEditPlanRow>(
                r#"
SELECT
    id,
    actor_thread_id,
    room,
    file_path,
    edit_slice,
    intent,
    peers_json,
    handoff,
    integrator,
    report_back,
    created_at,
    updated_at,
    lease_expires_at
FROM collaborative_edit_plans
WHERE file_path = ?
  AND lease_expires_at > ?
ORDER BY updated_at DESC, created_at DESC, id DESC
LIMIT 20
                "#,
            )
            .bind(file_path.to_string_lossy().as_ref())
            .bind(now)
            .fetch_all(self.pool.as_ref())
            .await?;
            for row in rows {
                plans.push(row.try_into()?);
            }
        }

        Ok(plans)
    }
}

async fn load_collaborative_edit_plan(
    runtime: &StateRuntime,
    id: &str,
) -> anyhow::Result<Option<CollaborativeEditPlan>> {
    sqlx::query_as::<_, CollaborativeEditPlanRow>(
        r#"
SELECT
    id,
    actor_thread_id,
    room,
    file_path,
    edit_slice,
    intent,
    peers_json,
    handoff,
    integrator,
    report_back,
    created_at,
    updated_at,
    lease_expires_at
FROM collaborative_edit_plans
WHERE id = ?
        "#,
    )
    .bind(id)
    .fetch_optional(runtime.pool.as_ref())
    .await?
    .map(TryInto::try_into)
    .transpose()
}

fn validate_collaborative_edit_plan(
    params: &CollaborativeEditPlanCreateParams,
) -> anyhow::Result<()> {
    if !params.file_path.is_absolute() {
        anyhow::bail!(
            "collaborative edit plans must use an absolute file path: {}",
            params.file_path.display()
        );
    }
    if params.edit_slice.trim().is_empty() {
        anyhow::bail!("collaborative edit plans require a non-empty slice");
    }
    if params.intent.trim().is_empty() {
        anyhow::bail!("collaborative edit plans require a non-empty intent");
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::StateRuntime;
    use codex_protocol::ThreadId;
    use pretty_assertions::assert_eq;
    use std::sync::Arc;
    use tempfile::TempDir;

    async fn new_runtime() -> (TempDir, Arc<StateRuntime>) {
        let codex_home = TempDir::new().expect("temp dir");
        let runtime = StateRuntime::init(codex_home.path().to_path_buf(), "test".to_string())
            .await
            .expect("state runtime");
        (codex_home, runtime)
    }

    #[tokio::test]
    async fn lists_active_plans_for_exact_files() {
        let (_codex_home, runtime) = new_runtime().await;
        let file_path = std::env::temp_dir().join("collaborative-edit-plan.rs");
        let actor_thread_id = ThreadId::new();
        let plan = runtime
            .record_collaborative_edit_plan(CollaborativeEditPlanCreateParams {
                id: "plan-1".to_string(),
                actor_thread_id,
                room: Some("room".to_string()),
                file_path: file_path.clone(),
                edit_slice: "parse helper".to_string(),
                intent: "narrow helper edit".to_string(),
                peers: vec!["peer-1".to_string()],
                handoff: Some("I patch first".to_string()),
                integrator: Some("peer-1".to_string()),
                report_back: Some("after patch".to_string()),
                lease_seconds: 60,
            })
            .await
            .expect("record plan");

        let plans = runtime
            .list_collaborative_edit_plans_for_files(std::slice::from_ref(&file_path))
            .await
            .expect("list plans");

        assert_eq!(plans, vec![plan]);
    }
}
