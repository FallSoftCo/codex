use super::*;
use crate::session::tests::make_session_and_context;
use crate::session::tests::make_session_and_context_with_rx;
use crate::tools::context::ToolInvocation;
use crate::tools::context::ToolPayload;
use crate::turn_diff_tracker::TurnDiffTracker;
use codex_protocol::ThreadId;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::SessionSource;
use codex_protocol::protocol::SubAgentSource;
use pretty_assertions::assert_eq;
use serde_json::json;
use std::sync::Arc;
use tokio::sync::Mutex;
use tokio::time::Duration;
use tokio::time::timeout;

#[tokio::test]
async fn restart_client_rejects_subagent_threads() {
    let (session, mut turn) = make_session_and_context().await;
    turn.session_source = SessionSource::SubAgent(SubAgentSource::ThreadSpawn {
        parent_thread_id: ThreadId::new(),
        depth: 1,
        agent_path: None,
        agent_nickname: None,
        agent_role: None,
    });

    let result = RestartClientHandler
        .handle(ToolInvocation {
            session: Arc::new(session),
            turn: Arc::new(turn),
            cancellation_token: tokio_util::sync::CancellationToken::new(),
            tracker: Arc::new(Mutex::new(TurnDiffTracker::default())),
            call_id: "call-1".to_string(),
            tool_name: codex_tools::ToolName::plain(RESTART_CLIENT_TOOL_NAME),
            payload: ToolPayload::Function {
                arguments: json!({
                    "reason": "roll to latest build",
                })
                .to_string(),
            },
        })
        .await;

    let Err(err) = result else {
        panic!("sub-agent restart_client should fail");
    };
    assert_eq!(
        err,
        FunctionCallError::RespondToModel(
            "restart_client can only be used by the root thread".to_string(),
        )
    );
}

#[tokio::test]
async fn restart_client_emits_restart_event_and_returns_requested_status() {
    let (session, turn, rx_event) = make_session_and_context_with_rx().await;
    let thread_id = session.conversation_id.to_string();

    let output = RestartClientHandler
        .handle(ToolInvocation {
            session,
            turn,
            cancellation_token: tokio_util::sync::CancellationToken::new(),
            tracker: Arc::new(Mutex::new(TurnDiffTracker::default())),
            call_id: "call-1".to_string(),
            tool_name: codex_tools::ToolName::plain(RESTART_CLIENT_TOOL_NAME),
            payload: ToolPayload::Function {
                arguments: json!({
                    "reason": "roll to latest build",
                })
                .to_string(),
            },
        })
        .await
        .expect("restart_client should succeed");

    let result: serde_json::Value =
        serde_json::from_str(&output.into_text()).expect("restart_client result should be json");
    assert_eq!(
        result,
        json!({
            "status": "requested",
            "thread_id": thread_id,
            "reason": "roll to latest build",
        })
    );

    let event = timeout(Duration::from_secs(1), rx_event.recv())
        .await
        .expect("restart event should arrive")
        .expect("restart event should be readable");
    match event.msg {
        EventMsg::ClientRestartRequested(
            codex_protocol::protocol::ClientRestartRequestedEvent { reason },
        ) => {
            assert_eq!(reason, Some("roll to latest build".to_string()));
        }
        other => panic!("expected restart request event, got {other:?}"),
    }
}
