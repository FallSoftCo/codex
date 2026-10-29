//! Complete native material travels with its comparison checkpoint, never as a
//! second Work store or a fold of incremental declarations. Only authorized
//! step acquisition calls collectors. Reads below consume owned data only.
use super::initial_context::InitialContextTemplate;
use super::*;
use crate::context_manager::ContextManager;
use crate::context_refill::AutomaticContextRefill;
use crate::context_refill::RetainedContextEvidence;
use codex_protocol::context_refill::ContextRefillPurpose;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use std::io;

const SCHEMA: &str = "lax-native-context-producer/v1";
const MAX_PRODUCER_BYTES: usize = 1024 * 1024;

fn producer_revision() -> String {
    format!(
        "{}:{}",
        env!("CARGO_PKG_VERSION"),
        option_env!("STABLE_GIT_COMMIT").unwrap_or("unversioned")
    )
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Source {
    schema: String,
    producer_revision: String,
    thread_id: String,
    context_id: String,
    reference: TurnContextItem,
    acquired_step: TurnContextItem,
    template: InitialContextTemplate,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    acquisition: Option<AcquisitionSource>,
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct AcquisitionSource {
    operation_id: String,
    state: codex_protocol::context_refill::ContextWindowState,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Producer {
    source: Source,
    sha256: String,
}

fn changed() -> io::Error {
    io::Error::other(
        "complete native producer unavailable, invalid or changed; normal acquisition required",
    )
}

fn digest(source: &Source) -> io::Result<String> {
    let mut value = serde_json::to_value(source)?;
    value.sort_all_objects();
    Ok(format!("{:x}", Sha256::digest(serde_json::to_vec(&value)?)))
}

fn admit_template(
    template: &InitialContextTemplate,
    reference: &TurnContextItem,
    ids: AutoCompactWindowIds,
) -> io::Result<()> {
    let updates = template
        .render(reference.turn_id.as_deref().unwrap_or(""), ids)?
        .0;
    let items = crate::context_manager::updates::merge_world_state_updates(updates);
    if items.len() > 256 {
        return Err(changed());
    }
    let mut bytes = 0;
    for item in &items {
        let size = crate::context_refill::encoded_size(
            item,
            crate::context_refill::native_prefix_item_byte_limit(item),
        )?;
        bytes += size;
        if bytes > crate::context_refill::MAX_NATIVE_PREFIX_DATA {
            return Err(changed());
        }
    }
    Ok(())
}

pub(super) fn seal(
    thread_id: String,
    context_id: String,
    reference: TurnContextItem,
    acquired_step: TurnContextItem,
    template: InitialContextTemplate,
    ids: AutoCompactWindowIds,
) -> io::Result<serde_json::Value> {
    admit_template(&template, &acquired_step, ids)?;
    let source = Source {
        schema: SCHEMA.into(),
        producer_revision: producer_revision(),
        thread_id,
        context_id,
        reference,
        acquired_step,
        template,
        acquisition: None,
    };
    let producer = Producer {
        sha256: digest(&source)?,
        source,
    };
    crate::context_refill::encoded_size(&producer, MAX_PRODUCER_BYTES)?;
    Ok(serde_json::to_value(producer)?)
}

/// Bind the original operation before appending the native checkpoint.
pub(super) fn bind_acquisition(
    value: serde_json::Value,
    operation_id: String,
    state: codex_protocol::context_refill::ContextWindowState,
) -> io::Result<serde_json::Value> {
    let mut producer: Producer = serde_json::from_value(value)?;
    if operation_id.is_empty()
        || operation_id.len() > 256
        || !state.idle
        || state.held_operation_id.is_some()
        || state.active_turn_id.is_some()
        || state.thread_id != producer.source.thread_id
        || state.context_id != producer.source.context_id
    {
        return Err(changed());
    }
    producer.source.acquisition = Some(AcquisitionSource {
        operation_id,
        state,
    });
    producer.sha256 = digest(&producer.source)?;
    crate::context_refill::encoded_size(&producer, MAX_PRODUCER_BYTES)?;
    Ok(serde_json::to_value(producer)?)
}

pub(super) fn acquisition_receipt(
    history: &ContextManager,
    current: &codex_protocol::context_refill::ContextWindowState,
    ids: AutoCompactWindowIds,
    operation_id: &str,
) -> io::Result<codex_protocol::context_refill::ContextWindowAcquisitionReceipt> {
    read(history, &current.thread_id, &current.context_id, ids)?;
    let producer: Producer = serde_json::from_value(
        history
            .native_context_producer()
            .ok_or_else(changed)?
            .clone(),
    )?;
    let original = producer.source.acquisition.ok_or_else(changed)?;
    if original.operation_id != operation_id
        || original.state.window_id != current.window_id
        || original.state.last_started_turn_id != current.last_started_turn_id
        || !current.idle
        || current.held_operation_id.is_some()
    {
        return Err(changed());
    }
    Ok(
        codex_protocol::context_refill::ContextWindowAcquisitionReceipt {
            operation_id: original.operation_id,
            source_state: original.state,
            producer_sha256: producer.sha256,
        },
    )
}

/// A digest is integrity/provenance inside the protected native rollout, not
/// cryptographic authority for client or model-supplied instructions. Clients
/// never populate this carrier. No fallback to historical Update groups.
pub(super) fn read(
    history: &ContextManager,
    thread_id: &str,
    context_id: &str,
    ids: AutoCompactWindowIds,
) -> io::Result<InitialContextTemplate> {
    let value = history.native_context_producer().ok_or_else(changed)?;
    crate::context_refill::encoded_size(value, MAX_PRODUCER_BYTES)?;
    let producer: Producer = serde_json::from_value(value.clone())?;
    let source = &producer.source;
    if source.schema != SCHEMA
        || source.producer_revision != producer_revision()
        || source.thread_id != thread_id
        || source.context_id != context_id
        || history.reference_context_item_ref() != Some(&source.reference)
        || history.world_state_snapshot() != Some(&source.template.snapshot)
        || digest(source)? != producer.sha256
    {
        return Err(changed());
    }
    admit_template(&source.template, &source.acquired_step, ids)?;
    Ok(producer.source.template)
}

pub(super) fn prefix(
    history: &ContextManager,
    thread_id: &str,
    context_id: &str,
    turn_id: &str,
    ids: AutoCompactWindowIds,
) -> io::Result<Vec<codex_history::ResponseItemEnvelope>> {
    let template = read(history, thread_id, context_id, ids)?;
    let items = crate::context_manager::updates::merge_world_state_updates(
        template.render(turn_id, ids)?.0,
    );
    super::context_prefix::stamp_complete(thread_id, context_id, ids.window_id, items)
}

/// A current inspection cut exposes only a fully validated producer identity,
/// never a claimed self-hash from stale, foreign or partial material.
pub(super) fn source_digest(
    history: &ContextManager,
    thread_id: &str,
    context_id: &str,
    ids: AutoCompactWindowIds,
) -> io::Result<String> {
    read(history, thread_id, context_id, ids)?;
    history
        .native_context_producer()
        .and_then(|value| value.get("sha256"))
        .and_then(serde_json::Value::as_str)
        .map(str::to_owned)
        .ok_or_else(changed)
}

/// Stable proposed UUID for this exact inspection cut, never a clock read,
/// random draw or persisted reservation during preview. Version 8 is UUID's
/// application-defined format; subsequent windows still keep their lineage.
pub(super) fn target_ids(
    old: AutoCompactWindowIds,
    context_id: &str,
    operation_id: &str,
    history_version: u64,
) -> AutoCompactWindowIds {
    let digest = Sha256::digest(
        serde_json::to_vec(&(
            "lax-native-context-target/v1",
            old.window_id.to_string(),
            context_id,
            operation_id,
            history_version,
        ))
        .expect("tuple of primitive target values"),
    );
    let mut bytes = [0u8; 16];
    bytes.copy_from_slice(&digest[..16]);
    bytes[6] = (bytes[6] & 0x0f) | 0x80;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    AutoCompactWindowIds {
        first_window_id: old.first_window_id,
        previous_window_id: Some(old.window_id),
        window_id: uuid::Uuid::from_bytes(bytes),
    }
}

impl Session {
    pub(super) fn complete_native_context_id(&self) -> Option<String> {
        self.services
            .thread_extension_data
            .get::<AutomaticContextRefill>()
            .filter(|policy| {
                policy.purpose == ContextRefillPurpose::Writer
                    && matches!(policy.evidence, RetainedContextEvidence::WholeItemsV1)
            })
            .map(|policy| policy.context_id.clone())
    }

    /// Persistence must succeed before the producer becomes available to pure
    /// reads. Keep the state cut locked across its original append, without any
    /// collector/provider work under that lock. Failure leaves live reads held.
    pub(super) async fn persist_initial_context_producer(
        &self,
        step: &StepContext,
        template: Option<InitialContextTemplate>,
    ) {
        let Some(context_id) = self.complete_native_context_id() else {
            return;
        };
        let mut state = self.state.lock().await;
        state.history.set_native_context_producer(None);
        let Some(snapshot) = state.history.world_state_snapshot().cloned() else {
            return;
        };
        let reference = state.history.reference_context_item();
        let producer = template
            .filter(|template| template.snapshot == snapshot)
            .zip(reference)
            .and_then(|(template, reference)| {
                seal(
                    self.thread_id.to_string(),
                    context_id,
                    reference,
                    step.to_turn_context_item(),
                    template,
                    state.auto_compact_window_ids(),
                )
                .ok()
            });
        let mut checkpoint = WorldStateItem::full(snapshot.into_object());
        checkpoint.native_context_producer = producer.clone();
        if self
            .persist_rollout_items(&[RolloutItem::WorldState(checkpoint)])
            .await
        {
            state.history.set_native_context_producer(producer);
        }
    }
}

#[cfg(test)]
#[path = "initial_context_producer_tests.rs"]
mod tests;
