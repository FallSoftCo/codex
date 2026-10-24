//! Actual native RPC/core/rollout with scripted provider wire. No real-model,
//! Hollywood authorization, retained-execution-payload or idle-installation claim.
use anyhow::Result;
use app_test_support::MockResponsesConfig;
use app_test_support::TestAppServer;
use codex_app_server_protocol::*;
use core_test_support::responses;
use pretty_assertions::assert_eq;
use serde_json::json;
use sha2::Digest;
use sha2::Sha256;
use std::time::Duration;
use tempfile::TempDir;
use tokio::time::timeout;

pub(super) const WAIT: Duration = Duration::from_secs(60);
const CONTEXT: &str = "897477fd-549e-46fa-a90b-e33528cbb7cc";
fn digest(value: &[u8]) -> String {
    format!("{:x}", Sha256::digest(value))
}
pub(super) fn policy() -> AutomaticContextRefillPolicy {
    serde_json::from_value(
        json!({"type":"canonicalRetainedActions","contextId":CONTEXT,"purpose":"writer"}),
    )
    .unwrap()
}
pub(super) async fn state(rpc: &mut TestAppServer, thread: &str) -> Result<ContextWindowState> {
    let id = rpc
        .send_raw_request(
            "thread/contextWindow/read",
            Some(json!({"threadId":thread})),
        )
        .await?;
    let response: ThreadContextWindowReadResponse = timeout(WAIT, rpc.read_response(id)).await??;
    Ok(response.state)
}
pub(super) fn packet(state: &ContextWindowState) -> ContextWindowRefillResponse {
    // Canonical selected-input fixture, deliberately no claimed native action pins.
    let agent = "22222222-2222-4222-8222-222222222222";
    let operation = "packet-inspection-original";
    let content = json!({"schema":"lax-context-rebuild/v1","agentId":agent,
        "contextId":state.context_id,"purpose":"writer","nativeThread":state.thread_id,
        "selection":{"selectionRevision":1,"marks":[]},"nextMaterialIds":["work"],
        "records":[{"reference":"role","content":{"role":"writer"}},
            {"reference":"work","content":{"objective":"original selected work"}}]})
    .to_string();
    let snapshot_sha = digest(content.as_bytes());
    let bundle = json!({"schema":"lax-retained-native-actions/v1","agentId":agent,
        "contextId":state.context_id,"purpose":"writer","nativeThread":state.thread_id,
        "selectionRevision":1,"canonicalSnapshotSha256":snapshot_sha,"entries":[]})
    .to_string();
    let mut items = Vec::new();
    for (namespace, name, schema, text) in [
        (
            "hollywood",
            "context_refill",
            "lax-context-refill-fragment/v1",
            content.as_str(),
        ),
        ("lax", "context_actions", "lax-native-action-index/v1", "[]"),
        (
            "lax",
            "retained_actions",
            "lax-retained-native-actions-fragment/v1",
            bundle.as_str(),
        ),
    ] {
        let mut output = json!({"schema":schema,"sha256":digest(text.as_bytes()),
            "totalBytes":text.len(),"offset":0,"content":text});
        if name == "context_refill" {
            output["operationId"] = operation.into();
        }
        if name == "context_actions" {
            output["retrieval"] = "context_action_read".into();
            output["meaning"]="Original action receipts for unfinished work. Never replay an effect merely because context was reset.".into();
        }
        items.push(json!({"type":"function_call_output","namespace":namespace,"name":name,"output":output.to_string()}));
    }
    ContextWindowRefillResponse {
        thread_id: state.thread_id.clone(),
        turn_id: state
            .active_turn_id
            .clone()
            .or_else(|| state.last_started_turn_id.clone())
            .unwrap_or_else(|| "no-original-turn".into()),
        operation_id: operation.into(),
        context_id: state.context_id.clone(),
        purpose: state.purpose.clone(),
        window_id: state.window_id.clone(),
        history_version: state.history_version,
        snapshot_operation_id: operation.into(),
        snapshot_read_point: "fixture-cut".into(),
        snapshot_sha256: snapshot_sha,
        native_actions_sha256: digest(b"[]"),
        selection_revision: 1,
        total_bytes: content.len() as u64,
        items,
    }
}
pub(super) async fn inspect(
    rpc: &mut TestAppServer,
    thread: &str,
    state: &ContextWindowState,
    packet: &ContextWindowRefillResponse,
) -> Result<ThreadContextWindowPreflightResponse> {
    let id = rpc
        .send_raw_request(
            "thread/contextWindow/preflight",
            Some(json!({"threadId":thread,"state":state,"packet":packet})),
        )
        .await?;
    timeout(WAIT, rpc.read_response(id)).await?
}
async fn refuse(
    rpc: &mut TestAppServer,
    thread: &str,
    state: &ContextWindowState,
    packet: &ContextWindowRefillResponse,
) -> Result<()> {
    let id = rpc
        .send_raw_request(
            "thread/contextWindow/preflight",
            Some(json!({"threadId":thread,"state":state,"packet":packet})),
        )
        .await?;
    let error = timeout(
        WAIT,
        rpc.read_stream_until_error_message(RequestId::Integer(id)),
    )
    .await??;
    assert!(error.error.message.contains("native preflight refused"));
    Ok(())
}
pub(super) async fn begin(rpc: &mut TestAppServer, thread: &str) -> Result<()> {
    let id = rpc
        .send_turn_start_request(TurnStartParams {
            thread_id: thread.into(),
            input: vec![UserInput::Text {
                text: "Actual native context recording fixture".into(),
                text_elements: vec![],
            }],
            ..Default::default()
        })
        .await?;
    let _: TurnStartResponse = timeout(WAIT, rpc.read_response(id)).await??;
    Ok(())
}

#[tokio::test]
async fn actual_idle_preflight_is_repeatable_read_only_and_refuses_stale_or_invalid_packets()
-> Result<()> {
    let server = responses::start_mock_server().await;
    let mock = responses::mount_sse_sequence(
        &server,
        vec![responses::sse(vec![
            responses::ev_assistant_message("message", "fixture complete"),
            responses::ev_completed("one"),
        ])],
    )
    .await;
    let home = TempDir::new()?;
    MockResponsesConfig::new(&server.uri())
        .with_provider_config("supports_websockets = false")
        .write(home.path())?;
    let mut rpc = TestAppServer::builder()
        .with_codex_home(home.path())
        .build_initialized()
        .await?;
    let thread = rpc
        .start_thread(ThreadStartParams {
            automatic_context_refill: Some(policy()),
            ..Default::default()
        })
        .await?
        .thread;
    begin(&mut rpc, &thread.id).await?;
    let completed: TurnCompletedNotification =
        timeout(WAIT, rpc.read_notification("turn/completed")).await??;
    assert_eq!(completed.turn.status, TurnStatus::Completed);
    let original = state(&mut rpc, &thread.id).await?;
    assert!(original.idle);
    let data = packet(&original);
    let before = tokio::fs::read(thread.path.as_ref().unwrap()).await?;
    let first = inspect(&mut rpc, &thread.id, &original, &data).await?;
    let mut reordered = serde_json::to_value(&data)?;
    reordered.sort_all_objects();
    let reordered: ContextWindowRefillResponse = serde_json::from_value(reordered)?;
    let second = inspect(&mut rpc, &thread.id, &original, &reordered).await?;
    assert_eq!(first, second);
    assert_eq!(first.preflight.state, original);
    assert!(first.preflight.prefix_item_count > 0);
    assert!(first.preflight.replacement_item_count > first.preflight.prefix_item_count);
    assert_eq!(first.preflight.packet_sha256.len(), 64);
    let mut stale = original.clone();
    stale.history_version += 1;
    refuse(&mut rpc, &thread.id, &stale, &data).await?;
    let mut invalid = data.clone();
    invalid.context_id = "other-context".into();
    refuse(&mut rpc, &thread.id, &original, &invalid).await?;
    let mut oversized = data.clone();
    oversized.items[0]["output"] = "x".repeat(32769).into();
    refuse(&mut rpc, &thread.id, &original, &oversized).await?;
    assert_eq!(state(&mut rpc, &thread.id).await?, original);
    assert_eq!(
        tokio::fs::read(thread.path.as_ref().unwrap()).await?,
        before
    );
    assert_eq!(mock.requests().len(), 1);
    Ok(())
}

#[tokio::test]
async fn active_tool_wait_can_preflight_without_steering_completing_or_starting_work() -> Result<()>
{
    let server = responses::start_mock_server().await;
    let mock = responses::mount_sse_sequence(
        &server,
        vec![
            responses::sse(vec![
                responses::ev_function_call("original-tool", "pause", "{}"),
                responses::ev_completed("one"),
            ]),
            responses::sse(vec![
                responses::ev_assistant_message("message", "fixture complete"),
                responses::ev_completed("two"),
            ]),
        ],
    )
    .await;
    let home = TempDir::new()?;
    MockResponsesConfig::new(&server.uri())
        .with_provider_config("supports_websockets = false")
        .write(home.path())?;
    let mut rpc = TestAppServer::builder()
        .with_codex_home(home.path())
        .build_initialized()
        .await?;
    let thread = rpc
        .start_thread(ThreadStartParams {
            automatic_context_refill: Some(policy()),
            dynamic_tools: Some(vec![DynamicToolSpec::Function(DynamicToolFunctionSpec {
                name: "pause".into(),
                description: "Original held tool fixture".into(),
                defer_loading: false,
                input_schema: json!({"type":"object","properties":{},"additionalProperties":false}),
            })]),
            ..Default::default()
        })
        .await?
        .thread;
    begin(&mut rpc, &thread.id).await?;
    let ServerRequest::DynamicToolCall { request_id, params } =
        timeout(WAIT, rpc.read_stream_until_request_message()).await??
    else {
        panic!("expected original tool")
    };
    assert_eq!(params.call_id, "original-tool");
    let original = state(&mut rpc, &thread.id).await?;
    assert!(!original.idle);
    assert!(original.active_turn_id.is_some());
    let inspected = inspect(&mut rpc, &thread.id, &original, &packet(&original)).await?;
    assert_eq!(inspected.preflight.state, original);
    let refused = rpc
        .send_raw_request(
            "thread/contextWindow/replaceIdle",
            Some(json!({
                "threadId":thread.id,"preflight":inspected.preflight,"packet":packet(&original)
            })),
        )
        .await?;
    let error = timeout(
        WAIT,
        rpc.read_stream_until_error_message(RequestId::Integer(refused)),
    )
    .await??;
    assert!(
        error
            .error
            .message
            .contains("native idle replacement refused")
    );
    assert_eq!(state(&mut rpc, &thread.id).await?, original);
    assert_eq!(mock.requests().len(), 1);
    rpc.send_response(
        request_id,
        json!({"contentItems":[{"type":"inputText","text":"original result"}],"success":true}),
    )
    .await?;
    let completed: TurnCompletedNotification =
        timeout(WAIT, rpc.read_notification("turn/completed")).await??;
    assert_eq!(Some(completed.turn.id), original.active_turn_id);
    assert_eq!(completed.turn.status, TurnStatus::Completed);
    assert_eq!(mock.requests().len(), 2);
    Ok(())
}
