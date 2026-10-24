use super::*;
use codex_app_server_protocol::ContextInputParams;
use codex_app_server_protocol::DynamicToolCallParams;
use codex_protocol::context_refill::ContextRefillPurpose;
use serde_json::json;

fn dynamic(thread: ThreadId, turn: &str) -> ServerRequestPayload {
    ServerRequestPayload::DynamicToolCall(DynamicToolCallParams {
        thread_id: thread.to_string(),
        turn_id: turn.into(),
        call_id: turn.into(),
        namespace: None,
        tool: "fixture".into(),
        arguments: json!({}),
    })
}

#[tokio::test]
async fn turn_cleanup_preserves_current_and_newer_callbacks() {
    let (tx, _rx) = mpsc::channel::<OutgoingEnvelope>(8);
    let outgoing = Arc::new(OutgoingMessageSender::new(
        tx,
        AnalyticsEventsClient::disabled(),
    ));
    let thread = ThreadId::new();
    let scoped =
        ThreadScopedOutgoingMessageSender::new(outgoing.clone(), vec![ConnectionId(1)], thread);
    let (_, old) = scoped.send_request(dynamic(thread, "old")).await;
    let (_, mut current) = scoped.send_request(dynamic(thread, "current")).await;
    scoped
        .abort_server_requests(TurnRequestCleanup::Starting("current"))
        .await;
    assert!(old.await.unwrap().is_err());
    assert!(matches!(
        current.try_recv(),
        Err(oneshot::error::TryRecvError::Empty)
    ));
    let (_, mut newer) = scoped.send_request(dynamic(thread, "newer")).await;
    scoped
        .abort_server_requests(TurnRequestCleanup::Ending("old"))
        .await;
    assert!(matches!(
        current.try_recv(),
        Err(oneshot::error::TryRecvError::Empty)
    ));
    assert!(matches!(
        newer.try_recv(),
        Err(oneshot::error::TryRecvError::Empty)
    ));
    scoped
        .abort_server_requests(TurnRequestCleanup::Ending("current"))
        .await;
    assert!(current.await.unwrap().is_err());
    assert!(matches!(
        newer.try_recv(),
        Err(oneshot::error::TryRecvError::Empty)
    ));
    scoped
        .abort_server_requests(TurnRequestCleanup::Ending("newer"))
        .await;
    assert!(newer.await.unwrap().is_err());
}

#[tokio::test]
async fn turn_started_preserves_original_owner_primary_callback() {
    let (tx, _rx) = mpsc::channel::<OutgoingEnvelope>(8);
    let outgoing = Arc::new(OutgoingMessageSender::new(
        tx,
        AnalyticsEventsClient::disabled(),
    ));
    let thread = ThreadId::new();
    let owner = ConnectionId(1);
    outgoing.enable_refill_connection(owner).await;
    let lease = outgoing
        .refill_connections
        .lock()
        .await
        .get(&owner)
        .unwrap()
        .clone();
    let scoped = ThreadScopedOutgoingMessageSender::new(outgoing.clone(), vec![owner], thread);
    let (id, mut waiting) = outgoing
        .send_refill_request(
            owner,
            &lease,
            ServerRequestPayload::ContextInput(ContextInputParams {
                thread_id: thread.to_string(),
                turn_id: "current".into(),
                operation_id: "original".into(),
                context_id: "context".into(),
                purpose: ContextRefillPurpose::Writer,
                material_ids: vec!["work".into()],
            }),
            thread,
        )
        .await;
    scoped
        .abort_server_requests(TurnRequestCleanup::Starting("current"))
        .await;
    scoped
        .abort_server_requests(TurnRequestCleanup::Ending("previous"))
        .await;
    assert!(matches!(
        waiting.try_recv(),
        Err(oneshot::error::TryRecvError::Empty)
    ));
    outgoing
        .notify_client_response(owner, id, json!({"fixture":"original-owner-ack"}))
        .await;
    assert_eq!(
        waiting.await.unwrap().unwrap(),
        json!({"fixture":"original-owner-ack"})
    );
}

#[tokio::test]
async fn idle_checkpoint_callback_survives_turn_cleanup_but_is_cancelled_on_shutdown() {
    let (tx, _rx) = mpsc::channel::<OutgoingEnvelope>(8);
    let outgoing = Arc::new(OutgoingMessageSender::new(
        tx,
        AnalyticsEventsClient::disabled(),
    ));
    let thread = ThreadId::new();
    let owner = ConnectionId(1);
    outgoing.enable_refill_connection(owner).await;
    let lease = outgoing
        .refill_connections
        .lock()
        .await
        .get(&owner)
        .unwrap()
        .clone();
    let scoped = ThreadScopedOutgoingMessageSender::new(outgoing.clone(), vec![owner], thread);
    let receipt: codex_app_server_protocol::ContextWindowInstalledParams =
        serde_json::from_value(json!({
            "threadId":thread.to_string(),"turnId":"previous","operationId":"idle-original",
            "contextId":"context","purpose":"writer","snapshotOperationId":"idle-original",
            "snapshotReadPoint":"cut","snapshotSha256":"a".repeat(64),
            "nativeActionsSha256":"b".repeat(64),"selectionRevision":1,"totalBytes":2,
            "previousWindowId":"old","windowId":"new","nativeHistoryBytes":100,
            "nativeHistorySha256":"c".repeat(64)
        }))
        .unwrap();
    for request in [
        ServerRequestPayload::ContextWindowIdleInstalled(receipt.clone()),
        ServerRequestPayload::ContextWindowReconcile(receipt),
    ] {
        let (_, mut waiting) = outgoing
            .send_refill_request(owner, &lease, request, thread)
            .await;
        scoped
            .abort_server_requests(TurnRequestCleanup::Ending("previous"))
            .await;
        scoped
            .abort_server_requests(TurnRequestCleanup::Starting("current"))
            .await;
        assert!(matches!(
            waiting.try_recv(),
            Err(oneshot::error::TryRecvError::Empty)
        ));
        scoped.abort_server_requests(TurnRequestCleanup::All).await;
        assert!(waiting.await.unwrap().is_err());
    }
}
