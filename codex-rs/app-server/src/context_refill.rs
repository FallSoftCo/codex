//! Runtime-only canonical refill transport. A lease names one initialized connection,
//! never "the first subscriber"; disconnect/replacement invalidates it permanently.

use std::future::Future;
use std::io;
use std::pin::Pin;
use std::sync::Arc;
use std::sync::Weak;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_app_server_protocol::JSONRPCErrorError;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ServerRequestPayload;
use codex_core::context_refill::AutomaticContextRefill;
use codex_core::context_refill::ContextRefillHost;
use codex_protocol::ThreadId;
use codex_protocol::context_refill::*;
use serde::de::DeserializeOwned;
use tokio_util::sync::CancellationToken;

use crate::error_code::invalid_request;
use crate::outgoing_message::ConnectionId;
use crate::outgoing_message::OutgoingMessageSender;

static NEXT_EPOCH: AtomicU64 = AtomicU64::new(1);

pub(crate) struct ConnectionLease {
    epoch: u64,
    pub(crate) closed: CancellationToken,
}

/// Native window inspection/replacement belongs to the exact initialized client.
/// Epochs are private correlation values, not model-facing authorization tokens.
pub(crate) async fn request_owner_epoch(
    outgoing: &OutgoingMessageSender,
    owner: ConnectionId,
) -> Result<u64, JSONRPCErrorError> {
    outgoing
        .refill_connections
        .lock()
        .await
        .get(&owner)
        .filter(|lease| !lease.closed.is_cancelled())
        .map(|lease| lease.epoch)
        .ok_or_else(|| invalid_request("original context owner connection unavailable"))
}

impl OutgoingMessageSender {
    pub(crate) async fn enable_refill_connection(&self, owner: ConnectionId) {
        let lease = Arc::new(ConnectionLease {
            epoch: NEXT_EPOCH.fetch_add(1, Ordering::Relaxed),
            closed: CancellationToken::new(),
        });
        if let Some(old) = self.refill_connections.lock().await.insert(owner, lease) {
            old.closed.cancel();
        }
    }
}

/// Capture once at explicit start/cold-resume after effective config loading.
/// Nothing here changes stored session policy or adopts another owner's work.
pub(crate) async fn configure(
    policy: Option<AutomaticContextRefillPolicy>,
    outgoing: Arc<OutgoingMessageSender>,
    owner: Option<ConnectionId>,
    ephemeral: bool,
) -> Result<Option<AutomaticContextRefill>, JSONRPCErrorError> {
    use codex_core::context_refill::RetainedContextEvidence;
    let (context_id, purpose, evidence) = match policy {
        None | Some(AutomaticContextRefillPolicy::Disabled) => return Ok(None),
        Some(AutomaticContextRefillPolicy::Canonical {
            context_id,
            purpose,
        }) => (context_id, purpose, RetainedContextEvidence::IndexOnly),
        Some(AutomaticContextRefillPolicy::CanonicalRetainedActions {
            context_id,
            purpose,
        }) => {
            if purpose != ContextRefillPurpose::Writer {
                return Err(invalid_request(
                    "retained native evidence requires Writer purpose",
                ));
            }
            (context_id, purpose, RetainedContextEvidence::WholeItemsV1)
        }
    };
    let host = owned_context_host(&context_id, outgoing, owner, ephemeral).await?;
    Ok(Some(AutomaticContextRefill {
        context_id,
        purpose,
        host,
        evidence,
    }))
}

/// Shared exact-client transport capture; no model, refill or input is started.
async fn owned_context_host(
    context_id: &str,
    outgoing: Arc<OutgoingMessageSender>,
    owner: Option<ConnectionId>,
    ephemeral: bool,
) -> Result<Arc<Host>, JSONRPCErrorError> {
    if ephemeral
        || context_id.is_empty()
        || context_id.len() > 256
        || context_id
            .chars()
            .any(|c| c.is_control() || c.is_whitespace())
    {
        return Err(invalid_request(
            "canonical context requires a bounded identity and non-ephemeral thread",
        ));
    }
    let owner =
        owner.ok_or_else(|| invalid_request("original context owner connection required"))?;
    let lease = outgoing
        .refill_connections
        .lock()
        .await
        .get(&owner)
        .cloned()
        .filter(|lease| !lease.closed.is_cancelled())
        .ok_or_else(|| {
            invalid_request("original context owner is disconnected or uninitialized")
        })?;
    Ok(Arc::new(Host {
        outgoing: Arc::downgrade(&outgoing),
        owner,
        lease,
    }))
}

struct Host {
    outgoing: Weak<OutgoingMessageSender>,
    owner: ConnectionId,
    lease: Arc<ConnectionLease>,
}

// Dropping a timed-out/cancelled core future removes only its original pending
// callback. It never retransmits, broadcasts, resets history or samples a model.
struct PendingRequest {
    outgoing: Weak<OutgoingMessageSender>,
    id: RequestId,
}

impl Drop for PendingRequest {
    fn drop(&mut self) {
        if let Some(outgoing) = self.outgoing.upgrade() {
            let id = self.id.clone();
            tokio::spawn(async move {
                outgoing.cancel_request(&id).await;
            });
        }
    }
}

fn held() -> io::Error {
    io::Error::other(
        "original canonical refill transport held; inspect original receipts without retry",
    )
}

impl Host {
    async fn call<T: DeserializeOwned>(
        &self,
        epoch: u64,
        thread_id: &str,
        payload: ServerRequestPayload,
    ) -> io::Result<T> {
        if !self.is_current(epoch) {
            return Err(held());
        }
        let thread = ThreadId::from_string(thread_id).map_err(|_| held())?;
        let outgoing = self.outgoing.upgrade().ok_or_else(held)?;
        let (id, receiver) = outgoing
            .send_refill_request(self.owner, &self.lease, payload, thread)
            .await;
        let _pending = PendingRequest {
            outgoing: Arc::downgrade(&outgoing),
            id,
        };
        let value = tokio::select! {
            biased;
            _ = self.lease.closed.cancelled() => return Err(held()),
            result = tokio::time::timeout(Duration::from_secs(30), receiver) =>
                result.map_err(|_| held())?.map_err(|_| held())?.map_err(|_| held())?,
        };
        if !self.is_current(epoch) || serde_json::to_vec(&value)?.len() > 1024 * 1024 {
            return Err(held());
        }
        serde_json::from_value(value).map_err(|_| held())
    }
}

impl ContextRefillHost for Host {
    fn owner_epoch(&self) -> u64 {
        self.lease.epoch
    }

    fn owner_disconnected(&self) -> CancellationToken {
        self.lease.closed.clone()
    }

    fn is_current(&self, epoch: u64) -> bool {
        epoch == self.lease.epoch
            && !self.lease.closed.is_cancelled()
            && self.outgoing.strong_count() > 0
    }

    fn primary_input(
        &self,
        epoch: u64,
        params: codex_protocol::context_input::ContextInputParams,
    ) -> Pin<
        Box<
            dyn Future<Output = io::Result<codex_protocol::context_input::ContextInputResponse>>
                + Send
                + '_,
        >,
    > {
        Box::pin(async move {
            let thread = params.thread_id.clone();
            self.call(epoch, &thread, ServerRequestPayload::ContextInput(params))
                .await
        })
    }

    fn refill(
        &self,
        epoch: u64,
        params: ContextWindowRefillParams,
    ) -> Pin<Box<dyn Future<Output = io::Result<ContextWindowRefillResponse>> + Send + '_>> {
        Box::pin(async move {
            let thread = params.thread_id.clone();
            self.call(
                epoch,
                &thread,
                ServerRequestPayload::ContextWindowRefill(params),
            )
            .await
        })
    }

    fn installed(
        &self,
        epoch: u64,
        params: ContextWindowInstalledParams,
    ) -> Pin<Box<dyn Future<Output = io::Result<ContextWindowInstalledResponse>> + Send + '_>> {
        Box::pin(async move {
            let thread = params.thread_id.clone();
            self.call(
                epoch,
                &thread,
                ServerRequestPayload::ContextWindowInstalled(params),
            )
            .await
        })
    }

    fn idle_installed(
        &self,
        epoch: u64,
        params: ContextWindowInstalledParams,
    ) -> Pin<Box<dyn Future<Output = io::Result<ContextWindowInstalledResponse>> + Send + '_>> {
        Box::pin(async move {
            let thread = params.thread_id.clone();
            self.call(
                epoch,
                &thread,
                ServerRequestPayload::ContextWindowIdleInstalled(params),
            )
            .await
        })
    }

    fn reconcile(
        &self,
        epoch: u64,
        params: ContextWindowInstalledParams,
    ) -> Pin<Box<dyn Future<Output = io::Result<ContextWindowInstalledResponse>> + Send + '_>> {
        Box::pin(async move {
            let thread = params.thread_id.clone();
            self.call(
                epoch,
                &thread,
                ServerRequestPayload::ContextWindowReconcile(params),
            )
            .await
        })
    }
}

#[cfg(test)]
#[path = "context_refill_tests.rs"]
mod tests;

/// Primary admission is independent of optional full-window reconstruction.
pub(crate) async fn configure_primary(
    policy: Option<codex_protocol::context_input::PrimaryContextInputPolicy>,
    refill: Option<&AutomaticContextRefillPolicy>,
    completion: Option<codex_protocol::inference_completion::InferenceCompletionPolicy>,
    outgoing: Arc<OutgoingMessageSender>,
    owner: Option<ConnectionId>,
    ephemeral: bool,
) -> Result<Option<codex_core::primary_context_input::PrimaryContextInput>, JSONRPCErrorError> {
    use codex_protocol::context_input::PrimaryContextInputPolicy;
    use codex_protocol::inference_completion::InferenceCompletionPolicy;
    let Some(PrimaryContextInputPolicy::Canonical {
        context_id,
        purpose,
    }) = policy
    else {
        return Ok(None);
    };
    if completion != Some(InferenceCompletionPolicy::HostTool) {
        return Err(invalid_request(
            "primary canonical input requires host-tool completion",
        ));
    }
    if let Some(
        AutomaticContextRefillPolicy::Canonical {
            context_id: refill_context,
            purpose: refill_purpose,
        }
        | AutomaticContextRefillPolicy::CanonicalRetainedActions {
            context_id: refill_context,
            purpose: refill_purpose,
        },
    ) = refill
        && (refill_context != &context_id || refill_purpose != &purpose)
    {
        return Err(invalid_request(
            "primary input and refill context identity differ",
        ));
    }
    let host = owned_context_host(&context_id, outgoing, owner, ephemeral).await?;
    Ok(Some(
        codex_core::primary_context_input::PrimaryContextInput {
            context_id,
            purpose,
            host,
        },
    ))
}
