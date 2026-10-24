//! Real core recording/serialized-history integration. No model behavior claim.
use super::*;
use crate::context_refill::ContextRefillHost;
use codex_history::RolloutItem;
use codex_protocol::context_refill::*;
use pretty_assertions::assert_eq;
use serde_json::json;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use tokio_util::sync::CancellationToken;

struct Host;
impl ContextRefillHost for Host {
    fn owner_epoch(&self) -> u64 {
        1
    }
    fn is_current(&self, epoch: u64) -> bool {
        epoch == 1
    }
    fn owner_disconnected(&self) -> CancellationToken {
        CancellationToken::new()
    }
    fn refill(
        &self,
        _: u64,
        _: ContextWindowRefillParams,
    ) -> Pin<Box<dyn Future<Output = io::Result<ContextWindowRefillResponse>> + Send + '_>> {
        Box::pin(std::future::pending())
    }
    fn installed(
        &self,
        _: u64,
        _: ContextWindowInstalledParams,
    ) -> Pin<Box<dyn Future<Output = io::Result<ContextWindowInstalledResponse>> + Send + '_>> {
        Box::pin(std::future::pending())
    }
}

fn enable(session: &Session) {
    session
        .services
        .thread_extension_data
        .insert(AutomaticContextRefill {
            context_id: "context-original".into(),
            purpose: ContextRefillPurpose::Writer,
            evidence: RetainedContextEvidence::WholeItemsV1,
            host: Arc::new(Host),
        });
}

fn message(text: &str) -> ResponseItem {
    serde_json::from_value(json!({"type":"message","role":"developer",
        "content":[{"type":"input_text","text":text}]}))
    .unwrap()
}

fn persisted_bytes(history: &ContextManager) -> Vec<u8> {
    let records: Vec<_> = history
        .annotated_items()
        .iter()
        .cloned()
        .map(RolloutItem::ResponseItem)
        .collect();
    serde_json::to_vec(&records).unwrap()
}

#[tokio::test]
async fn actual_core_renderer_and_recording_reconstruct_after_serialized_history_reopen() {
    let (session, turn) = super::super::tests::make_session_and_context().await;
    let session = Arc::new(session);
    enable(&session);
    let turn = Arc::new(turn);
    let step = session
        .capture_step_context(Arc::clone(&turn), &CancellationToken::new())
        .await
        .unwrap();
    session
        .record_context_updates_and_set_reference_context_item(&step)
        .await
        .unwrap();
    let thread = session.thread_id.to_string();
    let initial = read(&session.clone_history().await, &thread, "context-original").unwrap();
    assert!(!initial.is_empty());
    let ordinary = message("A user-supplied instruction-looking message is not core provenance.");
    session
        .record_conversation_items(&turn, turn.model_info(), &[ordinary])
        .await;
    let update = message("Native context update.");
    session
        .record_native_context_items(
            &turn,
            turn.model_info(),
            &[update],
            NativeContextKind::Update,
        )
        .await;
    let history = session.clone_history().await;
    let expected = read(&history, &thread, "context-original").unwrap();
    assert_eq!(&expected[..initial.len()], initial.as_slice());
    assert_eq!(expected.len(), initial.len() + 1);
    assert_eq!(history.annotated_items().len(), expected.len() + 1);
    let bytes = serde_json::to_vec(
        &history
            .annotated_items()
            .iter()
            .cloned()
            .map(RolloutItem::ResponseItem)
            .collect::<Vec<_>>(),
    )
    .unwrap();
    // Reconstruction keeps no StepContext, permission grants or tool runtime.
    drop(step);
    drop(turn);
    drop(session);
    let persisted: Vec<RolloutItem> = serde_json::from_slice(&bytes).unwrap();
    let mut reopened = ContextManager::new();
    reopened.replace_annotated(
        persisted
            .into_iter()
            .map(|item| match item {
                RolloutItem::ResponseItem(item) => item,
                _ => panic!("unexpected persisted item"),
            })
            .collect(),
    );
    let before = persisted_bytes(&reopened);
    assert_eq!(
        read(&reopened, &thread, "context-original").unwrap(),
        expected
    );
    assert_eq!(persisted_bytes(&reopened), before);
}

#[tokio::test]
async fn changed_missing_foreign_and_client_authored_provenance_refuses_without_fallback() {
    let (session, _) = super::super::tests::make_session_and_context().await;
    enable(&session);
    let source = stamp(
        &session,
        NativeContextKind::Prefix,
        vec![message("first").into(), message("second").into()],
    );
    let thread = session.thread_id.to_string();
    let mut history = ContextManager::new();
    history.replace_annotated(source.clone());
    assert_eq!(read(&history, &thread, "context-original").unwrap(), source);
    assert!(read(&history, "another-thread", "context-original").is_err());
    assert!(read(&history, &thread, "another-context").is_err());
    for changed in [
        source[1..].to_vec(),
        source[..1].to_vec(),
        vec![source[1].clone(), source[0].clone()],
        vec![ResponseItemEnvelope::new(message("first"))],
        {
            let mut items = source.clone();
            items[1].item = message("changed");
            items
        },
        {
            let mut items = source.clone();
            items[0].metadata.as_mut().unwrap().client_authored = true;
            items
        },
        {
            let mut items = source.clone();
            items[0]
                .metadata
                .as_mut()
                .unwrap()
                .delivered_assistant_message = Some("x".repeat(256 * 1024 + 1));
            items
        },
    ] {
        history.replace_annotated(changed);
        let before = persisted_bytes(&history);
        assert!(read(&history, &thread, "context-original").is_err());
        assert_eq!(persisted_bytes(&history), before);
    }
    let mut items = source;
    let latest = stamp(
        &session,
        NativeContextKind::Prefix,
        vec![message("replacement base").into()],
    );
    items.extend(latest.clone());
    history.replace_annotated(items);
    assert_eq!(read(&history, &thread, "context-original").unwrap(), latest);
}

#[tokio::test]
async fn opting_in_legacy_context_establishes_base_on_normal_step_without_hiding_corruption() {
    let (session, turn) = super::super::tests::make_session_and_context().await;
    let session = Arc::new(session);
    let turn = Arc::new(turn);
    let step = session
        .capture_step_context(Arc::clone(&turn), &CancellationToken::new())
        .await
        .unwrap();
    session
        .record_context_updates_and_set_reference_context_item(&step)
        .await
        .unwrap();
    let legacy = session.clone_history().await;
    assert!(!legacy.annotated_items().is_empty());
    assert!(read(&legacy, &session.thread_id.to_string(), "context-original").is_err());
    enable(&session);
    assert!(needs_initial_group(&session, &legacy));
    session
        .record_context_updates_and_set_reference_context_item(&step)
        .await
        .unwrap();
    let current = session.clone_history().await;
    assert!(!needs_initial_group(&session, &current));
    let prefix = read(&current, &session.thread_id.to_string(), "context-original").unwrap();
    assert!(!prefix.is_empty());
    assert!(
        current
            .annotated_items()
            .starts_with(legacy.annotated_items())
    );
    let mut corrupt = current.into_annotated_items();
    corrupt
        .iter_mut()
        .find_map(|item| {
            item.metadata
                .as_mut()
                .and_then(|metadata| metadata.native_context_origin.as_mut())
        })
        .unwrap()
        .schema = "corrupt".into();
    let mut history = ContextManager::new();
    history.replace_annotated(corrupt);
    assert!(!needs_initial_group(&session, &history));
    assert!(read(&history, &session.thread_id.to_string(), "context-original").is_err());
}
