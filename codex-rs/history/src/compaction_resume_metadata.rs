//! Defines resume metadata stored directly on a compaction.

use crate::RolloutItem;
use codex_protocol::protocol::MultiAgentVersion;
use codex_protocol::turn_input::CyberAccessProgram;
use codex_protocol::turn_input::TurnAttribution;
use schemars::JsonSchema;
use serde::Deserialize;
use serde::Serialize;

/// Resume metadata that is not represented by the companion records after a compaction.
///
/// Presence distinguishes compactions that explicitly persisted these values from older
/// compactions that did not. Each field is authoritative, including an intentionally absent value.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct CompactionResumeMetadata {
    /// Complete native rendering state for selected-context reconstruction.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub native_context: Option<NativeContextCheckpoint>,

    /// Selected runtime, including when the companion turn context is absent.
    pub multi_agent_version: Option<MultiAgentVersion>,
    /// Turn identity used to admit continuations after cold resume.
    pub last_started_turn_id: Option<String>,
    /// Attribution of the latest regular turn, independent of continuation eligibility.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub turn_attribution: Option<TurnAttribution>,
    pub previous_turn_settings: Option<PreviousTurnSettings>,
}

/// Previous user-turn settings used to reconstruct context changes after resume.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq, JsonSchema)]
pub struct PreviousTurnSettings {
    pub model: String,
    /// Historical program for this model; absence must not inherit the next turn's selection.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cyber_access_program: Option<CyberAccessProgram>,
    pub comp_hash: Option<String>,
    pub realtime_active: Option<bool>,
}

/// Returns the runtime version stored in a turn context or compaction resume metadata.
pub fn resume_multi_agent_version(item: &RolloutItem) -> Option<MultiAgentVersion> {
    match item {
        RolloutItem::TurnContext(context) => context.multi_agent_version,
        RolloutItem::Compacted(compacted) => compacted
            .resume_metadata
            .as_ref()
            .and_then(|metadata| metadata.multi_agent_version),
        RolloutItem::SessionState(_)
        | RolloutItem::SessionMeta(_)
        | RolloutItem::ResponseItem(_)
        | RolloutItem::InterAgentCommunication(_)
        | RolloutItem::InterAgentCommunicationMetadata { .. }
        | RolloutItem::TokenUsageRecord(_)
        | RolloutItem::WorldState(_)
        | RolloutItem::RetainedContext(_)
        | RolloutItem::SecurityRiskScore(_)
        | RolloutItem::RealtimeItem(_)
        | RolloutItem::EventMsg(_) => None,
    }
}

/// Native rendering state persisted atomically inside a context checkpoint.
/// This is data for reconstruction, never a saved permission or runtime policy.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct NativeContextCheckpoint {
    pub schema: String,
    pub thread_id: String,
    pub context_id: String,
    pub mode: NativeContextCheckpointMode,
    pub world_state: codex_protocol::protocol::WorldStateItem,
    pub reference_context: Option<codex_protocol::protocol::TurnContextItem>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum NativeContextCheckpointMode {
    StepBoundary,
    IdleRequest,
}

impl NativeContextCheckpoint {
    /// Validate reconstruction data only; callers separately enforce ownership,
    /// native cut identity, durable receipts and fresh execution permissions.
    pub fn supported(&self) -> bool {
        self.schema == "lax-native-context-checkpoint/v1"
            && !self.thread_id.is_empty()
            && self.thread_id.len() <= 128
            && !self.context_id.is_empty()
            && self.context_id.len() <= 256
            && self.world_state.full
    }
}
