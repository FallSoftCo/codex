use super::*;
use codex_protocol::context_refill::ContextRefillPurpose;
use codex_protocol::context_refill::ContextWindowRefillPhase;
use codex_protocol::context_refill::ContextWindowRefillReason;
use codex_protocol::protocol::ThreadHistoryMode;
use pretty_assertions::assert_eq;

fn intent() -> ContextWindowRefillIntentEvent {
    ContextWindowRefillIntentEvent {
        thread_id: "thread".into(),
        turn_id: "turn".into(),
        operation_id: "op".into(),
        context_id: "context".into(),
        purpose: ContextRefillPurpose::Writer,
        window_id: "old".into(),
        history_version: 7,
        snapshot_operation_id: "op".into(),
        snapshot_read_point: "read-point".into(),
        snapshot_sha256: "a".repeat(64),
        native_actions_sha256: "b".repeat(64),
        selection_revision: 4,
        total_bytes: 2,
        reason: ContextWindowRefillReason::ContextLimit,
        phase: ContextWindowRefillPhase::MidTurn,
        next_window_id: "new".into(),
    }
}

fn checkpoint() -> CompactedItem {
    // Exercise exact retained output ordering, not recursive set membership.
    serde_json::from_value(serde_json::json!({
        "message": "", "replacement_history": [{
            "type":"message", "role":"user",
            "content":[{"type":"input_text","text":"canonical data"}]
        }],
        "previous_window_id":"old", "window_id":"new"
    }))
    .unwrap()
}

fn state(path: &Path, file: std::fs::File) -> RolloutWriterState {
    RolloutWriterState {
        writer: Some(JsonlWriter {
            file: tokio::fs::File::from_std(file),
        }),
        deferred_creation: false,
        pending_items: Vec::new(),
        meta: None,
        cwd: path.parent().unwrap().into(),
        rollout_path: path.into(),
        ordinal_state: RolloutOrdinalState::Legacy,
        last_logged_error: None,
        refill_fault: None,
    }
}

#[tokio::test]
async fn durable_adjacent_receipt_has_non_circular_exact_prefix() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("rollout.jsonl");
    let file = std::fs::OpenOptions::new()
        .create_new(true)
        .read(true)
        .append(true)
        .open(&path)
        .unwrap();
    let mut writer = state(&path, file);
    let receipt = writer
        .install_context_refill_once(intent(), checkpoint())
        .await
        .unwrap();
    let bytes = std::fs::read(&path).unwrap();
    let lines: Vec<_> = bytes.split_inclusive(|b| *b == b'\n').collect();
    assert_eq!(lines.len(), 3);
    assert_eq!(
        receipt.native_history_bytes as usize,
        lines[0].len() + lines[1].len()
    );
    assert_eq!(
        receipt.native_history_sha256,
        format!(
            "{:x}",
            Sha256::digest(&bytes[..receipt.native_history_bytes as usize])
        )
    );
    let items: Vec<_> = lines
        .iter()
        .map(|line| crate::parse_rollout_line_bytes(line).unwrap().item)
        .collect();
    assert_eq!(
        serde_json::to_value(&items).unwrap(),
        serde_json::to_value(vec![
            RolloutItem::EventMsg(EventMsg::ContextWindowRefillIntent(intent())),
            RolloutItem::Compacted(Box::new(checkpoint())),
            RolloutItem::EventMsg(EventMsg::ContextWindowRefillInstalled(receipt)),
        ])
        .unwrap()
    );
    for mode in [ThreadHistoryMode::Legacy, ThreadHistoryMode::Paginated] {
        assert_eq!(
            serde_json::to_value(crate::policy::persisted_rollout_items(&items, mode)).unwrap(),
            serde_json::to_value(&items).unwrap()
        );
    }
}

#[tokio::test]
async fn failed_strict_write_terminates_queue_without_later_flush_or_shutdown_replay() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("rollout.jsonl");
    std::fs::write(&path, b"").unwrap();
    let readonly = std::fs::File::open(&path).unwrap();
    let writer = state(&path, readonly);
    let (tx, rx) = mpsc::channel(4);
    let (ack, receipt) = oneshot::channel();
    tx.send(RolloutCmd::ContextRefill {
        intent: Box::new(intent()),
        checkpoint: Box::new(checkpoint()),
        ack,
    })
    .await
    .unwrap();
    let (flush_ack, flush_result) = oneshot::channel();
    tx.send(RolloutCmd::Flush { ack: flush_ack }).await.unwrap();
    let (stop_ack, stop_result) = oneshot::channel();
    tx.send(RolloutCmd::Shutdown { ack: stop_ack })
        .await
        .unwrap();
    assert!(rollout_writer(writer, rx).await.is_err());
    assert!(receipt.await.unwrap().is_err());
    assert!(flush_result.await.is_err());
    assert!(stop_result.await.is_err());
    assert!(tx.is_closed());
    assert_eq!(std::fs::read(&path).unwrap(), b"");
}

#[tokio::test]
async fn recovery_or_deferred_writer_is_never_reopened_by_strict_refill() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("rollout.jsonl");
    let file = std::fs::OpenOptions::new()
        .create_new(true)
        .read(true)
        .append(true)
        .open(&path)
        .unwrap();
    let mut writer = state(&path, file);
    writer.last_logged_error = Some("original uncertain append".into());
    assert!(
        writer
            .install_context_refill_once(intent(), checkpoint())
            .await
            .is_err()
    );
    writer.last_logged_error = None;
    writer.writer = None;
    writer.deferred_creation = true;
    assert!(
        writer
            .install_context_refill_once(intent(), checkpoint())
            .await
            .is_err()
    );
    assert_eq!(std::fs::read(&path).unwrap(), b"");
}

#[tokio::test]
async fn partial_durability_and_lost_ack_never_reopen_or_replay_later_queue() {
    for fault in [
        RefillFault::AfterPrefix,
        RefillFault::AfterFirstSync,
        RefillFault::AfterReceiptSync,
    ] {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("rollout.jsonl");
        let file = std::fs::OpenOptions::new()
            .create_new(true)
            .read(true)
            .append(true)
            .open(&path)
            .unwrap();
        let mut writer = state(&path, file);
        writer.refill_fault = Some(fault);
        let (tx, rx) = mpsc::channel(5);
        let (ack, receipt) = oneshot::channel();
        tx.send(RolloutCmd::ContextRefill {
            intent: Box::new(intent()),
            checkpoint: Box::new(checkpoint()),
            ack,
        })
        .await
        .unwrap();
        // Would be auto-flushed/reopened by the ordinary recovery path if the
        // strict driver incorrectly continued after an uncertain partial effect.
        tx.send(RolloutCmd::AddItems(vec![RolloutItem::EventMsg(
            EventMsg::ContextWindowRefillIntent(ContextWindowRefillIntentEvent {
                operation_id: "forbidden-later-operation".into(),
                ..intent()
            }),
        )]))
        .await
        .unwrap();
        let (flush_ack, flush_result) = oneshot::channel();
        tx.send(RolloutCmd::Flush { ack: flush_ack }).await.unwrap();
        let (stop_ack, stop_result) = oneshot::channel();
        tx.send(RolloutCmd::Shutdown { ack: stop_ack })
            .await
            .unwrap();
        assert!(rollout_writer(writer, rx).await.is_err());
        assert!(receipt.await.unwrap().is_err());
        assert!(flush_result.await.is_err());
        assert!(stop_result.await.is_err());
        assert!(tx.is_closed());
        let original = std::fs::read(&path).unwrap();
        let items: Vec<_> = original
            .split_inclusive(|b| *b == b'\n')
            .map(|line| crate::parse_rollout_line_bytes(line).unwrap().item)
            .collect();
        assert_eq!(
            items.len(),
            if fault == RefillFault::AfterReceiptSync {
                3
            } else {
                2
            }
        );
        assert_eq!(
            serde_json::to_value(&items[0]).unwrap(),
            serde_json::to_value(RolloutItem::EventMsg(EventMsg::ContextWindowRefillIntent(
                intent()
            )))
            .unwrap()
        );
        assert_eq!(
            serde_json::to_value(&items[1]).unwrap(),
            serde_json::to_value(RolloutItem::Compacted(Box::new(checkpoint()))).unwrap()
        );
        let text = String::from_utf8(original.clone()).unwrap();
        assert!(!text.contains("forbidden-later-operation"));
        // Sending another ordinary barrier to the original closed driver must
        // fail, not create a new writer or repeat the original checkpoint.
        let (ack, _) = oneshot::channel();
        assert!(tx.send(RolloutCmd::Flush { ack }).await.is_err());
        assert_eq!(std::fs::read(&path).unwrap(), original);
    }
}

#[tokio::test]
async fn native_baseline_checkpoint_is_atomic_and_invalid_scope_never_writes() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("native-checkpoint.jsonl");
    let file = std::fs::OpenOptions::new()
        .create_new(true)
        .read(true)
        .append(true)
        .open(&path)
        .unwrap();
    let mut writer = state(&path, file);
    let mut native = serde_json::to_value(checkpoint()).unwrap();
    native["resume_metadata"] = serde_json::json!({
        "multi_agent_version":null, "last_started_turn_id":"turn",
        "previous_turn_settings":null,
        "native_context":{
            "schema":"lax-native-context-checkpoint/v1","thread_id":"thread","context_id":"context",
            "mode":"idle_request","world_state":{"full":true,"state":{"version":3}},
            "reference_context":null
        }
    });
    for (field, value) in [
        ("thread_id", serde_json::json!("foreign")),
        ("context_id", serde_json::json!("foreign")),
        ("schema", serde_json::json!("unknown")),
    ] {
        let mut invalid = native.clone();
        invalid["resume_metadata"]["native_context"][field] = value;
        assert!(
            writer
                .install_context_refill_once(intent(), serde_json::from_value(invalid).unwrap())
                .await
                .is_err()
        );
        assert_eq!(std::fs::read(&path).unwrap(), b"");
    }
    let mut patch = native.clone();
    patch["resume_metadata"]["native_context"]["world_state"]["full"] = serde_json::json!(false);
    assert!(
        writer
            .install_context_refill_once(intent(), serde_json::from_value(patch).unwrap())
            .await
            .is_err()
    );
    assert_eq!(std::fs::read(&path).unwrap(), b"");
    let mut oversized = native.clone();
    oversized["resume_metadata"]["native_context"]["world_state"]["state"]["large"] =
        serde_json::json!("x".repeat(1024 * 1024 + 1));
    assert!(
        writer
            .install_context_refill_once(intent(), serde_json::from_value(oversized).unwrap())
            .await
            .is_err()
    );
    assert_eq!(std::fs::read(&path).unwrap(), b"");
    let receipt = writer
        .install_context_refill_once(intent(), serde_json::from_value(native.clone()).unwrap())
        .await
        .unwrap();
    let bytes = std::fs::read(&path).unwrap();
    let lines: Vec<_> = bytes.split_inclusive(|b| *b == b'\n').collect();
    assert_eq!(lines.len(), 3);
    let persisted = crate::parse_rollout_line_bytes(lines[1]).unwrap().item;
    let RolloutItem::Compacted(checkpoint) = persisted else {
        panic!("missing checkpoint")
    };
    assert_eq!(serde_json::to_value(checkpoint).unwrap(), native);
    assert_eq!(
        receipt.native_history_bytes as usize,
        lines[0].len() + lines[1].len()
    );
    assert_eq!(
        receipt.native_history_sha256,
        format!(
            "{:x}",
            Sha256::digest(&bytes[..receipt.native_history_bytes as usize])
        )
    );
}
