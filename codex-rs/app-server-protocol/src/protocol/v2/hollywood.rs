use super::Thread;
use schemars::JsonSchema;
use serde::Deserialize;
use serde::Serialize;
use ts_rs::TS;

fn default_true() -> bool {
    true
}

#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub enum HollywoodAttentionMode {
    Focused,
    Ambient,
    Broad,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct HollywoodAttentionSettings {
    pub mode: HollywoodAttentionMode,
    #[serde(default = "default_true")]
    pub include_at_all: bool,
    #[serde(default = "default_true")]
    pub include_at_room: bool,
}

impl Default for HollywoodAttentionSettings {
    fn default() -> Self {
        Self {
            mode: HollywoodAttentionMode::Focused,
            include_at_all: true,
            include_at_room: true,
        }
    }
}

#[derive(Serialize, Deserialize, Debug, Default, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ThreadHollywoodAttachParams {
    pub thread_id: String,
    #[ts(optional = nullable)]
    pub url: Option<String>,
    #[ts(optional = nullable)]
    pub room: Option<String>,
    #[serde(default)]
    pub observed_rooms: Vec<String>,
    #[serde(default)]
    pub wake_rooms: Vec<String>,
    #[ts(optional = nullable)]
    pub attention: Option<HollywoodAttentionSettings>,
}

#[derive(Serialize, Deserialize, Debug, Default, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct HollywoodSessionAttachOptions {
    #[ts(type = "string | null")]
    pub url: Option<String>,
    #[ts(type = "string | null")]
    pub room: Option<String>,
    #[serde(default)]
    pub observed_rooms: Vec<String>,
    #[serde(default)]
    pub wake_rooms: Vec<String>,
    #[ts(type = "HollywoodAttentionSettings | null")]
    pub attention: Option<HollywoodAttentionSettings>,
}

#[derive(Serialize, Deserialize, Debug, Default, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ThreadHollywoodAttachResponse {}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ThreadHollywoodDetachParams {
    pub thread_id: String,
}

#[derive(Serialize, Deserialize, Debug, Default, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ThreadHollywoodDetachResponse {}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ThreadHollywoodAttentionSetParams {
    pub thread_id: String,
    pub attention: HollywoodAttentionSettings,
}

#[derive(Serialize, Deserialize, Debug, Default, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ThreadHollywoodAttentionSetResponse {}

#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub enum HollywoodSessionStatus {
    Persisted,
    Idle,
    Active,
    Waiting,
    Blocked,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct HollywoodSessionDiagnostics {
    pub current_turn_open: bool,
    #[ts(type = "string | null")]
    pub active_turn_id: Option<String>,
    #[ts(type = "number | null")]
    pub active_turn_started_at: Option<i64>,
    pub active_turn_item_count: u32,
    pub startup_turn_pending: bool,
    pub autonomous_turn_pending: bool,
    pub pending_semantic_wake_count: u32,
    pub outstanding_obligation_count: u32,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct HollywoodSessionState {
    pub attached: bool,
    pub url: String,
    pub primary_room: String,
    pub observed_rooms: Vec<String>,
    pub wake_rooms: Vec<String>,
    pub attention: HollywoodAttentionSettings,
    pub identities: Vec<String>,
    #[ts(type = "string | null")]
    pub session_kind: Option<String>,
    #[ts(type = "string | null")]
    pub resumed_from: Option<String>,
    pub status: HollywoodSessionStatus,
    #[ts(type = "HollywoodSessionDiagnostics | null")]
    pub diagnostics: Option<HollywoodSessionDiagnostics>,
}

#[derive(Serialize, Deserialize, Debug, Default, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ThreadHollywoodListParams {
    #[ts(optional = nullable)]
    pub cursor: Option<String>,
    #[ts(optional = nullable)]
    pub limit: Option<u32>,
    #[ts(optional = nullable)]
    pub rooms: Option<Vec<String>>,
    #[ts(optional = nullable)]
    pub statuses: Option<Vec<HollywoodSessionStatus>>,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ThreadHollywoodListResponse {
    pub data: Vec<Thread>,
    pub next_cursor: Option<String>,
}

#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub enum ThreadOwnershipPathKind {
    File,
    Directory,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ThreadOwnershipPathSpec {
    pub kind: ThreadOwnershipPathKind,
    pub path: String,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ThreadOwnershipPathClaim {
    pub id: String,
    pub owner_thread_id: String,
    pub kind: ThreadOwnershipPathKind,
    pub path: String,
    pub claimed_at: i64,
    pub updated_at: i64,
    pub lease_expires_at: i64,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ThreadOwnershipPathClaimConflict {
    pub requested: ThreadOwnershipPathSpec,
    pub blocking_claim: ThreadOwnershipPathClaim,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ThreadOwnershipClaimParams {
    pub thread_id: String,
    pub claims: Vec<ThreadOwnershipPathSpec>,
    #[ts(optional = nullable)]
    pub lease_seconds: Option<i64>,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ThreadOwnershipClaimResponse {
    pub acquired: bool,
    pub data: Vec<ThreadOwnershipPathClaim>,
    pub conflicts: Vec<ThreadOwnershipPathClaimConflict>,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ThreadOwnershipReleaseParams {
    pub thread_id: String,
    pub claims: Vec<ThreadOwnershipPathSpec>,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ThreadOwnershipReleaseResponse {
    pub released: u32,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ThreadOwnershipListParams {
    pub thread_id: String,
    #[ts(optional = nullable)]
    pub cursor: Option<String>,
    #[ts(optional = nullable)]
    pub limit: Option<u32>,
    #[ts(optional = nullable)]
    pub owner_thread_id: Option<String>,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ThreadOwnershipListResponse {
    pub data: Vec<ThreadOwnershipPathClaim>,
    pub next_cursor: Option<String>,
}

#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub enum HollywoodMessageAttention {
    Focused,
    Broadcast,
    Ambient,
    Broad,
}

#[derive(Serialize, Deserialize, Debug, Clone, Copy, Default, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub enum HollywoodMessageKind {
    #[default]
    Ambient,
    Broadcast,
    Direct,
}

#[derive(Serialize, Deserialize, Debug, Clone, Copy, Default, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub enum HollywoodResponsePolicy {
    Required,
    #[default]
    Optional,
    None,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct HollywoodMessage {
    pub id: i64,
    pub room: String,
    #[serde(default)]
    #[ts(type = "string | null")]
    pub sender_id: Option<String>,
    #[serde(default)]
    #[ts(type = "string | null")]
    pub recipient_id: Option<String>,
    #[serde(default)]
    pub message_kind: HollywoodMessageKind,
    #[serde(default)]
    pub response_policy: HollywoodResponsePolicy,
    pub body: String,
    pub created_at: String,
    pub mentions: Vec<String>,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct HollywoodMessageNotification {
    pub thread_id: String,
    pub message: HollywoodMessage,
    pub attention: HollywoodMessageAttention,
    pub mentioned: bool,
    pub self_authored: bool,
}
