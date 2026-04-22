use super::*;
use crate::session::tests::make_session_and_context;
use crate::session::turn_context::TurnContext;
use crate::tools::context::ToolInvocation;
use crate::tools::context::ToolPayload;
use crate::tools::registry::ToolHandler;
use crate::turn_diff_tracker::TurnDiffTracker;
use chrono::Utc;
use codex_protocol::ThreadId;
use codex_protocol::protocol::SessionSource;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use std::sync::Arc;
use tokio::sync::Mutex;

fn invocation(
    session: Arc<Session>,
    turn: Arc<TurnContext>,
    tool_name: &str,
    arguments: Value,
) -> ToolInvocation {
    ToolInvocation {
        session,
        turn,
        cancellation_token: tokio_util::sync::CancellationToken::new(),
        tracker: Arc::new(Mutex::new(TurnDiffTracker::default())),
        call_id: "call-1".to_string(),
        tool_name: codex_tools::ToolName::plain(tool_name),
        payload: ToolPayload::Function {
            arguments: arguments.to_string(),
        },
    }
}

async fn make_session_with_state_db() -> (
    Arc<Session>,
    Arc<TurnContext>,
    Arc<codex_state::StateRuntime>,
) {
    let (mut session, turn) = make_session_and_context().await;
    let state_db = codex_rollout::state_db::init(turn.config.as_ref())
        .await
        .expect("sqlite state db should be available for coordination tests");
    session.services.state_db = Some(Arc::clone(&state_db));
    let metadata = codex_state::ThreadMetadataBuilder::new(
        session.conversation_id,
        turn.config
            .codex_home
            .as_path()
            .join(format!("{}.jsonl", session.conversation_id)),
        Utc::now(),
        SessionSource::Exec,
    )
    .build(turn.config.model_provider_id.as_str());
    state_db
        .upsert_thread(&metadata)
        .await
        .expect("session thread metadata should be persisted");
    (Arc::new(session), Arc::new(turn), state_db)
}

fn parse_result(output: FunctionToolOutput) -> Value {
    serde_json::from_str(&output.into_text()).expect("coordination handler should return json")
}

async fn insert_thread_metadata(
    state_db: &Arc<codex_state::StateRuntime>,
    turn: &TurnContext,
    thread_id: ThreadId,
) {
    let metadata = codex_state::ThreadMetadataBuilder::new(
        thread_id,
        turn.config
            .codex_home
            .as_path()
            .join(format!("{thread_id}.jsonl")),
        Utc::now(),
        SessionSource::Exec,
    )
    .build(turn.config.model_provider_id.as_str());
    state_db
        .upsert_thread(&metadata)
        .await
        .expect("thread metadata should be persisted");
}

#[tokio::test]
async fn open_task_for_peer_persists_assigned_wake() {
    let (session, turn, state_db) = make_session_with_state_db().await;
    let owner_thread_id = ThreadId::new();
    let owner_thread_id_str = owner_thread_id.to_string();
    insert_thread_metadata(&state_db, turn.as_ref(), owner_thread_id).await;

    let output = CoordinationHandler
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Review patch",
                "details": "Inspect the new patch and report regressions.",
                "kind": "review",
                "owner": owner_thread_id_str,
                "notify_room": false,
            }),
        ))
        .await
        .expect("open_task should succeed");

    let result = parse_result(output);
    assert_eq!(result["task"]["status"], "awarded");
    assert_eq!(
        result["woken_threads"],
        json!([owner_thread_id.to_string()])
    );

    let scheduled_tasks = state_db
        .list_scheduled_tasks(Some(owner_thread_id))
        .await
        .expect("scheduled task query should succeed");
    assert_eq!(scheduled_tasks.len(), 1);
    assert_eq!(
        scheduled_tasks[0].title,
        "coordination:assigned:Review patch"
    );
    assert!(scheduled_tasks[0].prompt.contains("reason: assigned"));
    assert!(scheduled_tasks[0].prompt.contains("Review patch"));
    assert!(
        scheduled_tasks[0]
            .prompt
            .contains("Inspect the new patch and report regressions.")
    );
}

#[tokio::test]
async fn done_unblocks_awarded_dependency_and_persists_wake() {
    let (session, turn, state_db) = make_session_with_state_db().await;
    let owner_thread_id = ThreadId::new();
    let owner_thread_id_str = owner_thread_id.to_string();
    insert_thread_metadata(&state_db, turn.as_ref(), owner_thread_id).await;

    let dependency_output = CoordinationHandler
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Land protocol changes",
                "details": "Update the API shape first.",
                "kind": "implementation",
                "notify_room": false,
            }),
        ))
        .await
        .expect("dependency open_task should succeed");
    let dependency_result = parse_result(dependency_output);
    let dependency_task_id = dependency_result["task"]["id"]
        .as_str()
        .expect("dependency task id should exist")
        .to_string();

    let blocked_output = CoordinationHandler
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Adapt TUI",
                "details": "Follow the protocol once it lands.",
                "kind": "implementation",
                "owner": owner_thread_id_str,
                "depends_on": [dependency_task_id.clone()],
                "notify_room": false,
            }),
        ))
        .await
        .expect("blocked open_task should succeed");
    let blocked_result = parse_result(blocked_output);
    assert_eq!(blocked_result["task"]["status"], "blocked");
    assert_eq!(blocked_result["woken_threads"], json!([]));
    assert_eq!(
        state_db
            .list_scheduled_tasks(Some(owner_thread_id))
            .await
            .expect("scheduled task query should succeed")
            .len(),
        0
    );

    let done_output = CoordinationHandler
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "done",
                "task_id": dependency_task_id,
                "summary": "Protocol landed",
                "notify_room": false,
            }),
        ))
        .await
        .expect("done should succeed");
    let done_result = parse_result(done_output);
    assert_eq!(
        done_result["woken_threads"],
        json!([owner_thread_id.to_string()])
    );
    assert_eq!(
        done_result["unblocked_tasks"].as_array().map(Vec::len),
        Some(1)
    );
    assert_eq!(done_result["unblocked_tasks"][0]["status"], "awarded");

    let scheduled_tasks = state_db
        .list_scheduled_tasks(Some(owner_thread_id))
        .await
        .expect("scheduled task query should succeed");
    assert_eq!(scheduled_tasks.len(), 1);
    assert_eq!(scheduled_tasks[0].title, "coordination:unblocked:Adapt TUI");
    assert!(scheduled_tasks[0].prompt.contains("reason: unblocked"));
    assert!(scheduled_tasks[0].prompt.contains("Adapt TUI"));
}
