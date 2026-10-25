//! Recover only the previous installed context acknowledgement while idle.
//! This reuses the existing owner callback and never starts inference, changes
//! history, installs another window or accepts Work.
use codex_protocol::context_refill::ContextWindowState;
use codex_protocol::error::CodexErr;
use codex_protocol::error::Result as CodexResult;
use tokio_util::sync::CancellationToken;

use super::session::Session;

fn changed() -> CodexErr {
    CodexErr::InvalidRequest("original idle context reconciliation cut changed".into())
}

pub(crate) async fn reconcile(
    sess: &Session,
    epoch: u64,
    expected: ContextWindowState,
) -> CodexResult<ContextWindowState> {
    let observed = super::context_refill::read_window_state(sess, epoch).await?;
    if observed != expected || !expected.idle || expected.active_turn_id.is_some() {
        return Err(changed());
    }
    // Prevent a concurrent new task while the original owner observes its
    // durable receipt. The state mutex is released across that callback.
    let active = sess.active_turn.lock().await;
    if active.is_some() {
        return Err(changed());
    }
    {
        let state = sess.state.lock().await;
        if state.shutting_down
            || state.history.history_version() != expected.history_version
            || state.auto_compact_window_ids().window_id.to_string() != expected.window_id
            || state.last_started_turn_id != expected.last_started_turn_id
        {
            return Err(changed());
        }
    }
    // An installed marker alone is insufficient. sampling_fence performs the
    // same exact fresh-owner/Hollywood receipt handshake used before sampling,
    // but no provider, turn or task is admitted by this entry point.
    super::context_refill::sampling_fence(sess, &CancellationToken::new()).await?;
    drop(active);
    let current = super::context_refill::read_window_state(sess, epoch).await?;
    if !current.idle
        || current.held_operation_id.is_some()
        || current.window_id != expected.window_id
        || current.history_version != expected.history_version
        || current.last_started_turn_id != expected.last_started_turn_id
    {
        return Err(changed());
    }
    Ok(current)
}
