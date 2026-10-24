//! Opt-in callback capability and bounded data-only native refill validation.
//! This capability is injected at explicit start/resume, never restored from a rollout.

use std::future::Future;
use std::io;
use std::pin::Pin;
use std::sync::Arc;

use codex_history::ResponseItemEnvelope;
use codex_protocol::context_refill::*;
use codex_protocol::models::ResponseItem;
use serde::Deserialize;
use sha2::Digest;
use sha2::Sha256;

/// Object-safe, owner-connection-fenced native transport; never retries or broadcasts.
/// Implementations must invalidate their epoch on disconnect/replacement and await
/// the original correlated host installed acknowledgement, not a response-write event.
pub trait ContextRefillHost: Send + Sync {
    /// Capture the currently authenticated owner connection epoch.
    fn owner_epoch(&self) -> u64;
    /// Recheck exact owner and connection after every await.
    fn is_current(&self, epoch: u64) -> bool;
    /// Immutable cancellation capability for this original connection. Return a
    /// clone of the same token; replacement must never revive or replace it.
    fn owner_disconnected(&self) -> tokio_util::sync::CancellationToken;
    /// Supply current canonical admission data before the first provider sample.
    /// Unsupported hosts fail closed; ordinary profiles never call this method.
    fn primary_input(
        &self,
        _epoch: u64,
        _params: codex_protocol::context_input::ContextInputParams,
    ) -> Pin<
        Box<
            dyn Future<Output = io::Result<codex_protocol::context_input::ContextInputResponse>>
                + Send
                + '_,
        >,
    > {
        Box::pin(async { Err(io::Error::other("primary context input unsupported")) })
    }
    /// Make one original prepare request; errors/timeout never imply permission to retry.
    fn refill(
        &self,
        epoch: u64,
        params: ContextWindowRefillParams,
    ) -> Pin<Box<dyn Future<Output = io::Result<ContextWindowRefillResponse>> + Send + '_>>;
    /// Await exact original installed acknowledgement after native durable installation.
    fn installed(
        &self,
        epoch: u64,
        params: ContextWindowInstalledParams,
    ) -> Pin<Box<dyn Future<Output = io::Result<ContextWindowInstalledResponse>> + Send + '_>>;
    /// Acknowledge a separately admitted idle installation. This is not a live
    /// inference continuation; unsupported hosts fail closed.
    fn idle_installed(
        &self,
        _epoch: u64,
        _params: ContextWindowInstalledParams,
    ) -> Pin<Box<dyn Future<Output = io::Result<ContextWindowInstalledResponse>> + Send + '_>> {
        Box::pin(async { Err(io::Error::other("idle context installation unsupported")) })
    }
    /// Read the original durable host receipt on a fresh explicit owner connection.
    /// This never prepares, installs, resets history, or replays an effect.
    fn reconcile(
        &self,
        _epoch: u64,
        _params: ContextWindowInstalledParams,
    ) -> Pin<Box<dyn Future<Output = io::Result<ContextWindowInstalledResponse>> + Send + '_>> {
        Box::pin(async {
            Err(io::Error::other(
                "original receipt reconciliation unsupported",
            ))
        })
    }
}

/// Explicit data protocol negotiated by the owning host connection.
#[derive(Clone, Copy)]
pub enum RetainedContextEvidence {
    /// Existing unfinished-action index only.
    IndexOnly,
    /// Exact selected terminal native items in a separately bounded bundle.
    WholeItemsV1,
}

/// Explicit per-connection policy, held only in the native thread extension store.
#[derive(Clone)]
pub struct AutomaticContextRefill {
    pub context_id: String,
    pub purpose: ContextRefillPurpose,
    pub host: Arc<dyn ContextRefillHost>,
    pub evidence: RetainedContextEvidence,
}

/// Measure serialized data with a hard limit and no output buffer allocation.
pub(crate) fn encoded_size(value: &impl serde::Serialize, limit: usize) -> io::Result<usize> {
    struct Counter {
        written: usize,
        limit: usize,
    }
    impl io::Write for Counter {
        fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
            if bytes.len() > self.limit.saturating_sub(self.written) {
                return Err(io::Error::other("native checkpoint exceeds admitted size"));
            }
            self.written += bytes.len();
            Ok(bytes.len())
        }
        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }
    let mut counter = Counter { written: 0, limit };
    serde_json::to_writer(&mut counter, value)?;
    Ok(counter.written)
}

pub(crate) const MAX_REFILL_DATA: usize = 256 * 1024;
pub(crate) const MAX_REFILL_ITEM_BYTES: usize = 32 * 1024;

/// Bound a core-produced or provenance-verified native prefix item.
/// AdditionalTools carries the native tool vocabulary, rather than retained
/// task data. Preserve that atomic declaration within the existing aggregate
/// budget. Never use this allowance for host-supplied refill fragments.
pub(crate) fn native_prefix_item_byte_limit(item: &ResponseItem) -> usize {
    match item {
        ResponseItem::AdditionalTools { .. } => MAX_REFILL_DATA,
        _ => MAX_REFILL_ITEM_BYTES,
    }
}
const MAX_ITEMS: usize = 256;
const MAX_WIRE: usize = 1024 * 1024;
const MAX_OUTPUT: usize = 16 * 1024;
const MAX_CHUNK: usize = 3072;

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SnapshotFragment {
    schema: String,
    operation_id: String,
    sha256: String,
    total_bytes: u64,
    offset: u64,
    content: String,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ActionFragment {
    schema: String,
    sha256: String,
    total_bytes: u64,
    offset: u64,
    content: String,
    retrieval: String,
    meaning: String,
}

fn require(valid: bool) -> io::Result<()> {
    if valid {
        Ok(())
    } else {
        Err(io::Error::other("invalid or stale canonical refill data"))
    }
}

fn id(value: &str) -> bool {
    !value.is_empty() && value.len() <= 256
}

fn hash(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

/// Decode only exact original string outputs. No roles/messages, tool invocations,
/// arbitrary metadata, caller IDs or host-provided system/developer instructions.
pub(crate) fn validate_response(
    request: &ContextWindowRefillParams,
    response: &ContextWindowRefillResponse,
) -> io::Result<Vec<ResponseItemEnvelope>> {
    require(
        response.thread_id == request.thread_id
            && response.turn_id == request.turn_id
            && response.operation_id == request.operation_id
            && response.context_id == request.context_id
            && response.purpose == request.purpose
            && response.window_id == request.window_id
            && response.history_version == request.history_version
            && response.snapshot_operation_id == request.operation_id,
    )?;
    require(
        [
            request.thread_id.as_str(),
            request.turn_id.as_str(),
            request.operation_id.as_str(),
            request.context_id.as_str(),
            request.window_id.as_str(),
            response.snapshot_read_point.as_str(),
        ]
        .into_iter()
        .all(id),
    )?;
    require(
        hash(&response.snapshot_sha256)
            && hash(&response.native_actions_sha256)
            && response.total_bytes > 0
            && response.total_bytes <= MAX_REFILL_DATA as u64,
    )?;
    require(!response.items.is_empty() && response.items.len() <= MAX_ITEMS)?;
    require(serde_json::to_vec(&response.items)?.len() <= MAX_WIRE)?;
    let mut snapshot = String::new();
    let mut actions = String::new();
    let mut action_total = None;
    let mut action_schema = None;
    let mut result = Vec::with_capacity(response.items.len());
    for value in &response.items {
        let object = value
            .as_object()
            .ok_or_else(|| io::Error::other("refill item is not data"))?;
        require(
            object.len() == 4
                && object.get("type").and_then(|v| v.as_str()) == Some("function_call_output"),
        )?;
        let output = object
            .get("output")
            .and_then(|v| v.as_str())
            .ok_or_else(|| io::Error::other("refill output is not a string"))?;
        require(output.len() <= MAX_OUTPUT)?;
        let namespace = object.get("namespace").and_then(|v| v.as_str());
        let name = object.get("name").and_then(|v| v.as_str());
        match (namespace, name) {
            (Some("hollywood"), Some("context_refill")) => {
                require(action_total.is_none())?;
                let f: SnapshotFragment = serde_json::from_str(output)?;
                require(
                    f.schema == "lax-context-refill-fragment/v1"
                        && f.operation_id == request.operation_id
                        && f.sha256 == response.snapshot_sha256
                        && f.total_bytes == response.total_bytes
                        && f.offset == snapshot.len() as u64
                        && !f.content.is_empty()
                        && f.content.len() <= MAX_CHUNK,
                )?;
                require(snapshot.len() + f.content.len() <= MAX_REFILL_DATA)?;
                snapshot.push_str(&f.content);
            }
            (Some("lax"), Some("context_actions")) => {
                let f: ActionFragment = serde_json::from_str(output)?;
                require(
                    !snapshot.is_empty()
                        && matches!(
                            f.schema.as_str(),
                            "lax-native-action-index/v1" | "lax-native-action-index/v2"
                        )
                        && f.sha256 == response.native_actions_sha256
                        && f.offset == actions.len() as u64
                        && f.total_bytes > 0
                        && f.total_bytes <= MAX_REFILL_DATA as u64
                        && !f.content.is_empty()
                        && f.content.len() <= MAX_CHUNK
                        && f.retrieval == "context_action_read"
                        && f.meaning
                            == "Original action receipts for unfinished work. Never replay an effect merely because context was reset.",
                )?;
                require(
                    action_total.is_none_or(|n| n == f.total_bytes)
                        && action_schema.as_ref().is_none_or(|s| s == &f.schema),
                )?;
                action_total = Some(f.total_bytes);
                action_schema = Some(f.schema);
                require(actions.len() + f.content.len() <= MAX_REFILL_DATA)?;
                actions.push_str(&f.content);
            }
            _ => return Err(io::Error::other("noncanonical refill item")),
        }
        let item: ResponseItem = serde_json::from_value(value.clone())?;
        result.push(ResponseItemEnvelope::new(item));
    }
    require(
        snapshot.len() as u64 == response.total_bytes
            && action_total == Some(actions.len() as u64)
            && format!("{:x}", Sha256::digest(snapshot.as_bytes())) == response.snapshot_sha256
            && format!("{:x}", Sha256::digest(actions.as_bytes()))
                == response.native_actions_sha256,
    )?;
    let action_value: serde_json::Value = serde_json::from_str(&actions)?;
    if request.purpose != ContextRefillPurpose::Writer {
        require(action_value == serde_json::json!([]))?;
    } else {
        match action_schema.as_deref() {
            Some("lax-native-action-index/v1") => require(action_value.is_array())?,
            Some("lax-native-action-index/v2") => require(
                action_value.get("schema").and_then(|v| v.as_str())
                    == Some("lax-native-action-index/v2"),
            )?,
            _ => return Err(io::Error::other("missing original action descriptor")),
        }
    }
    // nativeActionsSha256 binds DELIVERED descriptor bytes, not its cached
    // full-index indexSha256. Preview/recentActions never stand for the full ledger.
    Ok(result)
}

#[cfg(test)]
#[path = "context_refill_tests.rs"]
mod tests;
