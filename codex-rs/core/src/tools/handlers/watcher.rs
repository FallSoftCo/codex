use crate::function_tool::FunctionCallError;
use crate::tools::context::FunctionToolOutput;
use crate::tools::context::ToolInvocation;
use crate::tools::context::ToolPayload;
use crate::tools::handlers::parse_arguments;
use crate::tools::registry::ToolHandler;
use crate::tools::registry::ToolKind;
use codex_protocol::ThreadId;
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
struct ListWatchersArgs {
    thread_id: Option<String>,
}

#[derive(Debug, Deserialize)]
struct CancelWatcherArgs {
    watcher_id: String,
}

#[derive(Debug, Serialize)]
struct WatchProcessExitResult {
    watcher_id: String,
    thread_id: String,
    status: String,
    summary: String,
}

#[derive(Debug, Serialize)]
struct CancelWatcherResult {
    accepted: bool,
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
        match tool_name.as_str() {
            "watch_process_exit" => {
                let args: WatchProcessExitArgs = parse_arguments(&arguments)?;
                let thread_id = resolve_thread_id(args.thread_id.as_deref(), &session)?;
                let timeout_at = args.timeout_seconds.map(|seconds| {
                    chrono::Utc::now()
                        + chrono::Duration::from_std(std::time::Duration::from_secs(seconds))
                            .expect("timeout conversion")
                });
                let watcher_id = uuid::Uuid::new_v4().to_string();
                db.create_watcher(codex_state::WatcherCreateParams {
                    id: watcher_id.clone(),
                    thread_id: thread_id.to_string(),
                    title: args.title.clone(),
                    prompt: args.prompt,
                    trigger_kind: codex_state::WatcherTriggerKind::ProcessExit,
                    process_id: Some(args.session_id),
                    timeout_at,
                    requires_response: args.requires_response,
                })
                .await
                .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
                let result = WatchProcessExitResult {
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
            other => Err(FunctionCallError::RespondToModel(format!(
                "unsupported watcher tool {other}"
            ))),
        }
    }
}

fn required_state_db(
    session: &Arc<crate::codex::Session>,
) -> Result<Arc<codex_state::StateRuntime>, FunctionCallError> {
    session.state_db().ok_or_else(|| {
        FunctionCallError::Fatal("sqlite state db is unavailable for this session".to_string())
    })
}

fn resolve_thread_id(
    thread_id: Option<&str>,
    session: &Arc<crate::codex::Session>,
) -> Result<ThreadId, FunctionCallError> {
    match thread_id {
        Some(thread_id) => ThreadId::from_string(thread_id)
            .map_err(|err| FunctionCallError::RespondToModel(err.to_string())),
        None => Ok(session.conversation_id.clone()),
    }
}
