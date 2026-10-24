//! Mechanical transport fixtures only, not native/model qualification.
use super::*;
use crate::outgoing_message::OutgoingEnvelope;
use crate::outgoing_message::OutgoingMessage;
use codex_analytics::AnalyticsEventsClient;
use codex_app_server_protocol::JSONRPCErrorError;
use tokio::sync::mpsc;

fn policy() -> Option<AutomaticContextRefillPolicy> {
    Some(AutomaticContextRefillPolicy::Canonical {
        context_id: "context".into(),
        purpose: ContextRefillPurpose::Writer,
    })
}

async fn bound() -> (
    Arc<OutgoingMessageSender>,
    mpsc::Receiver<OutgoingEnvelope>,
    AutomaticContextRefill,
) {
    let (tx, rx) = mpsc::channel(8);
    let outgoing = Arc::new(OutgoingMessageSender::new(
        tx,
        AnalyticsEventsClient::disabled(),
    ));
    outgoing.enable_refill_connection(ConnectionId(1)).await;
    let configured = configure(
        policy(),
        Arc::clone(&outgoing),
        Some(ConnectionId(1)),
        /*ephemeral*/ false,
    )
    .await
    .unwrap()
    .unwrap();
    (outgoing, rx, configured)
}

fn receipt() -> ContextWindowInstalledParams {
    ContextWindowInstalledParams {
        thread_id: ThreadId::new().to_string(),
        turn_id: "turn".into(),
        operation_id: "original".into(),
        context_id: "context".into(),
        purpose: ContextRefillPurpose::Writer,
        snapshot_operation_id: "original".into(),
        snapshot_read_point: "cut".into(),
        snapshot_sha256: "a".repeat(64),
        native_actions_sha256: "b".repeat(64),
        selection_revision: 1,
        total_bytes: 2,
        previous_window_id: "old".into(),
        window_id: "new".into(),
        native_history_bytes: 100,
        native_history_sha256: "c".repeat(64),
    }
}

#[tokio::test]
async fn missing_disabled_and_invalid_policy_keep_runtime_opt_in_explicit() {
    let (tx, _rx) = mpsc::channel(8);
    let out = Arc::new(OutgoingMessageSender::new(
        tx,
        AnalyticsEventsClient::disabled(),
    ));
    for policy in [None, Some(AutomaticContextRefillPolicy::Disabled)] {
        assert!(
            configure(policy, Arc::clone(&out), None, /*ephemeral*/ false)
                .await
                .unwrap()
                .is_none()
        );
    }
    assert!(
        configure(
            policy(),
            Arc::clone(&out),
            Some(ConnectionId(1)),
            /*ephemeral*/ false
        )
        .await
        .is_err()
    );
    out.enable_refill_connection(ConnectionId(1)).await;
    assert!(
        configure(
            policy(),
            Arc::clone(&out),
            Some(ConnectionId(1)),
            /*ephemeral*/ true
        )
        .await
        .is_err()
    );
    assert!(
        configure(policy(), out, None, /*ephemeral*/ false)
            .await
            .is_err()
    );
}

#[tokio::test]
async fn installed_ack_is_private_owner_correlated_and_never_replayed() {
    for idle in [false, true] {
        let (out, mut messages, configured) = bound().await;
        let params = receipt();
        let thread = ThreadId::from_string(&params.thread_id).unwrap();
        let host = configured.host;
        let epoch = host.owner_epoch();
        let pending = tokio::spawn(async move {
            if idle {
                host.idle_installed(epoch, params).await
            } else {
                host.installed(epoch, params).await
            }
        });
        let id = match messages.recv().await.unwrap() {
            OutgoingEnvelope::ToConnection {
                connection_id: ConnectionId(1),
                message: OutgoingMessage::Request(request),
                ..
            } => request.id().clone(),
            other => panic!("not the original owner: {other:?}"),
        };
        assert!(messages.try_recv().is_err());
        assert!(out.pending_requests_for_thread(thread).await.is_empty());
        out.replay_requests_to_connection_for_thread(ConnectionId(2), thread)
            .await;
        assert!(messages.try_recv().is_err());
        let ack = serde_json::json!({"operationId":"original","status":"recorded"});
        out.notify_client_response(ConnectionId(2), id.clone(), ack.clone())
            .await;
        out.notify_client_error(
            ConnectionId(2),
            id.clone(),
            JSONRPCErrorError {
                code: -1,
                message: "foreign".into(),
                data: None,
            },
        )
        .await;
        assert!(!pending.is_finished());
        out.notify_client_response(ConnectionId(1), id, ack).await;
        assert_eq!(
            pending.await.unwrap().unwrap(),
            ContextWindowInstalledResponse {
                operation_id: "original".into(),
                status: ContextWindowInstalledStatus::Recorded,
            }
        );
    }
}

#[tokio::test]
async fn disconnected_or_replaced_epoch_cannot_send_or_accept_an_old_callback() {
    for idle in [false, true] {
        let (out, mut messages, configured) = bound().await;
        let host = configured.host;
        let epoch = host.owner_epoch();
        let task_host = Arc::clone(&host);
        let pending = tokio::spawn(async move {
            if idle {
                task_host.idle_installed(epoch, receipt()).await
            } else {
                task_host.installed(epoch, receipt()).await
            }
        });
        let message = messages.recv().await.unwrap();
        let OutgoingEnvelope::ToConnection {
            message: OutgoingMessage::Request(request),
            ..
        } = message
        else {
            panic!("missing original callback");
        };
        out.connection_closed(ConnectionId(1)).await;
        assert!(pending.await.unwrap().is_err());
        out.enable_refill_connection(ConnectionId(1)).await;
        assert!(!host.is_current(epoch));
        out.notify_client_response(
            ConnectionId(1),
            request.id().clone(),
            serde_json::json!({"operationId":"original","status":"recorded"}),
        )
        .await;
        assert!(
            if idle {
                host.idle_installed(epoch, receipt()).await
            } else {
                host.installed(epoch, receipt()).await
            }
            .is_err()
        );
        assert!(messages.try_recv().is_err());
    }
}

#[tokio::test(start_paused = true)]
async fn original_timeout_does_not_retransmit() {
    let (_out, mut messages, configured) = bound().await;
    let host = configured.host;
    let pending = tokio::spawn(async move { host.installed(host.owner_epoch(), receipt()).await });
    messages.recv().await.unwrap();
    tokio::time::advance(Duration::from_secs(31)).await;
    assert!(pending.await.unwrap().is_err());
    assert!(messages.try_recv().is_err());
}

#[tokio::test]
async fn cold_reconciliation_is_owner_only_and_read_only_on_the_wire() {
    let (out, mut messages, configured) = bound().await;
    let host = configured.host;
    let epoch = host.owner_epoch();
    let task_host = Arc::clone(&host);
    let pending = tokio::spawn(async move { task_host.reconcile(epoch, receipt()).await });
    let id = match messages.recv().await.unwrap() {
        OutgoingEnvelope::ToConnection {
            connection_id: ConnectionId(1),
            message: OutgoingMessage::Request(request),
            ..
        } => {
            assert!(matches!(
                &request,
                codex_app_server_protocol::ServerRequest::ContextWindowReconcile { .. }
            ));
            request.id().clone()
        }
        other => panic!("reconciliation escaped the original owner: {other:?}"),
    };
    let answer = serde_json::json!({"operationId":"original","status":"recorded"});
    out.notify_client_response(ConnectionId(2), id.clone(), answer.clone())
        .await;
    assert!(!pending.is_finished());
    out.notify_client_response(ConnectionId(1), id, answer)
        .await;
    assert_eq!(
        pending.await.unwrap().unwrap(),
        ContextWindowInstalledResponse {
            operation_id: "original".into(),
            status: ContextWindowInstalledStatus::Recorded,
        }
    );
    out.connection_closed(ConnectionId(1)).await;
    assert!(host.reconcile(epoch, receipt()).await.is_err());
    assert!(messages.try_recv().is_err());
}
