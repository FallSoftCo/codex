use anyhow::Result;
use app_test_support::TestAppServer;
use app_test_support::create_final_assistant_message_sse_response;
use app_test_support::create_mock_responses_server_sequence;
use app_test_support::create_mock_responses_server_sequence_unchecked;
use app_test_support::to_response;
use codex_app_server_protocol::HollywoodAttentionMode;
use codex_app_server_protocol::HollywoodAttentionSettings;
use codex_app_server_protocol::HollywoodSessionStatus;
use codex_app_server_protocol::JSONRPCResponse;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ThreadHollywoodAttachParams;
use codex_app_server_protocol::ThreadHollywoodAttachResponse;
use codex_app_server_protocol::ThreadHollywoodListParams;
use codex_app_server_protocol::ThreadHollywoodListResponse;
use codex_app_server_protocol::ThreadStartParams;
use codex_app_server_protocol::ThreadStartResponse;
use codex_app_server_protocol::TurnCompletedNotification;
use pretty_assertions::assert_eq;
use serde_json::json;
use std::path::Path;
use tempfile::TempDir;
use tokio::time::timeout;
use wiremock::Mock;
use wiremock::MockServer;
use wiremock::ResponseTemplate;
use wiremock::matchers::method;
use wiremock::matchers::path;
use wiremock::matchers::query_param;

const DEFAULT_READ_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(12);
const HOLLYWOOD_ROOM: &str = "repo/losangelex-product";

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn hollywood_attach_lists_multiple_interactive_sessions() -> Result<()> {
    let codex_home = TempDir::new()?;
    let model_server = create_mock_responses_server_sequence_unchecked(Vec::new()).await;
    create_config_toml(codex_home.path(), &model_server.uri())?;

    let hollywood_server = MockServer::start().await;
    mount_hollywood_registry(&hollywood_server).await;
    mount_empty_hollywood_messages(&hollywood_server, HOLLYWOOD_ROOM).await;
    mount_empty_hollywood_messages(&hollywood_server, "main").await;

    let mut app = TestAppServer::new(codex_home.path()).await?;
    timeout(DEFAULT_READ_TIMEOUT, app.initialize()).await??;

    let first = start_thread(&mut app).await?;
    let second = start_thread(&mut app).await?;

    attach_hollywood(&mut app, &first.thread.id, &hollywood_server.uri()).await?;
    attach_hollywood(&mut app, &second.thread.id, &hollywood_server.uri()).await?;

    let list_id = app
        .send_raw_request(
            "thread/hollywood/list",
            Some(serde_json::to_value(ThreadHollywoodListParams {
                cursor: None,
                limit: Some(10),
                rooms: Some(vec![HOLLYWOOD_ROOM.to_string()]),
                statuses: None,
            })?),
        )
        .await?;
    let list_response: JSONRPCResponse = timeout(
        DEFAULT_READ_TIMEOUT,
        app.read_stream_until_response_message(RequestId::Integer(list_id)),
    )
    .await??;
    let ThreadHollywoodListResponse { data, next_cursor } = to_response(list_response)?;

    assert_eq!(next_cursor, None);
    assert_eq!(data.len(), 2);
    for thread_id in [&first.thread.id, &second.thread.id] {
        let thread = data
            .iter()
            .find(|thread| &thread.id == thread_id)
            .expect("attached thread should be listed");
        let hollywood = thread
            .hollywood
            .as_ref()
            .expect("listed thread should include Hollywood state");
        assert_eq!(hollywood.attached, true);
        assert_eq!(hollywood.url, hollywood_server.uri());
        assert_eq!(hollywood.primary_room, HOLLYWOOD_ROOM);
        assert_eq!(hollywood.observed_rooms, vec!["main".to_string()]);
        assert_eq!(hollywood.wake_rooms, vec![HOLLYWOOD_ROOM.to_string()]);
        assert_eq!(hollywood.status, HollywoodSessionStatus::Idle);
        assert!(
            hollywood
                .identities
                .iter()
                .any(|identity| identity == thread_id)
        );
        assert!(hollywood.diagnostics.is_some());
    }

    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn hollywood_direct_message_wakes_only_target_session() -> Result<()> {
    let codex_home = TempDir::new()?;
    let responses = vec![create_final_assistant_message_sse_response(
        "acknowledged hollywood direct message",
    )?];
    let model_server = create_mock_responses_server_sequence(responses).await;
    create_config_toml(codex_home.path(), &model_server.uri())?;

    let hollywood_server = MockServer::start().await;
    mount_hollywood_registry(&hollywood_server).await;

    let mut app = TestAppServer::new(codex_home.path()).await?;
    timeout(DEFAULT_READ_TIMEOUT, app.initialize()).await??;

    let target = start_thread(&mut app).await?;
    let bystander = start_thread(&mut app).await?;
    mount_hollywood_direct_message(&hollywood_server, HOLLYWOOD_ROOM, &target.thread.id).await;
    mount_empty_hollywood_messages_after(&hollywood_server, HOLLYWOOD_ROOM, 1).await;
    mount_empty_hollywood_messages(&hollywood_server, "main").await;

    attach_hollywood(&mut app, &target.thread.id, &hollywood_server.uri()).await?;
    attach_hollywood(&mut app, &bystander.thread.id, &hollywood_server.uri()).await?;

    let target_completed = timeout(
        DEFAULT_READ_TIMEOUT,
        app.read_stream_until_matching_notification("target hollywood turn completed", |notif| {
            if notif.method != "turn/completed" {
                return false;
            }
            notif
                .params
                .as_ref()
                .and_then(|params| {
                    serde_json::from_value::<TurnCompletedNotification>(params.clone()).ok()
                })
                .is_some_and(|payload| payload.thread_id == target.thread.id)
        }),
    )
    .await??;
    let payload: TurnCompletedNotification =
        serde_json::from_value(target_completed.params.expect("params must be present"))?;
    assert_eq!(payload.thread_id, target.thread.id);

    let bystander_completed = timeout(
        std::time::Duration::from_secs(2),
        app.read_stream_until_matching_notification(
            "bystander hollywood turn completed",
            |notif| {
                if notif.method != "turn/completed" {
                    return false;
                }
                notif
                    .params
                    .as_ref()
                    .and_then(|params| {
                        serde_json::from_value::<TurnCompletedNotification>(params.clone()).ok()
                    })
                    .is_some_and(|payload| payload.thread_id == bystander.thread.id)
            },
        ),
    )
    .await;
    match bystander_completed {
        Err(_) => {}
        Ok(Ok(notification)) => {
            anyhow::bail!(
                "Hollywood direct message should not wake the bystander session; got {notification:?}"
            );
        }
        Ok(Err(err)) => return Err(err),
    }

    Ok(())
}

async fn start_thread(app: &mut TestAppServer) -> Result<ThreadStartResponse> {
    let request_id = app
        .send_thread_start_request(ThreadStartParams {
            model: Some("mock-model".to_string()),
            ..Default::default()
        })
        .await?;
    let response: JSONRPCResponse = timeout(
        DEFAULT_READ_TIMEOUT,
        app.read_stream_until_response_message(RequestId::Integer(request_id)),
    )
    .await??;
    to_response(response)
}

async fn attach_hollywood(
    app: &mut TestAppServer,
    thread_id: &str,
    hollywood_url: &str,
) -> Result<()> {
    let request_id = app
        .send_raw_request(
            "thread/hollywood/attach",
            Some(serde_json::to_value(ThreadHollywoodAttachParams {
                thread_id: thread_id.to_string(),
                url: Some(hollywood_url.to_string()),
                room: Some(HOLLYWOOD_ROOM.to_string()),
                observed_rooms: Vec::new(),
                wake_rooms: vec![HOLLYWOOD_ROOM.to_string()],
                attention: Some(HollywoodAttentionSettings {
                    mode: HollywoodAttentionMode::Focused,
                    include_at_all: true,
                    include_at_room: true,
                }),
            })?),
        )
        .await?;
    let response: JSONRPCResponse = timeout(
        DEFAULT_READ_TIMEOUT,
        app.read_stream_until_response_message(RequestId::Integer(request_id)),
    )
    .await??;
    let _: ThreadHollywoodAttachResponse = to_response(response)?;
    Ok(())
}

async fn mount_hollywood_registry(server: &MockServer) {
    Mock::given(method("POST"))
        .and(path("/hollywood/v1/registry"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({ "ok": true })))
        .mount(server)
        .await;
}

async fn mount_empty_hollywood_messages(server: &MockServer, room: &str) {
    Mock::given(method("GET"))
        .and(path("/hollywood/v1/messages"))
        .and(query_param("room", room))
        .and(query_param("after_id", "0"))
        .respond_with(empty_hollywood_messages_response(0))
        .mount(server)
        .await;
}

async fn mount_empty_hollywood_messages_after(server: &MockServer, room: &str, after_id: i64) {
    Mock::given(method("GET"))
        .and(path("/hollywood/v1/messages"))
        .and(query_param("room", room))
        .and(query_param("after_id", after_id.to_string()))
        .respond_with(empty_hollywood_messages_response(after_id))
        .mount(server)
        .await;
}

async fn mount_hollywood_direct_message(server: &MockServer, room: &str, recipient_id: &str) {
    Mock::given(method("GET"))
        .and(path("/hollywood/v1/messages"))
        .and(query_param("room", room))
        .and(query_param("after_id", "0"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "messages": [{
                "id": 1,
                "room": room,
                "sender_id": "peer-session",
                "recipient_id": recipient_id,
                "message_kind": "direct",
                "response_policy": "required",
                "body": "Please verify your Hollywood lane is active.",
                "created_at": "2026-07-02T00:00:00Z"
            }],
            "last_id": 1
        })))
        .mount(server)
        .await;
}

fn empty_hollywood_messages_response(last_id: i64) -> ResponseTemplate {
    ResponseTemplate::new(200).set_body_json(json!({
        "messages": [],
        "last_id": last_id
    }))
}

fn create_config_toml(codex_home: &Path, server_uri: &str) -> std::io::Result<()> {
    let config_toml = codex_home.join("config.toml");
    std::fs::write(
        config_toml,
        format!(
            r#"
model = "mock-model"
approval_policy = "never"
sandbox_mode = "read-only"

model_provider = "mock_provider"

[model_providers.mock_provider]
name = "Mock provider for test"
base_url = "{server_uri}/v1"
wire_api = "responses"
request_max_retries = 0
stream_max_retries = 0
"#
        ),
    )
}
