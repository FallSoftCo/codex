//! Mechanical transport checks. The Responses fixture makes no semantic model claim.
use anyhow::Result;
use codex_core::StartThreadOptions;
use codex_core::TurnInputRequest;
use codex_protocol::dynamic_tools::DynamicToolCallOutputContentItem;
use codex_protocol::dynamic_tools::DynamicToolFunctionSpec;
use codex_protocol::dynamic_tools::DynamicToolResponse;
use codex_protocol::dynamic_tools::DynamicToolSpec;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::Op;
use codex_protocol::user_input::UserInput;
use core_test_support::responses;
use core_test_support::responses::ev_completed;
use core_test_support::responses::ev_function_call;
use core_test_support::responses::sse;
use core_test_support::skip_if_no_network;
use core_test_support::test_codex::test_codex;
use core_test_support::wait_for_event;
use pretty_assertions::assert_eq;
use serde_json::json;

#[test_case::test_case(false; "complete_batch")]
#[test_case::test_case(true; "invalid_batch_is_atomic")]
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn active_dynamic_callback_records_bounded_context_before_next_request(
    invalid: bool,
) -> Result<()> {
    skip_if_no_network!(Ok(()));
    let server = responses::start_mock_server().await;
    let mut builder = test_codex();
    let test = builder.build_with_auto_env(&server).await?;
    let thread = test
        .thread_manager
        .start_thread(StartThreadOptions {
            dynamic_tools: vec![DynamicToolSpec::Function(DynamicToolFunctionSpec {
                name: "material".to_string(),
                description: "Read canonical material.".to_string(),
                input_schema: json!({"type":"object"}),
                defer_loading: false,
            })],
            ..StartThreadOptions::new(test.config.clone())
        })
        .await?
        .thread;
    responses::mount_sse_once(
        &server,
        sse(vec![
            ev_function_call("material-call", "material", "{}"),
            ev_completed("first"),
        ]),
    )
    .await;
    let next = responses::mount_sse_once(&server, sse(vec![ev_completed("second")])).await;
    thread
        .start_or_steer_turn(TurnInputRequest::user_input(vec![UserInput::Text {
            text: "Disclosed mechanical active-tool callback fixture.".to_string(),
            text_elements: Vec::new(),
        }]))
        .await?;
    wait_for_event(&thread, |event| {
        matches!(event, EventMsg::DynamicToolCallRequest(_))
    })
    .await;
    let mut fragments = (0..21)
        .map(|i| format!("fragment-{i:02}:{}\nend-{i:02}", "abcd".repeat(1500)))
        .collect::<Vec<_>>();
    if invalid {
        fragments.push("x".repeat(8193));
    }
    thread
        .submit(Op::DynamicToolResponse {
            id: "material-call".to_string(),
            response: DynamicToolResponse {
                code_mode_text: None,
                context_fragments: fragments.clone(),
                content_items: vec![DynamicToolCallOutputContentItem::InputText {
                    text: "Complete material prepared by the original callback.".to_string(),
                }],
                success: true,
            },
        })
        .await?;
    wait_for_event(&thread, |event| matches!(event, EventMsg::TurnComplete(_))).await;
    let request = next.single_request();
    let inputs = request.input();
    let delivered = inputs
        .iter()
        .filter(|item| {
            item["type"] == "function_call_output"
                && item["name"] == "material"
                && item.get("call_id").is_none()
        })
        .map(|item| item["output"].as_str().expect("plain fragment").to_string())
        .collect::<Vec<_>>();
    assert_eq!(
        delivered,
        if invalid {
            Vec::<String>::new()
        } else {
            fragments
        }
    );
    Ok(())
}
