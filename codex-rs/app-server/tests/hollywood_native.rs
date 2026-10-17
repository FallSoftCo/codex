use anyhow::Result;
use app_test_support::MockResponsesConfig;
use app_test_support::TestAppServer;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::HollywoodAgentMessageParams;
use codex_app_server_protocol::HollywoodAgentMessageResponse;
use codex_app_server_protocol::HollywoodEventAudience;
use codex_app_server_protocol::HollywoodEventKind;
use codex_app_server_protocol::ThreadStartParams;
use codex_app_server_protocol::TurnStartParams;
use codex_app_server_protocol::UserInput;
use core_test_support::responses;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use std::collections::HashMap;
use tempfile::TempDir;
use tokio::time::timeout;

#[tokio::test]
async fn hollywood_agent_message_starts_without_human_input_and_survives_next_turn() -> Result<()> {
    let server = responses::start_mock_server().await;
    let response = |id: &str| {
        responses::sse(vec![
            responses::ev_response_created(id),
            responses::ev_assistant_message("reply", "Reviewed the peer request."),
            responses::ev_completed(id),
        ])
    };
    let observed = responses::mount_sse_sequence(
        &server,
        vec![response("peer-response"), response("human-response"), response("review-response")],
    )
    .await;
    let home = TempDir::new()?;
    MockResponsesConfig::new(&server.uri()).write(home.path())?;
    let mut app = TestAppServer::builder()
        .with_codex_home(home.path())
        .build_initialized()
        .await?;
    let native_contract = "LAX-owned-native-contract: communicate as independent Hollywood peers.";
    let thread = app
        .start_thread(ThreadStartParams {
            model: Some("mock-model".to_string()),
            base_instructions: Some(native_contract.to_string()),
            config: Some(HashMap::from([
                ("agents.enabled".to_string(), json!(false)),
                ("features.multi_agent".to_string(), json!(false)),
                ("features.multi_agent_v2".to_string(), json!(false)),
            ])),
            dynamic_tools: Some(serde_json::from_value(json!([{
                "type": "function",
                "name": "hollywood_context",
                "description": "Read current authenticated agent context.",
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": false}
            }]))?),
            ..Default::default()
        })
        .await?
        .thread;
    let authority = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
    let room = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
    let event = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
    let author = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
    let recipient = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee";
    let body = "peer-native-review: verify the shared schema before integrating.";
    let admitted: HollywoodAgentMessageResponse = app
        .request(|request_id| ClientRequest::HollywoodAgentMessage {
            request_id,
            params: HollywoodAgentMessageParams {
                thread_id: thread.id.clone(),
                authority_id: authority.to_string(),
                room_id: room.to_string(),
                event_id: event.to_string(),
                author_id: author.to_string(),
                recipient_id: recipient.to_string(),
                body: body.to_string(),
                audience: HollywoodEventAudience::Room,
                kind: HollywoodEventKind::Request,
                source_event_id: None,
                expects_reply: true,
            },
        })
        .await?;
    assert!(!admitted.turn.id.is_empty());
    timeout(
        std::time::Duration::from_secs(15),
        app.read_stream_until_notification_message("turn/completed"),
    )
    .await??;
    app.start_turn_and_wait_for_completion(TurnStartParams {
        thread_id: thread.id.clone(),
        model: Some("mock-model-override".to_string()),
        input: vec![UserInput::Text {
            text: "Now incorporate the review.".to_string(),
            text_elements: vec![],
        }],
        ..Default::default()
    })
    .await?;
    // Real Hollywood worker-report review events are addressed to their own
    // owner under the server's bounded lifecycle policy, not a peer self-loop.
    let review_event = "ffffffff-ffff-4fff-8fff-ffffffffffff";
    let review_body = "Review the newly submitted worker report against the accepted goal.";
    let _: HollywoodAgentMessageResponse = app
        .request(|request_id| ClientRequest::HollywoodAgentMessage {
            request_id,
            params: HollywoodAgentMessageParams {
                thread_id: thread.id.clone(),
                authority_id: authority.to_string(),
                room_id: room.to_string(),
                event_id: review_event.to_string(),
                author_id: recipient.to_string(),
                recipient_id: recipient.to_string(),
                body: review_body.to_string(),
                audience: HollywoodEventAudience::Room,
                kind: HollywoodEventKind::Request,
                source_event_id: Some(event.to_string()),
                expects_reply: false,
            },
        })
        .await?;
    timeout(
        std::time::Duration::from_secs(15),
        app.read_stream_until_notification_message("turn/completed"),
    )
    .await??;
    let requests = observed.requests();
    assert_eq!(requests.len(), 3);
    let expected = json!({
        "type": "agent_message",
        "author": author,
        "recipient": recipient,
        "content": [{
            "type": "input_text",
            "text": json!({
                "authorityId": authority,
                "roomId": room,
                "eventId": event,
                "sourceEventId": Value::Null,
                "audience": "room",
                "kind": "request",
                "expectsReply": true,
                "body": body,
            }).to_string(),
        }],
    });
    for (index, request) in requests.iter().enumerate() {
        let request_body = request.body_json();
        let tool_specs = request_body["tools"].to_string();
        assert!(tool_specs.contains("\"name\":\"hollywood_context\""));
        for upstream_tool in ["spawn_agent", "send_message", "wait_agent", "close_agent"] {
            assert!(!tool_specs.contains(&format!("\"name\":\"{upstream_tool}\"")));
        }
        let input = request_body["input"].as_array().unwrap().clone();
        // The current provider client serializes the owned base as a dedicated
        // developer prefix item, rather than the top-level instructions field.
        assert!(input.iter().any(|item| {
            item["role"] == "developer"
                && item["content"][0]["text"] == native_contract
        }));
        for text in input
            .iter()
            .filter_map(|item| item["content"].as_array())
            .flatten()
            .filter_map(|content| content["text"].as_str())
            .filter(|text| text.contains("<model_switch>"))
        {
            assert!(text.contains(native_contract), "{text}");
        }
        let peers: Vec<_> = input
            .iter()
            .filter(|item| item["type"] == "agent_message")
            .collect();
        assert_eq!(peers.len(), if index == 2 { 2 } else { 1 });
        let mut peer = peers[0].clone();
        peer.as_object_mut().unwrap().remove("id");
        assert_eq!(peer, expected);
        if index == 2 {
            assert_eq!(peers[1]["author"], recipient);
            assert_eq!(peers[1]["recipient"], recipient);
            let content: Value = serde_json::from_str(
                peers[1]["content"][0]["text"].as_str().unwrap(),
            )?;
            assert_eq!(content["eventId"], review_event);
            assert_eq!(content["sourceEventId"], event);
            assert_eq!(content["body"], review_body);
        }
        assert!(!input.iter().any(|item| {
            matches!(item["role"].as_str(), Some("user" | "developer"))
                && item.to_string().contains(body)
        }));
    }
    Ok(())
}
