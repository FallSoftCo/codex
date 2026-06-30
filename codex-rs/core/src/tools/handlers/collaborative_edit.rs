use crate::function_tool::FunctionCallError;
use crate::session::session::Session;
use crate::session::turn_context::TurnContext;
use crate::tools::context::FunctionToolOutput;
use crate::tools::context::ToolInvocation;
use crate::tools::context::ToolPayload;
use crate::tools::context::boxed_tool_output;
use crate::tools::handlers::parse_arguments;
use crate::tools::losangelex_spec::create_collaborative_edit_plan_tool;
use crate::tools::registry::ToolExecutor;
use codex_tools::ToolName;
use codex_tools::ToolSpec;
use reqwest::Client;
use serde::Deserialize;
use serde::Serialize;
use serde_json::json;
use std::path::PathBuf;
use std::sync::Arc;

pub struct CollaborativeEditPlanHandler;

const MAX_EDIT_SLICE_CHARS: usize = 400;
const MAX_EDIT_INTENT_CHARS: usize = 4_000;
const MAX_EDIT_OPTIONAL_FIELD_CHARS: usize = 1_000;
const MAX_EDIT_PEERS: usize = 12;

#[derive(Debug, Deserialize)]
struct CollaborativeEditPlanArgs {
    file: String,
    slice: String,
    intent: String,
    peers: Option<Vec<String>>,
    handoff: Option<String>,
    integrator: Option<String>,
    report_back: Option<String>,
    room: Option<String>,
    #[serde(default = "default_notify_room")]
    notify_room: bool,
    lease_seconds: Option<i64>,
}

#[derive(Debug, Serialize)]
struct CollaborativeEditPlanResult {
    plan: codex_state::CollaborativeEditPlan,
    room_notified: bool,
    room_notify_error: Option<String>,
    ok: bool,
}

fn default_notify_room() -> bool {
    true
}

impl ToolExecutor<ToolInvocation> for CollaborativeEditPlanHandler {
    fn tool_name(&self) -> ToolName {
        ToolName::new(None, "collaborative_edit_plan".to_string())
    }

    fn spec(&self) -> ToolSpec {
        create_collaborative_edit_plan_tool()
    }

    fn handle(&self, invocation: ToolInvocation) -> codex_tools::ToolExecutorFuture<'_> {
        Box::pin(async move {
            let output = async {
                let ToolInvocation {
                    session,
                    turn,
                    payload,
                    ..
                } = invocation;
                let ToolPayload::Function { arguments } = payload else {
                    return Err(FunctionCallError::RespondToModel(
                        "collaborative_edit_plan received unsupported payload".to_string(),
                    ));
                };
                let args: CollaborativeEditPlanArgs = parse_arguments(&arguments)?;
                handle_collaborative_edit_plan(&session, &turn, args).await
            }
            .await?;
            Ok(boxed_tool_output(output))
        })
    }
}

async fn handle_collaborative_edit_plan(
    session: &Arc<Session>,
    turn: &Arc<TurnContext>,
    args: CollaborativeEditPlanArgs,
) -> Result<FunctionToolOutput, FunctionCallError> {
    validate_args(&args)?;
    let db = session.state_db().ok_or_else(|| {
        FunctionCallError::RespondToModel(
            "collaborative edit plans are unavailable because the sqlite state db could not be initialized"
                .to_string(),
        )
    })?;
    let file_path = resolve_file_path(turn.as_ref(), args.file.as_str());
    let room = if args.room.is_some() {
        args.room.clone()
    } else {
        session
            .hollywood_session_config()
            .await
            .map(|config| config.room)
    };
    let plan = db
        .record_collaborative_edit_plan(codex_state::CollaborativeEditPlanCreateParams {
            id: uuid::Uuid::new_v4().to_string(),
            actor_thread_id: session.thread_id(),
            room: room.clone(),
            file_path,
            edit_slice: args.slice.trim().to_string(),
            intent: args.intent.trim().to_string(),
            peers: args.peers.clone().unwrap_or_default(),
            handoff: trim_optional(args.handoff.as_deref()),
            integrator: trim_optional(args.integrator.as_deref()),
            report_back: trim_optional(args.report_back.as_deref()),
            lease_seconds: args
                .lease_seconds
                .unwrap_or(codex_state::DEFAULT_COLLABORATIVE_EDIT_PLAN_LEASE_SECONDS),
        })
        .await
        .map_err(|err| FunctionCallError::RespondToModel(err.to_string()))?;

    let (room_notified, room_notify_error) = if args.notify_room {
        notify_hollywood(session, turn, &plan).await
    } else {
        (false, None)
    };
    let result = CollaborativeEditPlanResult {
        plan,
        room_notified,
        room_notify_error,
        ok: true,
    };
    Ok(FunctionToolOutput::from_text(
        serde_json::to_string_pretty(&result)
            .map_err(|err| FunctionCallError::Fatal(err.to_string()))?,
        Some(true),
    ))
}

fn resolve_file_path(turn: &TurnContext, file: &str) -> PathBuf {
    let path = PathBuf::from(file);
    if path.is_absolute() {
        return path;
    }
    turn.environments
        .single_local_environment_cwd()
        .unwrap_or_else(|| turn.config.cwd.clone())
        .join(path)
        .into_path_buf()
}

fn validate_args(args: &CollaborativeEditPlanArgs) -> Result<(), FunctionCallError> {
    validate_non_empty("file", args.file.as_str())?;
    validate_non_empty("slice", args.slice.as_str())?;
    validate_non_empty("intent", args.intent.as_str())?;
    validate_len("slice", args.slice.as_str(), MAX_EDIT_SLICE_CHARS)?;
    validate_len("intent", args.intent.as_str(), MAX_EDIT_INTENT_CHARS)?;
    if let Some(peers) = args.peers.as_ref()
        && peers.len() > MAX_EDIT_PEERS
    {
        return Err(FunctionCallError::RespondToModel(format!(
            "collaborative_edit_plan accepts at most {MAX_EDIT_PEERS} peers"
        )));
    }
    for (name, value) in [
        ("handoff", args.handoff.as_deref()),
        ("integrator", args.integrator.as_deref()),
        ("report_back", args.report_back.as_deref()),
    ] {
        if let Some(value) = value {
            validate_len(name, value, MAX_EDIT_OPTIONAL_FIELD_CHARS)?;
        }
    }
    Ok(())
}

fn validate_non_empty(name: &str, value: &str) -> Result<(), FunctionCallError> {
    if value.trim().is_empty() {
        return Err(FunctionCallError::RespondToModel(format!(
            "collaborative_edit_plan requires non-empty `{name}`"
        )));
    }
    Ok(())
}

fn validate_len(name: &str, value: &str, max: usize) -> Result<(), FunctionCallError> {
    if value.chars().count() > max {
        return Err(FunctionCallError::RespondToModel(format!(
            "collaborative_edit_plan `{name}` must be at most {max} characters"
        )));
    }
    Ok(())
}

fn trim_optional(value: Option<&str>) -> Option<String> {
    value
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToString::to_string)
}

async fn notify_hollywood(
    session: &Arc<Session>,
    turn: &Arc<TurnContext>,
    plan: &codex_state::CollaborativeEditPlan,
) -> (bool, Option<String>) {
    let Some(config) = session.hollywood_session_config().await else {
        return (false, None);
    };
    let room = plan.room.clone().unwrap_or(config.room.clone());
    let url = format!("{}/hollywood/v1/messages", config.url.trim_end_matches('/'));
    let body = format_collaborative_edit_plan_message(plan);
    let result = Client::new()
        .post(url)
        .json(&json!({
            "room": room,
            "sender_id": session.thread_id().to_string(),
            "recipient_id": serde_json::Value::Null,
            "message_kind": "ambient",
            "response_policy": "optional",
            "body": body,
        }))
        .send()
        .await
        .and_then(reqwest::Response::error_for_status);

    match result {
        Ok(_) => {
            session
                .mark_hollywood_send_for_turn(&turn.sub_id, room.as_str())
                .await;
            (true, None)
        }
        Err(err) => (false, Some(format!("Hollywood send failed: {err}"))),
    }
}

fn format_collaborative_edit_plan_message(plan: &codex_state::CollaborativeEditPlan) -> String {
    let peers = if plan.peers.is_empty() {
        "none named".to_string()
    } else {
        plan.peers.join(", ")
    };
    format!(
        "Collaborative edit plan: file `{}`; slice `{}`; intended hunk `{}`; peers `{}`; handoff `{}`; integrator `{}`; report-back `{}`.",
        plan.file_path.display(),
        plan.edit_slice,
        plan.intent,
        peers,
        plan.handoff.as_deref().unwrap_or("unspecified"),
        plan.integrator.as_deref().unwrap_or("unspecified"),
        plan.report_back.as_deref().unwrap_or("after patch"),
    )
}

#[cfg(test)]
#[path = "collaborative_edit_tests.rs"]
mod tests;
