use anyhow::Result;
use codex_core::TurnInputRequest;
use codex_core::config::Constrained;
use codex_protocol::config_types::ApprovalsReviewer;
use codex_protocol::protocol::AskForApproval;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::SandboxPolicy;
use codex_protocol::protocol::ThreadSettingsOverrides;
use codex_protocol::user_input::UserInput;
use core_test_support::responses::ev_completed;
use core_test_support::responses::ev_function_call;
use core_test_support::responses::ev_response_created;
use core_test_support::responses::mount_sse_sequence;
use core_test_support::responses::sse;
use core_test_support::responses::start_mock_server;
use core_test_support::test_codex::test_codex;
use core_test_support::wait_for_event;
use pretty_assertions::assert_eq;

#[test_case::test_case("{{ tenant_policy_config }}"; "tenant_policy")]
#[test_case::test_case("{{ extra_policy }}"; "extra_policy")]
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn oversized_local_guardian_policy_denies_without_reviewer_inference(
    placeholder: &str,
) -> Result<()> {
    let server = start_mock_server().await;
    let template = placeholder.repeat(3);
    let test = test_codex()
        .with_config(move |config| {
            config.model_provider.supports_websockets = false;
            config.permissions.approval_policy = Constrained::allow_any(AskForApproval::OnRequest);
            config.approvals_reviewer = ApprovalsReviewer::User;
            config.guardian_policy_template = Some(template);
            config.guardian_policy_config = Some("界".repeat(1_200));
            config.guardian_extra_policy = Some("界".repeat(1_200));
        })
        .build_with_auto_env(&server)
        .await?;
    let responses = mount_sse_sequence(
        &server,
        vec![
            sse(vec![
                ev_response_created("parent-action"),
                ev_function_call(
                    "bounded-action",
                    "exec_command",
                    r#"{"cmd":"printf executed > guardian-policy-bounds.txt","sandbox_permissions":"require_escalated","justification":"Exercise oversized local policy rejection."}"#,
                ),
                ev_completed("parent-action"),
            ]),
            sse(vec![ev_completed("parent-finished")]),
        ],
    )
    .await;
    test.codex
        .start_or_steer_turn(
            TurnInputRequest::user_input(vec![UserInput::Text {
                text: "Run the command after approval review.".to_string(),
                text_elements: Vec::new(),
            }])
            .with_thread_settings(ThreadSettingsOverrides {
                approval_policy: Some(AskForApproval::OnRequest),
                approvals_reviewer: Some(ApprovalsReviewer::AutoReview),
                sandbox_policy: Some(SandboxPolicy::WorkspaceWrite {
                    writable_roots: vec![],
                    network_access: false,
                    exclude_tmpdir_env_var: true,
                    exclude_slash_tmp: true,
                }),
                ..Default::default()
            }),
        )
        .await?;
    let mut warnings = Vec::new();
    wait_for_event(&test.codex, |event| {
        if let EventMsg::GuardianWarning(warning) = event {
            warnings.push(warning.message.clone());
        }
        matches!(event, EventMsg::TurnComplete(_))
    })
    .await;
    assert!(
        warnings.iter().any(|message| message.contains(
            "auto_review.experimental_policy_template expands beyond the 10,000 UTF-8 byte limit"
        )),
        "expected policy-size warning, got {warnings:?}"
    );
    let requests = responses.requests();
    assert_eq!(requests.len(), 2);
    assert_eq!(
        requests
            .iter()
            .filter(|request| {
                request.body_json()["client_metadata"]["x-openai-subagent"] == "guardian"
            })
            .count(),
        0
    );
    assert!(
        requests[1]
            .function_call_output_text("bounded-action")
            .expect("denied command output")
            .contains("automatic approval review could not be completed")
    );
    assert!(matches!(
        test.fs().get_metadata(
            &test.workspace_path_uri("guardian-policy-bounds.txt")?,
            Default::default(),
            /*sandbox*/ None,
        ).await,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound
    ));
    Ok(())
}
