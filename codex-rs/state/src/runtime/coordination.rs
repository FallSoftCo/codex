use super::*;
use crate::model::CoordinationAct;
use crate::model::CoordinationActKind;
use crate::model::CoordinationActRow;
use crate::model::CoordinationTask;
use crate::model::CoordinationTaskAcceptParams;
use crate::model::CoordinationTaskCreateParams;
use crate::model::CoordinationTaskDoneParams;
use crate::model::CoordinationTaskHandoffParams;
use crate::model::CoordinationTaskListFilter;
use crate::model::CoordinationTaskRow;
use crate::model::CoordinationTaskStatus;
use crate::model::CoordinationTaskTransitionOutcome;
use crate::model::CoordinationTaskYieldParams;
use crate::model::coordination_epoch_seconds_to_datetime;
impl StateRuntime {
    pub async fn create_coordination_task(
        &self,
        params: CoordinationTaskCreateParams,
    ) -> anyhow::Result<CoordinationTaskTransitionOutcome> {
        self.ensure_state_schema_current().await?;
        let now = Utc::now().timestamp();
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        reconcile_coordination_task_leases(&mut tx, now).await?;
        validate_dependency_ids(&mut tx, &params.dependency_task_ids).await?;
        let blocked_dependency_task_ids =
            load_blocked_dependency_ids(&mut tx, &params.dependency_task_ids).await?;
        if matches!(params.kind, crate::CoordinationTaskKind::Implementation)
            && params.owner_thread_id.is_some()
            && params.reserved_path_claims.is_empty()
        {
            anyhow::bail!(
                "coordination task {} requires exact ownership claims before it can be awarded",
                params.id
            );
        }
        if let Some(owner_thread_id) = params.owner_thread_id {
            let lease_seconds = params.claim_lease_seconds.max(1);
            let lease_expires_at = now.saturating_add(lease_seconds);
            let owner_thread_id = owner_thread_id.to_string();
            let claim_result = super::path_claims::try_claim_path_ownership_in_tx(
                &mut tx,
                owner_thread_id.as_str(),
                &params.reserved_path_claims,
                now,
                lease_expires_at,
            )
            .await?;
            if !claim_result.acquired {
                anyhow::bail!(
                    "{}",
                    format_award_path_claim_conflicts(params.id.as_str(), &claim_result.conflicts)
                );
            }
        }
        let status = initial_task_status(&blocked_dependency_task_ids, params.owner_thread_id);
        sqlx::query(
            r#"
INSERT INTO coordination_tasks (
    id,
    creator_thread_id,
    owner_thread_id,
    team_id,
    room,
    task_kind,
    status,
    summary,
    details,
    requested_capability,
    blocked_reason,
    lease_expires_at,
    created_at,
    updated_at,
    completed_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, NULL)
            "#,
        )
        .bind(&params.id)
        .bind(params.creator_thread_id.to_string())
        .bind(
            params
                .owner_thread_id
                .map(|thread_id| thread_id.to_string()),
        )
        .bind(&params.team_id)
        .bind(&params.room)
        .bind(params.kind.as_str())
        .bind(status.as_str())
        .bind(&params.summary)
        .bind(&params.details)
        .bind(&params.requested_capability)
        .bind(now)
        .bind(now)
        .execute(&mut *tx)
        .await?;

        for dependency_task_id in &params.dependency_task_ids {
            sqlx::query(
                r#"
INSERT INTO coordination_task_dependencies (
    task_id,
    depends_on_task_id,
    created_at
) VALUES (?, ?, ?)
                "#,
            )
            .bind(&params.id)
            .bind(dependency_task_id)
            .bind(now)
            .execute(&mut *tx)
            .await?;
        }

        insert_coordination_act(
            &mut tx,
            &params.act_id,
            Some(params.id.as_str()),
            params.creator_thread_id,
            CoordinationActKind::OpenTask,
            params.act_summary.as_deref(),
            params.act_payload_json.as_str(),
            now,
        )
        .await?;

        let task = load_coordination_task(&mut tx, params.id.as_str())
            .await?
            .ok_or_else(|| anyhow::anyhow!("created coordination task disappeared"))?;
        let act = load_coordination_act(&mut tx, params.act_id.as_str())
            .await?
            .ok_or_else(|| anyhow::anyhow!("created coordination act disappeared"))?;
        tx.commit().await?;
        Ok(CoordinationTaskTransitionOutcome {
            task,
            act,
            unblocked_tasks: Vec::new(),
        })
    }

    pub async fn get_coordination_task(
        &self,
        id: &str,
    ) -> anyhow::Result<Option<CoordinationTask>> {
        self.ensure_state_schema_current().await?;
        let now = Utc::now().timestamp();
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        reconcile_coordination_task_leases(&mut tx, now).await?;
        let task = load_coordination_task(&mut tx, id).await?;
        tx.commit().await?;
        Ok(task)
    }

    pub async fn list_coordination_tasks(
        &self,
        filter: CoordinationTaskListFilter,
    ) -> anyhow::Result<Vec<CoordinationTask>> {
        self.ensure_state_schema_current().await?;
        let now = Utc::now().timestamp();
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        reconcile_coordination_task_leases(&mut tx, now).await?;

        let mut query = QueryBuilder::<Sqlite>::new(
            r#"
SELECT
    id,
    creator_thread_id,
    owner_thread_id,
    team_id,
    room,
    task_kind,
    status,
    summary,
    details,
    requested_capability,
    blocked_reason,
    created_at,
    updated_at,
    completed_at,
    lease_expires_at
FROM coordination_tasks
            "#,
        );
        let mut first_clause = true;
        if filter.owner_thread_id.is_some()
            || filter.creator_thread_id.is_some()
            || filter.room.is_some()
            || !filter.statuses.is_empty()
        {
            query.push(" WHERE ");
        }
        if let Some(owner_thread_id) = filter.owner_thread_id {
            if !first_clause {
                query.push(" AND ");
            }
            first_clause = false;
            query.push("owner_thread_id = ");
            query.push_bind(owner_thread_id.to_string());
        }
        if let Some(creator_thread_id) = filter.creator_thread_id {
            if !first_clause {
                query.push(" AND ");
            }
            first_clause = false;
            query.push("creator_thread_id = ");
            query.push_bind(creator_thread_id.to_string());
        }
        if let Some(room) = filter.room {
            if !first_clause {
                query.push(" AND ");
            }
            first_clause = false;
            query.push("room = ");
            query.push_bind(room);
        }
        if !filter.statuses.is_empty() {
            if !first_clause {
                query.push(" AND ");
            }
            query.push("status IN (");
            let mut separated = query.separated(", ");
            for status in &filter.statuses {
                separated.push_bind(status.as_str());
            }
            separated.push_unseparated(")");
        }
        query.push(" ORDER BY updated_at DESC, created_at DESC, id DESC");

        let rows = query
            .build_query_as::<CoordinationTaskRow>()
            .fetch_all(&mut *tx)
            .await?;
        let mut tasks = Vec::with_capacity(rows.len());
        for row in rows {
            tasks.push(coordination_task_from_row(&mut tx, row).await?);
        }
        tx.commit().await?;
        Ok(tasks)
    }

    pub async fn list_coordination_acts(
        &self,
        task_id: Option<&str>,
    ) -> anyhow::Result<Vec<CoordinationAct>> {
        self.ensure_state_schema_current().await?;
        let rows = if let Some(task_id) = task_id {
            sqlx::query_as::<_, CoordinationActRow>(
                r#"
SELECT
    id,
    task_id,
    actor_thread_id,
    act_kind,
    summary,
    payload_json,
    created_at
FROM coordination_acts
WHERE task_id = ?
ORDER BY created_at DESC, id DESC
                "#,
            )
            .bind(task_id)
            .fetch_all(self.pool.as_ref())
            .await?
        } else {
            sqlx::query_as::<_, CoordinationActRow>(
                r#"
SELECT
    id,
    task_id,
    actor_thread_id,
    act_kind,
    summary,
    payload_json,
    created_at
FROM coordination_acts
ORDER BY created_at DESC, id DESC
                "#,
            )
            .fetch_all(self.pool.as_ref())
            .await?
        };
        rows.into_iter().map(TryInto::try_into).collect()
    }

    pub async fn accept_coordination_task(
        &self,
        params: CoordinationTaskAcceptParams,
    ) -> anyhow::Result<CoordinationTaskTransitionOutcome> {
        self.ensure_state_schema_current().await?;
        let now = Utc::now().timestamp();
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        reconcile_coordination_task_leases(&mut tx, now).await?;
        let task = load_coordination_task(&mut tx, params.task_id.as_str())
            .await?
            .ok_or_else(|| anyhow::anyhow!("coordination task {} not found", params.task_id))?;
        let actor_thread_id = params.actor_thread_id.to_string();
        let same_owner_active = matches!(task.status, CoordinationTaskStatus::Active)
            && task.owner_thread_id.as_deref() == Some(actor_thread_id.as_str());
        if !matches!(
            task.status,
            CoordinationTaskStatus::Open | CoordinationTaskStatus::Awarded
        ) && !same_owner_active
        {
            anyhow::bail!(
                "coordination task {} is not claimable from status `{}`",
                task.id,
                task.status.as_str()
            );
        }
        if !task.blocked_dependency_task_ids.is_empty() {
            anyhow::bail!(
                "coordination task {} is still blocked on dependencies: {}",
                task.id,
                task.blocked_dependency_task_ids.join(", ")
            );
        }
        if matches!(task.kind, crate::CoordinationTaskKind::Implementation)
            && params.path_claims.is_empty()
            && !same_owner_active
        {
            anyhow::bail!(
                "coordination task {} requires exact ownership claims before it can become active",
                task.id
            );
        }

        let lease_seconds = params.lease_seconds.max(1);
        let lease_expires_at = now.saturating_add(lease_seconds);
        if !params.path_claims.is_empty() {
            let claim_result = super::path_claims::try_claim_path_ownership_in_tx(
                &mut tx,
                actor_thread_id.as_str(),
                &params.path_claims,
                now,
                lease_expires_at,
            )
            .await?;
            if !claim_result.acquired {
                anyhow::bail!(
                    "{}",
                    format_accept_path_claim_conflicts(task.id.as_str(), &claim_result.conflicts)
                );
            }
        }
        sqlx::query(
            r#"
UPDATE coordination_tasks
SET owner_thread_id = ?,
    status = ?,
    blocked_reason = NULL,
    lease_expires_at = ?,
    updated_at = ?
WHERE id = ?
            "#,
        )
        .bind(actor_thread_id.as_str())
        .bind(CoordinationTaskStatus::Active.as_str())
        .bind(lease_expires_at)
        .bind(now)
        .bind(&params.task_id)
        .execute(&mut *tx)
        .await?;

        insert_coordination_act(
            &mut tx,
            &params.act_id,
            Some(params.task_id.as_str()),
            params.actor_thread_id,
            CoordinationActKind::Accept,
            params.act_summary.as_deref(),
            params.act_payload_json.as_str(),
            now,
        )
        .await?;

        let task = load_coordination_task(&mut tx, params.task_id.as_str())
            .await?
            .ok_or_else(|| anyhow::anyhow!("accepted coordination task disappeared"))?;
        let act = load_coordination_act(&mut tx, params.act_id.as_str())
            .await?
            .ok_or_else(|| anyhow::anyhow!("accept coordination act disappeared"))?;
        tx.commit().await?;
        Ok(CoordinationTaskTransitionOutcome {
            task,
            act,
            unblocked_tasks: Vec::new(),
        })
    }

    pub async fn complete_coordination_task(
        &self,
        params: CoordinationTaskDoneParams,
    ) -> anyhow::Result<CoordinationTaskTransitionOutcome> {
        self.ensure_state_schema_current().await?;
        let now = Utc::now().timestamp();
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        reconcile_coordination_task_leases(&mut tx, now).await?;
        let task = load_coordination_task(&mut tx, params.task_id.as_str())
            .await?
            .ok_or_else(|| anyhow::anyhow!("coordination task {} not found", params.task_id))?;
        ensure_task_allows_done(&task)?;

        sqlx::query(
            r#"
UPDATE coordination_tasks
SET status = ?,
    blocked_reason = NULL,
    lease_expires_at = NULL,
    completed_at = ?,
    updated_at = ?
WHERE id = ?
            "#,
        )
        .bind(CoordinationTaskStatus::Done.as_str())
        .bind(now)
        .bind(now)
        .bind(&params.task_id)
        .execute(&mut *tx)
        .await?;

        insert_coordination_act(
            &mut tx,
            &params.act_id,
            Some(params.task_id.as_str()),
            params.actor_thread_id,
            CoordinationActKind::Done,
            params.act_summary.as_deref(),
            params.act_payload_json.as_str(),
            now,
        )
        .await?;

        let unblocked_tasks =
            unblock_coordination_dependents(&mut tx, params.task_id.as_str(), now).await?;
        let task = load_coordination_task(&mut tx, params.task_id.as_str())
            .await?
            .ok_or_else(|| anyhow::anyhow!("completed coordination task disappeared"))?;
        let act = load_coordination_act(&mut tx, params.act_id.as_str())
            .await?
            .ok_or_else(|| anyhow::anyhow!("done coordination act disappeared"))?;
        tx.commit().await?;
        Ok(CoordinationTaskTransitionOutcome {
            task,
            act,
            unblocked_tasks,
        })
    }

    pub async fn handoff_coordination_task(
        &self,
        params: CoordinationTaskHandoffParams,
    ) -> anyhow::Result<CoordinationTaskTransitionOutcome> {
        self.ensure_state_schema_current().await?;
        let now = Utc::now().timestamp();
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        reconcile_coordination_task_leases(&mut tx, now).await?;
        let task = load_coordination_task(&mut tx, params.task_id.as_str())
            .await?
            .ok_or_else(|| anyhow::anyhow!("coordination task {} not found", params.task_id))?;
        ensure_task_allows_handoff(&task)?;
        let blocked_dependency_task_ids =
            load_blocked_dependency_ids(&mut tx, &task.dependency_task_ids).await?;
        let status = if blocked_dependency_task_ids.is_empty() {
            CoordinationTaskStatus::Awarded
        } else {
            CoordinationTaskStatus::Blocked
        };
        sqlx::query(
            r#"
UPDATE coordination_tasks
SET owner_thread_id = ?,
    status = ?,
    blocked_reason = NULL,
    lease_expires_at = NULL,
    completed_at = NULL,
    updated_at = ?
WHERE id = ?
            "#,
        )
        .bind(params.new_owner_thread_id.to_string())
        .bind(status.as_str())
        .bind(now)
        .bind(&params.task_id)
        .execute(&mut *tx)
        .await?;

        insert_coordination_act(
            &mut tx,
            &params.act_id,
            Some(params.task_id.as_str()),
            params.actor_thread_id,
            CoordinationActKind::Handoff,
            params.act_summary.as_deref(),
            params.act_payload_json.as_str(),
            now,
        )
        .await?;

        let task = load_coordination_task(&mut tx, params.task_id.as_str())
            .await?
            .ok_or_else(|| anyhow::anyhow!("handed-off coordination task disappeared"))?;
        let act = load_coordination_act(&mut tx, params.act_id.as_str())
            .await?
            .ok_or_else(|| anyhow::anyhow!("handoff coordination act disappeared"))?;
        tx.commit().await?;
        Ok(CoordinationTaskTransitionOutcome {
            task,
            act,
            unblocked_tasks: Vec::new(),
        })
    }

    pub async fn yield_coordination_task(
        &self,
        params: CoordinationTaskYieldParams,
    ) -> anyhow::Result<CoordinationTaskTransitionOutcome> {
        self.ensure_state_schema_current().await?;
        let now = Utc::now().timestamp();
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        reconcile_coordination_task_leases(&mut tx, now).await?;
        let task = load_coordination_task(&mut tx, params.task_id.as_str())
            .await?
            .ok_or_else(|| anyhow::anyhow!("coordination task {} not found", params.task_id))?;
        ensure_task_allows_yield(&task)?;
        let blocked_dependency_task_ids =
            load_blocked_dependency_ids(&mut tx, &task.dependency_task_ids).await?;
        let status = if blocked_dependency_task_ids.is_empty() {
            CoordinationTaskStatus::Open
        } else {
            CoordinationTaskStatus::Blocked
        };
        sqlx::query(
            r#"
UPDATE coordination_tasks
SET owner_thread_id = NULL,
    status = ?,
    blocked_reason = NULL,
    lease_expires_at = NULL,
    updated_at = ?
WHERE id = ?
            "#,
        )
        .bind(status.as_str())
        .bind(now)
        .bind(&params.task_id)
        .execute(&mut *tx)
        .await?;

        insert_coordination_act(
            &mut tx,
            &params.act_id,
            Some(params.task_id.as_str()),
            params.actor_thread_id,
            CoordinationActKind::Yield,
            params.act_summary.as_deref(),
            params.act_payload_json.as_str(),
            now,
        )
        .await?;

        let task = load_coordination_task(&mut tx, params.task_id.as_str())
            .await?
            .ok_or_else(|| anyhow::anyhow!("yielded coordination task disappeared"))?;
        let act = load_coordination_act(&mut tx, params.act_id.as_str())
            .await?
            .ok_or_else(|| anyhow::anyhow!("yield coordination act disappeared"))?;
        tx.commit().await?;
        Ok(CoordinationTaskTransitionOutcome {
            task,
            act,
            unblocked_tasks: Vec::new(),
        })
    }
}

async fn validate_dependency_ids(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    dependency_task_ids: &[String],
) -> anyhow::Result<()> {
    for dependency_task_id in dependency_task_ids {
        let exists =
            sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM coordination_tasks WHERE id = ?")
                .bind(dependency_task_id)
                .fetch_one(&mut **tx)
                .await?;
        if exists == 0 {
            anyhow::bail!("coordination dependency task {dependency_task_id} does not exist");
        }
    }
    Ok(())
}

fn format_accept_path_claim_conflicts(
    task_id: &str,
    conflicts: &[crate::PathClaimConflict],
) -> String {
    let Some(first) = conflicts.first() else {
        return format!(
            "coordination task {task_id} cannot become active because the requested scope conflicts with an existing ownership claim"
        );
    };

    let blocking_kind = first.blocking_claim.kind.as_str();
    let requested_path = first.requested.path.display();
    let blocking_path = first.blocking_claim.path.display();
    let owner_thread_id = &first.blocking_claim.owner_thread_id;
    let additional = conflicts
        .len()
        .checked_sub(1)
        .filter(|count| *count > 0)
        .map(|count| format!(" and {count} more conflicting claim(s)"))
        .unwrap_or_default();

    format!(
        "coordination task {task_id} cannot become active because thread {owner_thread_id} holds a {blocking_kind} claim at `{blocking_path}` which overlaps `{requested_path}`{additional}"
    )
}

fn format_award_path_claim_conflicts(
    task_id: &str,
    conflicts: &[crate::PathClaimConflict],
) -> String {
    let Some(first) = conflicts.first() else {
        return format!(
            "coordination task {task_id} cannot be awarded because the requested scope conflicts with an existing ownership claim"
        );
    };

    let blocking_kind = first.blocking_claim.kind.as_str();
    let requested_path = first.requested.path.display();
    let blocking_path = first.blocking_claim.path.display();
    let owner_thread_id = &first.blocking_claim.owner_thread_id;
    let additional = conflicts
        .len()
        .checked_sub(1)
        .filter(|count| *count > 0)
        .map(|count| format!(" and {count} more conflicting claim(s)"))
        .unwrap_or_default();

    format!(
        "coordination task {task_id} cannot be awarded because thread {owner_thread_id} holds a {blocking_kind} claim at `{blocking_path}` which overlaps `{requested_path}`{additional}"
    )
}

fn ensure_task_allows_done(task: &CoordinationTask) -> anyhow::Result<()> {
    if matches!(
        task.status,
        CoordinationTaskStatus::Cancelled | CoordinationTaskStatus::Yielded
    ) {
        anyhow::bail!(
            "coordination task {} cannot be completed from status `{}`",
            task.id,
            task.status.as_str()
        );
    }
    Ok(())
}

fn ensure_task_allows_handoff(task: &CoordinationTask) -> anyhow::Result<()> {
    if matches!(
        task.status,
        CoordinationTaskStatus::Done
            | CoordinationTaskStatus::Cancelled
            | CoordinationTaskStatus::Yielded
    ) {
        anyhow::bail!(
            "coordination task {} cannot be handed off from status `{}`",
            task.id,
            task.status.as_str()
        );
    }
    Ok(())
}

fn ensure_task_allows_yield(task: &CoordinationTask) -> anyhow::Result<()> {
    if matches!(
        task.status,
        CoordinationTaskStatus::Done
            | CoordinationTaskStatus::Cancelled
            | CoordinationTaskStatus::Yielded
    ) {
        anyhow::bail!(
            "coordination task {} cannot be yielded from status `{}`",
            task.id,
            task.status.as_str()
        );
    }
    Ok(())
}

fn initial_task_status(
    blocked_dependency_task_ids: &[String],
    owner_thread_id: Option<ThreadId>,
) -> CoordinationTaskStatus {
    if !blocked_dependency_task_ids.is_empty() {
        CoordinationTaskStatus::Blocked
    } else if owner_thread_id.is_some() {
        CoordinationTaskStatus::Awarded
    } else {
        CoordinationTaskStatus::Open
    }
}

async fn reconcile_coordination_task_leases(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    now: i64,
) -> anyhow::Result<()> {
    let expired_task_ids = sqlx::query_scalar::<_, String>(
        r#"
SELECT id
FROM coordination_tasks
WHERE status = ?
  AND lease_expires_at IS NOT NULL
  AND lease_expires_at <= ?
        "#,
    )
    .bind(CoordinationTaskStatus::Active.as_str())
    .bind(now)
    .fetch_all(&mut **tx)
    .await?;
    for task_id in expired_task_ids {
        let dependency_task_ids = load_dependency_ids(tx, task_id.as_str()).await?;
        let blocked_dependency_task_ids =
            load_blocked_dependency_ids(tx, &dependency_task_ids).await?;
        let status =
            initial_task_status(&blocked_dependency_task_ids, /*owner_thread_id*/ None);
        sqlx::query(
            r#"
UPDATE coordination_tasks
SET owner_thread_id = NULL,
    status = ?,
    blocked_reason = NULL,
    lease_expires_at = NULL,
    updated_at = ?
WHERE id = ?
            "#,
        )
        .bind(status.as_str())
        .bind(now)
        .bind(task_id)
        .execute(&mut **tx)
        .await?;
    }
    Ok(())
}

async fn load_coordination_task(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    id: &str,
) -> anyhow::Result<Option<CoordinationTask>> {
    let row = sqlx::query_as::<_, CoordinationTaskRow>(
        r#"
SELECT
    id,
    creator_thread_id,
    owner_thread_id,
    team_id,
    room,
    task_kind,
    status,
    summary,
    details,
    requested_capability,
    blocked_reason,
    created_at,
    updated_at,
    completed_at,
    lease_expires_at
FROM coordination_tasks
WHERE id = ?
        "#,
    )
    .bind(id)
    .fetch_optional(&mut **tx)
    .await?;
    if let Some(row) = row {
        Ok(Some(coordination_task_from_row(tx, row).await?))
    } else {
        Ok(None)
    }
}

async fn coordination_task_from_row(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    row: CoordinationTaskRow,
) -> anyhow::Result<CoordinationTask> {
    let dependency_task_ids = load_dependency_ids(tx, row.id.as_str()).await?;
    let blocked_dependency_task_ids = load_blocked_dependency_ids(tx, &dependency_task_ids).await?;
    Ok(CoordinationTask {
        id: row.id,
        creator_thread_id: row.creator_thread_id,
        owner_thread_id: row.owner_thread_id,
        team_id: row.team_id,
        room: row.room,
        kind: crate::CoordinationTaskKind::parse(row.task_kind.as_str())?,
        status: CoordinationTaskStatus::parse(row.status.as_str())?,
        summary: row.summary,
        details: row.details,
        requested_capability: row.requested_capability,
        blocked_reason: row.blocked_reason,
        dependency_task_ids,
        blocked_dependency_task_ids,
        created_at: coordination_epoch_seconds_to_datetime(row.created_at)?,
        updated_at: coordination_epoch_seconds_to_datetime(row.updated_at)?,
        completed_at: row
            .completed_at
            .map(coordination_epoch_seconds_to_datetime)
            .transpose()?,
        lease_expires_at: row
            .lease_expires_at
            .map(coordination_epoch_seconds_to_datetime)
            .transpose()?,
    })
}

async fn load_dependency_ids(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    task_id: &str,
) -> anyhow::Result<Vec<String>> {
    sqlx::query_scalar::<_, String>(
        r#"
SELECT depends_on_task_id
FROM coordination_task_dependencies
WHERE task_id = ?
ORDER BY depends_on_task_id ASC
        "#,
    )
    .bind(task_id)
    .fetch_all(&mut **tx)
    .await
    .map_err(Into::into)
}

async fn load_blocked_dependency_ids(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    dependency_task_ids: &[String],
) -> anyhow::Result<Vec<String>> {
    let mut blocked = Vec::new();
    for dependency_task_id in dependency_task_ids {
        let status =
            sqlx::query_scalar::<_, String>("SELECT status FROM coordination_tasks WHERE id = ?")
                .bind(dependency_task_id)
                .fetch_optional(&mut **tx)
                .await?;
        if status.as_deref() != Some(CoordinationTaskStatus::Done.as_str()) {
            blocked.push(dependency_task_id.clone());
        }
    }
    Ok(blocked)
}

async fn load_coordination_act(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    id: &str,
) -> anyhow::Result<Option<CoordinationAct>> {
    sqlx::query_as::<_, CoordinationActRow>(
        r#"
SELECT
    id,
    task_id,
    actor_thread_id,
    act_kind,
    summary,
    payload_json,
    created_at
FROM coordination_acts
WHERE id = ?
        "#,
    )
    .bind(id)
    .fetch_optional(&mut **tx)
    .await?
    .map(TryInto::try_into)
    .transpose()
}

async fn insert_coordination_act(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    id: &str,
    task_id: Option<&str>,
    actor_thread_id: ThreadId,
    kind: CoordinationActKind,
    summary: Option<&str>,
    payload_json: &str,
    now: i64,
) -> anyhow::Result<()> {
    validate_coordination_act_summary(kind, summary)?;
    sqlx::query(
        r#"
INSERT INTO coordination_acts (
    id,
    task_id,
    actor_thread_id,
    act_kind,
    summary,
    payload_json,
    created_at
) VALUES (?, ?, ?, ?, ?, ?, ?)
        "#,
    )
    .bind(id)
    .bind(task_id)
    .bind(actor_thread_id.to_string())
    .bind(kind.as_str())
    .bind(summary)
    .bind(payload_json)
    .bind(now)
    .execute(&mut **tx)
    .await?;
    Ok(())
}

fn validate_coordination_act_summary(
    kind: CoordinationActKind,
    summary: Option<&str>,
) -> anyhow::Result<()> {
    if let Some(summary) = summary.map(str::trim).filter(|summary| !summary.is_empty())
        && is_placeholder_coordination_summary(summary)
    {
        anyhow::bail!(
            "coordination act {} requires a concrete summary, not placeholder text",
            kind.as_str()
        );
    }

    if !matches!(
        kind,
        CoordinationActKind::Done | CoordinationActKind::Handoff | CoordinationActKind::Yield
    ) {
        return Ok(());
    }

    let Some(_summary) = summary.map(str::trim).filter(|summary| !summary.is_empty()) else {
        anyhow::bail!(
            "coordination act {} requires a concise non-empty summary",
            kind.as_str()
        );
    };

    Ok(())
}

fn is_placeholder_coordination_summary(summary: &str) -> bool {
    let normalized = summary
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() {
                ch.to_ascii_lowercase()
            } else {
                ' '
            }
        })
        .collect::<String>()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ");

    matches!(
        normalized.as_str(),
        "placeholder"
            | "placeholder summary"
            | "todo"
            | "tbd"
            | "none"
            | "n a"
            | "na"
            | "noop"
            | "no op"
    )
}

async fn unblock_coordination_dependents(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    completed_task_id: &str,
    now: i64,
) -> anyhow::Result<Vec<CoordinationTask>> {
    let dependent_ids = sqlx::query_scalar::<_, String>(
        r#"
SELECT task_id
FROM coordination_task_dependencies
WHERE depends_on_task_id = ?
ORDER BY task_id ASC
        "#,
    )
    .bind(completed_task_id)
    .fetch_all(&mut **tx)
    .await?;

    let mut unblocked = Vec::new();
    for task_id in dependent_ids {
        let Some(task) = load_coordination_task(tx, task_id.as_str()).await? else {
            continue;
        };
        if task.status != CoordinationTaskStatus::Blocked {
            continue;
        }
        if !task.blocked_dependency_task_ids.is_empty() {
            continue;
        }
        let new_status = if task.owner_thread_id.is_some() {
            CoordinationTaskStatus::Awarded
        } else {
            CoordinationTaskStatus::Open
        };
        sqlx::query(
            r#"
UPDATE coordination_tasks
SET status = ?,
    blocked_reason = NULL,
    updated_at = ?
WHERE id = ?
            "#,
        )
        .bind(new_status.as_str())
        .bind(now)
        .bind(task_id.as_str())
        .execute(&mut **tx)
        .await?;
        if let Some(updated_task) = load_coordination_task(tx, task_id.as_str()).await? {
            unblocked.push(updated_task);
        }
    }
    Ok(unblocked)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::CoordinationTaskKind;
    use crate::CoordinationTaskStatus;
    use pretty_assertions::assert_eq;

    #[tokio::test]
    async fn completed_dependency_unblocks_awarded_task() {
        let temp_dir = tempfile::tempdir().expect("tempdir");
        let db = StateRuntime::init(temp_dir.path().to_path_buf(), "openai".to_string())
            .await
            .expect("init db");
        let creator = ThreadId::from_string("019e0000-0000-7000-8000-000000000001").expect("id");
        let owner = ThreadId::from_string("019e0000-0000-7000-8000-000000000002").expect("id");
        let reserved_impl_path = temp_dir.path().join("repo/src/protocol.rs");

        let impl_task = db
            .create_coordination_task(crate::CoordinationTaskCreateParams {
                id: "task-impl".to_string(),
                creator_thread_id: creator,
                owner_thread_id: Some(creator),
                reserved_path_claims: vec![crate::PathClaimSpec {
                    kind: crate::PathClaimKind::File,
                    path: reserved_impl_path.clone(),
                }],
                claim_lease_seconds: crate::DEFAULT_COORDINATION_LEASE_SECONDS,
                team_id: None,
                room: Some("repo/ozzz".to_string()),
                kind: CoordinationTaskKind::Implementation,
                summary: "land API shape".to_string(),
                details: "protocol first".to_string(),
                requested_capability: None,
                dependency_task_ids: Vec::new(),
                act_id: "act-open-1".to_string(),
                act_summary: Some("opened impl task".to_string()),
                act_payload_json: "{}".to_string(),
            })
            .await
            .expect("create impl task");
        assert_eq!(impl_task.task.status, CoordinationTaskStatus::Awarded);

        let review_task = db
            .create_coordination_task(crate::CoordinationTaskCreateParams {
                id: "task-review".to_string(),
                creator_thread_id: creator,
                owner_thread_id: Some(owner),
                reserved_path_claims: Vec::new(),
                claim_lease_seconds: crate::DEFAULT_COORDINATION_LEASE_SECONDS,
                team_id: None,
                room: Some("repo/ozzz".to_string()),
                kind: CoordinationTaskKind::Review,
                summary: "review API shape".to_string(),
                details: "after impl lands".to_string(),
                requested_capability: None,
                dependency_task_ids: vec!["task-impl".to_string()],
                act_id: "act-open-2".to_string(),
                act_summary: Some("opened review task".to_string()),
                act_payload_json: "{}".to_string(),
            })
            .await
            .expect("create review task");
        assert_eq!(review_task.task.status, CoordinationTaskStatus::Blocked);
        assert_eq!(
            review_task.task.blocked_dependency_task_ids,
            vec!["task-impl".to_string()]
        );

        db.accept_coordination_task(crate::CoordinationTaskAcceptParams {
            task_id: "task-impl".to_string(),
            actor_thread_id: creator,
            path_claims: vec![crate::PathClaimSpec {
                kind: crate::PathClaimKind::File,
                path: reserved_impl_path,
            }],
            lease_seconds: 600,
            act_id: "act-accept".to_string(),
            act_summary: Some("taking impl".to_string()),
            act_payload_json: "{}".to_string(),
        })
        .await
        .expect("accept impl");

        let outcome = db
            .complete_coordination_task(crate::CoordinationTaskDoneParams {
                task_id: "task-impl".to_string(),
                actor_thread_id: creator,
                act_id: "act-done".to_string(),
                act_summary: Some("impl done".to_string()),
                act_payload_json: "{}".to_string(),
            })
            .await
            .expect("complete impl");
        assert_eq!(outcome.task.status, CoordinationTaskStatus::Done);
        assert_eq!(outcome.unblocked_tasks.len(), 1);
        assert_eq!(outcome.unblocked_tasks[0].id, "task-review");
        assert_eq!(
            outcome.unblocked_tasks[0].status,
            CoordinationTaskStatus::Awarded
        );
    }

    #[tokio::test]
    async fn active_task_reopens_after_lease_expiry() {
        let temp_dir = tempfile::tempdir().expect("tempdir");
        let db = StateRuntime::init(temp_dir.path().to_path_buf(), "openai".to_string())
            .await
            .expect("init db");
        let creator = ThreadId::from_string("019e0000-0000-7000-8000-000000000011").expect("id");

        db.create_coordination_task(crate::CoordinationTaskCreateParams {
            id: "task-1".to_string(),
            creator_thread_id: creator,
            owner_thread_id: Some(creator),
            reserved_path_claims: Vec::new(),
            claim_lease_seconds: crate::DEFAULT_COORDINATION_LEASE_SECONDS,
            team_id: None,
            room: None,
            kind: CoordinationTaskKind::General,
            summary: "take task".to_string(),
            details: String::new(),
            requested_capability: None,
            dependency_task_ids: Vec::new(),
            act_id: "act-open".to_string(),
            act_summary: None,
            act_payload_json: "{}".to_string(),
        })
        .await
        .expect("create task");

        db.accept_coordination_task(crate::CoordinationTaskAcceptParams {
            task_id: "task-1".to_string(),
            actor_thread_id: creator,
            path_claims: Vec::new(),
            lease_seconds: 1,
            act_id: "act-accept".to_string(),
            act_summary: None,
            act_payload_json: "{}".to_string(),
        })
        .await
        .expect("accept task");

        tokio::time::sleep(std::time::Duration::from_secs(2)).await;
        let task = db
            .get_coordination_task("task-1")
            .await
            .expect("get task")
            .expect("task should exist");
        assert_eq!(task.status, CoordinationTaskStatus::Open);
        assert_eq!(task.owner_thread_id, None);
        assert_eq!(task.lease_expires_at, None);
    }

    #[tokio::test]
    async fn done_rejects_placeholder_summary() {
        let temp_dir = tempfile::tempdir().expect("tempdir");
        let db = StateRuntime::init(temp_dir.path().to_path_buf(), "openai".to_string())
            .await
            .expect("init db");
        let creator = ThreadId::from_string("019e0000-0000-7000-8000-000000000021").expect("id");

        db.create_coordination_task(crate::CoordinationTaskCreateParams {
            id: "task-done".to_string(),
            creator_thread_id: creator,
            owner_thread_id: Some(creator),
            reserved_path_claims: Vec::new(),
            claim_lease_seconds: crate::DEFAULT_COORDINATION_LEASE_SECONDS,
            team_id: None,
            room: None,
            kind: CoordinationTaskKind::Qa,
            summary: "verify summary".to_string(),
            details: String::new(),
            requested_capability: None,
            dependency_task_ids: Vec::new(),
            act_id: "act-open-done".to_string(),
            act_summary: Some("opened verification".to_string()),
            act_payload_json: "{}".to_string(),
        })
        .await
        .expect("create task");

        let err = db
            .complete_coordination_task(crate::CoordinationTaskDoneParams {
                task_id: "task-done".to_string(),
                actor_thread_id: creator,
                act_id: "act-done-placeholder".to_string(),
                act_summary: Some("placeholder".to_string()),
                act_payload_json: "{}".to_string(),
            })
            .await
            .expect_err("placeholder done should fail");

        assert!(
            err.to_string().contains("requires a concrete summary"),
            "unexpected error: {err}"
        );
    }

    #[tokio::test]
    async fn accept_rejects_noop_summary() {
        let temp_dir = tempfile::tempdir().expect("tempdir");
        let db = StateRuntime::init(temp_dir.path().to_path_buf(), "openai".to_string())
            .await
            .expect("init db");
        let creator = ThreadId::from_string("019e0000-0000-7000-8000-000000000022").expect("id");

        db.create_coordination_task(crate::CoordinationTaskCreateParams {
            id: "task-accept".to_string(),
            creator_thread_id: creator,
            owner_thread_id: Some(creator),
            reserved_path_claims: Vec::new(),
            claim_lease_seconds: crate::DEFAULT_COORDINATION_LEASE_SECONDS,
            team_id: None,
            room: None,
            kind: CoordinationTaskKind::General,
            summary: "take task".to_string(),
            details: String::new(),
            requested_capability: None,
            dependency_task_ids: Vec::new(),
            act_id: "act-open-accept".to_string(),
            act_summary: Some("opened task".to_string()),
            act_payload_json: "{}".to_string(),
        })
        .await
        .expect("create task");

        let err = db
            .accept_coordination_task(crate::CoordinationTaskAcceptParams {
                task_id: "task-accept".to_string(),
                actor_thread_id: creator,
                path_claims: Vec::new(),
                lease_seconds: 600,
                act_id: "act-accept-noop".to_string(),
                act_summary: Some("noop".to_string()),
                act_payload_json: "{}".to_string(),
            })
            .await
            .expect_err("noop accept should fail");

        assert!(
            err.to_string().contains("requires a concrete summary"),
            "unexpected error: {err}"
        );
    }

    #[tokio::test]
    async fn implementation_accept_requires_path_claims() {
        let temp_dir = tempfile::tempdir().expect("tempdir");
        let db = StateRuntime::init(temp_dir.path().to_path_buf(), "openai".to_string())
            .await
            .expect("init db");
        let creator = ThreadId::from_string("019e0000-0000-7000-8000-000000000023").expect("id");

        db.create_coordination_task(crate::CoordinationTaskCreateParams {
            id: "task-impl-claims".to_string(),
            creator_thread_id: creator,
            owner_thread_id: None,
            reserved_path_claims: Vec::new(),
            claim_lease_seconds: crate::DEFAULT_COORDINATION_LEASE_SECONDS,
            team_id: None,
            room: None,
            kind: CoordinationTaskKind::Implementation,
            summary: "land impl".to_string(),
            details: String::new(),
            requested_capability: None,
            dependency_task_ids: Vec::new(),
            act_id: "act-open-impl-claims".to_string(),
            act_summary: Some("opened impl".to_string()),
            act_payload_json: "{}".to_string(),
        })
        .await
        .expect("create task");

        let err = db
            .accept_coordination_task(crate::CoordinationTaskAcceptParams {
                task_id: "task-impl-claims".to_string(),
                actor_thread_id: creator,
                path_claims: Vec::new(),
                lease_seconds: 600,
                act_id: "act-accept-impl-claims".to_string(),
                act_summary: Some("taking impl".to_string()),
                act_payload_json: "{}".to_string(),
            })
            .await
            .expect_err("implementation accept should require claims");

        assert!(
            err.to_string().contains("requires exact ownership claims"),
            "unexpected error: {err}"
        );

        let task = db
            .get_coordination_task("task-impl-claims")
            .await
            .expect("get task")
            .expect("task should exist");
        assert_eq!(task.status, CoordinationTaskStatus::Open);
        assert_eq!(task.owner_thread_id, None);
    }

    #[tokio::test]
    async fn conflicting_path_claims_block_accept_without_activating_task() {
        let temp_dir = tempfile::tempdir().expect("tempdir");
        let db = StateRuntime::init(temp_dir.path().to_path_buf(), "openai".to_string())
            .await
            .expect("init db");
        let creator = ThreadId::from_string("019e0000-0000-7000-8000-000000000024").expect("id");
        let blocker = ThreadId::from_string("019e0000-0000-7000-8000-000000000025").expect("id");
        let claimed_path = temp_dir.path().join("repo/src/lib.rs");

        db.create_coordination_task(crate::CoordinationTaskCreateParams {
            id: "task-impl-conflict".to_string(),
            creator_thread_id: creator,
            owner_thread_id: None,
            reserved_path_claims: Vec::new(),
            claim_lease_seconds: crate::DEFAULT_COORDINATION_LEASE_SECONDS,
            team_id: None,
            room: None,
            kind: CoordinationTaskKind::Implementation,
            summary: "land impl".to_string(),
            details: String::new(),
            requested_capability: None,
            dependency_task_ids: Vec::new(),
            act_id: "act-open-impl-conflict".to_string(),
            act_summary: Some("opened impl".to_string()),
            act_payload_json: "{}".to_string(),
        })
        .await
        .expect("create task");

        db.claim_path_ownership(
            blocker,
            &[crate::PathClaimSpec {
                kind: crate::PathClaimKind::File,
                path: claimed_path.clone(),
            }],
            std::time::Duration::from_secs(600),
        )
        .await
        .expect("blocker claim should succeed");

        let err = db
            .accept_coordination_task(crate::CoordinationTaskAcceptParams {
                task_id: "task-impl-conflict".to_string(),
                actor_thread_id: creator,
                path_claims: vec![crate::PathClaimSpec {
                    kind: crate::PathClaimKind::File,
                    path: claimed_path.clone(),
                }],
                lease_seconds: 600,
                act_id: "act-accept-impl-conflict".to_string(),
                act_summary: Some("taking impl".to_string()),
                act_payload_json: "{}".to_string(),
            })
            .await
            .expect_err("conflicting claim should block accept");

        assert!(
            err.to_string()
                .contains("cannot become active because thread"),
            "unexpected error: {err}"
        );

        let task = db
            .get_coordination_task("task-impl-conflict")
            .await
            .expect("get task")
            .expect("task should exist");
        assert_eq!(task.status, CoordinationTaskStatus::Open);
        assert_eq!(task.owner_thread_id, None);
        assert_eq!(
            db.list_path_claims(Some(creator))
                .await
                .expect("list claims for creator"),
            Vec::<crate::PathClaim>::new()
        );
    }

    #[tokio::test]
    async fn same_owner_active_accept_refreshes_task_instead_of_failing() {
        let temp_dir = tempfile::tempdir().expect("tempdir");
        let db = StateRuntime::init(temp_dir.path().to_path_buf(), "openai".to_string())
            .await
            .expect("init db");
        let creator = ThreadId::from_string("019e0000-0000-7000-8000-000000000028").expect("id");

        db.create_coordination_task(crate::CoordinationTaskCreateParams {
            id: "task-active-refresh".to_string(),
            creator_thread_id: creator,
            owner_thread_id: None,
            reserved_path_claims: Vec::new(),
            claim_lease_seconds: crate::DEFAULT_COORDINATION_LEASE_SECONDS,
            team_id: None,
            room: None,
            kind: CoordinationTaskKind::General,
            summary: "refresh task".to_string(),
            details: String::new(),
            requested_capability: None,
            dependency_task_ids: Vec::new(),
            act_id: "act-open-active-refresh".to_string(),
            act_summary: Some("opened task".to_string()),
            act_payload_json: "{}".to_string(),
        })
        .await
        .expect("create task");

        db.accept_coordination_task(crate::CoordinationTaskAcceptParams {
            task_id: "task-active-refresh".to_string(),
            actor_thread_id: creator,
            path_claims: Vec::new(),
            lease_seconds: 300,
            act_id: "act-accept-active-refresh-1".to_string(),
            act_summary: Some("taking task".to_string()),
            act_payload_json: "{}".to_string(),
        })
        .await
        .expect("initial accept should succeed");

        let refreshed = db
            .accept_coordination_task(crate::CoordinationTaskAcceptParams {
                task_id: "task-active-refresh".to_string(),
                actor_thread_id: creator,
                path_claims: Vec::new(),
                lease_seconds: 300,
                act_id: "act-accept-active-refresh-2".to_string(),
                act_summary: Some("refreshing lease".to_string()),
                act_payload_json: "{}".to_string(),
            })
            .await
            .expect("same-owner active accept should refresh instead of failing");

        assert_eq!(refreshed.task.status, CoordinationTaskStatus::Active);
        let owner = creator.to_string();
        assert_eq!(refreshed.task.owner_thread_id.as_deref(), Some(owner.as_str()));
    }

    #[tokio::test]
    async fn done_rejects_cancelled_task_status() {
        let temp_dir = tempfile::tempdir().expect("tempdir");
        let db = StateRuntime::init(temp_dir.path().to_path_buf(), "openai".to_string())
            .await
            .expect("init db");
        let creator = ThreadId::from_string("019e0000-0000-7000-8000-000000000029").expect("id");

        db.create_coordination_task(crate::CoordinationTaskCreateParams {
            id: "task-cancelled-done".to_string(),
            creator_thread_id: creator,
            owner_thread_id: None,
            reserved_path_claims: Vec::new(),
            claim_lease_seconds: crate::DEFAULT_COORDINATION_LEASE_SECONDS,
            team_id: None,
            room: None,
            kind: CoordinationTaskKind::General,
            summary: "cancelled task".to_string(),
            details: String::new(),
            requested_capability: None,
            dependency_task_ids: Vec::new(),
            act_id: "act-open-cancelled-done".to_string(),
            act_summary: Some("opened task".to_string()),
            act_payload_json: "{}".to_string(),
        })
        .await
        .expect("create task");

        sqlx::query("UPDATE coordination_tasks SET status = ? WHERE id = ?")
            .bind(CoordinationTaskStatus::Cancelled.as_str())
            .bind("task-cancelled-done")
            .execute(db.pool.as_ref())
            .await
            .expect("cancel task directly");

        let err = db
            .complete_coordination_task(crate::CoordinationTaskDoneParams {
                task_id: "task-cancelled-done".to_string(),
                actor_thread_id: creator,
                act_id: "act-done-cancelled".to_string(),
                act_summary: Some("trying to complete cancelled task".to_string()),
                act_payload_json: "{}".to_string(),
            })
            .await
            .expect_err("cancelled task should not become done");

        assert!(err.to_string().contains("cannot be completed from status `cancelled`"));
    }

    #[tokio::test]
    async fn direct_awarded_implementation_requires_reserved_path_claims_on_create() {
        let temp_dir = tempfile::tempdir().expect("tempdir");
        let db = StateRuntime::init(temp_dir.path().to_path_buf(), "openai".to_string())
            .await
            .expect("init db");
        let creator = ThreadId::from_string("019e0000-0000-7000-8000-000000000026").expect("id");
        let owner = ThreadId::from_string("019e0000-0000-7000-8000-000000000027").expect("id");

        let err = db
            .create_coordination_task(crate::CoordinationTaskCreateParams {
                id: "task-impl-award-missing".to_string(),
                creator_thread_id: creator,
                owner_thread_id: Some(owner),
                reserved_path_claims: Vec::new(),
                claim_lease_seconds: crate::DEFAULT_COORDINATION_LEASE_SECONDS,
                team_id: None,
                room: None,
                kind: CoordinationTaskKind::Implementation,
                summary: "land impl".to_string(),
                details: String::new(),
                requested_capability: None,
                dependency_task_ids: Vec::new(),
                act_id: "act-open-impl-award-missing".to_string(),
                act_summary: Some("opened impl".to_string()),
                act_payload_json: "{}".to_string(),
            })
            .await
            .expect_err("direct implementation award should require reserved claims");

        assert!(
            err.to_string()
                .contains("requires exact ownership claims before it can be awarded"),
            "unexpected error: {err}"
        );
        assert_eq!(
            db.get_coordination_task("task-impl-award-missing")
                .await
                .expect("get task should succeed"),
            None
        );
        assert_eq!(
            db.list_path_claims(Some(owner))
                .await
                .expect("owner claims should list cleanly"),
            Vec::<crate::PathClaim>::new()
        );
    }

    #[tokio::test]
    async fn conflicting_reserved_path_claims_block_direct_implementation_award() {
        let temp_dir = tempfile::tempdir().expect("tempdir");
        let db = StateRuntime::init(temp_dir.path().to_path_buf(), "openai".to_string())
            .await
            .expect("init db");
        let creator = ThreadId::from_string("019e0000-0000-7000-8000-000000000028").expect("id");
        let owner = ThreadId::from_string("019e0000-0000-7000-8000-000000000029").expect("id");
        let blocker = ThreadId::from_string("019e0000-0000-7000-8000-000000000030").expect("id");
        let claimed_path = temp_dir.path().join("repo/src/lib.rs");

        db.claim_path_ownership(
            blocker,
            &[crate::PathClaimSpec {
                kind: crate::PathClaimKind::File,
                path: claimed_path.clone(),
            }],
            std::time::Duration::from_secs(600),
        )
        .await
        .expect("blocker claim should succeed");

        let err = db
            .create_coordination_task(crate::CoordinationTaskCreateParams {
                id: "task-impl-award-conflict".to_string(),
                creator_thread_id: creator,
                owner_thread_id: Some(owner),
                reserved_path_claims: vec![crate::PathClaimSpec {
                    kind: crate::PathClaimKind::File,
                    path: claimed_path.clone(),
                }],
                claim_lease_seconds: crate::DEFAULT_COORDINATION_LEASE_SECONDS,
                team_id: None,
                room: None,
                kind: CoordinationTaskKind::Implementation,
                summary: "land impl".to_string(),
                details: String::new(),
                requested_capability: None,
                dependency_task_ids: Vec::new(),
                act_id: "act-open-impl-award-conflict".to_string(),
                act_summary: Some("opened impl".to_string()),
                act_payload_json: "{}".to_string(),
            })
            .await
            .expect_err("conflicting reserved claim should block create");

        assert!(
            err.to_string().contains("cannot be awarded because thread"),
            "unexpected error: {err}"
        );
        assert_eq!(
            db.get_coordination_task("task-impl-award-conflict")
                .await
                .expect("get task should succeed"),
            None
        );
        assert_eq!(
            db.list_path_claims(Some(owner))
                .await
                .expect("owner claims should list cleanly"),
            Vec::<crate::PathClaim>::new()
        );
        assert_eq!(
            db.list_path_claims(Some(blocker))
                .await
                .expect("blocker claims should list cleanly")
                .len(),
            1
        );
    }
}
