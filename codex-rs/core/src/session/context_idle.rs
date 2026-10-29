//! Owner-bound context packet inspection. Reads native provenance only; it
//! never captures a StepContext, refreshes tools or starts work. The separately
//! admitted idle operation uses the existing strict native transaction.
use super::session::Session;
use crate::context_refill::AutomaticContextRefill;
use codex_protocol::context_refill::*;
use codex_protocol::error::CodexErr;
use codex_protocol::error::Result as CodexResult;
use sha2::Digest;
use sha2::Sha256;

fn changed() -> CodexErr {
    CodexErr::InvalidRequest("native context cut changed or remains held".into())
}

/// Preflight may inspect an active turn; only a future idle commit can mutate
/// history, and must repeat these checks against its original exact cut.
pub(crate) async fn preflight(
    sess: &Session,
    expected_owner_epoch: u64,
    expected: ContextWindowState,
    response: ContextWindowRefillResponse,
) -> CodexResult<ContextWindowPreflight> {
    let observed = super::context_refill::read_window_state(sess, expected_owner_epoch).await?;
    if observed != expected || expected.held_operation_id.is_some() {
        return Err(changed());
    }
    let policy = sess
        .services
        .thread_extension_data
        .get::<AutomaticContextRefill>()
        .ok_or_else(changed)?;
    if policy.purpose != ContextRefillPurpose::Writer {
        return Err(changed());
    }
    let active = sess.active_turn.lock().await;
    let state = sess.state.lock().await;
    let turn = active
        .as_ref()
        .and_then(|turn| turn.task.as_ref())
        .map(|task| task.turn_context.sub_id.clone());
    if state.shutting_down
        || active.is_none() != expected.idle
        || turn != expected.active_turn_id
        || state.last_started_turn_id != expected.last_started_turn_id
        || state.history.history_version() != expected.history_version
        || state.auto_compact_window_ids().window_id.to_string() != expected.window_id
        || state
            .canonical_refill
            .as_ref()
            .is_some_and(|gate| !gate.acknowledged())
        || !policy.host.is_current(expected_owner_epoch)
        || policy.host.owner_disconnected().is_cancelled()
    {
        return Err(changed());
    }
    let turn_id = turn
        .or_else(|| state.last_started_turn_id.clone())
        .ok_or_else(|| {
            CodexErr::InvalidRequest("native core context has no original turn".into())
        })?;
    let producer_sha256 = super::initial_context_producer::source_digest(
        &state.history,
        &sess.thread_id.to_string(),
        &policy.context_id,
        state.auto_compact_window_ids(),
    )
    .map_err(|error| CodexErr::InvalidRequest(format!("native prefix unavailable: {error}")))?;
    if expected.producer_sha256.as_ref() != Some(&producer_sha256) {
        return Err(changed());
    }
    let ids = super::initial_context_producer::target_ids(
        state.auto_compact_window_ids(),
        &policy.context_id,
        &response.operation_id,
        observed.history_version,
    );
    let prefix = super::initial_context_producer::prefix(
        &state.history,
        &sess.thread_id.to_string(),
        &policy.context_id,
        &turn_id,
        ids,
    )
    .map_err(|error| CodexErr::InvalidRequest(format!("native prefix unavailable: {error}")))?;
    let request = ContextWindowRefillParams {
        thread_id: observed.thread_id.clone(),
        turn_id,
        operation_id: response.operation_id.clone(),
        context_id: observed.context_id.clone(),
        purpose: observed.purpose.clone(),
        window_id: observed.window_id.clone(),
        history_version: observed.history_version,
        // These are inspection correlation values, not a persisted maintenance
        // intent. The packet itself carries no compaction reason or phase.
        reason: ContextWindowRefillReason::ContextLimit,
        phase: if observed.idle {
            ContextWindowRefillPhase::PostTurn
        } else {
            ContextWindowRefillPhase::MidTurn
        },
    };
    let replacement = crate::context_retained_actions::validate(&request, &response, &prefix)
        .map_err(|error| CodexErr::InvalidRequest(format!("native packet refused: {error}")))?;
    let wire_items: Vec<_> = replacement.iter().map(|item| &item.item).collect();
    // Canonical object ordering survives a client journal's JSON reordering.
    let mut packet = serde_json::to_value(&response).map_err(|_| changed())?;
    packet.sort_all_objects();
    let mut content = serde_json::to_value(&wire_items).map_err(|_| changed())?;
    content.sort_all_objects();
    let result = ContextWindowPreflight {
        state: observed,
        operation_id: response.operation_id.clone(),
        next_window_id: ids.window_id.to_string(),
        producer_sha256,
        packet_sha256: format!(
            "{:x}",
            Sha256::digest(serde_json::to_vec(&packet).map_err(|_| changed())?)
        ),
        replacement_sha256: format!(
            "{:x}",
            Sha256::digest(serde_json::to_vec(&content).map_err(|_| changed())?)
        ),
        prefix_item_count: prefix.len() as u64,
        replacement_item_count: replacement.len() as u64,
        replacement_wire_bytes: serde_json::to_vec(&wire_items)
            .map_err(|_| changed())?
            .len() as u64,
    };
    if !policy.host.is_current(expected_owner_epoch)
        || policy.host.owner_disconnected().is_cancelled()
    {
        return Err(changed());
    }
    Ok(result)
}

/// Replace an exact idle cut without a task or provider call. Keep the native
/// admission lock through the bounded owner acknowledgement; state is unlocked
/// during that callback. Once dispatched, any failure leaves the original gate held.
pub(crate) async fn replace_idle(
    sess: &Session,
    epoch: u64,
    expected: ContextWindowPreflight,
    response: ContextWindowRefillResponse,
) -> CodexResult<ContextWindowInstalledParams> {
    use super::context_refill::RefillGate;
    use super::context_refill::host_call;
    use super::context_refill::live;
    use crate::context_manager::HistoryReplacement;
    use crate::context_refill::encoded_size;
    use crate::state::ReasoningEffortPin;
    use codex_history::CompactedItem;
    use codex_history::CompactionResumeMetadata;
    use codex_history::NativeContextCheckpoint;
    use codex_history::NativeContextCheckpointMode;
    use std::sync::Arc;

    if !expected.state.idle
        || expected.state.active_turn_id.is_some()
        || preflight(sess, epoch, expected.state.clone(), response.clone()).await? != expected
    {
        return Err(changed());
    }
    let policy = sess
        .services
        .thread_extension_data
        .get::<AutomaticContextRefill>()
        .ok_or_else(changed)?;
    let recorder = sess.services.live_thread.as_ref().ok_or_else(changed)?;
    let disconnected = policy.host.owner_disconnected();
    live(policy.host.as_ref(), epoch, &disconnected)?;
    let active = sess.active_turn.lock().await;
    let (receipt, installed_version) = {
        let mut state = sess.state.lock().await;
        let cut = &expected.state;
        if active.is_some()
            || state.shutting_down
            || state.startup_prewarm.is_some()
            || policy.context_id != cut.context_id
            || policy.purpose != cut.purpose
            || state.history.history_version() != cut.history_version
            || state.auto_compact_window_ids().window_id.to_string() != cut.window_id
            || state.last_started_turn_id != cut.last_started_turn_id
            || state
                .canonical_refill
                .as_ref()
                .is_some_and(|gate| !gate.acknowledged())
        {
            return Err(changed());
        }
        live(policy.host.as_ref(), epoch, &disconnected)?;
        let request = ContextWindowRefillParams {
            thread_id: cut.thread_id.clone(),
            turn_id: cut.last_started_turn_id.clone().ok_or_else(changed)?,
            operation_id: response.operation_id.clone(),
            context_id: cut.context_id.clone(),
            purpose: cut.purpose.clone(),
            window_id: cut.window_id.clone(),
            history_version: cut.history_version,
            reason: ContextWindowRefillReason::ExplicitRequest,
            phase: ContextWindowRefillPhase::PostTurn,
        };
        let ids = super::initial_context_producer::target_ids(
            state.auto_compact_window_ids(),
            &policy.context_id,
            &response.operation_id,
            cut.history_version,
        );
        if ids.window_id.to_string() != expected.next_window_id
            || super::initial_context_producer::source_digest(
                &state.history,
                &sess.thread_id.to_string(),
                &policy.context_id,
                state.auto_compact_window_ids(),
            )
            .map_err(|_| changed())?
                != expected.producer_sha256
        {
            return Err(changed());
        }
        let prefix = super::initial_context_producer::prefix(
            &state.history,
            &sess.thread_id.to_string(),
            &policy.context_id,
            &request.turn_id,
            ids,
        )
        .map_err(|_| changed())?;
        let replacement = crate::context_retained_actions::validate(&request, &response, &prefix)
            .map_err(|_| changed())?;
        // Admit existing native reconstruction data before copying it.
        let baseline = state.history.world_state_snapshot().ok_or_else(changed)?;
        encoded_size(baseline, 256 * 1024).map_err(|_| changed())?;
        encoded_size(&state.history.retained_context(), 256 * 1024).map_err(|_| changed())?;
        encoded_size(&state.history.reference_context_item_ref(), 256 * 1024)
            .map_err(|_| changed())?;
        let baseline = baseline.clone();
        let reference = state
            .history
            .reference_context_item_ref()
            .ok_or_else(changed)?
            .clone();
        let old = state.auto_compact_window_ids();
        let next = ids.window_id;
        let world_checkpoint = state.history.world_state_checkpoint().ok_or_else(changed)?;
        let producer = world_checkpoint.native_context_producer.clone();
        let number = state.auto_compact_window_number().saturating_add(1);
        let checkpoint = CompactedItem {
            message: String::new(),
            replacement_history: Some(replacement.clone()),
            guardian_history: None,
            retained_context: Some(state.history.retained_context().clone()),
            mcp_resource_origins: sess.services.mcp_runtime.resource_origin_checkpoint(),
            window_number: Some(number),
            first_window_id: Some(ids.first_window_id.to_string()),
            previous_window_id: Some(old.window_id.to_string()),
            window_id: Some(next.to_string()),
            compaction_response_id: None,
            latest_token_usage_record: state.latest_token_usage_record.clone(),
            resume_metadata: Some(CompactionResumeMetadata {
                native_context: Some(NativeContextCheckpoint {
                    schema: "lax-native-context-checkpoint/v1".into(),
                    thread_id: sess.thread_id.to_string(),
                    context_id: policy.context_id.clone(),
                    mode: NativeContextCheckpointMode::IdleRequest,
                    world_state: world_checkpoint,
                    reference_context: Some(reference.clone()),
                }),
                multi_agent_version: sess.multi_agent_version(),
                last_started_turn_id: state.last_started_turn_id.clone(),
                turn_attribution: state.turn_attribution.clone(),
                previous_turn_settings: state.previous_turn_settings(),
            }),
        };
        encoded_size(&checkpoint, 1024 * 1024).map_err(|_| changed())?;
        let intent = ContextWindowRefillIntentEvent {
            thread_id: request.thread_id.clone(),
            turn_id: request.turn_id.clone(),
            operation_id: request.operation_id.clone(),
            context_id: request.context_id.clone(),
            purpose: request.purpose.clone(),
            window_id: request.window_id.clone(),
            history_version: request.history_version,
            reason: request.reason,
            phase: request.phase,
            snapshot_operation_id: response.snapshot_operation_id.clone(),
            snapshot_read_point: response.snapshot_read_point.clone(),
            snapshot_sha256: response.snapshot_sha256.clone(),
            native_actions_sha256: response.native_actions_sha256.clone(),
            selection_revision: response.selection_revision,
            total_bytes: response.total_bytes,
            next_window_id: next.to_string(),
        };
        // No gate or durable event exists for any rejected preparation.
        state.canonical_refill = Some(RefillGate::pending(
            response.operation_id.clone(),
            epoch,
            Arc::clone(&policy.host),
        ));
        // Await the original strict writer result. Never select-cancel or retry.
        let receipt = recorder
            .install_context_refill(intent, checkpoint)
            .await
            .map_err(|_| changed())?;
        live(policy.host.as_ref(), epoch, &disconnected)?;
        state.replace_annotated_history(
            replacement,
            Some(reference),
            HistoryReplacement::Compaction {
                reviewer_compaction_hash: None,
            },
        );
        state.restore_auto_compact_window(number, ids);
        state.history.set_world_state_baseline(baseline);
        state.history.set_native_context_producer(producer);
        state.reasoning_effort_pin = ReasoningEffortPin::Compacted;
        (receipt, state.history.history_version())
    };
    let ack = host_call(
        policy.host.idle_installed(epoch, receipt.clone()),
        &disconnected,
    )
    .await?;
    live(policy.host.as_ref(), epoch, &disconnected)?;
    if ack.operation_id != receipt.operation_id
        || ack.status != ContextWindowInstalledStatus::Recorded
    {
        return Err(changed());
    }
    let mut state = sess.state.lock().await;
    if state.shutting_down || state.history.history_version() != installed_version {
        return Err(changed());
    }
    state
        .canonical_refill
        .as_mut()
        .ok_or_else(changed)?
        .acknowledge(&receipt.operation_id)?;
    drop(state);
    drop(active);
    Ok(receipt)
}
