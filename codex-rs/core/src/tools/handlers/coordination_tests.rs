use super::*;
use crate::session::tests::make_session_and_context;
use crate::session::turn_context::TurnContext;
use crate::tools::context::ToolCallSource;
use crate::tools::context::ToolInvocation;
use crate::tools::context::ToolOutput;
use crate::tools::context::ToolPayload;
use crate::turn_diff_tracker::TurnDiffTracker;
use chrono::Utc;
use codex_protocol::ThreadId;
use codex_protocol::models::ResponseInputItem;
use codex_protocol::protocol::HollywoodInputMessage;
use codex_protocol::protocol::SessionSource;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use std::sync::Arc;
use tokio::sync::Mutex;
use wiremock::Mock;
use wiremock::MockServer;
use wiremock::ResponseTemplate;
use wiremock::matchers::method;
use wiremock::matchers::path;

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
        source: ToolCallSource::Direct,
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
    let mut metadata = codex_state::ThreadMetadataBuilder::new(
        session.thread_id(),
        turn.config
            .codex_home
            .as_path()
            .join(format!("{}.jsonl", session.thread_id())),
        Utc::now(),
        SessionSource::Exec,
    )
    .build(turn.config.model_provider_id.as_str());
    metadata.cwd = turn.config.cwd.to_path_buf();
    state_db
        .upsert_thread(&metadata)
        .await
        .expect("session thread metadata should be persisted");
    (Arc::new(session), Arc::new(turn), state_db)
}

fn function_output_payload(
    output: &dyn ToolOutput,
) -> codex_protocol::models::FunctionCallOutputPayload {
    let payload = ToolPayload::Function {
        arguments: "{}".to_string(),
    };
    let ResponseInputItem::FunctionCallOutput { output, .. } =
        output.to_response_item("call-1", &payload)
    else {
        panic!("coordination handler should return function output");
    };
    output
}

fn output_success(output: &dyn ToolOutput) -> Option<bool> {
    function_output_payload(output).success
}

fn parse_result(output: Box<dyn ToolOutput>) -> Value {
    let output = function_output_payload(output.as_ref());
    let text = output
        .body
        .to_text()
        .expect("coordination handler output should be text");
    serde_json::from_str(&text).expect("coordination handler should return json")
}

fn coordination_handler() -> CoordinationHandler {
    CoordinationHandler::new("coordination_act")
}

async fn insert_thread_metadata(
    state_db: &Arc<codex_state::StateRuntime>,
    turn: &TurnContext,
    thread_id: ThreadId,
) {
    let mut metadata = codex_state::ThreadMetadataBuilder::new(
        thread_id,
        turn.config
            .codex_home
            .as_path()
            .join(format!("{thread_id}.jsonl")),
        Utc::now(),
        SessionSource::Exec,
    )
    .build(turn.config.model_provider_id.as_str());
    metadata.cwd = turn.config.cwd.to_path_buf();
    state_db
        .upsert_thread(&metadata)
        .await
        .expect("thread metadata should be persisted");
}

async fn insert_named_thread_metadata(
    state_db: &Arc<codex_state::StateRuntime>,
    turn: &TurnContext,
    thread_id: ThreadId,
    title: &str,
) {
    let mut metadata = codex_state::ThreadMetadataBuilder::new(
        thread_id,
        turn.config
            .codex_home
            .as_path()
            .join(format!("{thread_id}.jsonl")),
        Utc::now(),
        SessionSource::Exec,
    )
    .build(turn.config.model_provider_id.as_str());
    metadata.cwd = turn.config.cwd.to_path_buf();
    metadata.title = title.to_string();
    metadata.first_user_message = Some(format!("named thread {title}"));
    state_db
        .upsert_thread(&metadata)
        .await
        .expect("named thread metadata should be persisted");
}

async fn insert_fresh_named_thread_metadata_without_history(
    state_db: &Arc<codex_state::StateRuntime>,
    turn: &TurnContext,
    thread_id: ThreadId,
    title: &str,
) {
    let mut metadata = codex_state::ThreadMetadataBuilder::new(
        thread_id,
        turn.config
            .codex_home
            .as_path()
            .join(format!("{thread_id}.jsonl")),
        Utc::now(),
        SessionSource::Exec,
    )
    .build(turn.config.model_provider_id.as_str());
    metadata.cwd = turn.config.cwd.to_path_buf();
    metadata.title = title.to_string();
    metadata.first_user_message = None;
    state_db
        .upsert_thread(&metadata)
        .await
        .expect("fresh named thread metadata should be persisted");
}

async fn rename_thread_metadata(
    state_db: &Arc<codex_state::StateRuntime>,
    thread_id: ThreadId,
    title: &str,
) {
    let mut metadata = state_db
        .get_thread(thread_id)
        .await
        .expect("thread lookup should succeed")
        .expect("thread metadata should exist");
    metadata.title = title.to_string();
    state_db
        .upsert_thread(&metadata)
        .await
        .expect("renamed thread metadata should be persisted");
}

#[tokio::test]
async fn open_task_for_peer_persists_assigned_wake() {
    let (session, turn, state_db) = make_session_with_state_db().await;
    let owner_thread_id = ThreadId::new();
    let owner_thread_id_str = owner_thread_id.to_string();
    insert_thread_metadata(&state_db, turn.as_ref(), owner_thread_id).await;

    let output = coordination_handler()
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
    assert!(scheduled_tasks[0].prompt.contains("<coordination_brief>"));
    assert!(
        scheduled_tasks[0]
            .prompt
            .contains("call `coordination_act` `done` with a concise concrete result summary")
    );
    assert!(scheduled_tasks[0].prompt.contains("Review patch"));
    assert!(
        scheduled_tasks[0]
            .prompt
            .contains("Inspect the new patch and report regressions.")
    );
}

#[tokio::test]
async fn open_task_treats_unassigned_owner_as_unowned() {
    let (session, turn, _state_db) = make_session_with_state_db().await;

    let output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Leave this lane open",
                "details": "Do not assign an owner yet.",
                "kind": "general",
                "owner": "unassigned",
                "notify_room": false,
            }),
        ))
        .await
        .expect("open_task with unassigned owner should succeed");

    let result = parse_result(output);
    assert_eq!(result["task"]["status"], "open");
    assert!(result["task"]["owner_thread_id"].is_null());
    assert_eq!(result["woken_threads"], json!([]));
}

#[tokio::test]
async fn assigned_room_scoped_qa_wake_mentions_hollywood_read_and_done() {
    let (session, turn, state_db) = make_session_with_state_db().await;
    let owner_thread_id = ThreadId::new();
    let owner_thread_id_str = owner_thread_id.to_string();
    insert_thread_metadata(&state_db, turn.as_ref(), owner_thread_id).await;

    coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Verify durable award summary appears in Hollywood",
                "details": "Verify whether the Hollywood room showed the durable summary text for this award and report the observed wording.",
                "kind": "qa",
                "room": "repo/losangelex",
                "owner": owner_thread_id_str,
                "notify_room": false,
            }),
        ))
        .await
        .expect("open_task should succeed");

    let scheduled_tasks = state_db
        .list_scheduled_tasks(Some(owner_thread_id))
        .await
        .expect("scheduled task query should succeed");
    assert_eq!(scheduled_tasks.len(), 1);
    assert!(
        scheduled_tasks[0]
            .prompt
            .contains("use `hollywood_read` instead of shell commands")
    );
    assert!(
        scheduled_tasks[0]
            .prompt
            .contains("if the room message is absent, that absence is still a valid result")
    );
    assert!(
        scheduled_tasks[0]
            .prompt
            .contains("do not shell out to Hollywood HTTP endpoints or ad hoc scripts")
    );
    assert!(
        scheduled_tasks[0]
            .prompt
            .contains("for verification or QA tasks, gather the requested evidence, then call `coordination_act` `done` with the observed result")
    );
}

#[tokio::test]
async fn direct_awarded_implementation_wake_includes_reserved_scope_guidance() {
    let (session, turn, state_db) = make_session_with_state_db().await;
    let owner_thread_id = ThreadId::new();
    let owner_thread_id_str = owner_thread_id.to_string();
    insert_thread_metadata(&state_db, turn.as_ref(), owner_thread_id).await;

    let output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Land protocol changes",
                "details": "Update the protocol shape and keep ownership narrow.",
                "kind": "implementation",
                "owner": owner_thread_id_str,
                "claim_paths": [{
                    "kind": "file",
                    "path": "src/protocol.rs"
                }],
                "notify_room": false,
            }),
        ))
        .await
        .expect("direct implementation award should succeed");

    let result = parse_result(output);
    assert_eq!(result["task"]["status"], "awarded");

    let scheduled_tasks = state_db
        .list_scheduled_tasks(Some(owner_thread_id))
        .await
        .expect("scheduled task query should succeed");
    assert_eq!(scheduled_tasks.len(), 1);
    assert!(
        scheduled_tasks[0]
            .prompt
            .contains("Reserved implementation scope:")
    );
    assert!(
        scheduled_tasks[0]
            .prompt
            .contains("- file `src/protocol.rs`")
    );
    assert!(
        scheduled_tasks[0]
            .prompt
            .contains("reuse the exact reserved `claim_paths` listed in the task details")
    );
    assert!(
        scheduled_tasks[0]
            .prompt
            .contains("When you accept this task, reuse the same `claim_paths`.")
    );
    assert!(
        scheduled_tasks[0]
            .prompt
            .contains("call `coordination_act` `done` immediately in the same turn")
    );
    assert!(
        scheduled_tasks[0]
            .prompt
            .contains("end the current turn unless you already have a direct follow-up request")
    );
    assert!(
        scheduled_tasks[0]
            .prompt
            .contains("instead of waiting for room acknowledgment or final green")
    );
}

#[tokio::test]
async fn direct_awarded_implementation_accept_uses_reserved_claim_paths_by_default() {
    let (session, turn, state_db) = make_session_with_state_db().await;
    let (mut owner_session, owner_turn) = make_session_and_context().await;
    owner_session.services.state_db = Some(Arc::clone(&state_db));
    let owner_session = Arc::new(owner_session);
    let owner_turn = Arc::new(owner_turn);
    insert_thread_metadata(&state_db, owner_turn.as_ref(), owner_session.thread_id()).await;
    let reserved_path = turn.config.cwd.join("src/protocol.rs");

    let output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Land protocol changes",
                "details": "Update the protocol shape and keep ownership narrow.",
                "kind": "implementation",
                "owner": owner_session.thread_id().to_string(),
                "claim_paths": [{
                    "kind": "file",
                    "path": reserved_path.to_string_lossy()
                }],
                "notify_room": false,
            }),
        ))
        .await
        .expect("direct implementation award should succeed");
    let result = parse_result(output);
    let task_id = result["task"]["id"]
        .as_str()
        .expect("task id should exist")
        .to_string();

    let accept_output = coordination_handler()
        .handle(invocation(
            Arc::clone(&owner_session),
            Arc::clone(&owner_turn),
            "coordination_act",
            json!({
                "action": "accept",
                "task_id": task_id,
                "summary": "Taking the reserved protocol scope now.",
                "notify_room": false,
            }),
        ))
        .await
        .expect("accept should reuse reserved claim_paths");
    let accept_result = parse_result(accept_output);
    assert_eq!(accept_result["task"]["status"], "active");
    assert_eq!(
        accept_result["ownership"]["claims"][0]["path"],
        json!(reserved_path.to_string_lossy().to_string())
    );

    let owner_claims = state_db
        .list_path_claims(Some(owner_session.thread_id()))
        .await
        .expect("owner claims should list cleanly");
    assert_eq!(owner_claims.len(), 1);
    assert_eq!(owner_claims[0].path, reserved_path.to_path_buf());

    let acts = state_db
        .list_coordination_acts(Some(task_id.as_str()))
        .await
        .expect("act query should succeed");
    let accept_act = acts
        .iter()
        .find(|act| act.kind == codex_state::CoordinationActKind::Accept)
        .expect("accept act should exist");
    let accept_payload: Value =
        serde_json::from_str(accept_act.payload_json.as_str()).expect("accept payload json");
    assert_eq!(
        accept_payload["claim_paths"][0]["path"],
        json!(reserved_path.to_string_lossy().to_string())
    );
}

#[tokio::test]
async fn creator_can_cancel_active_implementation_lane_and_release_claims() {
    let (session, turn, state_db) = make_session_with_state_db().await;
    let (mut owner_session, owner_turn) = make_session_and_context().await;
    owner_session.services.state_db = Some(Arc::clone(&state_db));
    let owner_session = Arc::new(owner_session);
    let owner_turn = Arc::new(owner_turn);
    insert_thread_metadata(&state_db, owner_turn.as_ref(), owner_session.thread_id()).await;
    let reserved_path = turn.config.cwd.join("styles.css");

    let output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Polish styles",
                "details": "Own the CSS lane.",
                "kind": "implementation",
                "owner": owner_session.thread_id().to_string(),
                "claim_paths": [{
                    "kind": "file",
                    "path": reserved_path.to_string_lossy()
                }],
                "notify_room": false,
            }),
        ))
        .await
        .expect("direct implementation award should succeed");
    let result = parse_result(output);
    let task_id = result["task"]["id"]
        .as_str()
        .expect("task id should exist")
        .to_string();

    coordination_handler()
        .handle(invocation(
            Arc::clone(&owner_session),
            Arc::clone(&owner_turn),
            "coordination_act",
            json!({
                "action": "accept",
                "task_id": task_id,
                "summary": "Taking the CSS lane.",
                "notify_room": false,
            }),
        ))
        .await
        .expect("accept should succeed");

    let cancel_output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "cancel",
                "task_id": task_id,
                "summary": "The integrated app is already green without further CSS work.",
                "notify_room": false,
            }),
        ))
        .await
        .expect("creator cancel should succeed");
    let cancel_result = parse_result(cancel_output);
    assert_eq!(cancel_result["task"]["status"], "cancelled");
    assert_eq!(cancel_result["act"]["kind"], "cancel");
    assert_eq!(
        cancel_result["woken_threads"],
        json!([owner_session.thread_id().to_string()])
    );

    let owner_claims = state_db
        .list_path_claims(Some(owner_session.thread_id()))
        .await
        .expect("owner claims should list cleanly");
    assert!(owner_claims.is_empty());

    let scheduled_tasks = state_db
        .list_scheduled_tasks(Some(owner_session.thread_id()))
        .await
        .expect("scheduled task query should succeed");
    assert_eq!(scheduled_tasks.len(), 1);
    assert_eq!(
        scheduled_tasks[0].title,
        "coordination:cancelled:Polish styles"
    );
    assert!(scheduled_tasks[0].prompt.contains("reason: cancelled"));
    assert!(
        scheduled_tasks[0]
            .prompt
            .contains("stop active work on this lane immediately")
    );
    assert!(
        scheduled_tasks[0]
            .prompt
            .contains("interrupted an in-flight turn")
    );
}

#[tokio::test]
async fn accept_clears_pending_assigned_wake_for_owner() {
    let (session, turn, state_db) = make_session_with_state_db().await;
    let (mut owner_session, owner_turn) = make_session_and_context().await;
    owner_session.services.state_db = Some(Arc::clone(&state_db));
    let owner_session = Arc::new(owner_session);
    let owner_turn = Arc::new(owner_turn);
    insert_thread_metadata(&state_db, owner_turn.as_ref(), owner_session.thread_id()).await;

    let output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Review patch",
                "details": "Inspect the new patch and report regressions.",
                "kind": "review",
                "owner": owner_session.thread_id().to_string(),
                "notify_room": false,
            }),
        ))
        .await
        .expect("open_task should succeed");
    let result = parse_result(output);
    let task_id = result["task"]["id"]
        .as_str()
        .expect("task id should exist")
        .to_string();

    assert_eq!(
        state_db
            .list_scheduled_tasks(Some(owner_session.thread_id()))
            .await
            .expect("scheduled task query should succeed")
            .len(),
        1
    );

    coordination_handler()
        .handle(invocation(
            Arc::clone(&owner_session),
            Arc::clone(&owner_turn),
            "coordination_act",
            json!({
                "action": "accept",
                "task_id": task_id,
                "summary": "Taking the review task now.",
                "notify_room": false,
            }),
        ))
        .await
        .expect("accept should succeed");

    assert_eq!(
        state_db
            .list_scheduled_tasks(Some(owner_session.thread_id()))
            .await
            .expect("scheduled task query should succeed")
            .len(),
        0
    );
}

#[tokio::test]
async fn done_unblocks_awarded_dependency_and_persists_wake() {
    let (session, turn, state_db) = make_session_with_state_db().await;
    let owner_thread_id = ThreadId::new();
    let owner_thread_id_str = owner_thread_id.to_string();
    insert_thread_metadata(&state_db, turn.as_ref(), owner_thread_id).await;

    let dependency_output = coordination_handler()
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

    let blocked_output = coordination_handler()
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
                "claim_paths": [{
                    "kind": "directory",
                    "path": "codex-rs/tui"
                }],
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

    let done_output = coordination_handler()
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

#[tokio::test]
async fn open_task_named_owner_resolves_thread_title() {
    let (session, turn, state_db) = make_session_with_state_db().await;
    let owner_thread_id = ThreadId::new();
    insert_named_thread_metadata(&state_db, turn.as_ref(), owner_thread_id, "tony").await;

    let output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Validate operator replay",
                "details": "Check the control path after startup settles.",
                "owner": "tony",
                "notify_room": false,
            }),
        ))
        .await
        .expect("open_task with named owner should succeed");

    let result = parse_result(output);
    assert_eq!(
        result["task"]["owner_thread_id"],
        json!(owner_thread_id.to_string())
    );
    assert_eq!(
        result["woken_threads"],
        json!([owner_thread_id.to_string()])
    );
}

#[tokio::test]
async fn handoff_named_owner_resolves_thread_title() {
    let (session, turn, state_db) = make_session_with_state_db().await;
    let superseded_owner_thread_id = ThreadId::new();
    let owner_thread_id = ThreadId::new();
    insert_named_thread_metadata(
        &state_db,
        turn.as_ref(),
        superseded_owner_thread_id,
        "chris",
    )
    .await;
    insert_named_thread_metadata(&state_db, turn.as_ref(), owner_thread_id, "tony").await;

    let open_output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Coordinate handoff",
                "details": "Start unassigned so the creator can reassign it.",
                "owner": "chris",
                "notify_room": false,
            }),
        ))
        .await
        .expect("open_task should succeed");
    let open_result = parse_result(open_output);
    let task_id = open_result["task"]["id"]
        .as_str()
        .expect("task id should exist")
        .to_string();

    let handoff_output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "handoff",
                "task_id": task_id,
                "owner": "tony",
                "summary": "Reassigning the task to Tony for follow-through",
                "notify_room": false,
            }),
        ))
        .await
        .expect("handoff with named owner should succeed");

    let handoff_result = parse_result(handoff_output);
    assert_eq!(
        handoff_result["task"]["owner_thread_id"],
        json!(owner_thread_id.to_string())
    );
    assert_eq!(
        handoff_result["woken_threads"],
        json!([owner_thread_id.to_string()])
    );
    assert_eq!(
        handoff_result["superseded_owner_thread_id"],
        json!(superseded_owner_thread_id.to_string())
    );
}

#[tokio::test]
async fn handoff_requires_meaningful_summary() {
    let (session, turn, _state_db) = make_session_with_state_db().await;

    let open_output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Coordinate handoff",
                "notify_room": false,
            }),
        ))
        .await
        .expect("open_task should succeed");
    let open_result = parse_result(open_output);
    let task_id = open_result["task"]["id"]
        .as_str()
        .expect("task id should exist")
        .to_string();

    let output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "handoff",
                "task_id": task_id,
                "owner": ThreadId::new().to_string(),
                "notify_room": false,
            }),
        ))
        .await
        .expect("handoff without summary should return recoverable output");
    let result = parse_result(output);

    assert_eq!(result["ok"], json!(false));
    assert_eq!(
        result["error"],
        json!("coordination_act handoff requires a concise non-empty summary")
    );
}

#[tokio::test]
async fn yield_rejects_placeholder_summary() {
    let (session, turn, _state_db) = make_session_with_state_db().await;

    let open_output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Inspect room summary",
                "notify_room": false,
            }),
        ))
        .await
        .expect("open_task should succeed");
    let open_result = parse_result(open_output);
    let task_id = open_result["task"]["id"]
        .as_str()
        .expect("task id should exist")
        .to_string();

    let output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "yield",
                "task_id": task_id,
                "summary": "placeholder",
                "notify_room": false,
            }),
        ))
        .await
        .expect("placeholder yield should return recoverable output");
    let result = parse_result(output);

    assert_eq!(result["ok"], json!(false));
    assert_eq!(
        result["error"],
        json!("coordination_act yield requires a concrete summary, not placeholder text")
    );
}

#[tokio::test]
async fn cancel_rejects_placeholder_summary() {
    let (session, turn, _state_db) = make_session_with_state_db().await;

    let output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "cancel",
                "task_id": ThreadId::new().to_string(),
                "summary": "placeholder",
                "notify_room": false,
            }),
        ))
        .await
        .expect("cancel placeholder summary should return model-visible error");

    let result = parse_result(output);
    assert_eq!(
        result["error"],
        json!("coordination_act cancel requires a concrete summary, not placeholder text")
    );
}

#[tokio::test]
async fn accept_rejects_noop_summary() {
    let (session, turn, _state_db) = make_session_with_state_db().await;

    let open_output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Inspect room summary",
                "notify_room": false,
            }),
        ))
        .await
        .expect("open_task should succeed");
    let open_result = parse_result(open_output);
    let task_id = open_result["task"]["id"]
        .as_str()
        .expect("task id should exist")
        .to_string();

    let output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "accept",
                "task_id": task_id,
                "summary": "noop",
                "notify_room": false,
            }),
        ))
        .await
        .expect("noop accept should return recoverable output");
    let result = parse_result(output);

    assert_eq!(result["ok"], json!(false));
    assert_eq!(
        result["error"],
        json!("coordination_act accept requires a concrete summary, not placeholder text")
    );
}

#[tokio::test]
async fn implementation_accept_requires_exact_claim_paths() {
    let (session, turn, _state_db) = make_session_with_state_db().await;

    let open_output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Land protocol changes",
                "kind": "implementation",
                "notify_room": false,
            }),
        ))
        .await
        .expect("open_task should succeed");
    let open_result = parse_result(open_output);
    let task_id = open_result["task"]["id"]
        .as_str()
        .expect("task id should exist")
        .to_string();

    let output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "accept",
                "task_id": task_id,
                "summary": "Taking protocol ownership now.",
                "notify_room": false,
            }),
        ))
        .await
        .expect("implementation accept should return a recoverable failure output");

    assert_eq!(output_success(output.as_ref()), Some(false));
    let result = parse_result(output);
    assert!(
        result["error"]
            .as_str()
            .expect("error string should exist")
            .contains("requires exact ownership claims")
    );
    assert_eq!(result["task"]["status"], "open");
}

#[tokio::test]
async fn implementation_accept_rejects_conflicting_claim_paths() {
    let (session, turn, state_db) = make_session_with_state_db().await;
    let blocker = ThreadId::new();
    insert_thread_metadata(&state_db, turn.as_ref(), blocker).await;
    let claimed_path = turn.config.cwd.join("src/lib.rs");

    state_db
        .claim_path_ownership(
            blocker,
            &[codex_state::PathClaimSpec {
                kind: codex_state::PathClaimKind::File,
                path: claimed_path.to_path_buf(),
            }],
            std::time::Duration::from_secs(600),
        )
        .await
        .expect("blocker claim should succeed");

    let open_output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Land protocol changes",
                "kind": "implementation",
                "notify_room": false,
            }),
        ))
        .await
        .expect("open_task should succeed");
    let open_result = parse_result(open_output);
    let task_id = open_result["task"]["id"]
        .as_str()
        .expect("task id should exist")
        .to_string();

    let output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "accept",
                "task_id": task_id,
                "summary": "Taking protocol ownership now.",
                "claim_paths": [{
                    "kind": "file",
                    "path": claimed_path.to_string_lossy()
                }],
                "notify_room": false,
            }),
        ))
        .await
        .expect("conflicting claim should return a recoverable failure output");

    assert_eq!(output_success(output.as_ref()), Some(false));
    let result = parse_result(output);
    let message = result["error"]
        .as_str()
        .expect("error string should exist")
        .to_string();
    assert!(message.contains("cannot become active because thread"));
    assert!(message.contains(blocker.to_string().as_str()));
    assert_eq!(result["task"]["status"], "open");

    let task = state_db
        .get_coordination_task(&task_id)
        .await
        .expect("get task should succeed")
        .expect("task should exist");
    assert_eq!(task.status, codex_state::CoordinationTaskStatus::Open);
    assert_eq!(task.owner_thread_id, None);
    assert_eq!(
        state_db
            .list_path_claims(Some(session.thread_id()))
            .await
            .expect("list claims should succeed"),
        Vec::<codex_state::PathClaim>::new()
    );
}

#[tokio::test]
async fn implementation_open_task_requires_claim_paths_for_direct_owner() {
    let (session, turn, state_db) = make_session_with_state_db().await;
    let owner_thread_id = ThreadId::new();
    insert_named_thread_metadata(&state_db, turn.as_ref(), owner_thread_id, "tony").await;

    let output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Land protocol changes",
                "kind": "implementation",
                "owner": "tony",
                "notify_room": false,
            }),
        ))
        .await
        .expect("direct implementation award should return a recoverable failure output");

    assert_eq!(output_success(output.as_ref()), Some(false));
    let result = parse_result(output);
    assert!(
        result["error"]
            .as_str()
            .expect("error string should exist")
            .contains("requires exact claim_paths")
    );

    let tasks = state_db
        .list_coordination_tasks(codex_state::CoordinationTaskListFilter {
            owner_thread_id: None,
            creator_thread_id: None,
            room: None,
            statuses: Vec::new(),
        })
        .await
        .expect("list tasks should succeed");
    assert!(
        tasks.is_empty(),
        "direct award should not create a task on failure"
    );
}

#[tokio::test]
async fn auto_discovery_blocks_broad_implementation_open_task() {
    let server = MockServer::start().await;
    let leader_thread_id = ThreadId::new();
    let verifier_thread_id = ThreadId::new();
    Mock::given(method("GET"))
        .and(path("/hollywood/v1/rooms"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "rooms": [{
                "room": "repo/current-room",
                "contract_version": "losangelex-room/v2",
                "coordination_policy": "auto",
                "coordination_phase": "discovery",
                "coordination_epoch": 3,
                "leader_session_id": leader_thread_id.to_string(),
                "verifier_session_id": verifier_thread_id.to_string(),
            }]
        })))
        .expect(1)
        .mount(&server)
        .await;

    let (session, turn, _state_db) = make_session_with_state_db().await;
    session
        .set_hollywood_session_config(Some(crate::hollywood::HollywoodSessionConfig {
            url: server.uri(),
            room: "repo/current-room".to_string(),
            observed_rooms: Vec::new(),
            wake_rooms: Vec::new(),
            attention_mode: "focused".to_string(),
        }))
        .await;

    let output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Take the whole app",
                "details": "I'll just own the whole product lane for now.",
                "kind": "implementation",
                "room": "repo/current-room",
                "notify_room": false,
            }),
        ))
        .await
        .expect("auto discovery broad implementation claim should return a recoverable failure");

    assert_eq!(output_success(output.as_ref()), Some(false));
    let result = parse_result(output);
    assert!(
        result["error"]
            .as_str()
            .expect("error string should exist")
            .contains("blocks broad implementation claims")
    );
}

#[tokio::test]
async fn auto_execution_verifier_cannot_accept_unassigned_implementation_lane() {
    let server = MockServer::start().await;
    let (session, turn, state_db) = make_session_with_state_db().await;
    let leader_thread_id = ThreadId::new();
    Mock::given(method("GET"))
        .and(path("/hollywood/v1/rooms"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "rooms": [{
                "room": "repo/current-room",
                "contract_version": "losangelex-room/v2",
                "coordination_policy": "auto",
                "coordination_phase": "execution",
                "coordination_epoch": 4,
                "leader_session_id": leader_thread_id.to_string(),
                "verifier_session_id": session.thread_id().to_string(),
            }]
        })))
        .expect(1)
        .mount(&server)
        .await;
    session
        .set_hollywood_session_config(Some(crate::hollywood::HollywoodSessionConfig {
            url: server.uri(),
            room: "repo/current-room".to_string(),
            observed_rooms: Vec::new(),
            wake_rooms: Vec::new(),
            attention_mode: "focused".to_string(),
        }))
        .await;
    let claimed_path = turn.config.cwd.join("src/app.js");
    state_db
        .create_coordination_task(codex_state::CoordinationTaskCreateParams {
            id: "task-auto-verifier-blocked".to_string(),
            creator_thread_id: leader_thread_id,
            owner_thread_id: None,
            reserved_path_claims: Vec::new(),
            claim_lease_seconds: codex_state::DEFAULT_COORDINATION_LEASE_SECONDS,
            team_id: None,
            room: Some("repo/current-room".to_string()),
            kind: codex_state::CoordinationTaskKind::Implementation,
            summary: "Take app implementation lane".to_string(),
            details: "Implementation work is ready.".to_string(),
            requested_capability: None,
            dependency_task_ids: Vec::new(),
            act_id: "act-auto-verifier-blocked-open".to_string(),
            act_summary: None,
            act_payload_json: "{}".to_string(),
        })
        .await
        .expect("task create should succeed");

    let output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "accept",
                "task_id": "task-auto-verifier-blocked",
                "summary": "Taking the app implementation lane.",
                "claim_paths": [{
                    "kind": "file",
                    "path": claimed_path.to_string_lossy().to_string(),
                }],
                "notify_room": false,
            }),
        ))
        .await
        .expect("verifier implementation accept should return a recoverable failure");

    assert_eq!(output_success(output.as_ref()), Some(false));
    let result = parse_result(output);
    assert!(
        result["error"]
            .as_str()
            .expect("error string should exist")
            .contains("keeps the verifier on QA")
    );
}

#[tokio::test]
async fn auto_execution_verifier_can_accept_explicitly_awarded_implementation_lane() {
    let server = MockServer::start().await;
    let (session, turn, state_db) = make_session_with_state_db().await;
    let leader_thread_id = ThreadId::new();
    Mock::given(method("GET"))
        .and(path("/hollywood/v1/rooms"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "rooms": [{
                "room": "repo/current-room",
                "contract_version": "losangelex-room/v2",
                "coordination_policy": "auto",
                "coordination_phase": "execution",
                "coordination_epoch": 5,
                "leader_session_id": leader_thread_id.to_string(),
                "verifier_session_id": session.thread_id().to_string(),
            }]
        })))
        .expect(1)
        .mount(&server)
        .await;
    session
        .set_hollywood_session_config(Some(crate::hollywood::HollywoodSessionConfig {
            url: server.uri(),
            room: "repo/current-room".to_string(),
            observed_rooms: Vec::new(),
            wake_rooms: Vec::new(),
            attention_mode: "focused".to_string(),
        }))
        .await;
    let reserved_path = turn.config.cwd.join("src/app.js");
    let reserved_payload = json!({
        "claim_paths": [{
            "kind": "file",
            "path": reserved_path.to_string_lossy().to_string(),
        }]
    })
    .to_string();
    state_db
        .create_coordination_task(codex_state::CoordinationTaskCreateParams {
            id: "task-auto-verifier-awarded".to_string(),
            creator_thread_id: leader_thread_id,
            owner_thread_id: Some(session.thread_id()),
            reserved_path_claims: vec![codex_state::PathClaimSpec {
                kind: codex_state::PathClaimKind::File,
                path: reserved_path.to_path_buf(),
            }],
            claim_lease_seconds: codex_state::DEFAULT_COORDINATION_LEASE_SECONDS,
            team_id: None,
            room: Some("repo/current-room".to_string()),
            kind: codex_state::CoordinationTaskKind::Implementation,
            summary: "Take app implementation lane".to_string(),
            details: "Implementation work is explicitly assigned to the verifier.".to_string(),
            requested_capability: None,
            dependency_task_ids: Vec::new(),
            act_id: "act-auto-verifier-awarded-open".to_string(),
            act_summary: None,
            act_payload_json: reserved_payload,
        })
        .await
        .expect("task create should succeed");

    let output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "accept",
                "task_id": "task-auto-verifier-awarded",
                "summary": "Taking the explicitly awarded implementation lane.",
                "notify_room": false,
            }),
        ))
        .await
        .expect("awarded verifier implementation accept should succeed");

    assert_eq!(output_success(output.as_ref()), Some(true));
    let result = parse_result(output);
    assert_eq!(result["task"]["status"], "active");
    assert_eq!(
        result["task"]["owner_thread_id"],
        json!(session.thread_id().to_string())
    );
}

#[tokio::test]
async fn implementation_open_task_rejects_conflicting_reserved_claim_paths() {
    let (session, turn, state_db) = make_session_with_state_db().await;
    let owner_thread_id = ThreadId::new();
    let blocker = ThreadId::new();
    insert_named_thread_metadata(&state_db, turn.as_ref(), owner_thread_id, "tony").await;
    insert_thread_metadata(&state_db, turn.as_ref(), blocker).await;
    let claimed_path = turn.config.cwd.join("src/lib.rs");

    state_db
        .claim_path_ownership(
            blocker,
            &[codex_state::PathClaimSpec {
                kind: codex_state::PathClaimKind::File,
                path: claimed_path.to_path_buf(),
            }],
            std::time::Duration::from_secs(600),
        )
        .await
        .expect("blocker claim should succeed");

    let output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Land protocol changes",
                "kind": "implementation",
                "owner": "tony",
                "claim_paths": [{
                    "kind": "file",
                    "path": claimed_path.to_string_lossy()
                }],
                "notify_room": false,
            }),
        ))
        .await
        .expect("conflicting reserved claim should return a recoverable failure output");

    assert_eq!(output_success(output.as_ref()), Some(false));
    let result = parse_result(output);
    let message = result["error"]
        .as_str()
        .expect("error string should exist")
        .to_string();
    assert!(message.contains("cannot be awarded because thread"));
    assert!(message.contains(blocker.to_string().as_str()));

    let tasks = state_db
        .list_coordination_tasks(codex_state::CoordinationTaskListFilter {
            owner_thread_id: None,
            creator_thread_id: None,
            room: None,
            statuses: Vec::new(),
        })
        .await
        .expect("list tasks should succeed");
    assert!(
        tasks.is_empty(),
        "conflicting direct award should not persist a task"
    );
    assert_eq!(
        state_db
            .list_path_claims(Some(owner_thread_id))
            .await
            .expect("owner claims should list cleanly"),
        Vec::<codex_state::PathClaim>::new()
    );
}

#[tokio::test]
async fn implementation_open_task_dedupes_same_owner_same_scope() {
    let (session, turn, state_db) = make_session_with_state_db().await;
    let claimed_path = turn.config.cwd.join("src/lib.rs");

    let initial_open = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Land protocol changes",
                "details": "Own the implementation lane for src/lib.rs.",
                "kind": "implementation",
                "owner": session.thread_id().to_string(),
                "claim_paths": [{
                    "kind": "file",
                    "path": claimed_path.to_string_lossy()
                }],
                "room": "repo/ozzz",
                "notify_room": false,
            }),
        ))
        .await
        .expect("initial open_task should succeed");
    let initial_result = parse_result(initial_open);
    let task_id = initial_result["task"]["id"]
        .as_str()
        .expect("task id should exist")
        .to_string();

    coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "accept",
                "task_id": task_id,
                "claim_paths": [{
                    "kind": "file",
                    "path": claimed_path.to_string_lossy()
                }],
                "notify_room": false,
            }),
        ))
        .await
        .expect("accept should succeed");

    let duplicate_open = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Duplicate implementation lane",
                "details": "Re-state the same src/lib.rs ownership.",
                "kind": "implementation",
                "owner": session.thread_id().to_string(),
                "claim_paths": [{
                    "kind": "file",
                    "path": claimed_path.to_string_lossy()
                }],
                "room": "repo/ozzz",
                "notify_room": false,
            }),
        ))
        .await
        .expect("duplicate open_task should be idempotent");

    assert_eq!(output_success(duplicate_open.as_ref()), Some(true));
    let duplicate_result = parse_result(duplicate_open);
    assert_eq!(duplicate_result["deduped"], json!(true));
    assert_eq!(duplicate_result["task"]["id"], initial_result["task"]["id"]);
    assert_eq!(duplicate_result["task"]["status"], "active");
    assert_eq!(duplicate_result["act"], Value::Null);
    assert_eq!(duplicate_result["room_notified"], json!(false));
    assert_eq!(duplicate_result["woken_threads"], json!([]));

    let tasks = state_db
        .list_coordination_tasks(codex_state::CoordinationTaskListFilter {
            owner_thread_id: Some(session.thread_id()),
            creator_thread_id: None,
            room: Some("repo/ozzz".to_string()),
            statuses: Vec::new(),
        })
        .await
        .expect("list tasks should succeed");
    assert_eq!(tasks.len(), 1);
    assert_eq!(tasks[0].id, task_id);
}

#[tokio::test]
async fn self_opened_qa_lane_dedupes_existing_award_for_owner() {
    let (session, turn, state_db) = make_session_with_state_db().await;
    let (mut owner_session, owner_turn) = make_session_and_context().await;
    owner_session.services.state_db = Some(Arc::clone(&state_db));
    let owner_session = Arc::new(owner_session);
    let owner_turn = Arc::new(owner_turn);
    insert_thread_metadata(&state_db, owner_turn.as_ref(), owner_session.thread_id()).await;

    let initial_open = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Run final habit dashboard test gate",
                "details": "Verify the room stays green before final close.",
                "kind": "qa",
                "owner": owner_session.thread_id().to_string(),
                "room": "repo/ozzz",
                "notify_room": false,
            }),
        ))
        .await
        .expect("initial owner-awarded QA task should succeed");
    let initial_result = parse_result(initial_open);
    let task_id = initial_result["task"]["id"]
        .as_str()
        .expect("task id should exist")
        .to_string();

    let duplicate_open = coordination_handler()
        .handle(invocation(
            Arc::clone(&owner_session),
            Arc::clone(&owner_turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Run habit dashboard QA and final test gate",
                "details": "Double-check the final gate before reporting done.",
                "kind": "qa",
                "owner": owner_session.thread_id().to_string(),
                "room": "repo/ozzz",
                "notify_room": false,
            }),
        ))
        .await
        .expect("self-opened duplicate QA lane should be idempotent");

    assert_eq!(output_success(duplicate_open.as_ref()), Some(true));
    let duplicate_result = parse_result(duplicate_open);
    assert_eq!(duplicate_result["deduped"], json!(true));
    assert_eq!(duplicate_result["task"]["id"], json!(task_id));
    assert_eq!(duplicate_result["task"]["status"], "awarded");
    assert_eq!(duplicate_result["act"], Value::Null);
    assert_eq!(duplicate_result["room_notified"], json!(false));
    assert_eq!(duplicate_result["woken_threads"], json!([]));

    let tasks = state_db
        .list_coordination_tasks(codex_state::CoordinationTaskListFilter {
            owner_thread_id: Some(owner_session.thread_id()),
            creator_thread_id: None,
            room: Some("repo/ozzz".to_string()),
            statuses: Vec::new(),
        })
        .await
        .expect("list tasks should succeed");
    assert_eq!(tasks.len(), 1);
    assert_eq!(tasks[0].id, task_id);
}

#[tokio::test]
async fn missing_task_id_returns_recoverable_output() {
    let (session, turn, _state_db) = make_session_with_state_db().await;

    let output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "done",
                "summary": "finished",
            }),
        ))
        .await
        .expect("missing task id should return recoverable output");

    assert_eq!(output_success(output.as_ref()), Some(false));
    let result = parse_result(output);
    assert_eq!(result["ok"], false);
    assert_eq!(result["error"], "coordination_act requires `task_id`");
}

#[tokio::test]
async fn active_accept_by_same_owner_is_idempotent() {
    let (session, turn, state_db) = make_session_with_state_db().await;

    let open_output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Read-only QA",
                "kind": "qa",
                "room": "repo/ozzz",
                "notify_room": false,
            }),
        ))
        .await
        .expect("open_task should succeed");
    let open_result = parse_result(open_output);
    let task_id = open_result["task"]["id"]
        .as_str()
        .expect("task id should be string")
        .to_string();

    let accept_output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "accept",
                "task_id": task_id.as_str(),
                "summary": "Taking QA lane.",
                "notify_room": false,
            }),
        ))
        .await
        .expect("initial accept should succeed");
    let accept_result = parse_result(accept_output);
    assert_eq!(accept_result["task"]["status"], "active");

    let duplicate_accept = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "accept",
                "task_id": task_id.as_str(),
                "summary": "Re-accepting the same QA lane.",
                "notify_room": true,
            }),
        ))
        .await
        .expect("same-owner active accept should be idempotent");

    assert_eq!(output_success(duplicate_accept.as_ref()), Some(true));
    let duplicate_result = parse_result(duplicate_accept);
    assert_eq!(duplicate_result["deduped"], json!(true));
    assert_eq!(duplicate_result["task"]["id"], open_result["task"]["id"]);
    assert_eq!(duplicate_result["task"]["status"], "active");
    assert_eq!(duplicate_result["act"], Value::Null);
    assert_eq!(duplicate_result["room_notified"], json!(false));

    let acts = state_db
        .list_coordination_acts(Some(task_id.as_str()))
        .await
        .expect("list acts should succeed");
    let accept_count = acts
        .iter()
        .filter(|act| act.kind == codex_state::CoordinationActKind::Accept)
        .count();
    assert_eq!(accept_count, 1);
}

#[tokio::test]
async fn repeated_done_by_same_controller_is_idempotent() {
    let (session, turn, state_db) = make_session_with_state_db().await;

    let open_output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Verification lane",
                "kind": "qa",
                "room": "repo/ozzz",
                "notify_room": false,
            }),
        ))
        .await
        .expect("open_task should succeed");
    let open_result = parse_result(open_output);
    let task_id = open_result["task"]["id"]
        .as_str()
        .expect("task id should be string")
        .to_string();

    coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "accept",
                "task_id": task_id.as_str(),
                "summary": "Taking verification lane.",
                "notify_room": false,
            }),
        ))
        .await
        .expect("accept should succeed");

    let done_output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "done",
                "task_id": task_id.as_str(),
                "summary": "Verification complete.",
                "notify_room": false,
            }),
        ))
        .await
        .expect("first done should succeed");
    let done_result = parse_result(done_output);
    assert_eq!(done_result["task"]["status"], "done");

    let duplicate_done = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "done",
                "task_id": task_id.as_str(),
                "summary": "Repeating done after completion.",
                "notify_room": true,
            }),
        ))
        .await
        .expect("same-controller done should be idempotent");

    assert_eq!(output_success(duplicate_done.as_ref()), Some(true));
    let duplicate_result = parse_result(duplicate_done);
    assert_eq!(duplicate_result["deduped"], json!(true));
    assert_eq!(duplicate_result["task"]["id"], open_result["task"]["id"]);
    assert_eq!(duplicate_result["task"]["status"], "done");
    assert_eq!(duplicate_result["act"], Value::Null);
    assert_eq!(duplicate_result["room_notified"], json!(false));

    let acts = state_db
        .list_coordination_acts(Some(task_id.as_str()))
        .await
        .expect("list acts should succeed");
    let done_count = acts
        .iter()
        .filter(|act| act.kind == codex_state::CoordinationActKind::Done)
        .count();
    assert_eq!(done_count, 1);
}

#[tokio::test]
async fn unknown_task_returns_recoverable_output() {
    let (session, turn, _state_db) = make_session_with_state_db().await;

    let output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "done",
                "task_id": "self-pending-placeholder",
                "summary": "finished",
            }),
        ))
        .await
        .expect("unknown task should return recoverable output");

    assert_eq!(output_success(output.as_ref()), Some(false));
    let result = parse_result(output);
    assert_eq!(result["ok"], false);
    assert_eq!(
        result["error"],
        "coordination task self-pending-placeholder was not found"
    );
}

#[tokio::test]
async fn list_coordination_tasks_accepts_named_owner_and_status_alias() {
    let (session, turn, state_db) = make_session_with_state_db().await;
    let owner_thread_id = ThreadId::new();
    insert_named_thread_metadata(&state_db, turn.as_ref(), owner_thread_id, "tony").await;

    let open_output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Review semantic wake patch",
                "details": "Inspect the room-trigger changes.",
                "owner": "tony",
                "notify_room": false,
            }),
        ))
        .await
        .expect("open_task should succeed");
    let open_result = parse_result(open_output);
    let task_id = open_result["task"]["id"]
        .as_str()
        .expect("task id should exist")
        .to_string();

    let list_output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "list_coordination_tasks",
            json!({
                "owner": "tony",
                "statuses": ["accepted"],
            }),
        ))
        .await
        .expect("named owner + alias status should list tasks");

    let list_result = parse_result(list_output);
    assert_eq!(list_result["tasks"].as_array().map(Vec::len), Some(1));
    assert_eq!(list_result["tasks"][0]["id"], json!(task_id));
    assert_eq!(list_result["tasks"][0]["status"], json!("awarded"));
}

#[tokio::test]
async fn list_coordination_tasks_accepts_todo_status_alias_for_open() {
    let (session, turn, _state_db) = make_session_with_state_db().await;

    let open_output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Queue follow-up validation",
                "details": "Leave this unassigned so it stays open.",
                "notify_room": false,
            }),
        ))
        .await
        .expect("open_task should succeed");
    let open_result = parse_result(open_output);
    let task_id = open_result["task"]["id"]
        .as_str()
        .expect("task id should exist")
        .to_string();

    let list_output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "list_coordination_tasks",
            json!({
                "statuses": ["todo"],
            }),
        ))
        .await
        .expect("todo alias should list open tasks");

    let list_result = parse_result(list_output);
    assert_eq!(list_result["tasks"].as_array().map(Vec::len), Some(1));
    assert_eq!(list_result["tasks"][0]["id"], json!(task_id));
    assert_eq!(list_result["tasks"][0]["status"], json!("open"));
}

#[tokio::test]
async fn list_coordination_tasks_accepts_proposed_status_alias_for_open() {
    let (session, turn, _state_db) = make_session_with_state_db().await;

    coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Draft the next lane split",
                "notify_room": false,
            }),
        ))
        .await
        .expect("open_task should succeed");

    let list_output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "list_coordination_tasks",
            json!({
                "statuses": ["proposed"],
            }),
        ))
        .await
        .expect("proposed alias should list tasks");
    let list_result = parse_result(list_output);

    assert_eq!(list_result["tasks"][0]["status"], json!("open"));
}

#[tokio::test]
async fn open_task_named_owner_resolves_fresh_named_thread_without_history() {
    let (session, turn, state_db) = make_session_with_state_db().await;

    let stale_owner_thread_id = ThreadId::new();
    insert_named_thread_metadata(&state_db, turn.as_ref(), stale_owner_thread_id, "james").await;

    let fresh_owner_thread_id = ThreadId::new();
    insert_fresh_named_thread_metadata_without_history(
        &state_db,
        turn.as_ref(),
        fresh_owner_thread_id,
        "james",
    )
    .await;

    let output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Assign latest james thread",
                "details": "This should resolve to the freshest named james thread even before it has first-user history.",
                "owner": "james",
                "notify_room": false,
            }),
        ))
        .await
        .expect("open_task with fresh named owner should succeed");

    let result = parse_result(output);
    assert_eq!(
        result["task"]["owner_thread_id"],
        json!(fresh_owner_thread_id.to_string())
    );
}

#[tokio::test]
async fn open_task_named_owner_resolves_current_thread_title() {
    let (session, turn, state_db) = make_session_with_state_db().await;
    rename_thread_metadata(&state_db, session.thread_id(), "tony").await;

    let output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Hold operator lane and wait",
                "details": "Self-owned operator lane.",
                "owner": "tony",
                "notify_room": false,
            }),
        ))
        .await
        .expect("open_task with current thread title should succeed");

    let result = parse_result(output);
    assert_eq!(
        result["task"]["owner_thread_id"],
        json!(session.thread_id().to_string())
    );
}

#[tokio::test]
async fn open_task_named_owner_resolves_live_hollywood_identity_in_current_room() {
    let server = MockServer::start().await;
    let owner_thread_id = ThreadId::new();
    let now = Utc::now().to_rfc3339();
    Mock::given(method("GET"))
        .and(path("/hollywood/v1/registry"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "entries": [{
                "session_id": owner_thread_id.to_string(),
                "attached": true,
                "identities": [owner_thread_id.to_string(), "james"],
                "updated_at": now,
                "last_heartbeat_at": now,
            }]
        })))
        .expect(1)
        .mount(&server)
        .await;

    let (session, turn, state_db) = make_session_with_state_db().await;
    session
        .set_hollywood_session_config(Some(crate::hollywood::HollywoodSessionConfig {
            url: server.uri(),
            room: "repo/current-room".to_string(),
            observed_rooms: Vec::new(),
            wake_rooms: Vec::new(),
            attention_mode: "focused".to_string(),
        }))
        .await;
    insert_thread_metadata(&state_db, turn.as_ref(), owner_thread_id).await;

    let output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Assign live james",
                "details": "Resolve james from the current room's live Hollywood registry entry.",
                "owner": "james",
                "notify_room": false,
            }),
        ))
        .await
        .expect("open_task with live Hollywood owner should succeed");

    let result = parse_result(output);
    assert_eq!(
        result["task"]["owner_thread_id"],
        json!(owner_thread_id.to_string())
    );
}

#[tokio::test]
async fn open_task_named_owner_resolves_generated_runtime_suffix_identity_in_current_room() {
    let server = MockServer::start().await;
    let owner_thread_id = ThreadId::new();
    let now = Utc::now().to_rfc3339();
    Mock::given(method("GET"))
        .and(path("/hollywood/v1/registry"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "entries": [{
                "session_id": owner_thread_id.to_string(),
                "attached": true,
                "identities": [owner_thread_id.to_string(), "james-7c45ba"],
                "updated_at": now,
                "last_heartbeat_at": now,
            }]
        })))
        .expect(1)
        .mount(&server)
        .await;

    let (session, turn, state_db) = make_session_with_state_db().await;
    session
        .set_hollywood_session_config(Some(crate::hollywood::HollywoodSessionConfig {
            url: server.uri(),
            room: "repo/current-room".to_string(),
            observed_rooms: Vec::new(),
            wake_rooms: Vec::new(),
            attention_mode: "focused".to_string(),
        }))
        .await;
    insert_thread_metadata(&state_db, turn.as_ref(), owner_thread_id).await;

    let output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Assign generated runtime james",
                "details": "Resolve james from a generated runtime identity in the current room.",
                "owner": "james",
                "notify_room": false,
            }),
        ))
        .await
        .expect("open_task with generated runtime owner should succeed");

    let result = parse_result(output);
    assert_eq!(
        result["task"]["owner_thread_id"],
        json!(owner_thread_id.to_string())
    );
}

#[tokio::test]
async fn open_task_named_owner_in_hollywood_mode_requires_live_room_match() {
    let server = MockServer::start().await;
    Mock::given(method("GET"))
        .and(path("/hollywood/v1/registry"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "entries": []
        })))
        .expect(1)
        .mount(&server)
        .await;

    let (session, turn, state_db) = make_session_with_state_db().await;
    session
        .set_hollywood_session_config(Some(crate::hollywood::HollywoodSessionConfig {
            url: server.uri(),
            room: "repo/current-room".to_string(),
            observed_rooms: Vec::new(),
            wake_rooms: Vec::new(),
            attention_mode: "focused".to_string(),
        }))
        .await;
    let stale_named_thread = ThreadId::new();
    insert_named_thread_metadata(&state_db, turn.as_ref(), stale_named_thread, "james").await;

    let error = match coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Reject stale james fallback",
                "details": "Do not silently fall back to a non-live named thread in Hollywood mode.",
                "owner": "james",
                "notify_room": false,
            }),
        ))
        .await
    {
        Ok(_) => panic!("open_task should reject a non-live Hollywood named owner"),
        Err(error) => error,
    };

    assert_eq!(
        error.to_string(),
        "unknown live Hollywood agent `james` in room `repo/current-room`"
    );
}

#[tokio::test]
async fn open_task_notifies_room_using_live_session_hollywood_config() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/hollywood/v1/messages"))
        .respond_with(ResponseTemplate::new(201))
        .expect(1)
        .mount(&server)
        .await;

    let (session, turn, _state_db) = make_session_with_state_db().await;
    session
        .set_hollywood_session_config(Some(crate::hollywood::HollywoodSessionConfig {
            url: server.uri(),
            room: "repo/losangelex".to_string(),
            observed_rooms: vec!["main".to_string()],
            wake_rooms: Vec::new(),
            attention_mode: "focused".to_string(),
        }))
        .await;
    session
        .add_hollywood_obligation(&HollywoodInputMessage {
            message_id: 7,
            room: "repo/losangelex".to_string(),
            sender_id: "tony".to_string(),
            body: "Need a coordination update.".to_string(),
            mentions: Vec::new(),
            attention: Some("focused".to_string()),
            message_kind: Some("direct".to_string()),
            obligation: Some("obligation".to_string()),
            synthetic_brief: None,
            requires_response: true,
        })
        .await;

    let output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Broadcast durable lane",
                "details": "Prove notify_room uses the live attached session config.",
                "notify_room": true,
            }),
        ))
        .await
        .expect("open_task should succeed");

    let result = parse_result(output);
    assert_eq!(result["room_notified"], json!(true));

    let requests = server
        .received_requests()
        .await
        .expect("wiremock should capture requests");
    let message_request = requests
        .iter()
        .find(|request| request.method == "POST" && request.url.path() == "/hollywood/v1/messages")
        .expect("room notification request should be sent");
    let body: Value =
        serde_json::from_slice(&message_request.body).expect("room notify body should be json");
    assert_eq!(body["room"], json!("repo/losangelex"));
    assert_eq!(body["sender_id"], json!(session.thread_id().to_string()));
    assert_eq!(body["message_kind"], json!("broadcast"));

    let unresolved = session
        .resolve_hollywood_obligations_for_turn(&turn.sub_id)
        .await;
    assert!(
        unresolved.is_empty(),
        "successful room send should resolve same-room obligations"
    );
}

#[tokio::test]
async fn non_general_open_task_derives_task_room_from_hollywood_room() {
    let server = MockServer::start().await;
    Mock::given(method("GET"))
        .and(path("/hollywood/v1/rooms"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({ "rooms": [] })))
        .expect(1)
        .mount(&server)
        .await;

    let (session, turn, _state_db) = make_session_with_state_db().await;
    session
        .set_hollywood_session_config(Some(crate::hollywood::HollywoodSessionConfig {
            url: server.uri(),
            room: "repo/losangelex".to_string(),
            observed_rooms: vec!["main".to_string()],
            wake_rooms: Vec::new(),
            attention_mode: "focused".to_string(),
        }))
        .await;

    let output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "coordination_act",
            json!({
                "action": "open_task",
                "title": "Review Hollywood read filters",
                "kind": "review",
                "notify_room": false,
            }),
        ))
        .await
        .expect("open_task should succeed");

    let result = parse_result(output);
    assert_eq!(
        result["task"]["room"],
        json!("task/losangelex/review-hollywood-read-filters")
    );
}

#[tokio::test]
async fn self_authored_hollywood_message_does_not_create_obligation() {
    let (session, turn, _state_db) = make_session_with_state_db().await;
    let identities = crate::hollywood::identities(session.thread_id(), None);
    let sender_id = identities
        .get(1)
        .cloned()
        .unwrap_or_else(|| session.thread_id().to_string());

    session
        .add_hollywood_obligation(&HollywoodInputMessage {
            message_id: 8,
            room: "repo/losangelex".to_string(),
            sender_id,
            body: "Reply required from myself.".to_string(),
            mentions: Vec::new(),
            attention: Some("focused".to_string()),
            message_kind: Some("direct".to_string()),
            obligation: Some("obligation".to_string()),
            synthetic_brief: None,
            requires_response: true,
        })
        .await;

    let unresolved = session
        .resolve_hollywood_obligations_for_turn(&turn.sub_id)
        .await;
    assert!(
        unresolved.is_empty(),
        "self-authored Hollywood messages should not create obligations"
    );
}

#[tokio::test]
async fn list_coordination_tasks_defaults_to_attached_room_scope() {
    let (session, turn, state_db) = make_session_with_state_db().await;
    session
        .set_hollywood_session_config(Some(crate::hollywood::HollywoodSessionConfig {
            url: "http://127.0.0.1:8765".to_string(),
            room: "repo/current-room".to_string(),
            observed_rooms: vec!["main".to_string()],
            wake_rooms: Vec::new(),
            attention_mode: "focused".to_string(),
        }))
        .await;

    state_db
        .create_coordination_task(codex_state::CoordinationTaskCreateParams {
            id: "task-current".to_string(),
            creator_thread_id: session.thread_id(),
            owner_thread_id: None,
            reserved_path_claims: Vec::new(),
            claim_lease_seconds: codex_state::DEFAULT_COORDINATION_LEASE_SECONDS,
            team_id: None,
            room: Some("repo/current-room".to_string()),
            kind: codex_state::CoordinationTaskKind::Qa,
            summary: "Current room task".to_string(),
            details: "Should be visible by default.".to_string(),
            requested_capability: None,
            dependency_task_ids: Vec::new(),
            act_id: "act-current".to_string(),
            act_summary: Some("opened current room task".to_string()),
            act_payload_json: "{}".to_string(),
        })
        .await
        .expect("current room task should be created");
    state_db
        .create_coordination_task(codex_state::CoordinationTaskCreateParams {
            id: "task-other".to_string(),
            creator_thread_id: session.thread_id(),
            owner_thread_id: None,
            reserved_path_claims: Vec::new(),
            claim_lease_seconds: codex_state::DEFAULT_COORDINATION_LEASE_SECONDS,
            team_id: None,
            room: Some("repo/other-room".to_string()),
            kind: codex_state::CoordinationTaskKind::Qa,
            summary: "Other room task".to_string(),
            details: "Should be hidden by default.".to_string(),
            requested_capability: None,
            dependency_task_ids: Vec::new(),
            act_id: "act-other".to_string(),
            act_summary: Some("opened other room task".to_string()),
            act_payload_json: "{}".to_string(),
        })
        .await
        .expect("other room task should be created");

    let output = coordination_handler()
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "list_coordination_tasks",
            json!({
                "statuses": ["open"],
            }),
        ))
        .await
        .expect("list_coordination_tasks should succeed");

    let result = parse_result(output);
    assert_eq!(result["tasks"].as_array().map(Vec::len), Some(1));
    assert_eq!(result["tasks"][0]["id"], json!("task-current"));
    assert_eq!(result["tasks"][0]["room"], json!("repo/current-room"));
}
