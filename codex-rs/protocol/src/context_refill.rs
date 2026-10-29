//! Opt-in same-live-turn canonical window refill wire data.
//!
//! These values carry correlation, never host permissions or executable instructions.
//! A missing/null policy remains disabled at each start/resume boundary. Stored
//! history must never activate this capability implicitly.

use schemars::JsonSchema;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use ts_rs::TS;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(tag = "type", rename_all = "camelCase", deny_unknown_fields)]
#[ts(tag = "type", rename_all = "camelCase", export_to = "v2/")]
pub enum AutomaticContextRefillPolicy {
    Disabled,
    Canonical {
        #[serde(rename = "contextId")]
        #[ts(rename = "contextId")]
        context_id: String,
        purpose: ContextRefillPurpose,
    },
    /// Explicit negotiated whole-item evidence extension. Writer only; omission
    /// never restores this policy from native history.
    CanonicalRetainedActions {
        #[serde(rename = "contextId")]
        #[ts(rename = "contextId")]
        context_id: String,
        purpose: ContextRefillPurpose,
    },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
#[ts(rename_all = "camelCase", export_to = "v2/")]
pub enum ContextRefillPurpose {
    Reader,
    Writer,
    Responder,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
#[ts(rename_all = "camelCase", export_to = "v2/")]
pub enum ContextWindowRefillReason {
    /// Explicit native maintenance, not a provider or context-limit event.
    ExplicitRequest,
    ContextLimit,
    ModelDownshift,
    CompHashChanged,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
#[ts(rename_all = "camelCase", export_to = "v2/")]
pub enum ContextWindowRefillPhase {
    PreTurn,
    MidTurn,
    PostTurn,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
#[ts(rename_all = "camelCase", export_to = "v2/")]
pub enum ContextWindowInstalledStatus {
    Recorded,
}

/// Owner-bound request at a drained automatic window boundary.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
#[ts(rename_all = "camelCase", export_to = "v2/")]
pub struct ContextWindowRefillParams {
    pub thread_id: String,
    pub turn_id: String,
    pub operation_id: String,
    pub context_id: String,
    pub purpose: ContextRefillPurpose,
    pub window_id: String,
    pub history_version: u64,
    pub reason: ContextWindowRefillReason,
    pub phase: ContextWindowRefillPhase,
}

/// Exact immutable canonical snapshot and original action-reference data.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
#[ts(rename_all = "camelCase", export_to = "v2/")]
pub struct ContextWindowRefillResponse {
    pub thread_id: String,
    pub turn_id: String,
    pub operation_id: String,
    pub context_id: String,
    pub purpose: ContextRefillPurpose,
    pub window_id: String,
    pub history_version: u64,
    pub snapshot_operation_id: String,
    pub snapshot_read_point: String,
    pub snapshot_sha256: String,
    pub native_actions_sha256: String,
    pub selection_revision: u64,
    pub total_bytes: u64,
    #[ts(type = "unknown[]")]
    pub items: Vec<Value>,
}

/// Durable checkpoint provenance; prefix excludes the following receipt itself.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
#[ts(rename_all = "camelCase", export_to = "v2/")]
pub struct ContextWindowInstalledParams {
    pub thread_id: String,
    pub turn_id: String,
    pub operation_id: String,
    pub context_id: String,
    pub purpose: ContextRefillPurpose,
    pub snapshot_operation_id: String,
    pub snapshot_read_point: String,
    pub snapshot_sha256: String,
    pub native_actions_sha256: String,
    pub selection_revision: u64,
    pub total_bytes: u64,
    pub previous_window_id: String,
    pub window_id: String,
    pub native_history_bytes: u64,
    pub native_history_sha256: String,
}

/// Host acknowledgement required before any next provider sample.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
#[ts(rename_all = "camelCase", export_to = "v2/")]
pub struct ContextWindowInstalledResponse {
    pub operation_id: String,
    pub status: ContextWindowInstalledStatus,
}

/// Persisted immediately before the correlated full replacement checkpoint.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
#[ts(rename_all = "camelCase", export_to = "v2/")]
pub struct ContextWindowRefillIntentEvent {
    pub thread_id: String,
    pub turn_id: String,
    pub operation_id: String,
    pub context_id: String,
    pub purpose: ContextRefillPurpose,
    pub window_id: String,
    pub history_version: u64,
    pub snapshot_operation_id: String,
    pub snapshot_read_point: String,
    pub snapshot_sha256: String,
    pub native_actions_sha256: String,
    pub selection_revision: u64,
    pub total_bytes: u64,
    pub reason: ContextWindowRefillReason,
    pub phase: ContextWindowRefillPhase,
    pub next_window_id: String,
}

/// Persisted immediately after the checkpoint; byte/hash fields cover the prefix
/// through its newline, excluding this event's JSONL record (no self-hash).
pub type ContextWindowRefillInstalledEvent = ContextWindowInstalledParams;

#[cfg(test)]
#[path = "context_refill_tests.rs"]
mod tests;

/// Read-only native identity cut for a future CAS preflight/replacement. Reading
/// it neither starts/aborts a turn nor acknowledges an unsettled operation.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
#[ts(rename_all = "camelCase", export_to = "v2/")]
pub struct ContextWindowState {
    pub thread_id: String,
    pub context_id: String,
    pub purpose: ContextRefillPurpose,
    pub window_id: String,
    pub history_version: u64,
    pub last_started_turn_id: Option<String>,
    /// Validated complete native material at this cut. Legacy or invalid
    /// producers yield None; history_version remains the rewrite generation.
    #[serde(default)]
    pub producer_sha256: Option<String>,
    pub active_turn_id: Option<String>,
    pub idle: bool,
    pub held_operation_id: Option<String>,
}

/// Read-only measurement of the exact native context and selected data. This
/// neither installs history nor grants permission for any execution.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
#[ts(rename_all = "camelCase", export_to = "v2/")]
pub struct ContextWindowPreflight {
    pub state: ContextWindowState,
    pub operation_id: String,
    /// Deterministic proposed target, rendered before review and reused by install.
    pub next_window_id: String,
    /// Exact complete producer binding, distinct from the selected-input packet.
    pub producer_sha256: String,
    pub packet_sha256: String,
    pub replacement_sha256: String,
    pub prefix_item_count: u64,
    pub replacement_item_count: u64,
    pub replacement_wire_bytes: u64,
}

/// Original explicit collection provenance from a complete native checkpoint.
/// Reading it never repeats collection or acknowledges unknown external work.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
#[ts(rename_all = "camelCase", export_to = "v2/")]
pub struct ContextWindowAcquisitionReceipt {
    pub operation_id: String,
    pub source_state: ContextWindowState,
    pub producer_sha256: String,
}
