//! Real native/RPC execution against a deliberately synthetic provider.
//! These fixtures establish the lifecycle contract, not model capability.
use anyhow::Result;
use app_test_support::MockResponsesConfig;
use app_test_support::TestAppServer;
use codex_app_server_protocol::*;
use core_test_support::responses;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use std::time::Duration;
use tempfile::TempDir;
use tokio::time::timeout;

const WAIT: Duration = Duration::from_secs(60);

async fn start(rpc: &mut TestAppServer, thread: &str) -> Result<()> {
    let request = rpc
        .send_turn_start_request(TurnStartParams {
            thread_id: thread.into(),
            input: vec![UserInput::Text {
                text: "Do the work".into(),
                text_elements: vec![],
            }],
            ..Default::default()
        })
        .await?;
    let _: TurnStartResponse = timeout(WAIT, rpc.read_response(request)).await??;
    Ok(())
}

async fn tool(rpc: &mut TestAppServer, expected: &str, complete: bool) -> Result<()> {
    let ServerRequest::DynamicToolCall { request_id, params } =
        timeout(WAIT, rpc.read_stream_until_request_message()).await??
    else {
        panic!("expected a dynamic tool");
    };
    assert_eq!(params.call_id, expected);
    let mut result =
        json!({"success":true,"contentItems":[{"type":"inputText","text":"recorded"}]});
    if complete {
        result["turnControl"] = json!("complete");
    }
    rpc.send_response(request_id, result).await?;
    Ok(())
}

async fn finished(rpc: &mut TestAppServer) -> Result<Value> {
    let result = timeout(
        WAIT,
        rpc.read_stream_until_notification_message("turn/completed"),
    )
    .await??;
    Ok(result.params.unwrap()["turn"].clone())
}

fn declarations() -> Vec<DynamicToolSpec> {
    vec![DynamicToolSpec::Function(DynamicToolFunctionSpec {
        name: "settle".into(),
        description: "Record scoped work state".into(),
        defer_loading: false,
        input_schema: json!({"type":"object","properties":{},"additionalProperties":false}),
    })]
}

#[tokio::test]
async fn host_tool_settles_with_provider_auto_without_extra_sample() -> Result<()> {
    let server = responses::start_mock_server().await;
    let mock = responses::mount_sse_sequence(
        &server,
        vec![
            responses::sse(vec![
                responses::ev_function_call("first", "settle", "{}"),
                responses::ev_completed("one"),
            ]),
            responses::sse(vec![
                responses::ev_function_call("second", "settle", "{}"),
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
            inference_completion: Some(InferenceCompletionPolicy::HostTool),
            dynamic_tools: Some(declarations()),
            ..Default::default()
        })
        .await?;
    assert_eq!(
        started.inference_completion,
        Some(InferenceCompletionPolicy::HostTool)
    );
    start(&mut rpc, &started.thread.id).await?;
    tool(&mut rpc, "first", /*complete*/ false).await?;
    tool(&mut rpc, "second", /*complete*/ true).await?;
    assert_eq!(finished(&mut rpc).await?["status"], json!("completed"));
    let requests = mock.requests();
    assert_eq!(requests.len(), 2);
    for request in requests {
        assert_eq!(request.body_json()["tool_choice"], json!("auto"));
    }
    Ok(())
}

#[tokio::test]
async fn host_tool_plain_final_after_execution_is_failed_without_retry() -> Result<()> {
    let server = responses::start_mock_server().await;
    let mock = responses::mount_sse_sequence(
        &server,
        vec![
            responses::sse(vec![
                responses::ev_function_call("first", "settle", "{}"),
                responses::ev_completed("one"),
            ]),
            responses::sse(vec![
                responses::ev_assistant_message("empty", ""),
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
            inference_completion: Some(InferenceCompletionPolicy::HostTool),
            dynamic_tools: Some(declarations()),
            ..Default::default()
        })
        .await?;
    start(&mut rpc, &started.thread.id).await?;
    tool(&mut rpc, "first", /*complete*/ false).await?;
    let done = finished(&mut rpc).await?;
    assert_eq!(done["status"], json!("failed"));
    assert!(
        done["error"]["message"]
            .as_str()
            .unwrap()
            .contains("without authenticated tool settlement")
    );
    assert_eq!(mock.requests().len(), 2);
    for request in mock.requests() {
        assert_eq!(request.body_json()["tool_choice"], json!("auto"));
    }
    Ok(())
}

#[tokio::test]
async fn ordinary_model_final_still_completes_with_auto_choice() -> Result<()> {
    let server = responses::start_mock_server().await;
    let mock = responses::mount_sse_once(
        &server,
        responses::sse(vec![
            responses::ev_assistant_message("answer", "done"),
            responses::ev_completed("one"),
        ]),
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
    let started = rpc.start_thread(ThreadStartParams::default()).await?;
    assert_eq!(
        started.inference_completion,
        Some(InferenceCompletionPolicy::Model)
    );
    start(&mut rpc, &started.thread.id).await?;
    assert_eq!(finished(&mut rpc).await?["status"], json!("completed"));
    assert_eq!(
        mock.single_request().body_json()["tool_choice"],
        json!("auto")
    );
    Ok(())
}

#[tokio::test]
async fn host_tool_policy_is_reasserted_on_cold_resume() -> Result<()> {
    let server = responses::start_mock_server().await;
    let mock = responses::mount_sse_sequence(
        &server,
        vec![responses::sse(vec![
            responses::ev_function_call("cold", "settle", "{}"),
            responses::ev_completed("one"),
        ])],
    )
    .await;
    let home = TempDir::new()?;
    MockResponsesConfig::new(&server.uri())
        .with_provider_config("supports_websockets = false")
        .write(home.path())?;
    let mut original = TestAppServer::builder()
        .with_codex_home(home.path())
        .build_initialized()
        .await?;
    let started = original
        .start_thread(ThreadStartParams {
            inference_completion: Some(InferenceCompletionPolicy::HostTool),
            dynamic_tools: Some(declarations()),
            ..Default::default()
        })
        .await?;
    // Match the installed purpose runtime's metadata-only materialization:
    // upstream start is lazy until metadata or actual work is persisted.
    // This runs no model and keeps this a never-used-thread cold-resume check.
    let materialize = original
        .send_raw_request(
            "thread/name/set",
            Some(json!({"threadId":started.thread.id,"name":"fixture:writer"})),
        )
        .await?;
    let _: ThreadSetNameResponse = timeout(WAIT, original.read_response(materialize)).await??;
    // A loaded owner's lifecycle cannot be silently replaced or attached.
    let warm = original
        .send_thread_resume_request(ThreadResumeParams {
            thread_id: started.thread.id.clone(),
            inference_completion: Some(InferenceCompletionPolicy::HostTool),
            ..Default::default()
        })
        .await?;
    let rejected = timeout(
        WAIT,
        original.read_stream_until_error_message(RequestId::Integer(warm)),
    )
    .await??;
    assert!(rejected.error.message.contains("lifecycle ownership"));
    drop(original);
    let mut rpc = TestAppServer::builder()
        .with_codex_home(home.path())
        .build_initialized()
        .await?;
    let request = rpc
        .send_thread_resume_request(ThreadResumeParams {
            thread_id: started.thread.id.clone(),
            inference_completion: Some(InferenceCompletionPolicy::HostTool),
            ..Default::default()
        })
        .await?;
    let resumed: ThreadResumeResponse = timeout(WAIT, rpc.read_response(request)).await??;
    assert_eq!(
        resumed.inference_completion,
        Some(InferenceCompletionPolicy::HostTool)
    );
    assert_eq!(resumed.thread.id, started.thread.id);
    start(&mut rpc, &resumed.thread.id).await?;
    tool(&mut rpc, "cold", /*complete*/ true).await?;
    assert_eq!(finished(&mut rpc).await?["status"], json!("completed"));
    assert_eq!(
        mock.single_request().body_json()["tool_choice"],
        json!("auto")
    );
    Ok(())
}
