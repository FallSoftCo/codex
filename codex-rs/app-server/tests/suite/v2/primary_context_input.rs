//! Actual native RPC/provider-wire fixtures. No real model or Hollywood completion claim.
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
use std::time::Duration;
use tempfile::TempDir;
use tokio::time::timeout;
const WAIT: Duration = Duration::from_secs(60);
const MATERIAL: &str = "55907bc5-8e6b-44a8-afaf-f902c3367463";
const CONTEXT: &str = "897477fd-549e-46fa-a90b-e33528cbb7cc";

fn policy() -> PrimaryContextInputPolicy {
    serde_json::from_value(json!({"type":"canonical","contextId":CONTEXT,"purpose":"writer"}))
        .unwrap()
}
fn declarations() -> Vec<DynamicToolSpec> {
    vec![DynamicToolSpec::Function(DynamicToolFunctionSpec {
        name: "settle".into(),
        description: "Fixture authenticated settlement".into(),
        defer_loading: false,
        input_schema: json!({"type":"object","properties":{},"additionalProperties":false}),
    })]
}
async fn begin(rpc: &mut TestAppServer, thread: &str) -> Result<String> {
    let params = serde_json::from_value(json!({
        "threadId":thread,"input":[],
        "toolOutput":{"name":"context_material_available",
            "output":json!({"purpose":"writer","materialIds":[MATERIAL]}).to_string(),"retain":false},
    }))?;
    let id = rpc.send_turn_start_request(params).await?;
    // This response MUST arrive while the primary-input callback is held.
    let response: TurnStartResponse = timeout(WAIT, rpc.read_response(id)).await??;
    // Process the real start transition before acknowledging its primary callback.
    let started = timeout(
        WAIT,
        rpc.read_stream_until_notification_message("turn/started"),
    )
    .await??;
    assert_eq!(started.params.unwrap()["turn"]["id"], response.turn.id);
    Ok(response.turn.id)
}
async fn next_request(rpc: &mut TestAppServer) -> Result<ServerRequest> {
    loop {
        match timeout(WAIT, rpc.read_next_message()).await?? {
            JSONRPCMessage::Request(request) => return Ok(request.try_into()?),
            JSONRPCMessage::Notification(n) if n.method == "turn/completed" => {
                anyhow::bail!("Native turn ended before expected callback: {:?}", n.params);
            }
            _ => {}
        }
    }
}
async fn input(rpc: &mut TestAppServer) -> Result<(RequestId, ContextInputParams)> {
    let ServerRequest::ContextInput { request_id, params } = next_request(rpc).await? else {
        panic!("Expected owner-bound primary-input callback");
    };
    Ok((request_id, params))
}
fn packet(p: &ContextInputParams) -> Value {
    let admission = format!("context-begin:{}", p.turn_id);
    let bodies = [
        ("role",json!({"role":"PRIMARY_ROLE_FIRST_PROVIDER_CANARY"}).to_string()),
        (MATERIAL,json!({"id":MATERIAL,"kind":"work","state":"running",
            "objective":"PRIMARY_WORK_FIRST_PROVIDER_CANARY","exact":"arguments/results are source data"}).to_string()),
    ];
    let fragments: Vec<_> = bodies.iter().map(|(reference,content)| json!({
        "schema":"lax-context-material-fragment/v1","operationId":admission,
        "reference":reference,"revision":1,"sha256":format!("{:x}",Sha256::digest(content.as_bytes())),
        "totalBytes":content.len(),"offset":0,"content":content,
    }).to_string()).collect();
    let mut value = serde_json::to_value(p).unwrap();
    value["admissionOperationId"] = json!(admission);
    value["fragments"] = json!(fragments);
    value
}
async fn finish(rpc: &mut TestAppServer) -> Result<Value> {
    let n = timeout(
        WAIT,
        rpc.read_stream_until_notification_message("turn/completed"),
    )
    .await??;
    Ok(n.params.unwrap()["turn"].clone())
}
async fn settle(rpc: &mut TestAppServer) -> Result<()> {
    let ServerRequest::DynamicToolCall { request_id, .. } = next_request(rpc).await? else {
        panic!("Expected original fixture settlement");
    };
    rpc.send_response(request_id,json!({"success":true,
        "contentItems":[{"type":"inputText","text":"fixture settlement"}],"turnControl":"complete"})).await?;
    assert_eq!(finish(rpc).await?["status"], json!("completed"));
    Ok(())
}
fn exact_content(v: &Value, reference: &str, pieces: &mut Vec<(u64, String)>) {
    match v {
        Value::String(s) => {
            if let Ok(f) = serde_json::from_str::<Value>(s)
                && f["schema"] == "lax-context-material-fragment/v1"
                && f["reference"] == reference
            {
                pieces.push((
                    f["offset"].as_u64().unwrap(),
                    f["content"].as_str().unwrap().into(),
                ));
            }
        }
        Value::Array(a) => {
            for x in a {
                exact_content(x, reference, pieces);
            }
        }
        Value::Object(o) => {
            for x in o.values() {
                exact_content(x, reference, pieces);
            }
        }
        _ => {}
    }
}
#[tokio::test]
async fn held_admission_has_no_provider_and_first_request_has_complete_material() -> Result<()> {
    let server = responses::start_mock_server().await;
    let mock = responses::mount_sse_once(
        &server,
        responses::sse(vec![
            responses::ev_function_call("one", "settle", "{}"),
            responses::ev_completed("done"),
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
    let t = rpc
        .start_thread(ThreadStartParams {
            primary_context_input: Some(policy()),
            inference_completion: Some(InferenceCompletionPolicy::HostTool),
            dynamic_tools: Some(declarations()),
            ..Default::default()
        })
        .await?;
    let turn = begin(&mut rpc, &t.thread.id).await?;
    let (id, p) = input(&mut rpc).await?;
    assert_eq!(p.turn_id, turn);
    assert_eq!(p.material_ids, vec![MATERIAL.to_string()]);
    assert_eq!(mock.requests().len(), 0);
    let response = packet(&p);
    rpc.send_response(id, response.clone()).await?;
    settle(&mut rpc).await?;
    let body = mock.single_request().body_json();
    for reference in ["role", MATERIAL] {
        let mut pieces = Vec::new();
        exact_content(&body, reference, &mut pieces);
        pieces.sort_by_key(|x| x.0);
        assert_eq!(pieces.len(), 1);
        let original: Value = serde_json::from_str(
            response["fragments"]
                .as_array()
                .unwrap()
                .iter()
                .find(|x| {
                    serde_json::from_str::<Value>(x.as_str().unwrap()).unwrap()["reference"]
                        == reference
                })
                .unwrap()
                .as_str()
                .unwrap(),
        )?;
        assert_eq!(pieces[0].1, original["content"].as_str().unwrap());
    }
    assert_eq!(mock.requests().len(), 1);
    Ok(())
}
#[tokio::test]
async fn cancellation_while_admission_pending_never_samples() -> Result<()> {
    let server = responses::start_mock_server().await;
    let mock = responses::mount_sse_once(
        &server,
        responses::sse(vec![
            responses::ev_assistant_message("forbidden", "must not sample"),
            responses::ev_completed("done"),
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
    let t = rpc
        .start_thread(ThreadStartParams {
            primary_context_input: Some(policy()),
            inference_completion: Some(InferenceCompletionPolicy::HostTool),
            dynamic_tools: Some(declarations()),
            ..Default::default()
        })
        .await?;
    let turn = begin(&mut rpc, &t.thread.id).await?;
    let _original = input(&mut rpc).await?;
    let id = rpc
        .send_turn_interrupt_request(TurnInterruptParams {
            thread_id: t.thread.id,
            turn_id: turn,
        })
        .await?;
    let _: TurnInterruptResponse = timeout(WAIT, rpc.read_response(id)).await??;
    assert_eq!(finish(&mut rpc).await?["status"], json!("interrupted"));
    assert_eq!(mock.requests().len(), 0);
    Ok(())
}
#[tokio::test]
async fn invalid_complete_packet_fails_before_provider() -> Result<()> {
    let server = responses::start_mock_server().await;
    let mock = responses::mount_sse_once(
        &server,
        responses::sse(vec![
            responses::ev_assistant_message("forbidden", "must not sample"),
            responses::ev_completed("done"),
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
    let t = rpc
        .start_thread(ThreadStartParams {
            primary_context_input: Some(policy()),
            inference_completion: Some(InferenceCompletionPolicy::HostTool),
            dynamic_tools: Some(declarations()),
            ..Default::default()
        })
        .await?;
    begin(&mut rpc, &t.thread.id).await?;
    let (id, p) = input(&mut rpc).await?;
    let mut response = packet(&p);
    let mut fragment: Value = serde_json::from_str(response["fragments"][1].as_str().unwrap())?;
    fragment["content"] = json!("different bytes");
    response["fragments"][1] = json!(fragment.to_string());
    rpc.send_response(id, response).await?;
    assert_eq!(finish(&mut rpc).await?["status"], json!("failed"));
    assert_eq!(mock.requests().len(), 0);
    Ok(())
}
#[tokio::test]
async fn explicit_cold_resume_captures_fresh_primary_owner() -> Result<()> {
    let server = responses::start_mock_server().await;
    let mock = responses::mount_sse_once(
        &server,
        responses::sse(vec![
            responses::ev_function_call("one", "settle", "{}"),
            responses::ev_completed("done"),
        ]),
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
    let t = original
        .start_thread(ThreadStartParams {
            primary_context_input: Some(policy()),
            inference_completion: Some(InferenceCompletionPolicy::HostTool),
            dynamic_tools: Some(declarations()),
            ..Default::default()
        })
        .await?;
    let id = original
        .send_raw_request(
            "thread/name/set",
            Some(json!({"threadId":t.thread.id,"name":"fixture:primary"})),
        )
        .await?;
    let _: ThreadSetNameResponse = timeout(WAIT, original.read_response(id)).await??;
    drop(original);
    let mut rpc = TestAppServer::builder()
        .with_codex_home(home.path())
        .build_initialized()
        .await?;
    let id = rpc
        .send_thread_resume_request(ThreadResumeParams {
            thread_id: t.thread.id.clone(),
            primary_context_input: Some(policy()),
            inference_completion: Some(InferenceCompletionPolicy::HostTool),
            dynamic_tools: Some(declarations()),
            ..Default::default()
        })
        .await?;
    let _: ThreadResumeResponse = timeout(WAIT, rpc.read_response(id)).await??;
    begin(&mut rpc, &t.thread.id).await?;
    let (id, p) = input(&mut rpc).await?;
    assert_eq!(mock.requests().len(), 0);
    rpc.send_response(id, packet(&p)).await?;
    settle(&mut rpc).await?;
    assert_eq!(mock.requests().len(), 1);
    Ok(())
}

#[tokio::test]
async fn sample_cannot_fork_canonically_owned_context() -> Result<()> {
    let server = responses::start_mock_server().await;
    let mock = responses::mount_sse_once(
        &server,
        responses::sse(vec![responses::ev_completed("must-not-sample")]),
    )
    .await;
    let home = TempDir::new()?;
    MockResponsesConfig::new(&server.uri()).write(home.path())?;
    let mut rpc = TestAppServer::builder()
        .with_codex_home(home.path())
        .build_initialized()
        .await?;
    let parent = rpc
        .start_thread(ThreadStartParams {
            primary_context_input: Some(policy()),
            inference_completion: Some(InferenceCompletionPolicy::HostTool),
            dynamic_tools: Some(declarations()),
            ..Default::default()
        })
        .await?;
    let id = rpc
        .send_raw_request(
            "thread/sample",
            Some(json!({
                "threadId": parent.thread.id,
                "expectedTurnId": "original-finished-turn",
                "prompt": "This must not bypass canonical input ownership"
            })),
        )
        .await?;
    let error = timeout(
        WAIT,
        rpc.read_stream_until_error_message(RequestId::Integer(id)),
    )
    .await??;
    assert_eq!(
        error.error.message,
        "thread/sample cannot fork a canonically owned context"
    );
    assert_eq!(mock.requests().len(), 0);
    let list_id = rpc
        .send_raw_request("thread/loaded/list", Some(json!({})))
        .await?;
    let loaded: ThreadLoadedListResponse = timeout(WAIT, rpc.read_response(list_id)).await??;
    assert_eq!(loaded.data, vec![parent.thread.id]);
    Ok(())
}
