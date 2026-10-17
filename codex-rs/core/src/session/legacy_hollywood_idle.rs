//! Standalone Hollywood compatibility through current ordered idle admission.
use super::session::Session;
use codex_protocol::models::ResponseItem;
use codex_protocol::turn_input::NotSubmittedReason;
use codex_protocol::turn_input::TurnInputSubmission;
use std::sync::Arc;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TryStartTurnIfIdleRejectionReason {
    Busy,
    PlanMode,
    PendingTriggerTurn,
    Unavailable,
}

#[derive(Debug)]
pub struct TryStartTurnIfIdleError {
    reason: TryStartTurnIfIdleRejectionReason,
    input: Vec<ResponseItem>,
    detail: String,
}
impl TryStartTurnIfIdleError {
    pub fn reason(&self) -> TryStartTurnIfIdleRejectionReason {
        self.reason
    }
    pub fn into_input(self) -> Vec<ResponseItem> {
        self.input
    }
}
impl std::fmt::Display for TryStartTurnIfIdleError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.detail)
    }
}
impl std::error::Error for TryStartTurnIfIdleError {}
impl Session {
    pub(crate) async fn try_start_turn_if_idle(
        self: &Arc<Self>,
        input: Vec<ResponseItem>,
    ) -> Result<(), TryStartTurnIfIdleError> {
        self.try_start_turn_if_idle_with_sub_id(uuid::Uuid::new_v4().to_string(), input)
            .await
    }
    pub(crate) async fn try_start_turn_if_idle_with_sub_id(
        self: &Arc<Self>,
        sub_id: String,
        input: Vec<ResponseItem>,
    ) -> Result<(), TryStartTurnIfIdleError> {
        if input.is_empty() {
            return Ok(());
        }
        match super::turn_input::start_legacy_response_items(self, input.clone(), sub_id).await {
            Ok(TurnInputSubmission::Started { .. }) => Ok(()),
            Ok(TurnInputSubmission::NotSubmitted { reason }) => {
                let legacy = if reason == NotSubmittedReason::NotIdle {
                    TryStartTurnIfIdleRejectionReason::Busy
                } else if reason == NotSubmittedReason::PlanMode {
                    TryStartTurnIfIdleRejectionReason::PlanMode
                } else if reason == NotSubmittedReason::PendingTriggerTurn {
                    TryStartTurnIfIdleRejectionReason::PendingTriggerTurn
                } else {
                    TryStartTurnIfIdleRejectionReason::Unavailable
                };
                Err(TryStartTurnIfIdleError {
                    reason: legacy,
                    input,
                    detail: format!("idle input rejected: {reason:?}"),
                })
            }
            Ok(TurnInputSubmission::Steered { .. }) => unreachable!("idle admission cannot steer"),
            Err(error) => Err(TryStartTurnIfIdleError {
                reason: TryStartTurnIfIdleRejectionReason::Unavailable,
                input,
                detail: error.to_string(),
            }),
        }
    }
}
