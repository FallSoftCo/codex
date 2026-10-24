//! Reconstruct native context from its own recorded provenance, without runtime
//! discovery, permission handles, task admission, provider calls or history writes.
//! Actual execution still uses a newly captured StepContext at its normal boundary.

use codex_history::NativeContextKind;
use codex_history::NativeContextOrigin;
use codex_history::ResponseItemEnvelope;
use codex_protocol::context_refill::ContextRefillPurpose;
use codex_protocol::models::ResponseItem;
use codex_protocol::openai_models::ModelInfo;
use sha2::Digest;
use sha2::Sha256;
use std::io;

use super::session::Session;
use super::turn_context::TurnContext;
use crate::context_manager::ContextManager;
use crate::context_refill::AutomaticContextRefill;
use crate::context_refill::RetainedContextEvidence;

fn hash(items: &[ResponseItemEnvelope]) -> io::Result<String> {
    let values: Vec<_> = items.iter().map(|item| &item.item).collect();
    Ok(format!(
        "{:x}",
        Sha256::digest(serde_json::to_vec(&values)?)
    ))
}

/// Only native context producers call this. Client inputs and model/tool output
/// use the ordinary recording path and cannot supply harness provenance.
pub(crate) fn stamp(
    sess: &Session,
    kind: NativeContextKind,
    mut items: Vec<ResponseItemEnvelope>,
) -> Vec<ResponseItemEnvelope> {
    let Some(policy) = sess
        .services
        .thread_extension_data
        .get::<AutomaticContextRefill>()
    else {
        return items;
    };
    if !matches!(policy.evidence, RetainedContextEvidence::WholeItemsV1)
        || policy.purpose != ContextRefillPurpose::Writer
        || items.is_empty()
    {
        return items;
    }
    for item in &mut items {
        Session::assign_missing_response_item_id(&mut item.item);
    }
    let Ok(sha256) = hash(&items) else {
        // Normal execution is not stopped to enable optional maintenance.
        // A group without complete provenance remains unavailable to preflight.
        return items;
    };
    let group_id = uuid::Uuid::now_v7().to_string();
    let count = items.len();
    for (index, item) in items.iter_mut().enumerate() {
        item.metadata.get_or_insert_default().native_context_origin = Some(NativeContextOrigin {
            schema: "lax-native-core-context/v1".into(),
            thread_id: sess.thread_id.to_string(),
            context_id: policy.context_id.clone(),
            group_id: group_id.clone(),
            kind,
            index,
            count,
            sha256: sha256.clone(),
        });
    }
    items
}

/// A newly opted-in or forked session establishes its own provenance during its
/// next authorized normal step. Existing own provenance, even malformed, is never
/// silently repaired by this migration check.
pub(crate) fn needs_initial_group(sess: &Session, history: &ContextManager) -> bool {
    let Some(policy) = sess
        .services
        .thread_extension_data
        .get::<AutomaticContextRefill>()
    else {
        return false;
    };
    matches!(policy.evidence, RetainedContextEvidence::WholeItemsV1)
        && policy.purpose == ContextRefillPurpose::Writer
        && !history.annotated_items().iter().any(|item| {
            item.metadata
                .as_ref()
                .and_then(|metadata| metadata.native_context_origin.as_ref())
                .is_some_and(|origin| {
                    origin.kind == NativeContextKind::Prefix
                        && origin.thread_id == sess.thread_id.to_string()
                        && origin.context_id == policy.context_id
                })
        })
}

/// Bounded exact fold of the most recent complete native base and its recorded
/// updates. No text classification or reconstruction from missing provenance.
pub(crate) fn read(
    history: &ContextManager,
    thread_id: &str,
    context_id: &str,
) -> io::Result<Vec<ResponseItemEnvelope>> {
    fn origin(item: &ResponseItemEnvelope) -> Option<&NativeContextOrigin> {
        item.metadata
            .as_ref()
            .and_then(|metadata| metadata.native_context_origin.as_ref())
    }
    let items = history.annotated_items();
    let latest = items
        .iter()
        .rev()
        .filter_map(origin)
        .find(|marker| marker.kind == NativeContextKind::Prefix)
        .ok_or_else(|| io::Error::other("native core prefix provenance unavailable"))?;
    let start = items
        .iter()
        .position(|item| origin(item).is_some_and(|marker| marker.group_id == latest.group_id))
        .ok_or_else(|| io::Error::other("native core prefix is incomplete"))?;
    let mut result = Vec::new();
    let mut group: Option<NativeContextOrigin> = None;
    let mut group_start = 0;
    let mut bytes = 0;
    let mut metadata_bytes = 0;
    let refuse = || io::Error::other("native core context provenance is incomplete or changed");
    for item in &items[start..] {
        let Some(marker) = origin(item) else {
            continue;
        };
        if marker.schema != "lax-native-core-context/v1"
            || marker.thread_id != thread_id
            || marker.context_id != context_id
            || marker.count == 0
            || marker.count > 256
            || uuid::Uuid::parse_str(&marker.group_id).is_err()
            || marker.sha256.len() != 64
            || item
                .metadata
                .as_ref()
                .is_some_and(|metadata| metadata.client_authored)
        {
            return Err(refuse());
        }
        if let Some(current) = &group {
            if marker.group_id != current.group_id {
                return Err(refuse());
            }
            let mut expected = current.clone();
            expected.index = result.len() - group_start;
            if marker != &expected {
                return Err(refuse());
            }
        } else {
            if marker.index != 0
                || (result.is_empty() && marker.kind != NativeContextKind::Prefix)
                || (!result.is_empty() && marker.kind != NativeContextKind::Update)
            {
                return Err(refuse());
            }
            group_start = result.len();
            group = Some(marker.clone());
        }
        let item_bytes = serde_json::to_vec(&item.item)?.len();
        bytes += item_bytes;
        if item_bytes > crate::context_refill::native_prefix_item_byte_limit(&item.item) {
            return Err(io::Error::other(
                "native core prefix item exceeds its typed byte bound",
            ));
        }
        if bytes > crate::context_refill::MAX_REFILL_DATA || result.len() >= 256 {
            return Err(io::Error::other(
                "native core prefix exceeds its aggregate bound",
            ));
        }
        metadata_bytes += crate::context_refill::encoded_size(
            &item.metadata,
            (256 * 1024usize).saturating_sub(metadata_bytes),
        )?;
        result.push(item.clone());
        if result.len() - group_start == marker.count {
            if hash(&result[group_start..])? != marker.sha256 {
                return Err(refuse());
            }
            group = None;
        }
    }
    if group.is_some() {
        return Err(refuse());
    }
    Ok(result)
}

impl Session {
    /// Record native renderer output using the ordinary persistence and raw-item
    /// notification machinery, with source provenance added after item preparation.
    pub(crate) async fn record_native_context_items(
        &self,
        turn_context: &TurnContext,
        model_info: &ModelInfo,
        items: &[ResponseItem],
        kind: NativeContextKind,
    ) {
        let (items, image_preparations) = self
            .prepare_conversation_items_for_history(turn_context, model_info, items)
            .await;
        let items = items
            .into_owned()
            .into_iter()
            .map(ResponseItemEnvelope::new)
            .collect();
        let items = stamp(self, kind, items);
        self.record_prepared_conversation_items(
            turn_context,
            model_info,
            items,
            image_preparations,
        )
        .await;
    }
}

#[cfg(test)]
#[path = "context_prefix_tests.rs"]
mod tests;
