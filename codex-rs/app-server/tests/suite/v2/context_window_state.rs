//! Real native RPC/window identity. No model turn or retained installation.
use anyhow::Result;
use app_test_support::MockResponsesConfig;
use app_test_support::TestAppServer;
use codex_app_server_protocol::*;
use core_test_support::responses;
use pretty_assertions::assert_eq;
use serde_json::json;
use std::time::Duration;
use tempfile::TempDir;
use tokio::time::timeout;

const WAIT: Duration = Duration::from_secs(60);
const CONTEXT: &str = "897477fd-549e-46fa-a90b-e33528cbb7cc";

fn policy() -> AutomaticContextRefillPolicy {
    serde_json::from_value(json!({"type":"canonicalRetainedActions",
        "contextId":CONTEXT,"purpose":"writer"}))
    .unwrap()
}

async fn read(rpc: &mut TestAppServer, thread: &str) -> Result<ThreadContextWindowReadResponse> {
    let id = rpc
        .send_raw_request(
            "thread/contextWindow/read",
            Some(json!({"threadId":thread})),
        )
        .await?;
    timeout(WAIT, rpc.read_response(id)).await?
}

async fn materialize(rpc: &mut TestAppServer, thread: &str) -> Result<()> {
    let id = rpc
        .send_raw_request(
            "thread/name/set",
            Some(json!({"threadId":thread,"name":"fixture:window-state"})),
        )
        .await?;
    let _: ThreadSetNameResponse = timeout(WAIT, rpc.read_response(id)).await??;
    Ok(())
}

#[tokio::test]
async fn owned_window_read_is_repeatable_without_history_or_provider_work() -> Result<()> {
    let server = responses::start_mock_server().await;
    let home = TempDir::new()?;
    MockResponsesConfig::new(&server.uri()).write(home.path())?;
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
    materialize(&mut rpc, &thread.id).await?;
    let path = thread.path.as_ref().unwrap();
    let before = tokio::fs::read(path).await?;
    let first = read(&mut rpc, &thread.id).await?;
    let second = read(&mut rpc, &thread.id).await?;
    assert_eq!(first, second);
    assert_eq!(first.state.thread_id, thread.id);
    assert_eq!(first.state.context_id, CONTEXT);
    assert!(first.state.idle);
    assert_eq!(first.state.active_turn_id, None);
    assert_eq!(first.state.last_started_turn_id, None);
    assert_eq!(first.state.held_operation_id, None);
    assert_eq!(tokio::fs::read(path).await?, before);
    assert_eq!(server.received_requests().await.unwrap().len(), 0);
    Ok(())
}

#[tokio::test]
async fn ordinary_profile_cannot_use_retained_window_read() -> Result<()> {
    let server = responses::start_mock_server().await;
    let home = TempDir::new()?;
    MockResponsesConfig::new(&server.uri()).write(home.path())?;
    let mut rpc = TestAppServer::builder()
        .with_codex_home(home.path())
        .build_initialized()
        .await?;
    let thread = rpc.start_thread(ThreadStartParams::default()).await?.thread;
    materialize(&mut rpc, &thread.id).await?;
    let before = tokio::fs::read(thread.path.as_ref().unwrap()).await?;
    let id = rpc
        .send_raw_request(
            "thread/contextWindow/read",
            Some(json!({"threadId":thread.id})),
        )
        .await?;
    let error = timeout(
        WAIT,
        rpc.read_stream_until_error_message(RequestId::Integer(id)),
    )
    .await??;
    assert!(
        error
            .error
            .message
            .contains("explicit retained-context policy required")
    );
    assert_eq!(
        tokio::fs::read(thread.path.as_ref().unwrap()).await?,
        before
    );
    assert_eq!(server.received_requests().await.unwrap().len(), 0);
    Ok(())
}

#[tokio::test]
async fn cold_resume_without_policy_does_not_restore_retained_authority() -> Result<()> {
    let server = responses::start_mock_server().await;
    let home = TempDir::new()?;
    MockResponsesConfig::new(&server.uri()).write(home.path())?;
    let mut original = TestAppServer::builder()
        .with_codex_home(home.path())
        .build_initialized()
        .await?;
    let thread = original
        .start_thread(ThreadStartParams {
            automatic_context_refill: Some(policy()),
            ..Default::default()
        })
        .await?
        .thread;
    materialize(&mut original, &thread.id).await?;
    read(&mut original, &thread.id).await?;
    drop(original);
    let mut resumed = TestAppServer::builder()
        .with_codex_home(home.path())
        .build_initialized()
        .await?;
    let id = resumed
        .send_thread_resume_request(ThreadResumeParams {
            thread_id: thread.id.clone(),
            ..Default::default()
        })
        .await?;
    let _: ThreadResumeResponse = timeout(WAIT, resumed.read_response(id)).await??;
    let id = resumed
        .send_raw_request(
            "thread/contextWindow/read",
            Some(json!({"threadId":thread.id})),
        )
        .await?;
    let error = timeout(
        WAIT,
        resumed.read_stream_until_error_message(RequestId::Integer(id)),
    )
    .await??;
    assert!(
        error
            .error
            .message
            .contains("explicit retained-context policy required")
    );
    assert_eq!(server.received_requests().await.unwrap().len(), 0);
    Ok(())
}

#[tokio::test]
async fn retained_policy_is_rejected_for_reader_before_any_model_work() -> Result<()> {
    let server = responses::start_mock_server().await;
    let home = TempDir::new()?;
    MockResponsesConfig::new(&server.uri()).write(home.path())?;
    let mut rpc = TestAppServer::builder()
        .with_codex_home(home.path())
        .build_initialized()
        .await?;
    let id=rpc.send_raw_request("thread/start",Some(json!({
        "automaticContextRefill":{"type":"canonicalRetainedActions","contextId":CONTEXT,"purpose":"reader"}
    }))).await?;
    let error = timeout(
        WAIT,
        rpc.read_stream_until_error_message(RequestId::Integer(id)),
    )
    .await??;
    assert!(
        error
            .error
            .message
            .contains("retained native evidence requires Writer purpose")
    );
    assert_eq!(server.received_requests().await.unwrap().len(), 0);
    Ok(())
}
