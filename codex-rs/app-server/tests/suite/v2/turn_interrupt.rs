#![cfg(unix)]

use anyhow::Result;
use app_test_support::MockResponsesConfig;
use app_test_support::TestAppServer;
use app_test_support::create_final_assistant_message_sse_response;
use app_test_support::create_mock_responses_server_sequence;
use app_test_support::create_mock_responses_server_sequence_unchecked;
use app_test_support::create_shell_command_sse_response;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::JSONRPCError;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ServerRequest;
use codex_app_server_protocol::ServerRequestResolvedNotification;
use codex_app_server_protocol::ThreadStartParams;
use codex_app_server_protocol::ThreadStartResponse;
use codex_app_server_protocol::TurnCompletedNotification;
use codex_app_server_protocol::TurnInterruptParams;
use codex_app_server_protocol::TurnInterruptResponse;
use codex_app_server_protocol::TurnStartParams;
use codex_app_server_protocol::TurnStartResponse;
use codex_app_server_protocol::TurnStatus;
use codex_app_server_protocol::UserInput as V2UserInput;
use codex_protocol::ThreadId;
use core_test_support::responses;
use core_test_support::skip_if_remote;
use tempfile::TempDir;
use tokio::time::timeout;

const DEFAULT_READ_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(10);
const INVALID_REQUEST_ERROR_CODE: i64 = -32600;

fn create_coordination_cancel_sse_response(task_id: &str) -> Result<String> {
    let tool_call_arguments = serde_json::to_string(&serde_json::json!({
        "action": "cancel",
        "task_id": task_id,
        "summary": "App is already green."
    }))?;
    Ok(responses::sse(vec![
        responses::ev_response_created("resp-cancel"),
        responses::ev_function_call(
            "call_cancel_coordination",
            "coordination_act",
            &tool_call_arguments,
        ),
        responses::ev_completed("resp-cancel"),
    ]))
}

#[tokio::test]
async fn turn_interrupt_aborts_running_turn() -> Result<()> {
    // TODO(anp): Remove after the long-running command fixture can run in the selected remote environment.
    skip_if_remote!(
        Ok(()),
        "uses a host-local command and cwd fixture unavailable to remote executors"
    );

    // Use a portable sleep command to keep the turn running.
    #[cfg(target_os = "windows")]
    let shell_command = vec![
        "powershell".to_string(),
        "-Command".to_string(),
        "Start-Sleep -Seconds 10".to_string(),
    ];
    #[cfg(not(target_os = "windows"))]
    let shell_command = vec!["sleep".to_string(), "10".to_string()];

    let tmp = TempDir::new()?;
    let codex_home = tmp.path().join("codex_home");
    std::fs::create_dir(&codex_home)?;
    let working_directory = tmp.path().join("workdir");
    std::fs::create_dir(&working_directory)?;

    // Mock server: long-running shell command then (after abort) nothing else needed.
    let server =
        create_mock_responses_server_sequence_unchecked(vec![create_shell_command_sse_response(
            shell_command.clone(),
            Some(&working_directory),
            Some(10_000),
            "call_sleep",
        )?])
        .await;
    MockResponsesConfig::new(&server.uri())
        .with_sandbox_mode("workspace-write")
        .with_root_config(r#"approvals_reviewer = "user""#)
        .write(&codex_home)?;

    let mut mcp = TestAppServer::builder()
        .with_codex_home(&codex_home)
        .build_initialized()
        .await?;

    // Start a v2 thread and capture its id.
    let ThreadStartResponse { thread, .. } = mcp
        .start_thread(ThreadStartParams {
            model: Some("mock-model".to_string()),
            ..Default::default()
        })
        .await?;

    // Start a turn that triggers a long-running command.
    let TurnStartResponse { turn } = mcp
        .request(|request_id| ClientRequest::TurnStart {
            request_id,
            params: TurnStartParams {
                thread_id: thread.id.clone(),
                client_user_message_id: None,
                input: vec![V2UserInput::Text {
                    text: "run sleep".to_string(),
                    text_elements: Vec::new(),
                }],
                cwd: Some(working_directory.clone()),
                ..Default::default()
            },
        })
        .await?;
    let turn_id = turn.id.clone();

    // Give the command a brief moment to start.
    tokio::time::sleep(std::time::Duration::from_secs(1)).await;

    let thread_id = thread.id.clone();
    // Interrupt the in-progress turn by id (v2 API).
    let _: TurnInterruptResponse = mcp
        .request(|request_id| ClientRequest::TurnInterrupt {
            request_id,
            params: TurnInterruptParams {
                thread_id: thread_id.clone(),
                turn_id: turn_id.clone(),
            },
        })
        .await?;

    let completed: TurnCompletedNotification = timeout(
        DEFAULT_READ_TIMEOUT,
        mcp.read_notification("turn/completed"),
    )
    .await??;
    assert_eq!(completed.thread_id, thread_id);
    assert_eq!(completed.turn.status, TurnStatus::Interrupted);

    Ok(())
}

#[tokio::test]
async fn turn_interrupt_rejects_completed_turn() -> Result<()> {
    let tmp = TempDir::new()?;
    let codex_home = tmp.path().join("codex_home");
    std::fs::create_dir(&codex_home)?;

    let server = create_mock_responses_server_sequence_unchecked(vec![
        create_final_assistant_message_sse_response("done")?,
    ])
    .await;
    MockResponsesConfig::new(&server.uri())
        .with_sandbox_mode("workspace-write")
        .with_root_config(r#"approvals_reviewer = "user""#)
        .write(&codex_home)?;

    let mut mcp = TestAppServer::builder()
        .with_codex_home(&codex_home)
        .build_initialized()
        .await?;

    let ThreadStartResponse { thread, .. } = mcp
        .start_thread(ThreadStartParams {
            model: Some("mock-model".to_string()),
            ..Default::default()
        })
        .await?;

    let TurnStartResponse { turn } = mcp
        .request(|request_id| ClientRequest::TurnStart {
            request_id,
            params: TurnStartParams {
                thread_id: thread.id.clone(),
                client_user_message_id: None,
                input: vec![V2UserInput::Text {
                    text: "say done".to_string(),
                    text_elements: Vec::new(),
                }],
                ..Default::default()
            },
        })
        .await?;

    let completed: TurnCompletedNotification = timeout(
        DEFAULT_READ_TIMEOUT,
        mcp.read_notification("turn/completed"),
    )
    .await??;
    assert_eq!(completed.thread_id, thread.id);
    assert_eq!(completed.turn.id, turn.id);
    assert_eq!(completed.turn.status, TurnStatus::Completed);

    let interrupt_id = mcp
        .send_turn_interrupt_request(TurnInterruptParams {
            thread_id: thread.id,
            turn_id: turn.id,
        })
        .await?;

    let interrupt_err: JSONRPCError = timeout(
        std::time::Duration::from_millis(500),
        mcp.read_stream_until_error_message(RequestId::Integer(interrupt_id)),
    )
    .await??;
    assert_eq!(interrupt_err.error.code, INVALID_REQUEST_ERROR_CODE);

    Ok(())
}

#[tokio::test]
async fn turn_interrupt_resolves_pending_command_approval_request() -> Result<()> {
    // TODO(anp): Remove after the approval command fixture can run in the selected remote environment.
    skip_if_remote!(
        Ok(()),
        "uses a host-local command and cwd fixture unavailable to remote executors"
    );

    #[cfg(target_os = "windows")]
    let shell_command = vec![
        "powershell".to_string(),
        "-Command".to_string(),
        "Start-Sleep -Seconds 10".to_string(),
    ];
    #[cfg(not(target_os = "windows"))]
    let shell_command = vec![
        "python3".to_string(),
        "-c".to_string(),
        "import time; time.sleep(10)".to_string(),
    ];

    let tmp = TempDir::new()?;
    let codex_home = tmp.path().join("codex_home");
    std::fs::create_dir(&codex_home)?;
    let working_directory = tmp.path().join("workdir");
    std::fs::create_dir(&working_directory)?;

    let server = create_mock_responses_server_sequence(vec![create_shell_command_sse_response(
        shell_command.clone(),
        Some(&working_directory),
        Some(10_000),
        "call_sleep_approval",
    )?])
    .await;
    MockResponsesConfig::new(&server.uri())
        .with_approval_policy("untrusted")
        .with_root_config(r#"approvals_reviewer = "user""#)
        .write(&codex_home)?;

    let mut mcp = TestAppServer::builder()
        .with_codex_home(&codex_home)
        .build_initialized()
        .await?;

    let ThreadStartResponse { thread, .. } = mcp
        .start_thread(ThreadStartParams {
            model: Some("mock-model".to_string()),
            ..Default::default()
        })
        .await?;

    let TurnStartResponse { turn } = mcp
        .request(|request_id| ClientRequest::TurnStart {
            request_id,
            params: TurnStartParams {
                thread_id: thread.id.clone(),
                client_user_message_id: None,
                input: vec![V2UserInput::Text {
                    text: "run python".to_string(),
                    text_elements: Vec::new(),
                }],
                cwd: Some(working_directory),
                approval_policy: Some(codex_app_server_protocol::AskForApproval::UnlessTrusted),
                ..Default::default()
            },
        })
        .await?;

    let request = timeout(
        DEFAULT_READ_TIMEOUT,
        mcp.read_stream_until_request_message(),
    )
    .await??;
    let ServerRequest::CommandExecutionRequestApproval { request_id, params } = request else {
        panic!("expected CommandExecutionRequestApproval request");
    };
    assert_eq!(params.item_id, "call_sleep_approval");
    assert_eq!(params.thread_id, thread.id);
    assert_eq!(params.turn_id, turn.id);

    let _: TurnInterruptResponse = mcp
        .request(|request_id| ClientRequest::TurnInterrupt {
            request_id,
            params: TurnInterruptParams {
                thread_id: thread.id.clone(),
                turn_id: turn.id.clone(),
            },
        })
        .await?;

    let resolved: ServerRequestResolvedNotification = timeout(
        DEFAULT_READ_TIMEOUT,
        mcp.read_notification("serverRequest/resolved"),
    )
    .await??;
    assert_eq!(resolved.thread_id, thread.id);
    assert_eq!(resolved.request_id, request_id);

    let completed: TurnCompletedNotification = timeout(
        DEFAULT_READ_TIMEOUT,
        mcp.read_notification("turn/completed"),
    )
    .await??;
    assert_eq!(completed.thread_id, thread.id);
    assert_eq!(completed.turn.status, TurnStatus::Interrupted);

    Ok(())
}
#[tokio::test]
async fn cancelled_coordination_wake_interrupts_active_turn() -> Result<()> {
    // TODO: Remove after the long-running command fixture can run in the selected remote
    // environment.
    skip_if_remote!(
        Ok(()),
        "uses a host-local command and cwd fixture unavailable to remote executors"
    );

    #[cfg(target_os = "windows")]
    let shell_command = vec![
        "powershell".to_string(),
        "-Command".to_string(),
        "Start-Sleep -Seconds 30".to_string(),
    ];
    #[cfg(not(target_os = "windows"))]
    let shell_command = vec!["sleep".to_string(), "30".to_string()];

    let tmp = TempDir::new()?;
    let codex_home = tmp.path().join("codex_home");
    std::fs::create_dir(&codex_home)?;
    let working_directory = tmp.path().join("workdir");
    std::fs::create_dir(&working_directory)?;

    let server = create_mock_responses_server_sequence_unchecked(vec![
        create_shell_command_sse_response(
            shell_command,
            Some(&working_directory),
            Some(30_000),
            "call_sleep_cancelled_lane",
        )?,
        create_coordination_cancel_sse_response("task-cancelled-impl")?,
        create_final_assistant_message_sse_response("cancelled")?,
    ])
    .await;
    MockResponsesConfig::new(&server.uri())
        .with_sandbox_mode("workspace-write")
        .with_root_config(r#"approvals_reviewer = "user""#)
        .write(&codex_home)?;

    let mut mcp = TestAppServer::builder()
        .with_codex_home(&codex_home)
        .build_initialized()
        .await?;

    let ThreadStartResponse { thread, .. } = mcp
        .start_thread(ThreadStartParams {
            model: Some("mock-model".to_string()),
            ..Default::default()
        })
        .await?;
    let owner_thread_id = ThreadId::from_string(thread.id.as_str()).expect("thread id");

    let TurnStartResponse { turn } = mcp
        .request(|request_id| ClientRequest::TurnStart {
            request_id,
            params: TurnStartParams {
                thread_id: thread.id.clone(),
                input: vec![V2UserInput::Text {
                    text: "run sleep".to_string(),
                    text_elements: Vec::new(),
                }],
                cwd: Some(working_directory),
                ..Default::default()
            },
        })
        .await?;

    let ThreadStartResponse {
        thread: canceller_thread,
        ..
    } = mcp
        .start_thread(ThreadStartParams {
            model: Some("mock-model".to_string()),
            ..Default::default()
        })
        .await?;

    let state_db =
        codex_state::StateRuntime::init(codex_home.clone(), "mock_provider".to_string()).await?;
    let creator = ThreadId::from_string(canceller_thread.id.as_str()).expect("creator");

    state_db
        .create_coordination_task(codex_state::CoordinationTaskCreateParams {
            id: "task-cancelled-impl".to_string(),
            creator_thread_id: creator,
            owner_thread_id: Some(owner_thread_id),
            reserved_path_claims: vec![codex_state::PathClaimSpec {
                kind: codex_state::PathClaimKind::Directory,
                path: tmp.path().join("workdir"),
            }],
            claim_lease_seconds: codex_state::DEFAULT_COORDINATION_LEASE_SECONDS,
            team_id: None,
            room: Some("repo/test".to_string()),
            kind: codex_state::CoordinationTaskKind::Implementation,
            summary: "Polish styles".to_string(),
            details: "Own the CSS lane.".to_string(),
            requested_capability: None,
            dependency_task_ids: Vec::new(),
            act_id: "act-open-cancelled-impl".to_string(),
            act_summary: None,
            act_payload_json: "{}".to_string(),
        })
        .await?;
    state_db
        .accept_coordination_task(codex_state::CoordinationTaskAcceptParams {
            task_id: "task-cancelled-impl".to_string(),
            actor_thread_id: owner_thread_id,
            path_claims: vec![codex_state::PathClaimSpec {
                kind: codex_state::PathClaimKind::Directory,
                path: tmp.path().join("workdir"),
            }],
            lease_seconds: codex_state::DEFAULT_COORDINATION_LEASE_SECONDS,
            act_id: "act-accept-cancelled-impl".to_string(),
            act_summary: None,
            act_payload_json: "{}".to_string(),
        })
        .await?;

    let _: TurnStartResponse = mcp
        .request(|request_id| ClientRequest::TurnStart {
            request_id,
            params: TurnStartParams {
                thread_id: canceller_thread.id.clone(),
                input: vec![V2UserInput::Text {
                    text: "cancel the coordination lane".to_string(),
                    text_elements: Vec::new(),
                }],
                cwd: Some(tmp.path().join("workdir")),
                ..Default::default()
            },
        })
        .await?;

    let completed = loop {
        let completed: TurnCompletedNotification = timeout(
            std::time::Duration::from_secs(/*secs*/ 20),
            mcp.read_notification("turn/completed"),
        )
        .await??;
        if completed.thread_id == thread.id && completed.turn.id == turn.id {
            break completed;
        }
    };
    assert_eq!(completed.thread_id, thread.id);
    assert_eq!(completed.turn.id, turn.id);
    assert_eq!(completed.turn.status, TurnStatus::Interrupted);

    Ok(())
}
