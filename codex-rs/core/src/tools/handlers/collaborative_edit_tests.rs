use super::*;
use crate::session::step_context::StepContext;
use crate::session::tests::make_session_and_context;
use crate::tools::context::ToolCallSource;
use crate::tools::context::ToolOutput;
use crate::turn_diff_tracker::TurnDiffTracker;
use codex_protocol::models::ResponseInputItem;
use codex_protocol::protocol::SessionSource;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use tokio::sync::Mutex;
use wiremock::Mock;
use wiremock::MockServer;
use wiremock::ResponseTemplate;
use wiremock::matchers::method;
use wiremock::matchers::path;

async fn make_session_with_state_db() -> (
    Arc<Session>,
    Arc<TurnContext>,
    Arc<codex_state::StateRuntime>,
) {
    let (mut session, turn) = make_session_and_context().await;
    let state_db = codex_rollout::state_db::init(turn.config.as_ref())
        .await
        .expect("sqlite state db should initialize");
    session.services.state_db = Some(Arc::clone(&state_db));
    let mut metadata = codex_state::ThreadMetadataBuilder::new(
        session.thread_id(),
        turn.config
            .codex_home
            .as_path()
            .join(format!("{}.jsonl", session.thread_id())),
        chrono::Utc::now(),
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

fn invocation(session: Arc<Session>, turn: Arc<TurnContext>, arguments: Value) -> ToolInvocation {
    ToolInvocation {
        session,
        step_context: StepContext::for_test(Arc::clone(&turn)),
        turn,
        cancellation_token: tokio_util::sync::CancellationToken::new(),
        tracker: Arc::new(Mutex::new(TurnDiffTracker::default())),
        call_id: "call-1".to_string(),
        tool_name: codex_tools::ToolName::plain("collaborative_edit_plan"),
        source: ToolCallSource::Direct,
        payload: ToolPayload::Function {
            arguments: arguments.to_string(),
        },
    }
}

fn output_json(output: &dyn ToolOutput) -> Value {
    let payload = ToolPayload::Function {
        arguments: "{}".to_string(),
    };
    let ResponseInputItem::FunctionCallOutput { output, .. } =
        output.to_response_item("call-1", &payload)
    else {
        panic!("collaborative_edit_plan should return function output");
    };
    serde_json::from_str(
        output
            .body
            .to_text()
            .expect("function output should be text")
            .as_str(),
    )
    .expect("function output should be json")
}

#[tokio::test]
async fn collaborative_edit_plan_records_state_and_notifies_room() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/hollywood/v1/messages"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({ "ok": true })))
        .expect(1)
        .mount(&server)
        .await;

    let (session, turn, state_db) = make_session_with_state_db().await;
    session
        .set_hollywood_session_config(Some(crate::hollywood::HollywoodSessionConfig {
            url: server.uri(),
            room: "repo/losangelex".to_string(),
            observed_rooms: Vec::new(),
            wake_rooms: Vec::new(),
            attention_mode: "focused".to_string(),
        }))
        .await;

    let output = CollaborativeEditPlanHandler
        .handle(invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            json!({
                "file": "docs/guide.md",
                "slice": "Setup section",
                "intent": "replace the placeholder with dependency installation guidance",
                "peers": ["ValidationEditor"],
                "handoff": "I patch Setup first; ValidationEditor patches Validation after",
                "integrator": "ValidationEditor",
                "report_back": "after apply_patch",
            }),
        ))
        .await
        .expect("collaborative edit plan should record");

    let result = output_json(output.as_ref());
    assert_eq!(result["ok"], json!(true));
    assert_eq!(result["room_notified"], json!(true));
    assert_eq!(result["plan"]["room"], json!("repo/losangelex"));
    assert_eq!(result["plan"]["edit_slice"], json!("Setup section"));

    let file_path = turn.config.cwd.join("docs/guide.md").into_path_buf();
    let plans = state_db
        .list_collaborative_edit_plans_for_files(std::slice::from_ref(&file_path))
        .await
        .expect("plans should list");
    assert_eq!(plans.len(), 1);
    assert_eq!(plans[0].actor_thread_id, session.thread_id().to_string());
    assert_eq!(plans[0].file_path, file_path);
    assert_eq!(plans[0].edit_slice, "Setup section");
    assert_eq!(plans[0].peers, vec!["ValidationEditor".to_string()]);

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
    assert_eq!(body["message_kind"], json!("ambient"));
    assert_eq!(body["response_policy"], json!("optional"));
    assert!(
        body["body"]
            .as_str()
            .expect("body should be string")
            .contains("Collaborative edit plan")
    );
}
