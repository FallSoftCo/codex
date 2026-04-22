use crate::function_tool::FunctionCallError;
use crate::hollywood::HollywoodSessionConfig;
use crate::session::session::Session;
use crate::tools::context::FunctionToolOutput;
use crate::tools::context::ToolInvocation;
use crate::tools::context::ToolPayload;
use crate::tools::handlers::multi_agents::parse_agent_id_target;
use crate::tools::handlers::parse_arguments;
use crate::tools::registry::ToolHandler;
use crate::tools::registry::ToolKind;
use codex_protocol::ThreadId;
use reqwest::Client;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use serde_json::json;
use std::path::PathBuf;
use std::sync::Arc;

pub struct CoordinationHandler;

#[derive(Debug, Deserialize)]
struct CoordinationActArgs {
    action: String,
    task_id: Option<String>,
    title: Option<String>,
    details: Option<String>,
    kind: Option<String>,
    owner: Option<String>,
    team_id: Option<String>,
    room: Option<String>,
    capability: Option<String>,
    depends_on: Option<Vec<String>>,
    summary: Option<String>,
    #[serde(default = "default_notify_room")]
    notify_room: bool,
    claim_paths: Option<Vec<PathClaimArg>>,
    release_paths: Option<Vec<PathClaimArg>>,
    lease_seconds: Option<i64>,
}

#[derive(Debug, Deserialize)]
struct ListCoordinationTasksArgs {
    owner: Option<String>,
    creator: Option<String>,
    statuses: Option<Vec<String>>,
    #[serde(default)]
    include_history: bool,
}

#[derive(Debug, Deserialize, Serialize)]
struct PathClaimArg {
    kind: String,
    path: String,
}

#[derive(Debug, Serialize)]
struct CoordinationActResult {
    task: codex_state::CoordinationTask,
    act: codex_state::CoordinationAct,
    unblocked_tasks: Vec<codex_state::CoordinationTask>,
    ownership: Option<Value>,
    room_notified: bool,
    woken_threads: Vec<String>,
}

fn default_notify_room() -> bool {
    true
}

impl ToolHandler for CoordinationHandler {
    type Output = FunctionToolOutput;

    fn kind(&self) -> ToolKind {
        ToolKind::Function
    }

    async fn handle(&self, invocation: ToolInvocation) -> Result<Self::Output, FunctionCallError> {
        let ToolInvocation {
            session,
            tool_name,
            payload,
            ..
        } = invocation;

        let ToolPayload::Function { arguments } = payload else {
            return Err(FunctionCallError::RespondToModel(
                "coordination handler received unsupported payload".to_string(),
            ));
        };

        let db = required_state_db(&session)?;
        match tool_name.name.as_str() {
            "coordination_act" => {
                let args: CoordinationActArgs = parse_arguments(&arguments)?;
                handle_coordination_act(&session, &db, args).await
            }
            "list_coordination_tasks" => {
                let args: ListCoordinationTasksArgs = parse_arguments(&arguments)?;
                let owner_thread_id = args
                    .owner
                    .as_deref()
                    .map(parse_agent_id_target)
                    .transpose()
                    .map_err(|err| FunctionCallError::RespondToModel(err.to_string()))?;
                let creator_thread_id = args
                    .creator
                    .as_deref()
                    .map(parse_agent_id_target)
                    .transpose()
                    .map_err(|err| FunctionCallError::RespondToModel(err.to_string()))?;
                let statuses = args
                    .statuses
                    .unwrap_or_default()
                    .into_iter()
                    .map(|status| codex_state::CoordinationTaskStatus::parse(status.as_str()))
                    .collect::<Result<Vec<_>, _>>()
                    .map_err(|err| FunctionCallError::RespondToModel(err.to_string()))?;
                let tasks = db
                    .list_coordination_tasks(codex_state::CoordinationTaskListFilter {
                        owner_thread_id,
                        creator_thread_id,
                        statuses,
                    })
                    .await
                    .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
                let content = if args.include_history {
                    let task_ids = tasks.iter().map(|task| task.id.clone()).collect::<Vec<_>>();
                    let acts = db
                        .list_coordination_acts(None)
                        .await
                        .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
                    let acts = acts
                        .into_iter()
                        .filter(|act| {
                            act.task_id
                                .as_ref()
                                .is_some_and(|task_id| task_ids.contains(task_id))
                        })
                        .collect::<Vec<_>>();
                    json!({
                        "tasks": tasks,
                        "acts": acts,
                    })
                } else {
                    json!({ "tasks": tasks })
                };
                Ok(FunctionToolOutput::from_text(
                    serde_json::to_string_pretty(&content)
                        .map_err(|err| FunctionCallError::Fatal(err.to_string()))?,
                    Some(true),
                ))
            }
            other => Err(FunctionCallError::RespondToModel(format!(
                "unsupported coordination tool {other}"
            ))),
        }
    }
}

async fn handle_coordination_act(
    session: &Arc<Session>,
    db: &Arc<codex_state::StateRuntime>,
    args: CoordinationActArgs,
) -> Result<FunctionToolOutput, FunctionCallError> {
    let actor_thread_id = session.conversation_id;
    let action = args.action.as_str();
    let outcome = match action {
        "open_task" => {
            let title = args
                .title
                .clone()
                .filter(|title| !title.trim().is_empty())
                .ok_or_else(|| {
                    FunctionCallError::RespondToModel(
                        "coordination_act open_task requires a non-empty title".to_string(),
                    )
                })?;
            let kind = args
                .kind
                .as_deref()
                .map(codex_state::CoordinationTaskKind::parse)
                .transpose()
                .map_err(|err| FunctionCallError::RespondToModel(err.to_string()))?
                .unwrap_or(codex_state::CoordinationTaskKind::General);
            let owner_thread_id = args
                .owner
                .as_deref()
                .map(parse_agent_id_target)
                .transpose()
                .map_err(|err| FunctionCallError::RespondToModel(err.to_string()))?;
            db.create_coordination_task(codex_state::CoordinationTaskCreateParams {
                id: uuid::Uuid::new_v4().to_string(),
                creator_thread_id: actor_thread_id,
                owner_thread_id,
                team_id: args.team_id.clone(),
                room: args.room.clone(),
                kind,
                summary: title,
                details: args.details.clone().unwrap_or_default(),
                requested_capability: args.capability.clone(),
                dependency_task_ids: args.depends_on.clone().unwrap_or_default(),
                act_id: uuid::Uuid::new_v4().to_string(),
                act_summary: args.summary.clone(),
                act_payload_json: serde_json::to_string(&json!({
                    "action": "open_task",
                    "details": args.details,
                    "kind": args.kind,
                    "owner": args.owner,
                    "team_id": args.team_id,
                    "room": args.room,
                    "capability": args.capability,
                    "depends_on": args.depends_on,
                }))
                .map_err(|err| FunctionCallError::Fatal(err.to_string()))?,
            })
            .await
            .map_err(|err| FunctionCallError::Fatal(err.to_string()))?
        }
        "accept" => {
            let task = required_task(db, args.task_id.as_deref()).await?;
            if let Some(owner_thread_id) = task.owner_thread_id.as_deref()
                && owner_thread_id != actor_thread_id.to_string()
            {
                return Err(FunctionCallError::RespondToModel(format!(
                    "coordination task {} is currently awarded to {owner_thread_id}",
                    task.id
                )));
            }
            let lease_seconds = args
                .lease_seconds
                .unwrap_or(codex_state::DEFAULT_COORDINATION_LEASE_SECONDS);
            let ownership = if let Some(claim_paths) = args.claim_paths.as_deref() {
                Some(claim_paths_for_actor(db, actor_thread_id, claim_paths, lease_seconds).await?)
            } else {
                None
            };
            let outcome = db
                .accept_coordination_task(codex_state::CoordinationTaskAcceptParams {
                    task_id: task.id.clone(),
                    actor_thread_id,
                    lease_seconds,
                    act_id: uuid::Uuid::new_v4().to_string(),
                    act_summary: args.summary.clone(),
                    act_payload_json: serde_json::to_string(&json!({
                        "action": "accept",
                        "claim_paths": args.claim_paths,
                        "lease_seconds": lease_seconds,
                    }))
                    .map_err(|err| FunctionCallError::Fatal(err.to_string()))?,
                })
                .await
                .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
            return finalize_coordination_act(session, db, &args, outcome, ownership).await;
        }
        "done" => {
            let task = required_task(db, args.task_id.as_deref()).await?;
            ensure_task_control(&task, actor_thread_id)?;
            let outcome = db
                .complete_coordination_task(codex_state::CoordinationTaskDoneParams {
                    task_id: task.id.clone(),
                    actor_thread_id,
                    act_id: uuid::Uuid::new_v4().to_string(),
                    act_summary: args.summary.clone(),
                    act_payload_json: serde_json::to_string(&json!({
                        "action": "done",
                        "summary": args.summary,
                    }))
                    .map_err(|err| FunctionCallError::Fatal(err.to_string()))?,
                })
                .await
                .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
            let ownership = if let Some(release_paths) = args.release_paths.as_deref() {
                Some(release_paths_for_actor(db, actor_thread_id, release_paths).await?)
            } else {
                None
            };
            return finalize_coordination_act(session, db, &args, outcome, ownership).await;
        }
        "handoff" => {
            let task = required_task(db, args.task_id.as_deref()).await?;
            ensure_task_control(&task, actor_thread_id)?;
            let new_owner_thread_id = args
                .owner
                .as_deref()
                .ok_or_else(|| {
                    FunctionCallError::RespondToModel(
                        "coordination_act handoff requires `owner`".to_string(),
                    )
                })
                .and_then(|owner| {
                    parse_agent_id_target(owner)
                        .map_err(|err| FunctionCallError::RespondToModel(err.to_string()))
                })?;
            let outcome = db
                .handoff_coordination_task(codex_state::CoordinationTaskHandoffParams {
                    task_id: task.id.clone(),
                    actor_thread_id,
                    new_owner_thread_id,
                    act_id: uuid::Uuid::new_v4().to_string(),
                    act_summary: args.summary.clone(),
                    act_payload_json: serde_json::to_string(&json!({
                        "action": "handoff",
                        "owner": args.owner,
                        "summary": args.summary,
                    }))
                    .map_err(|err| FunctionCallError::Fatal(err.to_string()))?,
                })
                .await
                .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
            let ownership = if let Some(release_paths) = args.release_paths.as_deref() {
                Some(release_paths_for_actor(db, actor_thread_id, release_paths).await?)
            } else {
                None
            };
            return finalize_coordination_act(session, db, &args, outcome, ownership).await;
        }
        "yield" => {
            let task = required_task(db, args.task_id.as_deref()).await?;
            ensure_task_control(&task, actor_thread_id)?;
            let outcome = db
                .yield_coordination_task(codex_state::CoordinationTaskYieldParams {
                    task_id: task.id.clone(),
                    actor_thread_id,
                    act_id: uuid::Uuid::new_v4().to_string(),
                    act_summary: args.summary.clone(),
                    act_payload_json: serde_json::to_string(&json!({
                        "action": "yield",
                        "summary": args.summary,
                    }))
                    .map_err(|err| FunctionCallError::Fatal(err.to_string()))?,
                })
                .await
                .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
            let ownership = if let Some(release_paths) = args.release_paths.as_deref() {
                Some(release_paths_for_actor(db, actor_thread_id, release_paths).await?)
            } else {
                None
            };
            return finalize_coordination_act(session, db, &args, outcome, ownership).await;
        }
        other => {
            return Err(FunctionCallError::RespondToModel(format!(
                "invalid coordination action `{other}`; expected open_task, accept, done, handoff, or yield"
            )));
        }
    };
    finalize_coordination_act(session, db, &args, outcome, None).await
}

async fn finalize_coordination_act(
    session: &Arc<Session>,
    db: &Arc<codex_state::StateRuntime>,
    args: &CoordinationActArgs,
    outcome: codex_state::CoordinationTaskTransitionOutcome,
    ownership: Option<Value>,
) -> Result<FunctionToolOutput, FunctionCallError> {
    let mut woken_threads = Vec::new();
    if let Some(owner_thread_id) = outcome.task.owner_thread_id.as_deref()
        && owner_thread_id != session.conversation_id.to_string()
        && matches!(
            outcome.task.status,
            codex_state::CoordinationTaskStatus::Awarded
        )
    {
        enqueue_coordination_notification(db, owner_thread_id, &outcome.task, "assigned")
            .await
            .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
        woken_threads.push(owner_thread_id.to_string());
    }
    for task in &outcome.unblocked_tasks {
        if let Some(owner_thread_id) = task.owner_thread_id.as_deref()
            && owner_thread_id != session.conversation_id.to_string()
            && matches!(task.status, codex_state::CoordinationTaskStatus::Awarded)
        {
            enqueue_coordination_notification(db, owner_thread_id, task, "unblocked")
                .await
                .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
            woken_threads.push(owner_thread_id.to_string());
        }
    }
    let room_notified = if args.notify_room {
        send_coordination_room_summary(session, &outcome).await
    } else {
        false
    };

    let result = CoordinationActResult {
        task: outcome.task,
        act: outcome.act,
        unblocked_tasks: outcome.unblocked_tasks,
        ownership,
        room_notified,
        woken_threads,
    };
    Ok(FunctionToolOutput::from_text(
        serde_json::to_string_pretty(&result)
            .map_err(|err| FunctionCallError::Fatal(err.to_string()))?,
        Some(true),
    ))
}

fn required_state_db(
    session: &Arc<Session>,
) -> Result<Arc<codex_state::StateRuntime>, FunctionCallError> {
    session.state_db().ok_or_else(|| {
        FunctionCallError::RespondToModel(
            "durable coordination is unavailable for this session because the sqlite state db could not be initialized".to_string(),
        )
    })
}

async fn required_task(
    db: &Arc<codex_state::StateRuntime>,
    task_id: Option<&str>,
) -> Result<codex_state::CoordinationTask, FunctionCallError> {
    let task_id = task_id.ok_or_else(|| {
        FunctionCallError::RespondToModel("coordination_act requires `task_id`".to_string())
    })?;
    db.get_coordination_task(task_id)
        .await
        .map_err(|err| FunctionCallError::Fatal(err.to_string()))?
        .ok_or_else(|| {
            FunctionCallError::RespondToModel(format!("coordination task {task_id} was not found"))
        })
}

fn ensure_task_control(
    task: &codex_state::CoordinationTask,
    actor_thread_id: ThreadId,
) -> Result<(), FunctionCallError> {
    let actor_thread_id = actor_thread_id.to_string();
    let owner_matches = task.owner_thread_id.as_deref() == Some(actor_thread_id.as_str());
    let creator_matches = task.creator_thread_id == actor_thread_id;
    if owner_matches || creator_matches {
        return Ok(());
    }
    Err(FunctionCallError::RespondToModel(format!(
        "coordination task {} is controlled by creator {} and owner {:?}",
        task.id, task.creator_thread_id, task.owner_thread_id
    )))
}

async fn claim_paths_for_actor(
    db: &Arc<codex_state::StateRuntime>,
    actor_thread_id: ThreadId,
    claim_paths: &[PathClaimArg],
    lease_seconds: i64,
) -> Result<Value, FunctionCallError> {
    let claims = resolve_path_claim_specs_for_thread(db, actor_thread_id, claim_paths).await?;
    let result = db
        .claim_path_ownership(
            actor_thread_id,
            &claims,
            std::time::Duration::from_secs(u64::try_from(lease_seconds.max(1)).unwrap_or(u64::MAX)),
        )
        .await
        .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
    Ok(json!({
        "acquired": result.acquired,
        "claims": result.claims.into_iter().map(path_claim_to_json).collect::<Vec<_>>(),
        "conflicts": result.conflicts.into_iter().map(path_claim_conflict_to_json).collect::<Vec<_>>(),
    }))
}

async fn release_paths_for_actor(
    db: &Arc<codex_state::StateRuntime>,
    actor_thread_id: ThreadId,
    release_paths: &[PathClaimArg],
) -> Result<Value, FunctionCallError> {
    let claims = resolve_path_claim_specs_for_thread(db, actor_thread_id, release_paths).await?;
    let released = db
        .release_path_claims(actor_thread_id, &claims)
        .await
        .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
    Ok(json!({ "released": released }))
}

async fn resolve_path_claim_specs_for_thread(
    db: &Arc<codex_state::StateRuntime>,
    actor_thread_id: ThreadId,
    claims: &[PathClaimArg],
) -> Result<Vec<codex_state::PathClaimSpec>, FunctionCallError> {
    let metadata = db
        .get_thread(actor_thread_id)
        .await
        .map_err(|err| FunctionCallError::Fatal(err.to_string()))?
        .ok_or_else(|| {
            FunctionCallError::RespondToModel(format!(
                "thread metadata for {actor_thread_id} is unavailable"
            ))
        })?;
    resolve_path_claim_specs(claims, metadata.cwd.as_path())
}

fn resolve_path_claim_specs(
    claims: &[PathClaimArg],
    cwd: &std::path::Path,
) -> Result<Vec<codex_state::PathClaimSpec>, FunctionCallError> {
    claims
        .iter()
        .map(|claim| {
            let kind = match claim.kind.as_str() {
                "file" => codex_state::PathClaimKind::File,
                "directory" => codex_state::PathClaimKind::Directory,
                other => {
                    return Err(FunctionCallError::RespondToModel(format!(
                        "invalid path claim kind `{other}`; expected file or directory"
                    )));
                }
            };
            let path = PathBuf::from(&claim.path);
            let path = if path.is_absolute() {
                path
            } else {
                cwd.join(path)
            };
            Ok(codex_state::PathClaimSpec { kind, path })
        })
        .collect()
}

fn path_claim_to_json(claim: codex_state::PathClaim) -> Value {
    json!({
        "id": claim.id,
        "owner_thread_id": claim.owner_thread_id,
        "kind": claim.kind.as_str(),
        "path": claim.path,
        "claimed_at": claim.claimed_at.timestamp(),
        "updated_at": claim.updated_at.timestamp(),
        "lease_expires_at": claim.lease_expires_at.timestamp(),
    })
}

fn path_claim_conflict_to_json(conflict: codex_state::PathClaimConflict) -> Value {
    json!({
        "requested": {
            "kind": conflict.requested.kind.as_str(),
            "path": conflict.requested.path,
        },
        "blocking_claim": path_claim_to_json(conflict.blocking_claim),
    })
}

async fn enqueue_coordination_notification(
    db: &Arc<codex_state::StateRuntime>,
    thread_id: &str,
    task: &codex_state::CoordinationTask,
    reason: &str,
) -> anyhow::Result<()> {
    db.create_scheduled_task(codex_state::ScheduledTaskCreateParams {
        id: uuid::Uuid::new_v4().to_string(),
        thread_id: thread_id.to_string(),
        title: format!("coordination:{reason}:{}", task.summary),
        prompt: format_coordination_wake_prompt(task, reason),
        kind: codex_state::ScheduledTaskKind::Once,
        next_run_at: chrono::Utc::now(),
        interval_seconds: None,
        requires_response: true,
    })
    .await
}

fn format_coordination_wake_prompt(task: &codex_state::CoordinationTask, reason: &str) -> String {
    format!(
        concat!(
            "<coordination_context>\n",
            "reason: {reason}\n",
            "task_id: {task_id}\n",
            "task_kind: {task_kind}\n",
            "status: {status}\n",
            "creator_thread_id: {creator_thread_id}\n",
            "owner_thread_id: {owner_thread_id}\n",
            "room: {room}\n",
            "dependencies: {dependencies}\n",
            "</coordination_context>\n\n",
            "{summary}\n\n",
            "{details}\n\n",
            "Inspect the coordination task, claim or continue any needed ownership, and carry the work forward."
        ),
        reason = reason,
        task_id = task.id,
        task_kind = task.kind.as_str(),
        status = task.status.as_str(),
        creator_thread_id = task.creator_thread_id,
        owner_thread_id = task.owner_thread_id.as_deref().unwrap_or(""),
        room = task.room.as_deref().unwrap_or(""),
        dependencies = if task.dependency_task_ids.is_empty() {
            "none".to_string()
        } else {
            task.dependency_task_ids.join(", ")
        },
        summary = task.summary,
        details = task.details,
    )
}

async fn send_coordination_room_summary(
    session: &Arc<Session>,
    outcome: &codex_state::CoordinationTaskTransitionOutcome,
) -> bool {
    let Some(config) = HollywoodSessionConfig::from_env() else {
        return false;
    };
    let room = outcome
        .task
        .room
        .clone()
        .unwrap_or_else(|| config.room.clone());
    let body = coordination_room_summary(session.conversation_id, outcome);
    let url = format!("{}/hollywood/v1/messages", config.url.trim_end_matches('/'));
    Client::new()
        .post(url)
        .json(&json!({
            "room": room,
            "sender_id": session.conversation_id.to_string(),
            "message_kind": "ambient",
            "response_policy": "none",
            "body": body,
        }))
        .send()
        .await
        .ok()
        .and_then(|response| response.error_for_status().ok())
        .is_some()
}

fn coordination_room_summary(
    actor_thread_id: ThreadId,
    outcome: &codex_state::CoordinationTaskTransitionOutcome,
) -> String {
    let mut summary = format!(
        "Coordination update from {actor_thread_id}: {} `{}` [{}]",
        outcome.act.kind.as_str(),
        outcome.task.summary,
        outcome.task.id
    );
    if let Some(owner_thread_id) = outcome.task.owner_thread_id.as_deref() {
        summary.push_str(format!(" owner={owner_thread_id}").as_str());
    }
    if !outcome.unblocked_tasks.is_empty() {
        let unblocked = outcome
            .unblocked_tasks
            .iter()
            .map(|task| format!("{} [{}]", task.summary, task.id))
            .collect::<Vec<_>>()
            .join(", ");
        summary.push_str(format!(" unblocked={unblocked}").as_str());
    }
    summary
}

#[cfg(test)]
#[path = "coordination_tests.rs"]
mod tests;
