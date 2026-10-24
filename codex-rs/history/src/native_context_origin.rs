//! Data-only provenance for core context records, never an execution grant.
use schemars::JsonSchema;
use serde::Deserialize;
use serde::Serialize;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum NativeContextKind {
    Prefix,
    Update,
}

/// One item of an exact native-produced group. Missing parts cannot be treated
/// as a complete instruction prefix after trimming, copying or cold replay.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct NativeContextOrigin {
    pub schema: String,
    pub thread_id: String,
    pub context_id: String,
    pub group_id: String,
    pub kind: NativeContextKind,
    pub index: usize,
    pub count: usize,
    pub sha256: String,
}
