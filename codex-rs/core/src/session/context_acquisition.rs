//! Explicit owner-admitted legacy preparation, NOT a preview fallback. Collectors
//! may run here; no user input, task, provider request or window is fabricated.
use super::*;
use codex_protocol::context_refill::ContextWindowState;

fn changed() -> CodexErr {
    CodexErr::InvalidRequest("native acquisition cut changed, held or already prepared".into())
}

/// Journal this separate mutating request before dispatch. Observe a lost reply
/// from the original rollout/state; never automatically retry collection.
pub(crate) async fn acquire(
    sess: &Arc<Session>,
    epoch: u64,
    expected: ContextWindowState,
    operation_id: String,
) -> CodexResult<ContextWindowState> {
    if super::context_refill::read_window_state(sess, epoch).await? != expected
        || !expected.idle
        || expected.active_turn_id.is_some()
        || expected.held_operation_id.is_some()
        || operation_id.is_empty()
        || operation_id.len() > 256
    {
        return Err(changed());
    }
    let context_id = sess.complete_native_context_id().ok_or_else(changed)?;
    let original_turn = expected.last_started_turn_id.clone().ok_or_else(changed)?;
    {
        let state = sess.state.lock().await;
        if super::initial_context_producer::read(
            &state.history,
            &sess.thread_id.to_string(),
            &context_id,
            state.auto_compact_window_ids(),
        )
        .is_ok()
        {
            return Err(changed());
        }
    }
    // Recording context with original attribution, not submission/resumption.
    let turn = sess
        .initial_context_acquisition_context(original_turn)
        .await;
    let step = sess
        .capture_speculative_step_context(turn, &tokio_util::sync::CancellationToken::new())
        .await?;
    let world = sess
        .build_world_state_for_step(&step, /*new_window*/ true)
        .await?;
    let template = sess.collect_initial_context(&step).await.capture(&world);
    let reference = step.to_turn_context_item();
    let active = sess.active_turn.lock().await;
    let mut state = sess.state.lock().await;
    let policy = sess
        .services
        .thread_extension_data
        .get::<crate::context_refill::AutomaticContextRefill>()
        .ok_or_else(changed)?;
    if active.is_some()
        || state.shutting_down
        || state.startup_prewarm.is_some()
        || state.history.history_version() != expected.history_version
        || state.last_started_turn_id != expected.last_started_turn_id
        || state.auto_compact_window_ids().window_id.to_string() != expected.window_id
        || state
            .canonical_refill
            .as_ref()
            .is_some_and(|gate| !gate.acknowledged())
        || !policy.host.is_current(epoch)
        || policy.host.owner_disconnected().is_cancelled()
    {
        return Err(changed());
    }
    let ids = state.auto_compact_window_ids();
    let producer = super::initial_context_producer::seal(
        sess.thread_id.to_string(),
        context_id,
        reference.clone(),
        reference.clone(),
        template.clone(),
        ids,
    )
    .map_err(|error| CodexErr::InvalidRequest(format!("native acquisition refused: {error}")))?;
    let producer =
        super::initial_context_producer::bind_acquisition(producer, operation_id, expected.clone())
            .map_err(|_| changed())?;
    let items = crate::context_manager::updates::merge_world_state_updates(
        template
            .render(&step.turn.sub_id, ids)
            .map_err(|_| changed())?
            .0,
    );
    let mut items = super::context_prefix::stamp(
        sess,
        codex_history::NativeContextKind::Prefix,
        items
            .into_iter()
            .map(codex_history::ResponseItemEnvelope::new)
            .collect(),
    );
    let mut checkpoint = WorldStateItem::full(template.snapshot.clone().into_object());
    checkpoint.native_context_producer = Some(producer.clone());
    let mut records: Vec<_> = items
        .iter()
        .cloned()
        .map(RolloutItem::ResponseItem)
        .collect();
    records.push(RolloutItem::TurnContext(reference.clone()));
    records.push(RolloutItem::WorldState(checkpoint));
    crate::context_refill::encoded_size(&records, 2 * 1024 * 1024).map_err(|_| changed())?;
    let recorder = sess.services.live_thread.as_ref().ok_or_else(changed)?;
    // Append, not replace: the old usable window and original receipts remain.
    // Never cancel/repost across an uncertain original append or flush.
    state.history.set_native_context_producer(None);
    recorder
        .append_items(&records)
        .await
        .map_err(|_| changed())?;
    recorder.flush().await.map_err(|_| changed())?;
    if !policy.host.is_current(epoch) || policy.host.owner_disconnected().is_cancelled() {
        return Err(changed());
    }
    state.history.record_annotated_items(
        &mut items,
        step.settings.model_info.truncation_policy.into(),
    );
    state.set_reference_context_item(Some(reference));
    state.history.set_world_state_baseline(template.snapshot);
    state.history.set_native_context_producer(Some(producer));
    drop(state);
    drop(active);
    super::context_refill::read_window_state(sess, epoch).await
}

/// Pure original-operation query. Missing/partial/stale/foreign material remains
/// held; a hash alone never authorizes recollection or releases unknown work.
pub(crate) async fn read(
    sess: &Session,
    epoch: u64,
    operation_id: String,
) -> CodexResult<(
    ContextWindowState,
    codex_protocol::context_refill::ContextWindowAcquisitionReceipt,
)> {
    let current = super::context_refill::read_window_state(sess, epoch).await?;
    let active = sess.active_turn.lock().await;
    let state = sess.state.lock().await;
    let policy = sess
        .services
        .thread_extension_data
        .get::<crate::context_refill::AutomaticContextRefill>()
        .ok_or_else(changed)?;
    if active.is_some()
        || state.shutting_down
        || !policy.host.is_current(epoch)
        || policy.host.owner_disconnected().is_cancelled()
        || state.history.history_version() != current.history_version
        || state.auto_compact_window_ids().window_id.to_string() != current.window_id
    {
        return Err(changed());
    }
    let receipt = super::initial_context_producer::acquisition_receipt(
        &state.history,
        &current,
        state.auto_compact_window_ids(),
        &operation_id,
    )
    .map_err(|_| changed())?;
    if current.producer_sha256.as_ref() != Some(&receipt.producer_sha256) {
        return Err(changed());
    }
    Ok((current, receipt))
}
