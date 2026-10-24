//! Real native RPC/strict history/reopen journeys with scripted provider wire.
//! No Hollywood authorization, retained execution-payload, or model semantics claim.
use super::context_window_preflight::WAIT;
use super::context_window_preflight::begin;
use super::context_window_preflight::inspect;
use super::context_window_preflight::packet;
use super::context_window_preflight::policy;
use super::context_window_preflight::state;
use anyhow::Result;
use app_test_support::MockResponsesConfig;
use app_test_support::TestAppServer;
use codex_app_server_protocol::*;
use core_test_support::responses;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use sha2::Digest;
use sha2::Sha256;
use tempfile::TempDir;
use tokio::time::timeout;

async fn ready() -> Result<(
    TempDir,
    TestAppServer,
    ThreadStartResponse,
    responses::ResponseMock,
    wiremock::MockServer,
)> {
    let server = responses::start_mock_server().await;
    let mock = responses::mount_sse_sequence(
        &server,
        vec![
            responses::sse(vec![
                responses::ev_assistant_message("first", "initial complete"),
                responses::ev_completed("one"),
            ]),
            responses::sse(vec![
                responses::ev_assistant_message("second", "continued"),
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
    let started = rpc
        .start_thread(ThreadStartParams {
            automatic_context_refill: Some(policy()),
            ..Default::default()
        })
        .await?;
    begin(&mut rpc, &started.thread.id).await?;
    let completed: TurnCompletedNotification =
        timeout(WAIT, rpc.read_notification("turn/completed")).await??;
    assert_eq!(completed.turn.status, TurnStatus::Completed);
    assert_eq!(mock.requests().len(), 1);
    Ok((home, rpc, started, mock, server))
}

fn check_transaction(bytes: &[u8], receipt: &ContextWindowInstalledParams) -> Result<()> {
    let records: Vec<Value> = bytes
        .split(|byte| *byte == b'\n')
        .filter(|line| !line.is_empty())
        .map(serde_json::from_slice)
        .collect::<std::result::Result<_, _>>()?;
    let intents: Vec<_> = records
        .iter()
        .enumerate()
        .filter(|(_, record)| record["payload"]["type"] == "context_window_refill_intent")
        .collect();
    assert_eq!(intents.len(), 1);
    let index = intents[0].0;
    assert_eq!(
        records[index]["payload"]["operationId"],
        receipt.operation_id
    );
    assert_eq!(records[index]["payload"]["reason"], "explicitRequest");
    assert_eq!(records[index + 1]["type"], "compacted");
    let native = &records[index + 1]["payload"]["resume_metadata"]["native_context"];
    assert_eq!(native["mode"], "idle_request");
    assert_eq!(native["thread_id"], receipt.thread_id);
    assert_eq!(native["context_id"], receipt.context_id);
    assert_eq!(native["world_state"]["full"], true);
    assert!(
        native["world_state"]["state"]
            .as_object()
            .is_some_and(|state| !state.is_empty())
    );
    assert!(native["reference_context"].is_object());
    assert_eq!(
        records[index + 2]["payload"]["type"],
        "context_window_refill_installed"
    );
    assert_eq!(
        records[index + 2]["payload"]["operationId"],
        receipt.operation_id
    );
    assert_eq!(
        receipt.native_history_sha256,
        format!(
            "{:x}",
            Sha256::digest(&bytes[..receipt.native_history_bytes as usize])
        )
    );
    assert_eq!(
        records
            .iter()
            .filter(|record| record["payload"]["type"] == "context_window_refill_installed")
            .count(),
        1
    );
    Ok(())
}

async fn continue_input(rpc: &mut TestAppServer, thread: &str) -> Result<()> {
    let id = rpc
        .send_turn_start_request(TurnStartParams {
            thread_id: thread.into(),
            input: vec![UserInput::Text {
                text: "Continue from the installed selected material.".into(),
                text_elements: vec![],
            }],
            ..Default::default()
        })
        .await?;
    let _: TurnStartResponse = timeout(WAIT, rpc.read_response(id)).await??;
    Ok(())
}

#[tokio::test]
async fn idle_replacement_preserves_native_checkpoint_and_next_real_input() -> Result<()> {
    let (_home, mut rpc, started, mock, _server) = ready().await?;
    let thread = &started.thread.id;
    let cut = state(&mut rpc, thread).await?;
    let data = packet(&cut);
    let measured = inspect(&mut rpc, thread, &cut, &data).await?.preflight;
    let before = tokio::fs::read(started.thread.path.as_ref().unwrap()).await?;
    let mut changed = measured.clone();
    changed.packet_sha256 = "0".repeat(64);
    let invalid = rpc
        .send_raw_request(
            "thread/contextWindow/replaceIdle",
            Some(json!({"threadId":thread,"preflight":changed,"packet":data})),
        )
        .await?;
    let error = timeout(
        WAIT,
        rpc.read_stream_until_error_message(RequestId::Integer(invalid)),
    )
    .await??;
    assert!(
        error
            .error
            .message
            .contains("native idle replacement refused")
    );
    assert_eq!(state(&mut rpc, thread).await?, cut);
    assert_eq!(
        tokio::fs::read(started.thread.path.as_ref().unwrap()).await?,
        before
    );
    let id = rpc
        .send_raw_request(
            "thread/contextWindow/replaceIdle",
            Some(json!({"threadId":thread,"preflight":measured,"packet":data})),
        )
        .await?;
    let ServerRequest::ContextWindowIdleInstalled {
        request_id,
        params: receipt,
    } = timeout(WAIT, rpc.read_stream_until_request_message()).await??
    else {
        panic!("expected separate idle acknowledgement")
    };
    assert_eq!(mock.requests().len(), 1);
    check_transaction(
        &tokio::fs::read(started.thread.path.as_ref().unwrap()).await?,
        &receipt,
    )?;
    rpc.send_response(
        request_id,
        json!({"operationId":receipt.operation_id,"status":"recorded"}),
    )
    .await?;
    let installed: ThreadContextWindowReplaceIdleResponse =
        timeout(WAIT, rpc.read_response(id)).await??;
    assert_eq!(installed.receipt, receipt);
    let current = state(&mut rpc, thread).await?;
    assert!(current.idle);
    assert_eq!(current.last_started_turn_id, cut.last_started_turn_id);
    assert!(current.held_operation_id.is_none());
    assert_ne!(current.window_id, cut.window_id);
    assert_eq!(mock.requests().len(), 1);
    continue_input(&mut rpc, thread).await?;
    let completed: TurnCompletedNotification =
        timeout(WAIT, rpc.read_notification("turn/completed")).await??;
    assert_eq!(completed.turn.status, TurnStatus::Completed);
    assert_eq!(mock.requests().len(), 2);
    let input = mock.requests()[1].body_json()["input"].to_string();
    assert!(input.contains("original selected work"));
    assert!(input.contains("Continue from the installed selected material."));
    assert!(!input.contains("Actual native context recording fixture"));
    check_transaction(
        &tokio::fs::read(started.thread.path.as_ref().unwrap()).await?,
        &receipt,
    )?;
    Ok(())
}

#[tokio::test]
async fn idle_replacement_lost_ack_recovers_original_receipt_without_repeat_install() -> Result<()>
{
    let (home, mut rpc, started, mock, _server) = ready().await?;
    let thread = &started.thread.id;
    let cut = state(&mut rpc, thread).await?;
    let data = packet(&cut);
    let measured = inspect(&mut rpc, thread, &cut, &data).await?.preflight;
    let _id = rpc
        .send_raw_request(
            "thread/contextWindow/replaceIdle",
            Some(json!({"threadId":thread,"preflight":measured,"packet":data})),
        )
        .await?;
    let ServerRequest::ContextWindowIdleInstalled {
        request_id: _request_id,
        params: receipt,
    } = timeout(WAIT, rpc.read_stream_until_request_message()).await??
    else {
        panic!("expected original idle acknowledgement")
    };
    // Close the actual original transport without responding to the callback.
    // The API result is unknown; observe the durable original receipt, never resend.
    assert_eq!(mock.requests().len(), 1);
    check_transaction(
        &tokio::fs::read(started.thread.path.as_ref().unwrap()).await?,
        &receipt,
    )?;
    timeout(WAIT, rpc.shutdown_gracefully()).await??;
    let mut resumed = TestAppServer::builder()
        .with_codex_home(home.path())
        .build_initialized()
        .await?;
    let resume = resumed
        .send_thread_resume_request(ThreadResumeParams {
            thread_id: thread.clone(),
            automatic_context_refill: Some(policy()),
            ..Default::default()
        })
        .await?;
    let _: ThreadResumeResponse = timeout(WAIT, resumed.read_response(resume)).await??;
    assert_eq!(
        state(&mut resumed, thread)
            .await?
            .held_operation_id
            .as_deref(),
        Some(receipt.operation_id.as_str())
    );
    continue_input(&mut resumed, thread).await?;
    let ServerRequest::ContextWindowReconcile {
        request_id,
        params: original,
    } = timeout(WAIT, resumed.read_stream_until_request_message()).await??
    else {
        panic!("expected original receipt observation, no replacement prepare")
    };
    assert_eq!(original, receipt);
    assert_eq!(mock.requests().len(), 1);
    resumed
        .send_response(
            request_id,
            json!({"operationId":original.operation_id,"status":"recorded"}),
        )
        .await?;
    let completed: TurnCompletedNotification =
        timeout(WAIT, resumed.read_notification("turn/completed")).await??;
    assert_eq!(completed.turn.status, TurnStatus::Completed);
    assert_eq!(mock.requests().len(), 2);
    let input = mock.requests()[1].body_json()["input"].to_string();
    assert!(input.contains("original selected work"));
    check_transaction(
        &tokio::fs::read(started.thread.path.as_ref().unwrap()).await?,
        &receipt,
    )?;
    Ok(())
}
