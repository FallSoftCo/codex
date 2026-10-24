//! Per-owner inference lifecycle, independent of tool permissions or Work state.
use schemars::JsonSchema;
use serde::Deserialize;
use serde::Serialize;
use ts_rs::TS;

/// Supplied again on cold resume; never inferred from saved room/history data.
#[derive(Debug, Default, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub enum InferenceCompletionPolicy {
    /// Ordinary caller: a model final may end an inference.
    #[default]
    Model,
    /// Only authenticated host settlement may successfully end the inference
    /// after admitted tools drain. Provider tool selection is independent.
    HostTool,
}
