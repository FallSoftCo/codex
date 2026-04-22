use crate::function_tool::FunctionCallError;
use crate::tools::context::FunctionToolOutput;
use crate::tools::context::ToolInvocation;
use crate::tools::context::ToolPayload;
use crate::tools::handlers::multi_agents::parse_agent_id_target;
use crate::tools::handlers::parse_arguments;
use crate::tools::registry::ToolHandler;
use crate::tools::registry::ToolKind;
use codex_protocol::ThreadId;
use codex_protocol::protocol::AgentStatus;
use serde::Deserialize;
use serde::Serialize;
use std::sync::Arc;

pub struct WatcherHandler;

#[derive(Debug, Deserialize)]
struct WatchProcessExitArgs {
    session_id: i32,
    title: String,
    prompt: String,
    timeout_seconds: Option<u64>,
    thread_id: Option<String>,
    #[serde(default = "default_requires_response")]
    requires_response: bool,
}

#[derive(Debug, Deserialize)]
struct WatchAgentCompletionArgs {
    target: String,
    title: String,
    prompt: String,
    condition: Option<String>,
    timeout_seconds: Option<u64>,
    thread_id: Option<String>,
    #[serde(default = "default_requires_response")]
    requires_response: bool,
}

#[derive(Debug, Deserialize)]
struct WatchTaskPeriodicallyArgs {
    title: String,
    objective: String,
    prompt: String,
    check_every_seconds: u64,
    initial_delay_seconds: Option<u64>,
    thread_id: Option<String>,
    max_checks: Option<u32>,
    #[serde(default = "default_requires_response")]
    requires_response: bool,
}

#[derive(Debug, Deserialize)]
struct ListTaskWatchesArgs {
    thread_id: Option<String>,
}

#[derive(Debug, Deserialize)]
struct UpdateTaskWatchArgs {
    task_watch_id: String,
    action: String,
    check_every_seconds: Option<u64>,
    delay_seconds: Option<u64>,
    max_checks: Option<u32>,
    decision: Option<String>,
    observation: Option<String>,
}

#[derive(Debug, Deserialize)]
struct CancelTaskWatchArgs {
    task_watch_id: String,
}

#[derive(Debug, Deserialize)]
struct ListWatchersArgs {
    thread_id: Option<String>,
}

#[derive(Debug, Deserialize)]
struct CancelWatcherArgs {
    watcher_id: String,
}

#[derive(Debug, Serialize)]
struct WatcherRegistrationResult {
    watcher_id: String,
    thread_id: String,
    status: String,
    summary: String,
}

#[derive(Debug, Serialize)]
struct CancelWatcherResult {
    accepted: bool,
}

#[derive(Debug, Serialize)]
struct TaskWatchRegistrationResult {
    task_watch_id: String,
    thread_id: String,
    status: String,
    summary: String,
}

fn default_requires_response() -> bool {
    true
}

impl ToolHandler for WatcherHandler {
    type Output = FunctionToolOutput;

    fn kind(&self) -> ToolKind {
        ToolKind::Function
    }

    fn matches_kind(&self, payload: &ToolPayload) -> bool {
        matches!(payload, ToolPayload::Function { .. })
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
                "watcher handler received unsupported payload".to_string(),
            ));
        };

        let db = required_state_db(&session)?;
        match tool_name.name.as_str() {
            "watch_process_exit" => {
                let args: WatchProcessExitArgs = parse_arguments(&arguments)?;
                let thread_id = resolve_thread_id(args.thread_id.as_deref(), &session)?;
                let timeout_at = args
                    .timeout_seconds
                    .map(timeout_at_from_seconds)
                    .transpose()?;
                let watcher_id = uuid::Uuid::new_v4().to_string();
                db.create_watcher(codex_state::WatcherCreateParams {
                    id: watcher_id.clone(),
                    thread_id: thread_id.to_string(),
                    title: args.title.clone(),
                    prompt: args.prompt,
                    trigger_kind: codex_state::WatcherTriggerKind::ProcessExit,
                    process_id: Some(args.session_id),
                    target_thread_id: None,
                    agent_completion_condition: None,
                    timeout_at,
                    requires_response: args.requires_response,
                })
                .await
                .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
                let result = WatcherRegistrationResult {
                    watcher_id: watcher_id.clone(),
                    thread_id: thread_id.to_string(),
                    status: "armed".to_string(),
                    summary: format!(
                        "Watching exec_command session {} for exit; the thread will wake when it completes.",
                        args.session_id
                    ),
                };
                let text = serde_json::to_string_pretty(&result)
                    .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
                Ok(FunctionToolOutput::from_text(text, Some(true)))
            }
            "watch_agent_completion" => {
                let args: WatchAgentCompletionArgs = parse_arguments(&arguments)?;
                let thread_id = resolve_thread_id(args.thread_id.as_deref(), &session)?;
                let target_thread_id = parse_agent_id_target(&args.target)?;
                let target_status = session
                    .services
                    .agent_control
                    .get_status(target_thread_id)
                    .await;
                if matches!(target_status, AgentStatus::NotFound) {
                    return Err(FunctionCallError::RespondToModel(format!(
                        "target agent {target_thread_id} was not found"
                    )));
                }
                let timeout_at = args
                    .timeout_seconds
                    .map(timeout_at_from_seconds)
                    .transpose()?;
                let condition = args
                    .condition
                    .as_deref()
                    .map(codex_state::WatcherAgentCompletionCondition::parse)
                    .transpose()
                    .map_err(|err| FunctionCallError::RespondToModel(err.to_string()))?
                    .unwrap_or(codex_state::WatcherAgentCompletionCondition::Final);
                let watcher_id = uuid::Uuid::new_v4().to_string();
                db.create_watcher(codex_state::WatcherCreateParams {
                    id: watcher_id.clone(),
                    thread_id: thread_id.to_string(),
                    title: args.title,
                    prompt: args.prompt,
                    trigger_kind: codex_state::WatcherTriggerKind::AgentCompletion,
                    process_id: None,
                    target_thread_id: Some(target_thread_id.to_string()),
                    agent_completion_condition: Some(condition),
                    timeout_at,
                    requires_response: args.requires_response,
                })
                .await
                .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
                let result = WatcherRegistrationResult {
                    watcher_id: watcher_id.clone(),
                    thread_id: thread_id.to_string(),
                    status: "armed".to_string(),
                    summary: format!(
                        "Watching agent {} for `{}` completion; the thread will wake when the condition is satisfied.",
                        target_thread_id,
                        condition.as_str()
                    ),
                };
                let text = serde_json::to_string_pretty(&result)
                    .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
                Ok(FunctionToolOutput::from_text(text, Some(true)))
            }
            "list_watchers" => {
                let args: ListWatchersArgs = parse_arguments(&arguments)?;
                let thread_id = args
                    .thread_id
                    .as_deref()
                    .map(|value| resolve_thread_id(Some(value), &session))
                    .transpose()?;
                let watchers = db
                    .list_watchers(thread_id)
                    .await
                    .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
                let text = serde_json::to_string_pretty(&watchers)
                    .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
                Ok(FunctionToolOutput::from_text(text, Some(true)))
            }
            "cancel_watcher" => {
                let args: CancelWatcherArgs = parse_arguments(&arguments)?;
                let accepted = db
                    .cancel_watcher(args.watcher_id.as_str())
                    .await
                    .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
                let text = serde_json::to_string_pretty(&CancelWatcherResult { accepted })
                    .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
                Ok(FunctionToolOutput::from_text(text, Some(true)))
            }
            "watch_task_periodically" => {
                let args: WatchTaskPeriodicallyArgs = parse_arguments(&arguments)?;
                let thread_id = resolve_thread_id(args.thread_id.as_deref(), &session)?;
                let now = chrono::Utc::now();
                let cadence_seconds = i64::try_from(args.check_every_seconds)
                    .map_err(|err| FunctionCallError::RespondToModel(err.to_string()))?;
                let initial_delay_seconds = args
                    .initial_delay_seconds
                    .unwrap_or(args.check_every_seconds);
                let next_check_at = checked_offset_from_now(now, initial_delay_seconds)?;
                let task_watch_id = uuid::Uuid::new_v4().to_string();
                db.create_task_watch(codex_state::TaskWatchCreateParams {
                    id: task_watch_id.clone(),
                    thread_id: thread_id.to_string(),
                    title: args.title.clone(),
                    objective: args.objective,
                    prompt: args.prompt,
                    cadence_seconds,
                    next_check_at,
                    max_checks: args.max_checks.map(i64::from),
                    requires_response: args.requires_response,
                })
                .await
                .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
                let result = TaskWatchRegistrationResult {
                    task_watch_id: task_watch_id.clone(),
                    thread_id: thread_id.to_string(),
                    status: codex_state::TaskWatchStatus::Active.as_str().to_string(),
                    summary: format!(
                        "Watching task `{}` every {cadence_seconds}s; the thread will wake periodically to reevaluate it.",
                        args.title
                    ),
                };
                let text = serde_json::to_string_pretty(&result)
                    .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
                Ok(FunctionToolOutput::from_text(text, Some(true)))
            }
            "list_task_watches" => {
                let args: ListTaskWatchesArgs = parse_arguments(&arguments)?;
                let thread_id = args
                    .thread_id
                    .as_deref()
                    .map(|value| resolve_thread_id(Some(value), &session))
                    .transpose()?;
                let task_watches = db
                    .list_task_watches(thread_id)
                    .await
                    .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
                let text = serde_json::to_string_pretty(&task_watches)
                    .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
                Ok(FunctionToolOutput::from_text(text, Some(true)))
            }
            "update_task_watch" => {
                let args: UpdateTaskWatchArgs = parse_arguments(&arguments)?;
                let action = parse_task_watch_action(args.action.as_str())?;
                let now = chrono::Utc::now();
                let next_check_at = args
                    .delay_seconds
                    .map(|seconds| checked_offset_from_now(now, seconds))
                    .transpose()?;
                let cadence_seconds = args
                    .check_every_seconds
                    .map(i64::try_from)
                    .transpose()
                    .map_err(|err| FunctionCallError::RespondToModel(err.to_string()))?;
                let status = match action {
                    TaskWatchAction::Continue
                    | TaskWatchAction::Backoff
                    | TaskWatchAction::Snooze => None,
                    TaskWatchAction::Complete => Some(codex_state::TaskWatchStatus::Completed),
                    TaskWatchAction::Stop => Some(codex_state::TaskWatchStatus::Stopped),
                };
                let accepted = db
                    .update_task_watch(codex_state::TaskWatchUpdateParams {
                        id: args.task_watch_id.clone(),
                        cadence_seconds,
                        next_check_at,
                        max_checks: args.max_checks.map(i64::from),
                        last_decision: Some(
                            args.decision.unwrap_or_else(|| action.as_str().to_string()),
                        ),
                        last_observation: args.observation,
                        status,
                    })
                    .await
                    .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
                let text = serde_json::to_string_pretty(&CancelWatcherResult { accepted })
                    .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
                Ok(FunctionToolOutput::from_text(text, Some(true)))
            }
            "cancel_task_watch" => {
                let args: CancelTaskWatchArgs = parse_arguments(&arguments)?;
                let accepted = db
                    .cancel_task_watch(
                        args.task_watch_id.as_str(),
                        codex_state::TaskWatchStatus::Stopped,
                    )
                    .await
                    .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
                let text = serde_json::to_string_pretty(&CancelWatcherResult { accepted })
                    .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
                Ok(FunctionToolOutput::from_text(text, Some(true)))
            }
            other => Err(FunctionCallError::RespondToModel(format!(
                "unsupported watcher tool {other}"
            ))),
        }
    }
}

fn required_state_db(
    session: &Arc<crate::session::session::Session>,
) -> Result<Arc<codex_state::StateRuntime>, FunctionCallError> {
    session.state_db().ok_or_else(|| {
        FunctionCallError::RespondToModel(
            "watch tools are unavailable for this session because the sqlite state db could not be initialized".to_string(),
        )
    })
}

fn resolve_thread_id(
    thread_id: Option<&str>,
    session: &Arc<crate::session::session::Session>,
) -> Result<ThreadId, FunctionCallError> {
    match thread_id {
        Some(thread_id) => ThreadId::from_string(thread_id)
            .map_err(|err| FunctionCallError::RespondToModel(err.to_string())),
        None => Ok(session.conversation_id),
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum TaskWatchAction {
    Continue,
    Backoff,
    Snooze,
    Complete,
    Stop,
}

impl TaskWatchAction {
    const fn as_str(self) -> &'static str {
        match self {
            Self::Continue => "continue",
            Self::Backoff => "backoff",
            Self::Snooze => "snooze",
            Self::Complete => "complete",
            Self::Stop => "stop",
        }
    }
}

fn parse_task_watch_action(value: &str) -> Result<TaskWatchAction, FunctionCallError> {
    match value {
        "continue" => Ok(TaskWatchAction::Continue),
        "backoff" => Ok(TaskWatchAction::Backoff),
        "snooze" => Ok(TaskWatchAction::Snooze),
        "complete" => Ok(TaskWatchAction::Complete),
        "stop" => Ok(TaskWatchAction::Stop),
        _ => Err(FunctionCallError::RespondToModel(format!(
            "invalid task watch action `{value}`; expected continue, backoff, snooze, complete, or stop"
        ))),
    }
}

fn timeout_at_from_seconds(
    seconds: u64,
) -> Result<chrono::DateTime<chrono::Utc>, FunctionCallError> {
    checked_offset_from_now(chrono::Utc::now(), seconds)
}

fn checked_offset_from_now(
    now: chrono::DateTime<chrono::Utc>,
    seconds: u64,
) -> Result<chrono::DateTime<chrono::Utc>, FunctionCallError> {
    let duration = chrono::Duration::from_std(std::time::Duration::from_secs(seconds))
        .map_err(|err| FunctionCallError::RespondToModel(err.to_string()))?;
    Ok(now + duration)
}
