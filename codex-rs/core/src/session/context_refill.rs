//! One original same-turn operation. Any interrupted/unknown attempt remains held:
//! no retry, summary fallback, second reset or provider sample can pass the gate.

use std::future::Future;
use std::io;
use std::sync::Arc;
use std::time::Duration;

use crate::client::ModelClientSession;
use crate::context_manager::HistoryReplacement;
use crate::context_refill::AutomaticContextRefill;
use crate::context_refill::ContextRefillHost;
use crate::context_refill::validate_response;
use crate::session::session::Session;
use crate::session::step_context::StepContext;
use crate::state::AutoCompactWindowIds;
use crate::state::ReasoningEffortPin;
use codex_analytics::CompactionPhase;
use codex_analytics::CompactionReason;
use codex_history::CompactedItem;
use codex_history::CompactionResumeMetadata;
use codex_history::ResponseItemEnvelope;
use codex_history::RolloutItem;
use codex_protocol::context_refill::*;
use codex_protocol::error::CodexErr;
use codex_protocol::error::Result as CodexResult;
use codex_protocol::protocol::EventMsg;
use tokio_util::sync::CancellationToken;
use uuid::Uuid;

pub(crate) struct RefillGate {
    operation_id: String,
    owner_epoch: u64,
    host: Option<Arc<dyn ContextRefillHost>>,
    acknowledged: bool,
    recovered_installation: Option<ContextWindowInstalledParams>,
}

impl RefillGate {
    pub(super) fn pending(
        operation_id: String,
        owner_epoch: u64,
        host: Arc<dyn ContextRefillHost>,
    ) -> Self {
        Self {
            operation_id,
            owner_epoch,
            host: Some(host),
            acknowledged: false,
            recovered_installation: None,
        }
    }

    pub(super) fn acknowledge(&mut self, operation_id: &str) -> CodexResult<()> {
        if self.operation_id != operation_id {
            return Err(held());
        }
        self.acknowledged = true;
        Ok(())
    }

    pub(super) fn acknowledged(&self) -> bool {
        self.acknowledged
    }
}

fn held() -> CodexErr {
    CodexErr::Fatal("Original canonical refill is held; inspect its original durable receipt, never retry/reset/replay".into())
}

pub(super) fn live(
    host: &dyn ContextRefillHost,
    epoch: u64,
    cancel: &CancellationToken,
) -> CodexResult<()> {
    if cancel.is_cancelled() {
        return Err(CodexErr::TurnAborted);
    }
    if !host.is_current(epoch) {
        return Err(held());
    }
    Ok(())
}

pub(super) async fn host_call<T>(
    future: impl Future<Output = io::Result<T>>,
    cancel: &CancellationToken,
) -> CodexResult<T> {
    tokio::select! {
        biased;
        _ = cancel.cancelled() => Err(CodexErr::TurnAborted),
        result = tokio::time::timeout(Duration::from_secs(30), future) =>
            result.map_err(|_| held())?.map_err(|_| held()),
    }
}

/// Read under the same active-turn -> state lock order as task admission.
/// This function has no task, provider, preparation, event or persistence path.
pub(crate) async fn read_window_state(
    sess: &Session,
    expected_owner_epoch: u64,
) -> CodexResult<ContextWindowState> {
    let policy = sess
        .services
        .thread_extension_data
        .get::<AutomaticContextRefill>()
        .ok_or_else(|| {
            CodexErr::InvalidRequest("explicit retained-context policy required".into())
        })?;
    if !matches!(
        policy.evidence,
        crate::context_refill::RetainedContextEvidence::WholeItemsV1
    ) {
        return Err(CodexErr::InvalidRequest(
            "explicit retained-context policy required".into(),
        ));
    }
    let epoch = policy.host.owner_epoch();
    if epoch != expected_owner_epoch
        || !policy.host.is_current(epoch)
        || policy.host.owner_disconnected().is_cancelled()
    {
        return Err(held());
    }
    let active = sess.active_turn.lock().await;
    let state = sess.state.lock().await;
    if !policy.host.is_current(epoch) {
        return Err(held());
    }
    Ok(ContextWindowState {
        thread_id: sess.thread_id.to_string(),
        context_id: policy.context_id.clone(),
        purpose: policy.purpose.clone(),
        window_id: state.auto_compact_window_ids().window_id.to_string(),
        history_version: state.history.history_version(),
        last_started_turn_id: state.last_started_turn_id.clone(),
        active_turn_id: active
            .as_ref()
            .and_then(|turn| turn.task.as_ref())
            .map(|task| task.turn_context.sub_id.clone()),
        idle: active.is_none(),
        held_operation_id: state
            .canonical_refill
            .as_ref()
            .filter(|gate| !gate.acknowledged)
            .map(|gate| gate.operation_id.clone()),
    })
}

pub(super) fn configured(sess: &Session) -> bool {
    sess.services
        .thread_extension_data
        .get::<AutomaticContextRefill>()
        .is_some()
}

/// A native installed record proves disk durability, NOT host acknowledgement.
/// Hold on cold resume until the fresh explicit owner observes the original
/// durable Hollywood receipt. Never infer acknowledgement from TurnComplete,
/// policy omission, a new connection, or the installed EventMsg itself.
/// Before any complete native marker (including truncated appends), the owning
/// connector's persistent pending/unknown journal remains the recovery fence.
pub(super) fn recover_hold(items: &[RolloutItem]) -> Option<RefillGate> {
    items.iter().rev().find_map(|item| {
        let operation_id = match item {
            RolloutItem::EventMsg(EventMsg::ContextWindowRefillIntent(event)) => {
                &event.operation_id
            }
            RolloutItem::EventMsg(EventMsg::ContextWindowRefillInstalled(event)) => {
                &event.operation_id
            }
            _ => return None,
        };
        Some(RefillGate {
            operation_id: operation_id.clone(),
            owner_epoch: 0,
            host: None,
            acknowledged: false,
            recovered_installation: match item {
                RolloutItem::EventMsg(EventMsg::ContextWindowRefillInstalled(event)) => {
                    Some(event.clone())
                }
                _ => None,
            },
        })
    })
}

/// Captured under the short state lock, retained across provider preparation and
/// response waits. It never holds that mutex over network activity.
pub(super) struct SamplingFence {
    host: Arc<dyn ContextRefillHost>,
    epoch: u64,
}

impl SamplingFence {
    /// Biased cancellation BEFORE polling the request matters: OrCancelExt's
    /// unbiased select may poll a ready dispatch even when already disconnected.
    /// Keep guarding the entire stream-open future, including connect/auth waits.
    pub(super) async fn run<T>(
        &self,
        cancel: &CancellationToken,
        future: impl Future<Output = CodexResult<T>>,
    ) -> CodexResult<T> {
        live(self.host.as_ref(), self.epoch, cancel)?;
        let disconnected = self.host.owner_disconnected();
        tokio::select! {
            biased;
            _ = cancel.cancelled() => Err(CodexErr::TurnAborted),
            _ = disconnected.cancelled() => Err(held()),
            result = future => {
                live(self.host.as_ref(), self.epoch, cancel)?;
                result
            },
        }
    }
}

pub(super) async fn sampling_fence(
    sess: &Session,
    cancel: &CancellationToken,
) -> CodexResult<Option<SamplingFence>> {
    let recovery = {
        let state = sess.state.lock().await;
        state.canonical_refill.as_ref().and_then(|gate| {
            if gate.acknowledged || gate.host.is_some() {
                return None;
            }
            let original = gate.recovered_installation.clone()?;
            let policy = sess
                .services
                .thread_extension_data
                .get::<AutomaticContextRefill>()?;
            Some((original, policy))
        })
    };
    if let Some((original, policy)) = recovery {
        if original.thread_id != sess.thread_id.to_string()
            || original.context_id != policy.context_id
            || original.purpose != policy.purpose
        {
            return Err(held());
        }
        let epoch = policy.host.owner_epoch();
        live(policy.host.as_ref(), epoch, cancel)?;
        // The host observes the original receipt by GET. It cannot repeat an
        // installation or grant a new Work/turn/effect permission through this port.
        let ack = host_call(policy.host.reconcile(epoch, original.clone()), cancel).await?;
        live(policy.host.as_ref(), epoch, cancel)?;
        if ack.operation_id != original.operation_id
            || ack.status != ContextWindowInstalledStatus::Recorded
        {
            return Err(held());
        }
        let mut state = sess.state.lock().await;
        if state.shutting_down {
            return Err(held());
        }
        let gate = state.canonical_refill.as_mut().ok_or_else(held)?;
        if gate.operation_id != original.operation_id
            || gate.recovered_installation.as_ref() != Some(&original)
        {
            return Err(held());
        }
        live(policy.host.as_ref(), epoch, cancel)?;
        gate.host = Some(Arc::clone(&policy.host));
        gate.owner_epoch = epoch;
        gate.acknowledged = true;
    }
    let state = sess.state.lock().await;
    let fence = if let Some(gate) = &state.canonical_refill {
        if !gate.acknowledged {
            return Err(CodexErr::Fatal(format!(
                "Original canonical refill {} is held; inspect its original receipt without retry/reset/replay",
                gate.operation_id,
            )));
        }
        Some(SamplingFence {
            host: Arc::clone(gate.host.as_ref().ok_or_else(held)?),
            epoch: gate.owner_epoch,
        })
    } else {
        sess.services
            .thread_extension_data
            .get::<AutomaticContextRefill>()
            .map(|policy| SamplingFence {
                host: Arc::clone(&policy.host),
                epoch: policy.host.owner_epoch(),
            })
            .or_else(|| {
                sess.services
                    .thread_extension_data
                    .get::<crate::primary_context_input::PrimaryContextInput>()
                    .map(|policy| SamplingFence {
                        host: Arc::clone(&policy.host),
                        epoch: policy.host.owner_epoch(),
                    })
            })
    };
    if let Some(fence) = &fence {
        live(fence.host.as_ref(), fence.epoch, cancel)?;
    }
    Ok(fence)
}

/// Preliminary checks do not replace the final dispatch fence below.
pub(super) async fn check_sampling(sess: &Session, cancel: &CancellationToken) -> CodexResult<()> {
    sampling_fence(sess, cancel).await.map(|_| ())
}

/// Invoked exclusively after the foreground tool futures are drained, before
/// automatic compaction of any kind. Initial/pending inputs retain their normal
/// run_turn order; this never drains/adopts/acknowledges an inbox itself.
pub(super) async fn run(
    sess: &Arc<Session>,
    step: &StepContext,
    client: &mut ModelClientSession,
    reason: CompactionReason,
    phase: CompactionPhase,
    cancel: &CancellationToken,
) -> CodexResult<bool> {
    let Some(policy) = sess
        .services
        .thread_extension_data
        .get::<AutomaticContextRefill>()
    else {
        return Ok(false);
    };
    check_sampling(sess, cancel).await?;
    if step.turn.config.ephemeral {
        return Err(held());
    }
    let recorder = sess.services.live_thread.as_ref().ok_or_else(held)?;
    let epoch = policy.host.owner_epoch();
    live(policy.host.as_ref(), epoch, cancel)?;
    let request = {
        let mut state = sess.state.lock().await;
        if state.shutting_down || state.last_started_turn_id.as_deref() != Some(&step.turn.sub_id) {
            return Err(held());
        }
        let request = ContextWindowRefillParams {
            thread_id: sess.thread_id.to_string(),
            turn_id: step.turn.sub_id.clone(),
            operation_id: Uuid::now_v7().to_string(),
            context_id: policy.context_id.clone(),
            purpose: policy.purpose.clone(),
            window_id: state.auto_compact_window_ids().window_id.to_string(),
            history_version: state.history.history_version(),
            reason: match reason {
                CompactionReason::ModelDownshift => ContextWindowRefillReason::ModelDownshift,
                CompactionReason::CompHashChanged => ContextWindowRefillReason::CompHashChanged,
                _ => ContextWindowRefillReason::ContextLimit,
            },
            phase: match phase {
                CompactionPhase::PreTurn => ContextWindowRefillPhase::PreTurn,
                CompactionPhase::PostTurn => ContextWindowRefillPhase::PostTurn,
                _ => ContextWindowRefillPhase::MidTurn,
            },
        };
        // Never clear this on an error, cancellation or dropped future.
        state.canonical_refill = Some(RefillGate::pending(
            request.operation_id.clone(),
            epoch,
            Arc::clone(&policy.host),
        ));
        request
    };
    let response = host_call(policy.host.refill(epoch, request.clone()), cancel).await?;
    live(policy.host.as_ref(), epoch, cancel)?;
    let world = sess
        .build_world_state_for_step(step, /*new_window*/ true)
        .await?;
    let (updates, baseline) = sess
        .build_initial_context_with_world_state(step, &world)
        .await;
    let mut replacement: Vec<ResponseItemEnvelope> =
        crate::context_manager::updates::merge_world_state_updates(updates)
            .into_iter()
            .map(ResponseItemEnvelope::new)
            .collect();
    replacement =
        super::context_prefix::stamp(sess, codex_history::NativeContextKind::Prefix, replacement);
    let prefix_item_count = replacement.len();
    match policy.evidence {
        crate::context_refill::RetainedContextEvidence::IndexOnly => {
            replacement.extend(validate_response(&request, &response).map_err(|_| held())?);
        }
        crate::context_refill::RetainedContextEvidence::WholeItemsV1 => {
            replacement =
                crate::context_retained_actions::validate(&request, &response, &replacement)
                    .map_err(|_| held())?;
        }
    }
    // Core-owned typed initial instructions are the only non-data prefix.
    // Hard fail oversized native prefixes; never truncate canonical fragments.
    // Bounds apply to model-visible items; history envelopes persist their
    // harness metadata separately through CompactedItem serialization.
    let wire_items: Vec<_> = replacement.iter().map(|entry| &entry.item).collect();
    let encoded = serde_json::to_vec(&wire_items).map_err(|_| held())?;
    if encoded.len() > 1024 * 1024
        || replacement.iter().take(prefix_item_count).any(|item| {
            serde_json::to_vec(&item.item).map_or(true, |bytes| {
                bytes.len() > crate::context_refill::native_prefix_item_byte_limit(&item.item)
            })
        })
        || replacement.iter().skip(prefix_item_count).any(|item| {
            serde_json::to_vec(&item.item).map_or(true, |bytes| {
                bytes.len() > crate::context_refill::MAX_REFILL_ITEM_BYTES
            })
        })
    {
        return Err(held());
    }
    live(policy.host.as_ref(), epoch, cancel)?;
    let (receipt, installed_version) = {
        // Serialize CAS + dedicated disk transaction + in-memory swap with all
        // history writers. Cancel/connection tokens remain independently routable.
        let mut state = sess.state.lock().await;
        live(policy.host.as_ref(), epoch, cancel)?;
        if state.shutting_down
            || state.history.history_version() != request.history_version
            || state.auto_compact_window_ids().window_id.to_string() != request.window_id
            || state.last_started_turn_id.as_deref() != Some(&request.turn_id)
            || state
                .canonical_refill
                .as_ref()
                .is_none_or(|g| g.operation_id != request.operation_id)
        {
            return Err(held());
        }
        let old_ids = state.auto_compact_window_ids();
        let next = Uuid::now_v7();
        let ids = AutoCompactWindowIds {
            first_window_id: old_ids.first_window_id,
            previous_window_id: Some(old_ids.window_id),
            window_id: next,
        };
        let number = state.auto_compact_window_number().saturating_add(1);
        let checkpoint = CompactedItem {
            message: String::new(),
            replacement_history: Some(replacement.clone()),
            guardian_history: None,
            retained_context: Some(state.history.retained_context().clone()),
            mcp_resource_origins: sess.services.mcp_runtime.resource_origin_checkpoint(),
            window_number: Some(number),
            first_window_id: Some(ids.first_window_id.to_string()),
            previous_window_id: Some(old_ids.window_id.to_string()),
            window_id: Some(next.to_string()),
            compaction_response_id: None,
            latest_token_usage_record: state.latest_token_usage_record.clone(),
            resume_metadata: Some(CompactionResumeMetadata {
                native_context: match policy.evidence {
                    crate::context_refill::RetainedContextEvidence::IndexOnly => None,
                    crate::context_refill::RetainedContextEvidence::WholeItemsV1 => {
                        Some(codex_history::NativeContextCheckpoint {
                            schema: "lax-native-context-checkpoint/v1".into(),
                            thread_id: sess.thread_id.to_string(),
                            context_id: policy.context_id.clone(),
                            mode: codex_history::NativeContextCheckpointMode::StepBoundary,
                            world_state: codex_protocol::protocol::WorldStateItem::full(
                                baseline.clone().into_object(),
                            ),
                            reference_context: Some(step.to_turn_context_item()),
                        })
                    }
                },
                multi_agent_version: sess.multi_agent_version(),
                last_started_turn_id: state.last_started_turn_id.clone(),
                turn_attribution: state.turn_attribution.clone(),
                previous_turn_settings: state.previous_turn_settings(),
            }),
        };
        let intent = ContextWindowRefillIntentEvent {
            thread_id: request.thread_id.clone(),
            turn_id: request.turn_id.clone(),
            operation_id: request.operation_id.clone(),
            context_id: request.context_id.clone(),
            purpose: request.purpose.clone(),
            window_id: request.window_id.clone(),
            history_version: request.history_version,
            reason: request.reason.clone(),
            phase: request.phase.clone(),
            snapshot_operation_id: response.snapshot_operation_id.clone(),
            snapshot_read_point: response.snapshot_read_point.clone(),
            snapshot_sha256: response.snapshot_sha256.clone(),
            native_actions_sha256: response.native_actions_sha256.clone(),
            selection_revision: response.selection_revision,
            total_bytes: response.total_bytes,
            next_window_id: next.to_string(),
        };
        // Do not select-cancel this dispatched append. Await the ORIGINAL outcome.
        // Its strict writer poisons/exits on any uncertainty, including later flush.
        let receipt = recorder
            .install_context_refill(intent, checkpoint)
            .await
            .map_err(|_| held())?;
        live(policy.host.as_ref(), epoch, cancel)?;
        state.replace_annotated_history(
            replacement,
            Some(step.to_turn_context_item()),
            HistoryReplacement::Compaction {
                reviewer_compaction_hash: None,
            },
        );
        state.restore_auto_compact_window(number, ids);
        state.history.set_world_state_baseline(baseline);
        state.reasoning_effort_pin = ReasoningEffortPin::Compacted;
        (receipt, state.history.history_version())
    };
    // Durable installation is NOT host acceptance. Never sample on a lost reply.
    live(policy.host.as_ref(), epoch, cancel)?;
    let ack = host_call(policy.host.installed(epoch, receipt), cancel).await?;
    live(policy.host.as_ref(), epoch, cancel)?;
    if ack.operation_id != request.operation_id
        || ack.status != ContextWindowInstalledStatus::Recorded
    {
        return Err(held());
    }
    {
        let mut state = sess.state.lock().await;
        if state.shutting_down || state.history.history_version() != installed_version {
            return Err(held());
        }
        let gate = state.canonical_refill.as_mut().ok_or_else(held)?;
        gate.acknowledge(&request.operation_id)?;
    }
    client.reset_after_canonical_refill();
    sess.recompute_token_usage(&step.turn).await;
    Ok(true)
}

#[cfg(test)]
#[path = "context_refill_tests.rs"]
mod tests;
