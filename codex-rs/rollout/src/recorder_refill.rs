//! A single exclusive writer command, deliberately outside ordinary recovery.
//! A strict error exits the writer task: no flush/shutdown/reopen can replay
//! an uncertain suffix. The caller must hold its live-turn gate through host ack.

use super::*;
use crate::CompactedItem;
use codex_protocol::context_refill::ContextWindowInstalledParams;
use codex_protocol::context_refill::ContextWindowRefillIntentEvent;
use codex_protocol::protocol::EventMsg;
use sha2::Digest;
use sha2::Sha256;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncSeekExt;

// Per-writer test injection only; never process-global or environment driven.
#[cfg(test)]
#[derive(Clone, Copy, PartialEq, Eq)]
pub(super) enum RefillFault {
    AfterPrefix,
    AfterFirstSync,
    AfterReceiptSync,
}

impl RolloutRecorder {
    /// Append intent, full replacement, and receipt to an already materialized
    /// non-ephemeral rollout. Never retry this operation after an uncertain reply.
    pub async fn install_context_refill(
        &self,
        intent: ContextWindowRefillIntentEvent,
        checkpoint: CompactedItem,
    ) -> std::io::Result<ContextWindowInstalledParams> {
        let (ack, result) = oneshot::channel();
        self.tx
            .send(RolloutCmd::ContextRefill {
                intent: Box::new(intent),
                checkpoint: Box::new(checkpoint),
                ack,
            })
            .await
            .map_err(|err| {
                self.writer_task
                    .terminal_failure()
                    .unwrap_or_else(|| IoError::other(err.to_string()))
            })?;
        result.await.map_err(|err| {
            self.writer_task
                .terminal_failure()
                .unwrap_or_else(|| IoError::other(err.to_string()))
        })?
    }
}

impl RolloutWriterState {
    pub(super) async fn install_context_refill_once(
        &mut self,
        intent: ContextWindowRefillIntentEvent,
        checkpoint: CompactedItem,
    ) -> std::io::Result<ContextWindowInstalledParams> {
        if self.deferred_creation
            || self.meta.is_some()
            || !self.pending_items.is_empty()
            || self.last_logged_error.is_some()
        {
            return Err(IoError::other(
                "strict refill requires a clean materialized writer",
            ));
        }
        if !checkpoint.message.is_empty()
            || checkpoint
                .replacement_history
                .as_ref()
                .is_none_or(Vec::is_empty)
            || checkpoint.previous_window_id.as_deref() != Some(intent.window_id.as_str())
            || checkpoint.window_id.as_deref() != Some(intent.next_window_id.as_str())
            || intent.window_id == intent.next_window_id
        {
            return Err(IoError::other(
                "strict refill checkpoint correlation mismatch",
            ));
        }
        if checkpoint
            .resume_metadata
            .as_ref()
            .and_then(|metadata| metadata.native_context.as_ref())
            .is_some_and(|native| {
                !native.supported()
                    || native.thread_id != intent.thread_id
                    || native.context_id != intent.context_id
            })
        {
            return Err(IoError::other(
                "native context checkpoint scope or baseline mismatch",
            ));
        }
        if checkpoint
            .resume_metadata
            .as_ref()
            .is_some_and(|metadata| metadata.native_context.is_some())
            && serde_json::to_vec(&checkpoint)?.len() > 1024 * 1024
        {
            return Err(IoError::other(
                "native context checkpoint exceeds durable payload limit",
            ));
        }
        let writer = self
            .writer
            .as_mut()
            .ok_or_else(|| IoError::other("strict refill writer unavailable; never reopen"))?;
        let mut receipt = ContextWindowInstalledParams {
            thread_id: intent.thread_id.clone(),
            turn_id: intent.turn_id.clone(),
            operation_id: intent.operation_id.clone(),
            context_id: intent.context_id.clone(),
            purpose: intent.purpose.clone(),
            snapshot_operation_id: intent.snapshot_operation_id.clone(),
            snapshot_read_point: intent.snapshot_read_point.clone(),
            snapshot_sha256: intent.snapshot_sha256.clone(),
            native_actions_sha256: intent.native_actions_sha256.clone(),
            selection_revision: intent.selection_revision,
            total_bytes: intent.total_bytes,
            previous_window_id: intent.window_id.clone(),
            window_id: intent.next_window_id.clone(),
            native_history_bytes: 0,
            native_history_sha256: String::new(),
        };
        for item in [
            RolloutItem::EventMsg(EventMsg::ContextWindowRefillIntent(intent)),
            RolloutItem::Compacted(Box::new(checkpoint)),
        ] {
            writer
                .write_rollout_item(&item, self.ordinal_state.current()?)
                .await?;
            self.ordinal_state.advance();
        }
        writer.file.flush().await?;
        #[cfg(test)]
        if self.refill_fault == Some(RefillFault::AfterPrefix) {
            return Err(IoError::other("injected uncertain prefix append"));
        }
        writer.file.sync_all().await?;
        #[cfg(test)]
        if self.refill_fault == Some(RefillFault::AfterFirstSync) {
            return Err(IoError::other("injected lost first sync acknowledgement"));
        }
        // Clone the SAME open file, not a path reopened after an uncertain write.
        let mut prefix = writer.file.try_clone().await?;
        let metadata = prefix.metadata().await?;
        if !metadata.is_file() {
            return Err(IoError::other(
                "strict refill requires original regular JSONL",
            ));
        }
        let end = metadata.len();
        prefix.seek(SeekFrom::Start(0)).await?;
        let mut remaining = end;
        let mut digest = Sha256::new();
        let mut buffer = [0u8; 64 * 1024];
        while remaining > 0 {
            let limit = remaining.min(buffer.len() as u64) as usize;
            let read = prefix.read(&mut buffer[..limit]).await?;
            if read == 0 {
                return Err(IoError::other("strict refill prefix incomplete"));
            }
            digest.update(&buffer[..read]);
            remaining -= read as u64;
        }
        if prefix.metadata().await?.len() != end {
            return Err(IoError::other("strict refill prefix changed"));
        }
        receipt.native_history_bytes = end;
        receipt.native_history_sha256 = format!("{:x}", digest.finalize());
        // The immediately following receipt is OUTSIDE its own hashed prefix.
        writer
            .write_rollout_item(
                &RolloutItem::EventMsg(EventMsg::ContextWindowRefillInstalled(receipt.clone())),
                self.ordinal_state.current()?,
            )
            .await?;
        self.ordinal_state.advance();
        writer.file.flush().await?;
        writer.file.sync_all().await?;
        #[cfg(test)]
        if self.refill_fault == Some(RefillFault::AfterReceiptSync) {
            return Err(IoError::other(
                "injected lost durable receipt acknowledgement",
            ));
        }
        Ok(receipt)
    }
}

#[cfg(test)]
#[path = "recorder_refill_tests.rs"]
mod tests;
