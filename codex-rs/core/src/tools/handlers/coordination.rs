use crate::function_tool::FunctionCallError;
use crate::hollywood::HollywoodSessionConfig;
use crate::hollywood::canonicalize_agent_identity;
use crate::hollywood::canonicalize_hollywood_identity;
use crate::hollywood::live_identity_matches_target;
use crate::session::session::Session;
use crate::session::turn_context::TurnContext;
use crate::tools::context::FunctionToolOutput;
use crate::tools::context::ToolInvocation;
use crate::tools::context::ToolPayload;
use crate::tools::handlers::multi_agents::parse_agent_id_target;
use crate::tools::handlers::parse_arguments;
use crate::tools::registry::ToolHandler;
use crate::tools::registry::ToolKind;
use chrono::DateTime;
use chrono::Duration;
use chrono::Utc;
use codex_protocol::ThreadId;
use reqwest::Client;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use serde_json::json;
use std::path::PathBuf;
use std::sync::Arc;

pub struct CoordinationHandler;
const HOLLYWOOD_REGISTRY_STALE_AFTER: Duration = Duration::seconds(90);

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
    room: Option<String>,
    #[serde(default)]
    include_history: bool,
}

#[derive(Debug, Deserialize, Serialize)]
struct PathClaimArg {
    kind: String,
    path: String,
}

#[derive(Debug, Deserialize)]
struct OpenTaskActPayload {
    #[serde(default)]
    claim_paths: Option<Vec<PathClaimArg>>,
}

#[derive(Debug, Serialize)]
struct CoordinationActResult {
    task: codex_state::CoordinationTask,
    act: Option<codex_state::CoordinationAct>,
    unblocked_tasks: Vec<codex_state::CoordinationTask>,
    ownership: Option<Value>,
    room_notified: bool,
    woken_threads: Vec<String>,
    deduped: bool,
}

#[derive(Debug, Deserialize)]
struct HollywoodRegistryListResponse {
    entries: Vec<HollywoodRegistryEntry>,
}

#[derive(Debug, Deserialize)]
struct HollywoodRegistryEntry {
    session_id: String,
    attached: bool,
    identities: Vec<String>,
    updated_at: Option<String>,
    last_heartbeat_at: Option<String>,
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
            turn,
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
                handle_coordination_act(&session, &turn, &db, args).await
            }
            "list_coordination_tasks" => {
                let args: ListCoordinationTasksArgs = parse_arguments(&arguments)?;
                let owner_thread_id = if let Some(owner) = args.owner.as_deref() {
                    Some(resolve_coordination_target(&session, &turn, &db, owner).await?)
                } else {
                    None
                };
                let creator_thread_id = if let Some(creator) = args.creator.as_deref() {
                    Some(resolve_coordination_target(&session, &turn, &db, creator).await?)
                } else {
                    None
                };
                let statuses = args
                    .statuses
                    .unwrap_or_default()
                    .into_iter()
                    .map(|status| parse_coordination_status(status.as_str()))
                    .collect::<Result<Vec<_>, _>>()
                    .map_err(FunctionCallError::RespondToModel)?;
                let room = match args.room {
                    Some(room) => Some(room),
                    None => hollywood_config_for_session(&session, &db)
                        .await?
                        .map(|config| config.room),
                };
                let tasks = db
                    .list_coordination_tasks(codex_state::CoordinationTaskListFilter {
                        owner_thread_id,
                        creator_thread_id,
                        room,
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
    turn: &Arc<TurnContext>,
    db: &Arc<codex_state::StateRuntime>,
    args: CoordinationActArgs,
) -> Result<FunctionToolOutput, FunctionCallError> {
    let actor_thread_id = session.conversation_id;
    let action = args.action.as_str();
    match validate_coordination_act_summary(action, args.summary.as_deref()) {
        Ok(()) => {}
        Err(FunctionCallError::RespondToModel(message)) => {
            return coordination_failure_output(message, None);
        }
        Err(fatal) => return Err(fatal),
    }
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
            let owner_thread_id = if let Some(owner) = args.owner.as_deref() {
                Some(resolve_coordination_target(session, turn, db, owner).await?)
            } else {
                None
            };
            if args.claim_paths.is_some() && owner_thread_id.is_none() {
                return coordination_failure_output(
                    "coordination_act open_task requires `owner` when reserving claim_paths"
                        .to_string(),
                    None,
                );
            }
            let reserved_path_claims = if let Some(claim_paths) = args.claim_paths.as_deref() {
                let owner_thread_id = owner_thread_id.ok_or_else(|| {
                    FunctionCallError::RespondToModel(
                        "coordination_act open_task requires `owner` when reserving claim_paths"
                            .to_string(),
                    )
                })?;
                resolve_path_claim_specs_for_thread(db, owner_thread_id, claim_paths).await?
            } else {
                Vec::new()
            };
            if matches!(kind, codex_state::CoordinationTaskKind::Implementation)
                && owner_thread_id.is_some()
                && reserved_path_claims.is_empty()
            {
                return coordination_failure_output(
                    "coordination_act open_task requires exact claim_paths before it can direct-assign implementation work".to_string(),
                    None,
                );
            }
            let details = if matches!(kind, codex_state::CoordinationTaskKind::Implementation) {
                with_reserved_scope_details(
                    args.details.clone().unwrap_or_default(),
                    args.claim_paths.as_deref().unwrap_or(&[]),
                )
            } else {
                args.details.clone().unwrap_or_default()
            };
            let reserved_claim_paths_json = path_claim_specs_to_json(&reserved_path_claims);
            let act_payload_json = serde_json::to_string(&json!({
                "action": "open_task",
                "details": args.details,
                "kind": args.kind,
                "owner": args.owner,
                "claim_paths": reserved_claim_paths_json,
                "team_id": args.team_id,
                "room": args.room,
                "capability": args.capability,
                "depends_on": args.depends_on,
            }))
            .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
            match db.create_coordination_task(codex_state::CoordinationTaskCreateParams {
                id: uuid::Uuid::new_v4().to_string(),
                creator_thread_id: actor_thread_id,
                owner_thread_id,
                reserved_path_claims,
                claim_lease_seconds: args
                    .lease_seconds
                    .unwrap_or(codex_state::DEFAULT_COORDINATION_LEASE_SECONDS),
                team_id: args.team_id.clone(),
                room: args.room.clone(),
                kind,
                summary: title,
                details,
                requested_capability: args.capability.clone(),
                dependency_task_ids: args.depends_on.clone().unwrap_or_default(),
                act_id: uuid::Uuid::new_v4().to_string(),
                act_summary: args.summary.clone(),
                act_payload_json,
            })
            .await
            {
                Ok(outcome) => outcome,
                Err(err) => {
                    let message = err.to_string();
                    if let Some(existing_task_id) =
                        parse_duplicate_implementation_task_id(message.as_str())
                    {
                        let existing_task = db
                            .get_coordination_task(existing_task_id)
                            .await
                            .map_err(|load_err| FunctionCallError::Fatal(load_err.to_string()))?
                            .ok_or_else(|| {
                                FunctionCallError::Fatal(format!(
                                    "duplicate coordination task {existing_task_id} disappeared"
                                ))
                            })?;
                        return coordination_duplicate_output(existing_task);
                    }
                    match map_coordination_open_task_message(message) {
                        FunctionCallError::RespondToModel(message) => {
                            return coordination_failure_output(message, None);
                        }
                        fatal => return Err(fatal),
                    }
                }
            }
        }
        "accept" => {
            let task = match required_task(db, args.task_id.as_deref()).await {
                Ok(task) => task,
                Err(FunctionCallError::RespondToModel(message)) => {
                    return coordination_failure_output(message, None);
                }
                Err(fatal) => return Err(fatal),
            };
            if let Some(owner_thread_id) = task.owner_thread_id.as_deref()
                && owner_thread_id != actor_thread_id.to_string()
            {
                return coordination_failure_output(
                    format!(
                        "coordination task {} is currently awarded to {owner_thread_id}",
                        task.id
                    ),
                    Some(&task),
                );
            }
            if task.status == codex_state::CoordinationTaskStatus::Active
                && task.owner_thread_id.as_deref() == Some(actor_thread_id.to_string().as_str())
            {
                return coordination_duplicate_output(task);
            }
            let lease_seconds = args
                .lease_seconds
                .unwrap_or(codex_state::DEFAULT_COORDINATION_LEASE_SECONDS);
            let path_claims = if let Some(claim_paths) = args.claim_paths.as_deref() {
                resolve_path_claim_specs_for_thread(db, actor_thread_id, claim_paths).await?
            } else if matches!(task.kind, codex_state::CoordinationTaskKind::Implementation)
                && matches!(task.status, codex_state::CoordinationTaskStatus::Awarded)
            {
                reserved_claim_paths_for_task(db, actor_thread_id, task.id.as_str()).await?
            } else {
                Vec::new()
            };
            let outcome = match db
                .accept_coordination_task(codex_state::CoordinationTaskAcceptParams {
                    task_id: task.id.clone(),
                    actor_thread_id,
                    path_claims: path_claims.clone(),
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
            {
                Ok(outcome) => outcome,
                Err(err) => {
                    if let Some(current_task) =
                        same_owner_active_task(db, task.id.as_str(), actor_thread_id).await?
                    {
                        return coordination_duplicate_output(current_task);
                    }
                    match map_coordination_transition_error(err) {
                        FunctionCallError::RespondToModel(message) => {
                            return coordination_failure_output(message, Some(&task));
                        }
                        fatal => return Err(fatal),
                    }
                }
            };
            let ownership = if path_claims.is_empty() {
                None
            } else {
                Some(accepted_claim_paths_for_actor(db, actor_thread_id, &path_claims).await?)
            };
            return finalize_coordination_act(session, turn, db, &args, outcome, ownership).await;
        }
        "done" => {
            let task = match required_task(db, args.task_id.as_deref()).await {
                Ok(task) => task,
                Err(FunctionCallError::RespondToModel(message)) => {
                    return coordination_failure_output(message, None);
                }
                Err(fatal) => return Err(fatal),
            };
            match ensure_task_control(&task, actor_thread_id) {
                Ok(()) => {}
                Err(FunctionCallError::RespondToModel(message)) => {
                    return coordination_failure_output(message, Some(&task));
                }
                Err(fatal) => return Err(fatal),
            }
            if task.status == codex_state::CoordinationTaskStatus::Done {
                return coordination_duplicate_output(task);
            }
            let outcome = match db
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
            {
                Ok(outcome) => outcome,
                Err(err) => {
                    if let Some(current_task) =
                        same_controller_done_task(db, task.id.as_str(), actor_thread_id).await?
                    {
                        return coordination_duplicate_output(current_task);
                    }
                    match map_coordination_transition_error(err) {
                        FunctionCallError::RespondToModel(message) => {
                            return coordination_failure_output(message, Some(&task));
                        }
                        fatal => return Err(fatal),
                    }
                }
            };
            let ownership = if let Some(release_paths) = args.release_paths.as_deref() {
                Some(release_paths_for_actor(db, actor_thread_id, release_paths).await?)
            } else {
                None
            };
            return finalize_coordination_act(session, turn, db, &args, outcome, ownership).await;
        }
        "handoff" => {
            let task = match required_task(db, args.task_id.as_deref()).await {
                Ok(task) => task,
                Err(FunctionCallError::RespondToModel(message)) => {
                    return coordination_failure_output(message, None);
                }
                Err(fatal) => return Err(fatal),
            };
            match ensure_task_control(&task, actor_thread_id) {
                Ok(()) => {}
                Err(FunctionCallError::RespondToModel(message)) => {
                    return coordination_failure_output(message, Some(&task));
                }
                Err(fatal) => return Err(fatal),
            }
            let new_owner_thread_id = args
                .owner
                .as_deref()
                .ok_or_else(|| {
                    FunctionCallError::RespondToModel(
                        "coordination_act handoff requires `owner`".to_string(),
                    )
                })
                .map(|owner| async { resolve_coordination_target(session, turn, db, owner).await })
                .expect("owner should exist")
                .await?;
            let outcome = match db
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
            {
                Ok(outcome) => outcome,
                Err(err) => match map_coordination_transition_error(err) {
                    FunctionCallError::RespondToModel(message) => {
                        return coordination_failure_output(message, Some(&task));
                    }
                    fatal => return Err(fatal),
                },
            };
            let ownership = if let Some(release_paths) = args.release_paths.as_deref() {
                Some(release_paths_for_actor(db, actor_thread_id, release_paths).await?)
            } else {
                None
            };
            return finalize_coordination_act(session, turn, db, &args, outcome, ownership).await;
        }
        "yield" => {
            let task = match required_task(db, args.task_id.as_deref()).await {
                Ok(task) => task,
                Err(FunctionCallError::RespondToModel(message)) => {
                    return coordination_failure_output(message, None);
                }
                Err(fatal) => return Err(fatal),
            };
            match ensure_task_control(&task, actor_thread_id) {
                Ok(()) => {}
                Err(FunctionCallError::RespondToModel(message)) => {
                    return coordination_failure_output(message, Some(&task));
                }
                Err(fatal) => return Err(fatal),
            }
            let outcome = match db
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
            {
                Ok(outcome) => outcome,
                Err(err) => match map_coordination_transition_error(err) {
                    FunctionCallError::RespondToModel(message) => {
                        return coordination_failure_output(message, Some(&task));
                    }
                    fatal => return Err(fatal),
                },
            };
            let ownership = if let Some(release_paths) = args.release_paths.as_deref() {
                Some(release_paths_for_actor(db, actor_thread_id, release_paths).await?)
            } else {
                None
            };
            return finalize_coordination_act(session, turn, db, &args, outcome, ownership).await;
        }
        other => {
            return Err(FunctionCallError::RespondToModel(format!(
                "invalid coordination action `{other}`; expected open_task, accept, done, handoff, or yield"
            )));
        }
    };
    finalize_coordination_act(session, turn, db, &args, outcome, None).await
}

async fn finalize_coordination_act(
    session: &Arc<Session>,
    turn: &Arc<TurnContext>,
    db: &Arc<codex_state::StateRuntime>,
    args: &CoordinationActArgs,
    outcome: codex_state::CoordinationTaskTransitionOutcome,
    ownership: Option<Value>,
) -> Result<FunctionToolOutput, FunctionCallError> {
    clear_superseded_coordination_notifications(db, &outcome)
        .await
        .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;

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
        send_coordination_room_summary(session, turn, db, &outcome).await
    } else {
        false
    };

    let result = CoordinationActResult {
        task: outcome.task,
        act: Some(outcome.act),
        unblocked_tasks: outcome.unblocked_tasks,
        ownership,
        room_notified,
        woken_threads,
        deduped: false,
    };
    Ok(FunctionToolOutput::from_text(
        serde_json::to_string_pretty(&result)
            .map_err(|err| FunctionCallError::Fatal(err.to_string()))?,
        Some(true),
    ))
}

async fn clear_superseded_coordination_notifications(
    db: &Arc<codex_state::StateRuntime>,
    outcome: &codex_state::CoordinationTaskTransitionOutcome,
) -> anyhow::Result<()> {
    let task_id = outcome.task.id.as_str();
    let actor_thread_id = ThreadId::from_string(&outcome.act.actor_thread_id).ok();
    let owner_thread_id = outcome
        .task
        .owner_thread_id
        .as_deref()
        .and_then(|thread_id| ThreadId::from_string(thread_id).ok());

    match outcome.act.kind {
        codex_state::CoordinationActKind::Accept | codex_state::CoordinationActKind::Done => {
            if let Some(owner_thread_id) = owner_thread_id {
                clear_coordination_notifications_for_thread(
                    db,
                    owner_thread_id,
                    task_id,
                    &["assigned", "unblocked"],
                )
                .await?;
            }
        }
        codex_state::CoordinationActKind::Handoff | codex_state::CoordinationActKind::Yield => {
            if let Some(actor_thread_id) = actor_thread_id {
                clear_coordination_notifications_for_thread(
                    db,
                    actor_thread_id,
                    task_id,
                    &["assigned", "unblocked"],
                )
                .await?;
            }
        }
        codex_state::CoordinationActKind::OpenTask => {}
    }

    Ok(())
}

async fn clear_coordination_notifications_for_thread(
    db: &Arc<codex_state::StateRuntime>,
    thread_id: ThreadId,
    task_id: &str,
    reasons: &[&str],
) -> anyhow::Result<usize> {
    let task_id_marker = format!("task_id: {task_id}");
    let scheduled_tasks = db.list_scheduled_tasks(Some(thread_id)).await?;
    let matching_task_ids = scheduled_tasks
        .into_iter()
        .filter(|scheduled_task| {
            reasons.iter().any(|reason| {
                scheduled_task
                    .title
                    .starts_with(format!("coordination:{reason}:").as_str())
            }) && scheduled_task.prompt.contains(&task_id_marker)
        })
        .map(|scheduled_task| scheduled_task.id)
        .collect::<Vec<_>>();

    for scheduled_task_id in &matching_task_ids {
        let _deleted = db.delete_scheduled_task(scheduled_task_id).await?;
    }

    Ok(matching_task_ids.len())
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

fn validate_coordination_act_summary(
    action: &str,
    summary: Option<&str>,
) -> Result<(), FunctionCallError> {
    if let Some(summary) = summary.map(str::trim).filter(|summary| !summary.is_empty())
        && is_placeholder_coordination_summary(summary)
    {
        return Err(FunctionCallError::RespondToModel(format!(
            "coordination_act {action} requires a concrete summary, not placeholder text"
        )));
    }

    if !matches!(action, "done" | "handoff" | "yield") {
        return Ok(());
    }

    let Some(_summary) = summary.map(str::trim).filter(|summary| !summary.is_empty()) else {
        return Err(FunctionCallError::RespondToModel(format!(
            "coordination_act {action} requires a concise non-empty summary"
        )));
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

fn parse_coordination_status(value: &str) -> Result<codex_state::CoordinationTaskStatus, String> {
    let normalized = value.trim().to_ascii_lowercase().replace(['-', ' '], "_");
    let canonical = match normalized.as_str() {
        "pending" | "todo" | "new" | "pending_review" | "proposed" => "open",
        "accepted" | "assigned" => "awarded",
        "claimed" | "in_progress" | "inprogress" | "handoff" | "handoff_pending" => "active",
        "complete" | "completed" | "closed" => "done",
        "canceled" => "cancelled",
        other => other,
    };
    codex_state::CoordinationTaskStatus::parse(canonical).map_err(|err| err.to_string())
}

async fn resolve_coordination_target(
    session: &Arc<Session>,
    turn: &Arc<TurnContext>,
    db: &Arc<codex_state::StateRuntime>,
    target: &str,
) -> Result<ThreadId, FunctionCallError> {
    if let Ok(thread_id) = parse_agent_id_target(target) {
        return Ok(thread_id);
    }

    if let Some(session_id) = canonicalize_agent_identity(target) {
        return ThreadId::from_string(&session_id).map_err(|err| {
            FunctionCallError::RespondToModel(format!("invalid agent id {target}: {err:?}"))
        });
    }

    if let Some(thread_id) = resolve_current_thread_target(session, db, target).await? {
        return Ok(thread_id);
    }

    let hollywood_config = hollywood_config_for_session(session, db).await?;
    if let Some(identity) = canonicalize_hollywood_identity(target)
        && let Some(config) = hollywood_config.as_ref()
    {
        if let Some(thread_id) = resolve_live_hollywood_identity(config, &identity).await? {
            return Ok(thread_id);
        }
        return Err(FunctionCallError::RespondToModel(format!(
            "unknown live Hollywood agent `{target}` in room `{}`",
            config.room
        )));
    }

    if hollywood_config.is_none()
        && let Some(thread_id) = resolve_thread_by_exact_title(db, turn, target).await?
    {
        return Ok(thread_id);
    }

    Err(FunctionCallError::RespondToModel(format!(
        "unknown agent id or name `{target}`"
    )))
}

async fn resolve_live_hollywood_identity(
    config: &HollywoodSessionConfig,
    identity: &str,
) -> Result<Option<ThreadId>, FunctionCallError> {
    let mut matches = Vec::new();
    for room in room_scoped_candidate_rooms(config) {
        let entries = fetch_registry_entries(config, &room).await?;
        for entry in entries {
            if !entry.attached {
                continue;
            }
            if (entry.session_id == identity
                || entry
                    .identities
                    .iter()
                    .any(|value| live_identity_matches_target(value, identity)))
                && !matches.iter().any(|value| value == &entry.session_id)
            {
                matches.push(entry.session_id);
            }
        }
    }

    match matches.len() {
        0 => Ok(None),
        1 => ThreadId::from_string(&matches[0]).map(Some).map_err(|err| {
            FunctionCallError::RespondToModel(format!(
                "Hollywood registry returned invalid session id for `{identity}`: {err:?}"
            ))
        }),
        _ => Err(FunctionCallError::RespondToModel(format!(
            "Hollywood identity `{identity}` is ambiguous across live sessions: {}",
            matches.join(", ")
        ))),
    }
}

async fn resolve_current_thread_target(
    session: &Arc<Session>,
    db: &Arc<codex_state::StateRuntime>,
    target: &str,
) -> Result<Option<ThreadId>, FunctionCallError> {
    let Some(target_title) = crate::util::normalize_thread_name(target.trim_start_matches('@'))
    else {
        return Ok(None);
    };
    let metadata = db
        .get_thread(session.conversation_id)
        .await
        .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
    let Some(metadata) = metadata else {
        return Ok(None);
    };
    let Some(current_title) = crate::util::normalize_thread_name(&metadata.title) else {
        return Ok(None);
    };
    if current_title == target_title {
        Ok(Some(session.conversation_id))
    } else {
        Ok(None)
    }
}

async fn resolve_thread_by_exact_title(
    db: &Arc<codex_state::StateRuntime>,
    turn: &Arc<TurnContext>,
    target: &str,
) -> Result<Option<ThreadId>, FunctionCallError> {
    let Some(title) = crate::util::normalize_thread_name(target.trim_start_matches('@')) else {
        return Ok(None);
    };
    let allowed_sources = Vec::<String>::new();
    db.find_thread_by_exact_title_including_empty_history(
        &title,
        &allowed_sources,
        None,
        /*archived_only*/ false,
        Some(turn.config.cwd.as_path()),
    )
    .await
    .map(|metadata| metadata.map(|thread| thread.id))
    .map_err(|err| FunctionCallError::Fatal(err.to_string()))
}

fn room_scoped_candidate_rooms(config: &HollywoodSessionConfig) -> Vec<String> {
    let mut rooms = Vec::new();
    let mut seen = std::collections::HashSet::new();
    for room in std::iter::once(config.room.as_str())
        .chain(config.observed_rooms.iter().map(String::as_str))
    {
        if !room.is_empty() && seen.insert(room.to_string()) {
            rooms.push(room.to_string());
        }
    }
    rooms
}

async fn hollywood_config_for_session(
    session: &Arc<Session>,
    db: &Arc<codex_state::StateRuntime>,
) -> Result<Option<HollywoodSessionConfig>, FunctionCallError> {
    if let Some(config) = session.hollywood_session_config().await {
        return Ok(Some(config));
    }

    let metadata = db
        .get_thread(session.conversation_id)
        .await
        .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
    let Some(hollywood) = metadata.and_then(|thread| thread.hollywood) else {
        return Ok(None);
    };

    Ok(Some(HollywoodSessionConfig {
        url: hollywood.url,
        room: hollywood.room,
        observed_rooms: Vec::new(),
        wake_rooms: Vec::new(),
        attention_mode: hollywood.attention_mode,
    }))
}

async fn fetch_registry_entries(
    config: &HollywoodSessionConfig,
    room: &str,
) -> Result<Vec<HollywoodRegistryEntry>, FunctionCallError> {
    let url = format!("{}/hollywood/v1/registry", config.url.trim_end_matches('/'));
    Client::new()
        .get(&url)
        .query(&[("room", room), ("limit", "1000")])
        .send()
        .await
        .map_err(|err| {
            FunctionCallError::RespondToModel(format!("Hollywood registry read failed: {err}"))
        })?
        .error_for_status()
        .map_err(|err| {
            FunctionCallError::RespondToModel(format!("Hollywood registry read failed: {err}"))
        })?
        .json::<HollywoodRegistryListResponse>()
        .await
        .map_err(|err| {
            FunctionCallError::RespondToModel(format!(
                "Hollywood registry response parse failed: {err}"
            ))
        })
        .map(|response| {
            let now = Utc::now();
            response
                .entries
                .into_iter()
                .filter(|entry| registry_entry_is_fresh(entry, &now))
                .collect()
        })
}

fn registry_entry_is_fresh(entry: &HollywoodRegistryEntry, now: &DateTime<Utc>) -> bool {
    let cutoff = *now - HOLLYWOOD_REGISTRY_STALE_AFTER;
    let heartbeat_at = entry
        .last_heartbeat_at
        .as_deref()
        .or(entry.updated_at.as_deref());
    heartbeat_at
        .and_then(parse_registry_timestamp)
        .is_some_and(|heartbeat_at| heartbeat_at >= cutoff)
}

fn parse_registry_timestamp(value: &str) -> Option<DateTime<Utc>> {
    DateTime::parse_from_rfc3339(value)
        .ok()
        .map(|parsed| parsed.with_timezone(&Utc))
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

async fn same_owner_active_task(
    db: &Arc<codex_state::StateRuntime>,
    task_id: &str,
    actor_thread_id: ThreadId,
) -> Result<Option<codex_state::CoordinationTask>, FunctionCallError> {
    let actor_thread_id = actor_thread_id.to_string();
    let Some(task) = db
        .get_coordination_task(task_id)
        .await
        .map_err(|err| FunctionCallError::Fatal(err.to_string()))?
    else {
        return Ok(None);
    };
    let same_owner_active = task.status == codex_state::CoordinationTaskStatus::Active
        && task.owner_thread_id.as_deref() == Some(actor_thread_id.as_str());
    Ok(same_owner_active.then_some(task))
}

async fn same_controller_done_task(
    db: &Arc<codex_state::StateRuntime>,
    task_id: &str,
    actor_thread_id: ThreadId,
) -> Result<Option<codex_state::CoordinationTask>, FunctionCallError> {
    let actor_thread_id = actor_thread_id.to_string();
    let Some(task) = db
        .get_coordination_task(task_id)
        .await
        .map_err(|err| FunctionCallError::Fatal(err.to_string()))?
    else {
        return Ok(None);
    };
    let same_controller_done = task.status == codex_state::CoordinationTaskStatus::Done
        && (task.owner_thread_id.as_deref() == Some(actor_thread_id.as_str())
            || task.creator_thread_id == actor_thread_id);
    Ok(same_controller_done.then_some(task))
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
    claim_paths: &[codex_state::PathClaimSpec],
) -> Result<Value, FunctionCallError> {
    let owned_claims = db
        .list_path_claims(Some(actor_thread_id))
        .await
        .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
    let claims = owned_claims
        .into_iter()
        .filter(|claim| {
            claim_paths
                .iter()
                .any(|requested| requested.kind == claim.kind && requested.path == claim.path)
        })
        .collect::<Vec<_>>();
    Ok(json!({
        "acquired": true,
        "claims": claims.into_iter().map(path_claim_to_json).collect::<Vec<_>>(),
        "conflicts": Vec::<Value>::new(),
    }))
}

async fn accepted_claim_paths_for_actor(
    db: &Arc<codex_state::StateRuntime>,
    actor_thread_id: ThreadId,
    claim_paths: &[codex_state::PathClaimSpec],
) -> Result<Value, FunctionCallError> {
    claim_paths_for_actor(db, actor_thread_id, claim_paths).await
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

async fn reserved_claim_paths_for_task(
    db: &Arc<codex_state::StateRuntime>,
    actor_thread_id: ThreadId,
    task_id: &str,
) -> Result<Vec<codex_state::PathClaimSpec>, FunctionCallError> {
    let acts = db
        .list_coordination_acts(Some(task_id))
        .await
        .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
    let claim_paths = acts
        .into_iter()
        .find(|act| matches!(act.kind, codex_state::CoordinationActKind::OpenTask))
        .and_then(|act| {
            serde_json::from_str::<OpenTaskActPayload>(act.payload_json.as_str())
                .ok()
                .and_then(|payload| payload.claim_paths)
        })
        .unwrap_or_default();
    resolve_path_claim_specs_for_thread(db, actor_thread_id, &claim_paths).await
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

fn path_claim_specs_to_json(claims: &[codex_state::PathClaimSpec]) -> Vec<Value> {
    claims
        .iter()
        .map(|claim| {
            json!({
                "kind": claim.kind.as_str(),
                "path": claim.path,
            })
        })
        .collect()
}

fn parse_duplicate_implementation_task_id(message: &str) -> Option<&str> {
    message
        .strip_prefix("duplicate coordination implementation task ")
        .and_then(|rest| rest.strip_suffix(" already covers this scope"))
}

fn coordination_duplicate_output(
    task: codex_state::CoordinationTask,
) -> Result<FunctionToolOutput, FunctionCallError> {
    let result = CoordinationActResult {
        task,
        act: None,
        unblocked_tasks: Vec::new(),
        ownership: None,
        room_notified: false,
        woken_threads: Vec::new(),
        deduped: true,
    };
    Ok(FunctionToolOutput::from_text(
        serde_json::to_string_pretty(&result)
            .map_err(|err| FunctionCallError::Fatal(err.to_string()))?,
        Some(true),
    ))
}

fn coordination_failure_output(
    message: String,
    task: Option<&codex_state::CoordinationTask>,
) -> Result<FunctionToolOutput, FunctionCallError> {
    let payload = match task {
        Some(task) => json!({
            "ok": false,
            "error": message,
            "task": task,
        }),
        None => json!({
            "ok": false,
            "error": message,
        }),
    };
    Ok(FunctionToolOutput::from_text(
        serde_json::to_string_pretty(&payload)
            .map_err(|err| FunctionCallError::Fatal(err.to_string()))?,
        Some(false),
    ))
}

fn map_coordination_transition_error(err: anyhow::Error) -> FunctionCallError {
    let message = err.to_string();
    if message.contains("is not claimable")
        || message.contains("is still blocked on dependencies")
        || message.contains("requires exact ownership claims")
        || message.contains("cannot become active because thread")
        || message.contains("cannot be completed from status")
        || message.contains("cannot be handed off from status")
        || message.contains("cannot be yielded from status")
    {
        FunctionCallError::RespondToModel(message)
    } else {
        FunctionCallError::Fatal(message)
    }
}

fn map_coordination_open_task_message(message: String) -> FunctionCallError {
    if message.contains("requires exact ownership claims")
        || message.contains("cannot be awarded because thread")
    {
        FunctionCallError::RespondToModel(message)
    } else {
        FunctionCallError::Fatal(message)
    }
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
    let wake_brief = format_coordination_wake_brief(task, reason);
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
            "<coordination_brief>\n",
            "{wake_brief}\n",
            "</coordination_brief>\n\n",
            "{summary}\n\n",
            "{details}\n\n",
            "Use the structured coordination brief above to choose the next concrete action."
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
        wake_brief = wake_brief,
        summary = task.summary,
        details = task.details,
    )
}

fn format_coordination_wake_brief(task: &codex_state::CoordinationTask, reason: &str) -> String {
    let mut lines = vec![
        format!("wake_reason: {reason}"),
        format!("status_now: {}", task.status.as_str()),
        format!("task_kind: {}", task.kind.as_str()),
    ];

    if let Some(room) = task.room.as_deref().filter(|room| !room.is_empty()) {
        lines.push(format!("room: {room}"));
    }
    if let Some(owner_thread_id) = task
        .owner_thread_id
        .as_deref()
        .filter(|owner| !owner.is_empty())
    {
        lines.push(format!("current_owner_thread_id: {owner_thread_id}"));
    }

    lines.push("facts:".to_string());
    lines.push(
        "- this wake came from durable coordination state, not ambient room chatter".to_string(),
    );
    match reason {
        "assigned" => {
            lines.push(
                "- the task is currently awarded to you and expects an ownership decision"
                    .to_string(),
            );
        }
        "unblocked" => {
            lines.push("- a dependency cleared and the task is actionable again".to_string());
        }
        other => {
            lines.push(format!(
                "- wake reason `{other}` came from the durable coordination scheduler"
            ));
        }
    }
    if !task.details.trim().is_empty() {
        lines.push(
            "- task details already contain the objective; answer that objective directly"
                .to_string(),
        );
    }

    lines.push("valid_next_moves:".to_string());
    lines.push("- if you are taking the task, call `coordination_act` `accept` once and keep ownership while you work".to_string());
    if matches!(task.kind, codex_state::CoordinationTaskKind::Implementation)
        && matches!(task.status, codex_state::CoordinationTaskStatus::Awarded)
    {
        lines.push(
            "- for direct implementation awards, reuse the exact reserved `claim_paths` listed in the task details when you call `accept`"
                .to_string(),
        );
    }
    if coordination_task_needs_room_read(task) {
        lines.push("- use `hollywood_read` instead of shell commands when the task asks about Hollywood visibility, wording, or message history".to_string());
        if let Some(room) = task.room.as_deref().filter(|room| !room.is_empty()) {
            lines.push(format!(
                "- exact verification target: inspect room `{room}` for a message mentioning task id `{}` and the awarded summary",
                task.id
            ));
        }
        lines.push("- preferred sequence: call `hollywood_read`, inspect the returned messages, then finish with `coordination_act` `done`".to_string());
        lines.push("- if the room message is absent, that absence is still a valid result; record it with `coordination_act` `done` instead of continuing to probe".to_string());
        lines.push(
            "- do not shell out to Hollywood HTTP endpoints or ad hoc scripts for this check"
                .to_string(),
        );
    }
    if coordination_task_is_verification(task) {
        lines.push("- for verification or QA tasks, gather the requested evidence, then call `coordination_act` `done` with the observed result".to_string());
    } else {
        lines.push("- when the requested work is complete, call `coordination_act` `done` with a concise concrete result summary".to_string());
    }
    lines.push("- do not call `accept` repeatedly just to restate ownership unless you intentionally yielded or the lease actually lapsed".to_string());
    lines.push("- only call `yield` or `handoff` if you are explicitly giving up the task, and include a concrete reason or target".to_string());
    lines.push(
        "- never use placeholder durable summaries like `placeholder`, `todo`, or `tbd`"
            .to_string(),
    );

    lines.join("\n")
}

fn with_reserved_scope_details(details: String, claim_paths: &[PathClaimArg]) -> String {
    if claim_paths.is_empty() {
        return details;
    }

    let scope_lines = claim_paths
        .iter()
        .map(|claim| format!("- {} `{}`", claim.kind, claim.path))
        .collect::<Vec<_>>()
        .join("\n");
    let scope_block = format!(
        "Reserved implementation scope:\n{scope_lines}\nWhen you accept this task, reuse the same `claim_paths`."
    );

    if details.trim().is_empty() {
        scope_block
    } else {
        format!("{details}\n\n{scope_block}")
    }
}

fn coordination_task_is_verification(task: &codex_state::CoordinationTask) -> bool {
    matches!(task.kind, codex_state::CoordinationTaskKind::Qa)
        || coordination_task_text_contains_any(
            task,
            &[
                "verify",
                "verification",
                "confirm",
                "check",
                "proof",
                "validate",
            ],
        )
}

fn coordination_task_needs_room_read(task: &codex_state::CoordinationTask) -> bool {
    task.room.as_deref().is_some_and(|room| !room.is_empty())
        && coordination_task_text_contains_any(
            task,
            &[
                "hollywood",
                "room",
                "message",
                "messages",
                "broadcast",
                "summary",
                "visible",
                "visibility",
                "wording",
            ],
        )
}

fn coordination_task_text_contains_any(
    task: &codex_state::CoordinationTask,
    needles: &[&str],
) -> bool {
    let haystack = format!(
        "{}\n{}",
        task.summary.to_ascii_lowercase(),
        task.details.to_ascii_lowercase()
    );
    needles.iter().any(|needle| haystack.contains(needle))
}

async fn send_coordination_room_summary(
    session: &Arc<Session>,
    turn: &Arc<TurnContext>,
    db: &Arc<codex_state::StateRuntime>,
    outcome: &codex_state::CoordinationTaskTransitionOutcome,
) -> bool {
    let Ok(Some(config)) = hollywood_config_for_session(session, db).await else {
        return false;
    };
    let room = outcome
        .task
        .room
        .clone()
        .unwrap_or_else(|| config.room.clone());
    let body = coordination_room_summary(session.conversation_id, outcome);
    let url = format!("{}/hollywood/v1/messages", config.url.trim_end_matches('/'));
    let client = Client::new();

    for _attempt in 0..2 {
        let sent = client
            .post(&url)
            .json(&json!({
                "room": room,
                "sender_id": session.conversation_id.to_string(),
                "message_kind": "broadcast",
                "response_policy": "none",
                "body": body,
            }))
            .send()
            .await
            .ok()
            .and_then(|response| response.error_for_status().ok())
            .is_some();
        if sent {
            session
                .mark_hollywood_send_for_turn(&turn.sub_id, &room)
                .await;
            return true;
        }
        tokio::time::sleep(std::time::Duration::from_millis(100)).await;
    }

    false
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
