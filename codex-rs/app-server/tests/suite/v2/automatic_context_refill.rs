//! Public JSON-RPC + real native core/rollout regression SOURCE with mocked model
//! HTTP only. These deterministic fixtures do not establish actual-model behavior.
use anyhow::Result;
use app_test_support::MockResponsesConfig;
use app_test_support::TestAppServer;
use codex_app_server_protocol::*;
use codex_protocol::context_refill::*;
use core_test_support::responses;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use sha2::Digest;
use sha2::Sha256;
use std::time::Duration;
use tempfile::TempDir;
use test_case::test_case;
use tokio::time::timeout;

const WAIT: Duration = Duration::from_secs(60);

fn digest(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn canonical(request: &ContextWindowRefillParams) -> ContextWindowRefillResponse {
    let snapshot = serde_json::to_string(&json!({
        "schema":"lax-context-rebuild/v1", "agentId":"fixture-agent",
        "contextId":request.context_id, "purpose":request.purpose,
        "nativeThread":request.thread_id, "records":[],
        "nextMaterialIds":["same-original-work"], "fixture":"FRESH_CANONICAL"
    }))
    .unwrap();
    let actions = "[]";
    let sha = digest(snapshot.as_bytes());
    let action_sha = digest(actions.as_bytes());
    let snapshot_fragment = json!({
        "schema":"lax-context-refill-fragment/v1", "operationId":request.operation_id,
        "sha256":sha, "totalBytes":snapshot.len(), "offset":0,"content":snapshot
    });
    let action_fragment = json!({
        "schema":"lax-native-action-index/v1","sha256":action_sha,
        "totalBytes":actions.len(),"offset":0,"content":actions,"retrieval":"context_action_read",
        "meaning":"Original action receipts for unfinished work. Never replay an effect merely because context was reset."
    });
    ContextWindowRefillResponse {
        thread_id: request.thread_id.clone(),
        turn_id: request.turn_id.clone(),
        operation_id: request.operation_id.clone(),
        context_id: request.context_id.clone(),
        purpose: request.purpose.clone(),
        window_id: request.window_id.clone(),
        history_version: request.history_version,
        snapshot_operation_id: request.operation_id.clone(),
        snapshot_read_point: "fixture-cut".into(),
        snapshot_sha256: sha,
        native_actions_sha256: action_sha,
        selection_revision: 1,
        total_bytes: snapshot.len() as u64,
        items: vec![
            json!({"type":"function_call_output","namespace":"hollywood","name":"context_refill","output":snapshot_fragment.to_string()}),
            json!({"type":"function_call_output","namespace":"lax","name":"context_actions","output":action_fragment.to_string()}),
        ],
    }
}

async fn setup(
    policy: Value,
    tail: Vec<String>,
) -> Result<(
    TempDir,
    TestAppServer,
    responses::ResponseMock,
    ThreadStartResponse,
    wiremock::MockServer,
)> {
    let server = responses::start_mock_server().await;
    let mut bodies = vec![responses::sse(vec![
        responses::ev_function_call("original-tool", "pause", "{}"),
        responses::ev_completed_with_tokens("tool-response", /*total_tokens*/ 330_000),
    ])];
    bodies.extend(tail);
    let mock = responses::mount_sse_sequence(&server, bodies).await;
    let home = TempDir::new()?;
    MockResponsesConfig::new(&server.uri())
        .with_root_config("model_auto_compact_token_limit = 200000\nmodel_post_turn_compact_threshold_percent = 0")
        .with_provider_config("supports_websockets = false")
        .write(home.path())?;
    let mut rpc = TestAppServer::builder()
        .with_codex_home(home.path())
        .build_initialized()
        .await?;
    let started = rpc
        .start_thread(ThreadStartParams {
            automatic_context_refill: serde_json::from_value(policy)?,
            dynamic_tools: Some(vec![DynamicToolSpec::Function(DynamicToolFunctionSpec {
                name: "pause".into(),
                description: "Suspended tool fixture".into(),
                defer_loading: false,
                input_schema: json!({"type":"object","properties":{},"additionalProperties":false}),
            })]),
            ..Default::default()
        })
        .await?;
    // Return the listener as well; dropping it would invalidate fixture routing.
    Ok((home, rpc, mock, started, server))
}

async fn drained_callback(
    rpc: &mut TestAppServer,
    thread: &str,
) -> Result<(RequestId, ContextWindowRefillParams)> {
    let turn = rpc
        .send_turn_start_request(TurnStartParams {
            thread_id: thread.into(),
            input: vec![UserInput::Text {
                text: "STALE_WINDOW_MARKER".into(),
                text_elements: vec![],
            }],
            ..Default::default()
        })
        .await?;
    let _: TurnStartResponse = timeout(WAIT, rpc.read_response(turn)).await??;
    let ServerRequest::DynamicToolCall { request_id, params } =
        timeout(WAIT, rpc.read_stream_until_request_message()).await??
    else {
        panic!("refill ran before the foreground tool");
    };
    assert_eq!(params.call_id, "original-tool");
    assert!(
        timeout(
            Duration::from_millis(50),
            rpc.read_stream_until_request_message()
        )
        .await
        .is_err()
    );
    rpc.send_response(
        request_id,
        json!({
            "success":true,"contentItems":[{"type":"inputText","text":"drained"}],
            "contextFragments":[],"codeModeText":null
        }),
    )
    .await?;
    let ServerRequest::ContextWindowRefill {
        request_id,
        params: refill,
    } = timeout(WAIT, rpc.read_stream_until_request_message()).await??
    else {
        panic!("missing drained canonical callback");
    };
    assert_eq!(refill.turn_id, params.turn_id);
    assert_eq!(refill.thread_id, thread);
    Ok((request_id, refill))
}

fn final_response(id: &str) -> String {
    responses::sse(vec![
        responses::ev_assistant_message("answer", "done"),
        responses::ev_completed_with_tokens(id, /*total_tokens*/ 120),
    ])
}

#[tokio::test]
async fn same_live_turn_drain_arrival_durable_receipt_and_full_provider_replacement() -> Result<()>
{
    let (_home, mut rpc, mock, started, _server) = setup(
        json!({"type":"canonical","contextId":"context","purpose":"writer"}),
        vec![
            final_response("after-refill"),
            final_response("after-arrival"),
        ],
    )
    .await?;
    let (id, request) = drained_callback(&mut rpc, &started.thread.id).await?;
    let arrival = rpc
        .send_raw_request(
            "turn/steer",
            Some(json!({
                "threadId":request.thread_id,"expectedTurnId":request.turn_id,
                "input":[{"type":"text","text":"ARRIVED_DURING_REFILL","textElements":[]}]
            })),
        )
        .await?;
    let _: TurnSteerResponse = timeout(WAIT, rpc.read_response(arrival)).await??;
    // The old explicit idle API must not bypass the active automatic gate.
    let inject = rpc
        .send_raw_request(
            "thread/inject_items",
            Some(json!({
                "threadId":request.thread_id,"items":[]
            })),
        )
        .await?;
    timeout(
        WAIT,
        rpc.read_stream_until_error_message(RequestId::Integer(inject)),
    )
    .await??;
    let response = canonical(&request);
    rpc.send_response(id, serde_json::to_value(&response)?)
        .await?;
    let ServerRequest::ContextWindowInstalled {
        request_id: ack_id,
        params: installed,
    } = timeout(WAIT, rpc.read_stream_until_request_message()).await??
    else {
        panic!("missing durable install");
    };
    assert_eq!(installed.operation_id, request.operation_id);
    assert_eq!(installed.snapshot_operation_id, request.operation_id);
    assert_eq!(installed.snapshot_sha256, response.snapshot_sha256);
    assert_eq!(installed.previous_window_id, request.window_id);
    assert_ne!(installed.window_id, request.window_id);
    assert_eq!(mock.requests().len(), 1); // no sample before host recorded acknowledgement
    let bytes = std::fs::read(started.thread.path.as_ref().expect("materialized rollout"))?;
    let boundary = usize::try_from(installed.native_history_bytes)?;
    assert_eq!(digest(&bytes[..boundary]), installed.native_history_sha256);
    let before: Vec<Value> = bytes[..boundary]
        .split(|b| *b == b'\n')
        .filter(|b| !b.is_empty())
        .map(serde_json::from_slice)
        .collect::<std::result::Result<_, _>>()?;
    let checkpoint = before.last().unwrap();
    assert_eq!(checkpoint["type"], "compacted");
    assert_eq!(
        before[before.len() - 2]["payload"]["operationId"],
        request.operation_id
    );
    let history = checkpoint["payload"]["replacement_history"]
        .as_array()
        .unwrap();
    assert_eq!(
        &history[history.len() - response.items.len()..],
        response.items.as_slice()
    );
    let receipt: Value =
        serde_json::from_slice(bytes[boundary..].split(|b| *b == b'\n').next().unwrap())?;
    let mut exact = serde_json::to_value(&installed)?;
    exact
        .as_object_mut()
        .unwrap()
        .insert("type".into(), json!("context_window_refill_installed"));
    assert_eq!(receipt["payload"], exact);
    rpc.send_response(
        ack_id,
        json!({"operationId":request.operation_id,"status":"recorded"}),
    )
    .await?;
    let completed: TurnCompletedNotification =
        timeout(WAIT, rpc.read_notification("turn/completed")).await??;
    assert_eq!(completed.turn.id, request.turn_id);
    assert_eq!(completed.turn.status, TurnStatus::Completed);
    let requests = mock.requests();
    assert_eq!(requests.len(), 3);
    let body = requests[1].body_json();
    assert!(body.get("previous_response_id").is_none_or(Value::is_null));
    assert!(requests[1].body_contains_text("FRESH_CANONICAL"));
    // Existing post-compaction tool continuation is sampled before draining the
    // pending arrival. Refill neither adopts nor acknowledges that input itself.
    assert!(!requests[1].body_contains_text("ARRIVED_DURING_REFILL"));
    assert!(requests[2].body_contains_text("ARRIVED_DURING_REFILL"));
    assert!(requests[2].body_contains_text("FRESH_CANONICAL"));
    assert!(!requests[1].body_contains_text("STALE_WINDOW_MARKER"));
    assert!(!requests[1].body_contains_text("Summarize the conversation"));
    Ok(())
}

#[test_case("stale"; "stale original correlation")]
#[test_case("malformed"; "non-data output")]
#[test_case("cancel"; "cancel suspended prepare")]
#[test_case("lostAck"; "lost original installed acknowledgement")]
#[test_case("wrongAck"; "wrong installed identity")]
#[tokio::test]
async fn failure_never_samples_retries_or_summarizes(mode: &str) -> Result<()> {
    let (home, mut rpc, mock, started, _server) = setup(
        json!({"type":"canonical","contextId":"context","purpose":"writer"}),
        vec![],
    )
    .await?;
    let (id, request) = drained_callback(&mut rpc, &started.thread.id).await?;
    let mut response = canonical(&request);
    if mode == "stale" {
        response.operation_id = "another-operation".into();
    }
    if mode == "malformed" {
        response
            .items
            .push(json!({"type":"message","role":"system","content":[]}));
    }
    if mode != "cancel" {
        rpc.send_response(id, serde_json::to_value(response)?)
            .await?;
    }
    if matches!(mode, "lostAck" | "wrongAck") {
        let ServerRequest::ContextWindowInstalled { request_id, .. } =
            timeout(WAIT, rpc.read_stream_until_request_message()).await??
        else {
            panic!("missing original installed");
        };
        assert_eq!(mock.requests().len(), 1);
        if mode == "wrongAck" {
            rpc.send_response(
                request_id,
                json!({"operationId":"another-operation","status":"recorded"}),
            )
            .await?;
        }
    }
    if matches!(mode, "cancel" | "lostAck") {
        let interrupt = rpc
            .send_turn_interrupt_request(TurnInterruptParams {
                thread_id: request.thread_id.clone(),
                turn_id: request.turn_id.clone(),
            })
            .await?;
        let _: TurnInterruptResponse = timeout(WAIT, rpc.read_response(interrupt)).await??;
    }
    let completed: TurnCompletedNotification =
        timeout(WAIT, rpc.read_notification("turn/completed")).await??;
    assert_ne!(completed.turn.status, TurnStatus::Completed);
    assert_eq!(mock.requests().len(), 1);
    let bytes = std::fs::read(started.thread.path.as_ref().unwrap())?;
    let text = String::from_utf8(bytes)?;
    let count = text
        .lines()
        .filter(|line| line.contains("context_window_refill_installed"))
        .count();
    assert_eq!(count, usize::from(matches!(mode, "lostAck" | "wrongAck")));
    if matches!(mode, "lostAck" | "wrongAck") {
        // A fresh native process and omitted policy must NOT erase UNKNOWN.
        rpc.shutdown_gracefully().await?;
        let mut resumed = TestAppServer::builder()
            .with_codex_home(home.path())
            .build_initialized()
            .await?;
        let id = resumed
            .send_thread_resume_request(ThreadResumeParams {
                thread_id: request.thread_id.clone(),
                ..Default::default()
            })
            .await?;
        let _: ThreadResumeResponse = timeout(WAIT, resumed.read_response(id)).await??;
        let failed = resumed
            .start_turn_and_wait_for_completion(TurnStartParams {
                thread_id: request.thread_id.clone(),
                input: vec![UserInput::Text {
                    text: "Do not bypass the original unknown checkpoint".into(),
                    text_elements: vec![],
                }],
                ..Default::default()
            })
            .await?;
        assert_ne!(failed.turn.status, TurnStatus::Completed);
        assert_eq!(mock.requests().len(), 1);
        let after = std::fs::read_to_string(started.thread.path.as_ref().unwrap())?;
        assert_eq!(
            after
                .lines()
                .filter(|line| line.contains("context_window_refill_installed"))
                .count(),
            count
        );
    }
    Ok(())
}

#[test_case("absent"; "absent stays vanilla")]
#[test_case("null"; "null stays vanilla")]
#[test_case("disabled"; "explicit disabled stays vanilla")]
#[tokio::test]
async fn default_policy_keeps_automatic_summary_and_idle_manual_guards(mode: &str) -> Result<()> {
    let server = responses::start_mock_server().await;
    let mock = responses::mount_sse_sequence(
        &server,
        vec![
            responses::sse(vec![
                responses::ev_assistant_message("seed", "OLD_HISTORY"),
                responses::ev_completed_with_tokens("seed", /*total_tokens*/ 330_000),
            ]),
            responses::sse(vec![
                responses::ev_assistant_message("summary", "VANILLA_SUMMARY"),
                responses::ev_completed_with_tokens("summary", /*total_tokens*/ 120),
            ]),
            final_response("after-refill"),
            responses::sse(vec![
                responses::ev_assistant_message("manual", "MANUAL_SUMMARY"),
                responses::ev_completed_with_tokens("manual", /*total_tokens*/ 120),
            ]),
        ],
    )
    .await;
    let home = TempDir::new()?;
    MockResponsesConfig::new(&server.uri())
        .with_root_config("model_auto_compact_token_limit = 200000\nmodel_post_turn_compact_threshold_percent = 0\ncompact_prompt = \"Summarize the conversation.\"")
        .with_provider_config("supports_websockets = false").write(home.path())?;
    let mut rpc = TestAppServer::builder()
        .with_codex_home(home.path())
        .build_initialized()
        .await?;
    let mut params = serde_json::to_value(ThreadStartParams::default())?;
    // Preserve foreign execution test environment defaults even for raw omission cases.
    params["environments"] = json!([rpc.auto_env_params()?]);
    match mode {
        "absent" => {
            params
                .as_object_mut()
                .unwrap()
                .remove("automaticContextRefill");
        }
        "null" => params["automaticContextRefill"] = Value::Null,
        "disabled" => params["automaticContextRefill"] = json!({"type":"disabled"}),
        _ => unreachable!(),
    }
    let id = rpc.send_raw_request("thread/start", Some(params)).await?;
    let started: ThreadStartResponse = timeout(WAIT, rpc.read_response(id)).await??;
    for _ in 0..2 {
        let completed = rpc
            .start_turn_and_wait_for_completion(TurnStartParams {
                thread_id: started.thread.id.clone(),
                input: vec![UserInput::Text {
                    text: "Continue".into(),
                    text_elements: vec![],
                }],
                ..Default::default()
            })
            .await?;
        assert_eq!(completed.turn.status, TurnStatus::Completed);
    }
    assert_eq!(mock.requests().len(), 3);
    assert!(mock.requests()[1].body_contains_text("Summarize the conversation."));
    let compact = rpc
        .send_thread_compact_start_request(ThreadCompactStartParams {
            thread_id: started.thread.id.clone(),
        })
        .await?;
    let _: ThreadCompactStartResponse = timeout(WAIT, rpc.read_response(compact)).await??;
    // Observe completion through native item events; no canonical callback is consumed.
    timeout(
        WAIT,
        rpc.read_stream_until_matching_notification("manual compaction", |n| {
            n.method == "item/completed"
                && n.params
                    .as_ref()
                    .is_some_and(|p| p["item"]["type"] == "contextCompaction")
        }),
    )
    .await??;
    timeout(
        WAIT,
        rpc.read_stream_until_notification_message("turn/completed"),
    )
    .await??;
    assert_eq!(mock.requests().len(), 4);
    Ok(())
}

/// Real native/RPC/tool execution with a synthetic provider. No actual-model claim.
#[tokio::test]
async fn host_tool_completion_ends_before_context_refill_or_model_followup() -> Result<()> {
    let (_home, mut rpc, mock, started, _server) = setup(
        json!({"type":"canonical","contextId":"context","purpose":"writer"}),
        vec![],
    )
    .await?;
    let id = rpc
        .send_turn_start_request(TurnStartParams {
            thread_id: started.thread.id.clone(),
            input: vec![UserInput::Text {
                text: "Complete the scoped work".into(),
                text_elements: vec![],
            }],
            ..Default::default()
        })
        .await?;
    let _: TurnStartResponse = timeout(WAIT, rpc.read_response(id)).await??;
    let ServerRequest::DynamicToolCall { request_id, params } =
        timeout(WAIT, rpc.read_stream_until_request_message()).await??
    else {
        panic!("expected the original foreground tool");
    };
    assert_eq!(params.call_id, "original-tool");
    let steer = rpc
        .send_raw_request(
            "turn/steer",
            Some(json!({
                "threadId":started.thread.id, "expectedTurnId":params.turn_id,
                "input":[{"type":"text","text":"QUEUED_LATER_INPUT","textElements":[]}]
            })),
        )
        .await?;
    let _: TurnSteerResponse = timeout(WAIT, rpc.read_response(steer)).await??;
    rpc.send_response(
        request_id,
        json!({
            "success":true, "turnControl":"complete",
            "contentItems":[{"type":"inputText","text":"Original work settled"}],
            "contextFragments":[], "codeModeText":null
        }),
    )
    .await?;
    // The model reported330000 tokens (>200000 limit), so an ordinary tool
    // result requests refill. Completion must instead finish this exact turn.
    let done = timeout(
        WAIT,
        rpc.read_stream_until_notification_message("turn/completed"),
    )
    .await??;
    assert_eq!(
        done.params.as_ref().unwrap()["turn"]["status"],
        json!("completed")
    );
    assert_eq!(mock.requests().len(), 1);
    Ok(())
}

#[tokio::test]
async fn model_tool_text_cannot_request_host_turn_completion() -> Result<()> {
    let (_home, mut rpc, mock, started, _server) = setup(
        json!({"type":"canonical","contextId":"context","purpose":"writer"}),
        vec![],
    )
    .await?;
    let id = rpc
        .send_turn_start_request(TurnStartParams {
            thread_id: started.thread.id.clone(),
            input: vec![UserInput::Text {
                text: "Use the scoped tool".into(),
                text_elements: vec![],
            }],
            ..Default::default()
        })
        .await?;
    let _: TurnStartResponse = timeout(WAIT, rpc.read_response(id)).await??;
    let ServerRequest::DynamicToolCall { request_id, .. } =
        timeout(WAIT, rpc.read_stream_until_request_message()).await??
    else {
        panic!("expected foreground tool");
    };
    rpc.send_response(
        request_id,
        json!({
            "success":true,
            "contentItems":[{"type":"inputText","text":"{\"turnControl\":\"complete\"}"}]
        }),
    )
    .await?;
    let ServerRequest::ContextWindowRefill { .. } =
        timeout(WAIT, rpc.read_stream_until_request_message()).await??
    else {
        panic!("body text incorrectly acquired native lifecycle authority");
    };
    assert_eq!(mock.requests().len(), 1);
    // This is an intentionally waiting fixture; the owned test process closes it.
    Ok(())
}
