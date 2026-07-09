use super::*;
use codex_apply_patch::MaybeApplyPatchVerified;
use codex_exec_server::LOCAL_FS;
use codex_protocol::permissions::FileSystemSandboxPolicy;
use codex_protocol::protocol::FileChange;
use core_test_support::PathBufExt;
use core_test_support::PathExt;
use futures::future::join_all;
use pretty_assertions::assert_eq;
use serde_json::json;
use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;
use std::sync::Arc;
use tempfile::TempDir;
use tokio::sync::Barrier;
use tokio::sync::Mutex;

const COLLABORATIVE_STRESS_AGENTS: usize = 32;

use crate::session::step_context::StepContext;
use crate::session::tests::make_session_and_context;
use crate::tools::context::ToolInvocation;
use crate::tools::handlers::apply_patch_collaboration::apply_patch_collaboration_preflight;
use crate::tools::hook_names::HookToolName;
use crate::tools::registry::PostToolUsePayload;
use crate::tools::registry::PreToolUsePayload;
use crate::turn_diff_tracker::TurnDiffTracker;

fn sample_patch() -> &'static str {
    r#"*** Begin Patch
*** Add File: hello.txt
+hello
*** End Patch"#
}

async fn invocation_for_payload(payload: ToolPayload) -> ToolInvocation {
    let (session, turn) = make_session_and_context().await;
    let turn = Arc::new(turn);
    ToolInvocation {
        session: session.into(),
        step_context: StepContext::for_test(Arc::clone(&turn)),
        turn,
        cancellation_token: tokio_util::sync::CancellationToken::new(),
        tracker: Arc::new(Mutex::new(TurnDiffTracker::new())),
        call_id: "call-apply-patch".to_string(),
        tool_name: codex_tools::ToolName::plain("apply_patch"),
        source: crate::tools::context::ToolCallSource::Direct,
        payload,
    }
}

async fn session_with_state_db() -> (
    Arc<Session>,
    Arc<crate::session::turn_context::TurnContext>,
    Arc<codex_state::StateRuntime>,
) {
    let (mut session, turn) = make_session_and_context().await;
    let state_db = codex_rollout::state_db::init(turn.config.as_ref())
        .await
        .expect("sqlite state db should initialize");
    session.services.state_db = Some(Arc::clone(&state_db));
    (Arc::new(session), Arc::new(turn), state_db)
}

async fn apply_patch_after_collaboration_preflight(
    session: &Session,
    cwd: &AbsolutePathBuf,
    patch: &str,
) -> String {
    apply_patch_after_collaboration_preflight_with_barrier(session, cwd, patch, None).await
}

async fn apply_patch_after_collaboration_preflight_with_barrier(
    session: &Session,
    cwd: &AbsolutePathBuf,
    patch: &str,
    start_barrier: Option<Arc<Barrier>>,
) -> String {
    let argv = vec!["apply_patch".to_string(), patch.to_string()];
    let cwd = PathUri::from_abs_path(cwd);
    let action = match codex_apply_patch::maybe_parse_apply_patch_verified(
        &argv,
        &cwd,
        LOCAL_FS.as_ref(),
        None,
    )
    .await
    {
        MaybeApplyPatchVerified::Body(action) => action,
        other => panic!("expected verified patch body, got: {other:?}"),
    };
    let file_paths = file_paths_for_action(&action);
    let collaboration = apply_patch_collaboration_preflight(session, &file_paths)
        .await
        .expect("collaborative edit plan should allow apply_patch");

    if let Some(start_barrier) = start_barrier {
        start_barrier.wait().await;
    }

    let mut stdout = Vec::new();
    let mut stderr = Vec::new();
    codex_apply_patch::apply_patch(
        &action.patch,
        &action.cwd,
        &mut stdout,
        &mut stderr,
        LOCAL_FS.as_ref(),
        None,
    )
    .await
    .expect("collaborative edit apply_patch should write file");

    let _stdout = String::from_utf8(stdout).expect("apply_patch stdout should be utf8");
    assert_eq!(
        String::from_utf8(stderr).expect("apply_patch stderr should be utf8"),
        ""
    );
    collaboration.append_notice("Success. Updated files.".to_string())
}

async fn apply_collaborative_patch_wave(
    agents: &[Arc<Session>],
    cwd: &AbsolutePathBuf,
    patches: Vec<String>,
) -> Vec<String> {
    assert_eq!(agents.len(), patches.len());
    let start_barrier = Arc::new(Barrier::new(agents.len()));
    let edits = agents.iter().zip(patches.iter()).map(|(session, patch)| {
        apply_patch_after_collaboration_preflight_with_barrier(
            session.as_ref(),
            cwd,
            patch,
            Some(Arc::clone(&start_barrier)),
        )
    });
    join_all(edits).await
}

#[tokio::test]
async fn pre_tool_use_payload_uses_freeform_patch_input() {
    let patch = sample_patch();
    let payload = ToolPayload::Custom {
        input: patch.to_string(),
    };
    let invocation = invocation_for_payload(payload).await;
    let handler = ApplyPatchHandler::default();

    assert_eq!(
        handler.pre_tool_use_payload(&invocation),
        Some(PreToolUsePayload {
            tool_name: HookToolName::apply_patch(),
            tool_input: json!({ "command": patch }),
        })
    );
}

#[tokio::test]
async fn post_tool_use_payload_uses_patch_input_and_tool_output() {
    let patch = sample_patch();
    let payload = ToolPayload::Custom {
        input: patch.to_string(),
    };
    let invocation = invocation_for_payload(payload).await;
    let output = ApplyPatchToolOutput::from_text("Success. Updated files.".to_string());
    let handler = ApplyPatchHandler::default();

    assert_eq!(
        handler.post_tool_use_payload(&invocation, &output),
        Some(PostToolUsePayload {
            tool_name: HookToolName::apply_patch(),
            tool_use_id: "call-apply-patch".to_string(),
            tool_input: json!({ "command": patch }),
            tool_response: json!("Success. Updated files."),
        })
    );
}

#[tokio::test]
async fn preflight_blocks_peer_claim_without_collaborative_edit_plan() {
    let (session, turn, state_db) = session_with_state_db().await;
    let claimed_by_peer = codex_protocol::ThreadId::new();
    let file_path = turn.config.cwd.join("shared.rs").into_path_buf();
    state_db
        .claim_path_ownership(
            claimed_by_peer,
            &[codex_state::PathClaimSpec {
                kind: codex_state::PathClaimKind::File,
                path: file_path.clone(),
            }],
            std::time::Duration::from_secs(300),
        )
        .await
        .expect("claim path");
    let file_uri = PathUri::from_abs_path(
        &AbsolutePathBuf::from_absolute_path(file_path).expect("absolute file path"),
    );

    let err = apply_patch_collaboration_preflight(session.as_ref(), &[file_uri])
        .await
        .expect_err("peer-owned file should require a collaborative plan");

    let FunctionCallError::RespondToModel(message) = err else {
        panic!("expected model-facing preflight error");
    };
    assert!(message.contains("collaborative_edit_plan"));
    assert!(message.contains(claimed_by_peer.to_string().as_str()));
}

#[tokio::test]
async fn preflight_allows_peer_claim_with_collaborative_edit_plan() {
    let (session, turn, state_db) = session_with_state_db().await;
    let claimed_by_peer = codex_protocol::ThreadId::new();
    let file_path = turn.config.cwd.join("shared.rs").into_path_buf();
    state_db
        .claim_path_ownership(
            claimed_by_peer,
            &[codex_state::PathClaimSpec {
                kind: codex_state::PathClaimKind::File,
                path: file_path.clone(),
            }],
            std::time::Duration::from_secs(300),
        )
        .await
        .expect("claim path");
    state_db
        .record_collaborative_edit_plan(codex_state::CollaborativeEditPlanCreateParams {
            id: "plan-1".to_string(),
            actor_thread_id: session.thread_id(),
            room: Some("room".to_string()),
            file_path: file_path.clone(),
            edit_slice: "validation helper".to_string(),
            intent: "patch only the validation helper".to_string(),
            peers: vec![claimed_by_peer.to_string()],
            handoff: Some("I patch helper; peer reviews same file after".to_string()),
            integrator: Some(claimed_by_peer.to_string()),
            report_back: Some("after apply_patch".to_string()),
            lease_seconds: 300,
        })
        .await
        .expect("record plan");
    let file_uri = PathUri::from_abs_path(
        &AbsolutePathBuf::from_absolute_path(file_path).expect("absolute file path"),
    );

    let context = apply_patch_collaboration_preflight(session.as_ref(), &[file_uri])
        .await
        .expect("plan should allow peer-owned file");

    let output = context.append_notice("Success. Updated files.".to_string());
    assert!(output.contains("Collaborative edit plan matched"));
    assert!(output.contains("validation helper"));
}

#[tokio::test]
async fn preflight_allows_peer_claim_when_plan_uses_owner_hollywood_alias() {
    let (session, turn, state_db) = session_with_state_db().await;
    let claimed_by_peer = codex_protocol::ThreadId::new();
    let file_path = turn.config.cwd.join("shared.rs").into_path_buf();
    let config = session.get_config().await;
    crate::rollout::append_thread_name(
        config.codex_home.as_path(),
        claimed_by_peer,
        "BobAgent-e2ea841c",
    )
    .await
    .expect("record owner thread name");
    state_db
        .claim_path_ownership(
            claimed_by_peer,
            &[codex_state::PathClaimSpec {
                kind: codex_state::PathClaimKind::File,
                path: file_path.clone(),
            }],
            std::time::Duration::from_secs(300),
        )
        .await
        .expect("claim path");
    state_db
        .record_collaborative_edit_plan(codex_state::CollaborativeEditPlanCreateParams {
            id: "plan-1".to_string(),
            actor_thread_id: session.thread_id(),
            room: Some("room".to_string()),
            file_path: file_path.clone(),
            edit_slice: "Alice section only".to_string(),
            intent: "patch only Alice's shared notes section".to_string(),
            peers: vec!["bobagent-e2ea841c".to_string()],
            handoff: Some("Alice patches Alice section; Bob owns Bob section".to_string()),
            integrator: Some("aliceagent-e2ea841c".to_string()),
            report_back: Some("after apply_patch".to_string()),
            lease_seconds: 300,
        })
        .await
        .expect("record plan with owner alias");
    let file_uri = PathUri::from_abs_path(
        &AbsolutePathBuf::from_absolute_path(file_path).expect("absolute file path"),
    );

    let context = apply_patch_collaboration_preflight(session.as_ref(), &[file_uri])
        .await
        .expect("plan using owner Hollywood alias should allow peer-owned file");

    let output = context.append_notice("Success. Updated files.".to_string());
    assert!(output.contains("Collaborative edit plan matched"));
    assert!(output.contains("Alice section only"));
}

#[tokio::test]
async fn preflight_allows_peer_owned_file_when_owner_invites_actor() {
    let (session, turn, state_db) = session_with_state_db().await;
    let claimed_by_peer = codex_protocol::ThreadId::new();
    let file_path = turn.config.cwd.join("shared.rs").into_path_buf();
    state_db
        .claim_path_ownership(
            claimed_by_peer,
            &[codex_state::PathClaimSpec {
                kind: codex_state::PathClaimKind::File,
                path: file_path.clone(),
            }],
            std::time::Duration::from_secs(300),
        )
        .await
        .expect("claim path");
    state_db
        .record_collaborative_edit_plan(codex_state::CollaborativeEditPlanCreateParams {
            id: "plan-1".to_string(),
            actor_thread_id: claimed_by_peer,
            room: Some("room".to_string()),
            file_path: file_path.clone(),
            edit_slice: "render_toolbar".to_string(),
            intent: "add disabled-state label after the peer refactor".to_string(),
            peers: vec![session.thread_id().to_string()],
            handoff: Some("owner lands toolbar refactor; actor patches label after".to_string()),
            integrator: Some(claimed_by_peer.to_string()),
            report_back: Some("after apply_patch with exact slice and merge risk".to_string()),
            lease_seconds: 300,
        })
        .await
        .expect("record owner-authored plan");
    let file_uri = PathUri::from_abs_path(
        &AbsolutePathBuf::from_absolute_path(file_path).expect("absolute file path"),
    );

    let context = apply_patch_collaboration_preflight(session.as_ref(), &[file_uri])
        .await
        .expect("owner-authored plan should allow invited actor to patch peer-owned file");

    let output = context.append_notice("Success. Updated files.".to_string());
    assert!(output.contains("Collaborative edit plan matched"));
    assert!(output.contains("render_toolbar"));
    assert!(output.contains(claimed_by_peer.to_string().as_str()));
}

#[tokio::test]
async fn apply_patch_edits_peer_owned_file_when_owner_invites_actor() {
    let (session, _turn, state_db) = session_with_state_db().await;
    let tmp = TempDir::new().expect("tmp");
    let cwd = tmp.path().abs();
    let claimed_by_peer = codex_protocol::ThreadId::new();
    let file_path = cwd.join("shared.rs").into_path_buf();
    fs::write(
        &file_path,
        "pub fn render_toolbar() -> &'static str {\n    \"enabled\"\n}\n",
    )
    .expect("write collaborative edit fixture");
    state_db
        .claim_path_ownership(
            claimed_by_peer,
            &[codex_state::PathClaimSpec {
                kind: codex_state::PathClaimKind::File,
                path: file_path.clone(),
            }],
            std::time::Duration::from_secs(300),
        )
        .await
        .expect("claim path");
    state_db
        .record_collaborative_edit_plan(codex_state::CollaborativeEditPlanCreateParams {
            id: "plan-1".to_string(),
            actor_thread_id: claimed_by_peer,
            room: Some("room".to_string()),
            file_path: file_path.clone(),
            edit_slice: "render_toolbar".to_string(),
            intent: "replace the enabled label with the disabled-state label".to_string(),
            peers: vec![session.thread_id().to_string()],
            handoff: Some("owner lands toolbar refactor; actor patches label after".to_string()),
            integrator: Some(claimed_by_peer.to_string()),
            report_back: Some("after apply_patch with exact slice and merge risk".to_string()),
            lease_seconds: 300,
        })
        .await
        .expect("record owner-authored plan");
    let patch = r#"*** Begin Patch
*** Update File: shared.rs
@@
 pub fn render_toolbar() -> &'static str {
-    "enabled"
+    "disabled-state label"
 }
*** End Patch"#;
    let output = apply_patch_after_collaboration_preflight(session.as_ref(), &cwd, patch).await;

    assert_eq!(
        fs::read_to_string(&file_path).expect("read patched collaborative edit fixture"),
        "pub fn render_toolbar() -> &'static str {\n    \"disabled-state label\"\n}\n"
    );
    assert!(output.contains("Collaborative edit plan matched"));
    assert!(output.contains("render_toolbar"));
    assert!(output.contains(claimed_by_peer.to_string().as_str()));
}

#[tokio::test]
async fn two_agents_start_collaborative_edits_to_same_file_concurrently() {
    let (agent_a, _turn_a, state_db) = session_with_state_db().await;
    let (mut agent_b, _turn_b) = make_session_and_context().await;
    agent_b.services.state_db = Some(Arc::clone(&state_db));
    let agent_b = Arc::new(agent_b);
    assert_ne!(agent_a.thread_id(), agent_b.thread_id());

    let tmp = TempDir::new().expect("tmp");
    let cwd = tmp.path().abs();
    let file_path = cwd.join("shared.rs").into_path_buf();
    fs::write(
        &file_path,
        concat!(
            "pub fn render_toolbar() -> &'static str {\n",
            "    \"enabled\"\n",
            "}\n\n",
            "pub fn render_status() -> &'static str {\n",
            "    \"idle\"\n",
            "}\n",
        ),
    )
    .expect("write shared collaborative edit fixture");
    state_db
        .claim_path_ownership(
            agent_a.thread_id(),
            &[codex_state::PathClaimSpec {
                kind: codex_state::PathClaimKind::File,
                path: file_path.clone(),
            }],
            std::time::Duration::from_secs(300),
        )
        .await
        .expect("agent A should claim shared file");
    state_db
        .record_collaborative_edit_plan(codex_state::CollaborativeEditPlanCreateParams {
            id: "plan-1".to_string(),
            actor_thread_id: agent_a.thread_id(),
            room: Some("room".to_string()),
            file_path: file_path.clone(),
            edit_slice: "render_toolbar and render_status".to_string(),
            intent: "agent A updates toolbar label; agent B updates status label".to_string(),
            peers: vec![agent_b.thread_id().to_string()],
            handoff: Some(
                "agent A patches toolbar first; agent B patches status after".to_string(),
            ),
            integrator: Some(agent_a.thread_id().to_string()),
            report_back: Some("each agent reports after apply_patch with exact slice".to_string()),
            lease_seconds: 300,
        })
        .await
        .expect("record shared collaborative edit plan");

    let agent_a_patch = r#"*** Begin Patch
*** Update File: shared.rs
@@
 pub fn render_toolbar() -> &'static str {
-    "enabled"
+    "ready from agent A"
 }
*** End Patch"#
        .to_string();
    let agent_b_patch = r#"*** Begin Patch
*** Update File: shared.rs
@@
 pub fn render_status() -> &'static str {
-    "idle"
+    "collaborating from agent B"
 }
*** End Patch"#
        .to_string();

    let agents = vec![Arc::clone(&agent_a), Arc::clone(&agent_b)];
    let outputs =
        apply_collaborative_patch_wave(&agents, &cwd, vec![agent_a_patch, agent_b_patch]).await;
    let agent_a_output = &outputs[0];
    let agent_b_output = &outputs[1];

    assert!(agent_a_output.contains("Collaborative edit plan matched"));
    assert!(agent_a_output.contains("render_toolbar and render_status"));
    assert!(agent_a_output.contains(agent_a.thread_id().to_string().as_str()));
    assert!(agent_b_output.contains("Collaborative edit plan matched"));
    assert!(agent_b_output.contains("render_toolbar and render_status"));
    assert!(agent_b_output.contains(agent_a.thread_id().to_string().as_str()));

    assert_eq!(
        fs::read_to_string(&file_path).expect("read jointly edited file"),
        concat!(
            "pub fn render_toolbar() -> &'static str {\n",
            "    \"ready from agent A\"\n",
            "}\n\n",
            "pub fn render_status() -> &'static str {\n",
            "    \"collaborating from agent B\"\n",
            "}\n",
        )
    );
}

#[tokio::test]
async fn many_agents_apply_two_rounds_of_collaborative_edits_to_same_file() {
    let (agent_a, _turn_a, state_db) = session_with_state_db().await;
    let mut agents = vec![agent_a];
    for _ in 1..COLLABORATIVE_STRESS_AGENTS {
        let (mut agent, _turn) = make_session_and_context().await;
        agent.services.state_db = Some(Arc::clone(&state_db));
        agents.push(Arc::new(agent));
    }
    for left in 0..agents.len() {
        for right in (left + 1)..agents.len() {
            assert_ne!(agents[left].thread_id(), agents[right].thread_id());
        }
    }

    let tmp = TempDir::new().expect("tmp");
    let cwd = tmp.path().abs();
    let file_path = cwd.join("shared.rs").into_path_buf();
    let patch_for = |agent_id: usize, from: &str, to: &str| {
        format!(
            "*** Begin Patch\n*** Update File: shared.rs\n@@\n pub fn section_{agent_id}() -> &'static str {{\n-    \"{from}\"\n+    \"{to}\"\n }}\n*** End Patch"
        )
    };

    let mut initial = String::new();
    let mut round_one_expected = String::new();
    let mut round_two_expected = String::new();
    let mut round_one_patches = Vec::new();
    let mut round_two_patches = Vec::new();
    for agent_id in 0..agents.len() {
        let separator = if agent_id + 1 == agents.len() {
            "\n"
        } else {
            "\n\n"
        };
        let initial_label = format!("agent-{agent_id}-v0");
        let round_one_label = format!("agent-{agent_id}-round-1");
        let round_two_label = format!("agent-{agent_id}-round-2");
        initial.push_str(&format!(
            "pub fn section_{agent_id}() -> &'static str {{\n    \"{initial_label}\"\n}}{separator}"
        ));
        round_one_expected.push_str(&format!(
            "pub fn section_{agent_id}() -> &'static str {{\n    \"{round_one_label}\"\n}}{separator}"
        ));
        round_two_expected.push_str(&format!(
            "pub fn section_{agent_id}() -> &'static str {{\n    \"{round_two_label}\"\n}}{separator}"
        ));
        round_one_patches.push(patch_for(agent_id, &initial_label, &round_one_label));
        round_two_patches.push(patch_for(agent_id, &round_one_label, &round_two_label));
    }
    fs::write(&file_path, initial).expect("write shared collaborative edit fixture");

    let owner_id = agents[0].thread_id();
    state_db
        .claim_path_ownership(
            owner_id,
            &[codex_state::PathClaimSpec {
                kind: codex_state::PathClaimKind::File,
                path: file_path.clone(),
            }],
            std::time::Duration::from_secs(300),
        )
        .await
        .expect("owner should claim shared file");
    let edit_slice = format!("{COLLABORATIVE_STRESS_AGENTS} independent section labels");
    state_db
        .record_collaborative_edit_plan(codex_state::CollaborativeEditPlanCreateParams {
            id: format!("plan-{COLLABORATIVE_STRESS_AGENTS}-agent-rounds"),
            actor_thread_id: owner_id,
            room: Some("room".to_string()),
            file_path: file_path.clone(),
            edit_slice: edit_slice.clone(),
            intent: "each agent updates its assigned section label across repeated waves"
                .to_string(),
            peers: agents
                .iter()
                .skip(1)
                .map(|agent| agent.thread_id().to_string())
                .collect(),
            handoff: Some(
                "all agents patch their section in each wave and report completion".to_string(),
            ),
            integrator: Some(owner_id.to_string()),
            report_back: Some("each agent reports after apply_patch with exact slice".to_string()),
            lease_seconds: 300,
        })
        .await
        .expect("record shared collaborative edit plan");

    let round_one_outputs = apply_collaborative_patch_wave(&agents, &cwd, round_one_patches).await;
    for output in &round_one_outputs {
        assert!(output.contains("Collaborative edit plan matched"));
        assert!(output.contains(&edit_slice));
        assert!(output.contains(owner_id.to_string().as_str()));
    }
    assert_eq!(
        fs::read_to_string(&file_path).expect("read round-one collaboratively edited file"),
        round_one_expected
    );

    let round_two_outputs = apply_collaborative_patch_wave(&agents, &cwd, round_two_patches).await;
    for output in &round_two_outputs {
        assert!(output.contains("Collaborative edit plan matched"));
        assert!(output.contains(&edit_slice));
        assert!(output.contains(owner_id.to_string().as_str()));
    }
    assert_eq!(
        fs::read_to_string(&file_path).expect("read round-two collaboratively edited file"),
        round_two_expected
    );
}

#[tokio::test]
async fn preflight_rejects_plan_that_omits_blocking_owner() {
    let (session, turn, state_db) = session_with_state_db().await;
    let claimed_by_peer = codex_protocol::ThreadId::new();
    let file_path = turn.config.cwd.join("shared.rs").into_path_buf();
    state_db
        .claim_path_ownership(
            claimed_by_peer,
            &[codex_state::PathClaimSpec {
                kind: codex_state::PathClaimKind::File,
                path: file_path.clone(),
            }],
            std::time::Duration::from_secs(300),
        )
        .await
        .expect("claim path");
    state_db
        .record_collaborative_edit_plan(codex_state::CollaborativeEditPlanCreateParams {
            id: "plan-1".to_string(),
            actor_thread_id: session.thread_id(),
            room: Some("room".to_string()),
            file_path: file_path.clone(),
            edit_slice: "validation helper".to_string(),
            intent: "patch only the validation helper".to_string(),
            peers: Vec::new(),
            handoff: Some("I patch helper; peer reviews same file after".to_string()),
            integrator: None,
            report_back: Some("after apply_patch".to_string()),
            lease_seconds: 300,
        })
        .await
        .expect("record plan");
    let file_uri = PathUri::from_abs_path(
        &AbsolutePathBuf::from_absolute_path(file_path).expect("absolute file path"),
    );

    let err = apply_patch_collaboration_preflight(session.as_ref(), &[file_uri])
        .await
        .expect_err("plan should name the blocking owner");

    let FunctionCallError::RespondToModel(message) = err else {
        panic!("expected model-facing preflight error");
    };
    assert!(message.contains("claim owned by"));
    assert!(message.contains(claimed_by_peer.to_string().as_str()));
}

#[test]
fn diff_consumer_streams_apply_patch_changes() {
    let mut consumer = ApplyPatchArgumentDiffConsumer::default();
    assert!(
        consumer
            .push_delta("call-1".to_string(), "*** Begin Patch\n")
            .is_none()
    );

    let event = consumer
        .push_delta("call-1".to_string(), "*** Add File: hello.txt\n+hello")
        .expect("progress event");
    assert_eq!(
        (event.call_id, event.changes),
        (
            "call-1".to_string(),
            HashMap::from([(
                PathBuf::from("hello.txt"),
                FileChange::Add {
                    content: String::new(),
                },
            )]),
        )
    );

    assert!(
        consumer
            .push_delta("call-1".to_string(), "\n+world")
            .is_none()
    );
    assert!(
        consumer
            .push_delta("call-1".to_string(), "\n*** End Patch")
            .is_none()
    );

    let event = consumer
        .finish_update_on_complete()
        .expect("finish update")
        .expect("progress event");
    assert_eq!(
        (event.call_id, event.changes),
        (
            "call-1".to_string(),
            HashMap::from([(
                PathBuf::from("hello.txt"),
                FileChange::Add {
                    content: "hello\nworld\n".to_string(),
                },
            )]),
        )
    );
}

#[test]
fn diff_consumer_streams_apply_patch_changes_with_environment_header() {
    let mut consumer = ApplyPatchArgumentDiffConsumer::default();
    assert!(
        consumer
            .push_delta(
                "call-1".to_string(),
                "*** Begin Patch\n*** Environment ID: remote\n",
            )
            .is_none()
    );

    let event = consumer
        .push_delta("call-1".to_string(), "*** Add File: hello.txt\n+hello")
        .expect("progress event");
    assert_eq!(
        event.changes,
        HashMap::from([(
            PathBuf::from("hello.txt"),
            FileChange::Add {
                content: String::new(),
            },
        )])
    );
}

#[test]
fn diff_consumer_sends_next_update_after_buffer_interval() {
    let mut consumer = ApplyPatchArgumentDiffConsumer::default();
    consumer.push_delta("call-1".to_string(), "*** Begin Patch\n");
    let first = consumer
        .push_delta("call-1".to_string(), "*** Add File: hello.txt\n+hello")
        .expect("first progress event");
    assert_eq!(
        first.changes,
        HashMap::from([(
            PathBuf::from("hello.txt"),
            FileChange::Add {
                content: String::new(),
            },
        )])
    );

    consumer.last_sent_at =
        Some(std::time::Instant::now() - APPLY_PATCH_ARGUMENT_DIFF_BUFFER_INTERVAL);
    let second = consumer
        .push_delta("call-1".to_string(), "\n+world")
        .expect("second progress event");
    assert_eq!(
        second.changes,
        HashMap::from([(
            PathBuf::from("hello.txt"),
            FileChange::Add {
                content: "hello\n".to_string(),
            },
        )])
    );
}

#[test]
fn reconcile_environment_id_requires_selection_when_enabled() {
    assert_eq!(
        require_environment_id(Some("remote"), /*allow_environment_id*/ false),
        Err(FunctionCallError::RespondToModel(
            "apply_patch environment selection is unavailable for this turn".to_string(),
        ))
    );
    assert_eq!(
        require_environment_id(
            /*parsed_environment_id*/ None, /*allow_environment_id*/ true
        ),
        Ok(None)
    );
}

#[tokio::test]
async fn approval_keys_include_move_destination() {
    let tmp = TempDir::new().expect("tmp");
    let cwd_path = tmp.path();
    let cwd = cwd_path.abs();
    std::fs::create_dir_all(cwd_path.join("old")).expect("create old dir");
    std::fs::create_dir_all(cwd_path.join("renamed/dir")).expect("create dest dir");
    std::fs::write(cwd_path.join("old/name.txt"), "old content\n").expect("write old file");
    let patch = r#"*** Begin Patch
*** Update File: old/name.txt
*** Move to: renamed/dir/name.txt
@@
-old content
+new content
*** End Patch"#;
    let argv = vec!["apply_patch".to_string(), patch.to_string()];
    // TODO(anp): Keep apply_patch handler test cwd values as PathUri.
    let cwd = PathUri::from_abs_path(&cwd);
    let action = match codex_apply_patch::maybe_parse_apply_patch_verified(
        &argv,
        &cwd,
        LOCAL_FS.as_ref(),
        /*sandbox*/ None,
    )
    .await
    {
        MaybeApplyPatchVerified::Body(action) => action,
        other => panic!("expected patch body, got: {other:?}"),
    };

    let keys = file_paths_for_action(&action);
    assert_eq!(keys.len(), 2);
}

#[test]
fn write_permissions_for_paths_skip_dirs_already_writable_under_workspace_root() {
    let tmp = TempDir::new().expect("tmp");
    let cwd_path = tmp.path();
    let cwd = cwd_path.abs();
    let nested = cwd_path.join("nested");
    std::fs::create_dir_all(&nested).expect("create nested dir");
    let file_path = AbsolutePathBuf::try_from(nested.join("file.txt"))
        .expect("nested file path should be absolute");
    let sandbox_policy = FileSystemSandboxPolicy::workspace_write(
        &[],
        /*exclude_tmpdir_env_var*/ true,
        /*exclude_slash_tmp*/ false,
    );

    let permissions = write_permissions_for_paths(&[file_path], &sandbox_policy, &cwd);

    assert_eq!(permissions, None);
}

#[test]
fn write_permissions_for_paths_keep_dirs_outside_workspace_root() {
    let tmp = TempDir::new().expect("tmp");
    let cwd = tmp.path().join("workspace");
    let outside = tmp.path().join("outside");
    std::fs::create_dir_all(&cwd).expect("create cwd");
    std::fs::create_dir_all(&outside).expect("create outside dir");
    let file_path = AbsolutePathBuf::try_from(outside.join("file.txt"))
        .expect("outside file path should be absolute");
    let cwd_abs = cwd.abs();
    let sandbox_policy = FileSystemSandboxPolicy::workspace_write(
        &[],
        /*exclude_tmpdir_env_var*/ true,
        /*exclude_slash_tmp*/ true,
    );

    let permissions = write_permissions_for_paths(&[file_path], &sandbox_policy, &cwd_abs);
    let expected_outside =
        dunce::simplified(&outside.canonicalize().expect("canonicalize outside dir")).abs();

    assert_eq!(
        permissions
            .and_then(|profile| profile.file_system)
            .and_then(|fs| fs.legacy_read_write_roots())
            .and_then(|(_read, write)| write),
        Some(vec![expected_outside])
    );
}

#[test]
fn format_apply_patch_verification_error_adds_stale_context_recovery_hint() {
    let formatted =
        format_apply_patch_verification_error("Failed to find expected lines in /tmp/x:\nold");

    assert!(formatted.contains("apply_patch verification failed"));
    assert!(formatted.contains("Failed to find expected lines in /tmp/x"));
    assert!(formatted.contains("Re-read the current file or diff"));
}

#[test]
fn format_apply_patch_verification_error_leaves_other_errors_plain() {
    let formatted = format_apply_patch_verification_error("invalid hunk header");

    assert_eq!(
        formatted,
        "apply_patch verification failed: invalid hunk header"
    );
}

#[test]
fn format_apply_patch_verification_error_adds_missing_file_recovery_hint() {
    let formatted = format_apply_patch_verification_error(
        "Failed to read file to update /tmp/missing.js: No such file or directory (os error 2)",
    );

    assert!(formatted.contains("apply_patch paths must reference real files"));
    assert!(formatted.contains("rewrite it relative to the workspace root"));
    assert!(formatted.contains("retarget or reopen the task"));
}

#[test]
fn format_apply_patch_verification_error_adds_generic_missing_read_hint() {
    let formatted = format_apply_patch_verification_error(
        "Failed to read /tmp/missing.js: No such file or directory (os error 2)",
    );

    assert!(formatted.contains("apply_patch paths must reference real files"));
    assert!(formatted.contains("rewrite it relative to the workspace root"));
}
