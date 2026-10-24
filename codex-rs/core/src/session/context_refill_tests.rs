//! Mechanical gate regressions, not model qualification.
use super::*;
use pretty_assertions::assert_eq;
use std::pin::Pin;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

struct Host(AtomicBool, CancellationToken);
impl ContextRefillHost for Host {
    fn owner_epoch(&self) -> u64 {
        7
    }
    fn is_current(&self, epoch: u64) -> bool {
        epoch == 7 && self.0.load(Ordering::SeqCst) && !self.1.is_cancelled()
    }
    fn owner_disconnected(&self) -> CancellationToken {
        self.1.clone()
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

#[tokio::test]
async fn cancelled_callback_is_not_an_acknowledgement() {
    let cancel = CancellationToken::new();
    cancel.cancel();
    assert!(
        host_call::<()>(std::future::pending(), &cancel)
            .await
            .is_err()
    );
}

#[test]
fn disconnect_and_stale_epoch_fail_closed() {
    let host = Host(AtomicBool::new(true), CancellationToken::new());
    let cancel = CancellationToken::new();
    assert!(live(&host, 7, &cancel).is_ok());
    assert!(live(&host, 6, &cancel).is_err());
    host.0.store(false, Ordering::SeqCst);
    assert!(live(&host, 7, &cancel).is_err());
}

#[tokio::test]
async fn host_error_never_becomes_success() {
    let cancel = CancellationToken::new();
    let result = host_call::<()>(
        async { Err(io::Error::other("lost original reply")) },
        &cancel,
    )
    .await;
    assert!(result.is_err());
}

#[tokio::test]
async fn disconnect_during_blocked_provider_preparation_never_dispatches_or_replays() {
    use std::sync::atomic::AtomicUsize;
    use tokio::sync::oneshot;
    let host = Arc::new(Host(AtomicBool::new(true), CancellationToken::new()));
    let owner: Arc<dyn ContextRefillHost> = host.clone();
    let fence = SamplingFence {
        host: owner,
        epoch: 7,
    };
    let cancel = CancellationToken::new();
    // This reproduces a successful preliminary check followed by a deeper
    // request preparation await (connect/auth/etc), not a pre-cancel-only test.
    live(host.as_ref(), 7, &cancel).unwrap();
    let dispatched = Arc::new(AtomicUsize::new(0));
    let counter = Arc::clone(&dispatched);
    let (entered_tx, entered_rx) = oneshot::channel();
    let (release_tx, release_rx) = oneshot::channel();
    let task = tokio::spawn(async move {
        fence
            .run(&cancel, async move {
                entered_tx.send(()).unwrap();
                release_rx.await.unwrap();
                counter.fetch_add(1, Ordering::SeqCst);
                Ok(())
            })
            .await
    });
    entered_rx.await.unwrap();
    host.1.cancel();
    // Both cancellation and request readiness are now present. A biased owner
    // guard must win without polling the dispatch suffix.
    let _ = release_tx.send(());
    assert!(task.await.unwrap().is_err());
    assert_eq!(dispatched.load(Ordering::SeqCst), 0);
    assert!(!host.is_current(7));
}

#[tokio::test]
async fn already_disconnected_owner_never_polls_even_a_ready_provider_future() {
    let host = Arc::new(Host(AtomicBool::new(true), CancellationToken::new()));
    host.1.cancel();
    let fence = SamplingFence { host, epoch: 7 };
    let polled = AtomicBool::new(false);
    assert!(
        fence
            .run(&CancellationToken::new(), async {
                polled.store(true, Ordering::SeqCst);
                Ok(())
            })
            .await
            .is_err()
    );
    assert!(!polled.load(Ordering::SeqCst));
}

#[test]
fn cold_resume_never_interprets_native_installed_as_host_acknowledged() {
    use serde_json::json;
    let installed: ContextWindowInstalledParams = serde_json::from_value(json!({
        "threadId":"thread","turnId":"turn","operationId":"original",
        "contextId":"context","purpose":"writer","snapshotOperationId":"original",
        "snapshotReadPoint":"cut","snapshotSha256":"a".repeat(64),
        "nativeActionsSha256":"b".repeat(64),"selectionRevision":1,"totalBytes":2,
        "previousWindowId":"old","windowId":"new",
        "nativeHistoryBytes":100,"nativeHistorySha256":"c".repeat(64)
    }))
    .unwrap();
    let intent: ContextWindowRefillIntentEvent = serde_json::from_value(json!({
        "threadId":"thread","turnId":"turn","operationId":"original",
        "contextId":"context","purpose":"writer","snapshotOperationId":"original",
        "snapshotReadPoint":"cut","snapshotSha256":"a".repeat(64),
        "nativeActionsSha256":"b".repeat(64),"selectionRevision":1,"totalBytes":2,
        "windowId":"old","historyVersion":1,"reason":"contextLimit",
        "phase":"midTurn","nextWindowId":"new"
    }))
    .unwrap();
    let original = RolloutItem::EventMsg(EventMsg::ContextWindowRefillIntent(intent));
    let durable = RolloutItem::EventMsg(EventMsg::ContextWindowRefillInstalled(installed));
    for items in [
        vec![original.clone()],
        vec![original, durable.clone()],
        vec![durable],
    ] {
        // Simulate serialization/reload, preserving original identity exactly.
        let reloaded: Vec<RolloutItem> =
            serde_json::from_slice(&serde_json::to_vec(&items).unwrap()).unwrap();
        let gate = recover_hold(&reloaded).unwrap();
        assert_eq!(gate.operation_id, "original");
        assert!(!gate.acknowledged);
        assert!(gate.host.is_none()); // never rebind the old owner on reload
    }
    assert!(recover_hold(&[]).is_none()); // ordinary legacy history stays vanilla
}
