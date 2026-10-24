//! Explicit connection-owned admission data before a purpose-native model sample.
use crate::context_refill::ContextRefillPurpose;
use schemars::JsonSchema;
use serde::Deserialize;
use serde::Serialize;
use ts_rs::TS;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(tag = "type", rename_all = "camelCase", deny_unknown_fields)]
#[ts(tag = "type", rename_all = "camelCase", export_to = "v2/")]
pub enum PrimaryContextInputPolicy {
    Disabled,
    Canonical {
        #[serde(rename = "contextId")]
        #[ts(rename = "contextId")]
        context_id: String,
        purpose: ContextRefillPurpose,
    },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
#[ts(rename_all = "camelCase", export_to = "v2/")]
pub struct ContextInputParams {
    pub thread_id: String,
    pub turn_id: String,
    pub operation_id: String,
    pub context_id: String,
    pub purpose: ContextRefillPurpose,
    pub material_ids: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
#[ts(rename_all = "camelCase", export_to = "v2/")]
pub struct ContextInputResponse {
    pub thread_id: String,
    pub turn_id: String,
    pub operation_id: String,
    pub context_id: String,
    pub purpose: ContextRefillPurpose,
    pub material_ids: Vec<String>,
    pub admission_operation_id: String,
    pub fragments: Vec<String>,
}
