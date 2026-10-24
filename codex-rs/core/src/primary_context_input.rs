//! Exact canonical admission material, independent of optional context reconstruction.
use crate::context_refill::ContextRefillHost;
use codex_history::CodexHarnessMetadata;
use codex_history::ResponseItemEnvelope;
use codex_protocol::context_input::ContextInputParams;
use codex_protocol::context_input::ContextInputResponse;
use codex_protocol::context_refill::ContextRefillPurpose;
use codex_protocol::models::FunctionCallOutputPayload;
use codex_protocol::models::ResponseItem;
use serde::Deserialize;
use sha2::Digest;
use sha2::Sha256;
use std::collections::BTreeSet;
use std::sync::Arc;

#[derive(Clone)]
pub struct PrimaryContextInput {
    pub context_id: String,
    pub purpose: ContextRefillPurpose,
    pub host: Arc<dyn ContextRefillHost>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Fragment {
    schema: String,
    operation_id: String,
    reference: String,
    revision: u64,
    sha256: String,
    total_bytes: usize,
    offset: usize,
    content: String,
}

/// Validate the complete packet before appending any item. This proves bytes,
/// not Hollywood authority, comprehension, execution or Work completion.
pub(crate) fn validate(
    request: &ContextInputParams,
    response: &ContextInputResponse,
) -> Result<Vec<ResponseItemEnvelope>, String> {
    if response.thread_id != request.thread_id
        || response.turn_id != request.turn_id
        || response.operation_id != request.operation_id
        || response.context_id != request.context_id
        || response.purpose != request.purpose
        || response.material_ids != request.material_ids
        || response.admission_operation_id != format!("context-begin:{}", request.turn_id)
        || response.fragments.len() > 64
        || response
            .fragments
            .iter()
            .any(|s| s.is_empty() || !s.is_ascii() || s.len() > 8192)
        || response.fragments.iter().map(String::len).sum::<usize>() > 262144
    {
        return Err("Original primary-input scope or byte bounds changed".into());
    }
    if request.purpose == ContextRefillPurpose::Reader {
        return if response.fragments.is_empty() {
            Ok(Vec::new())
        } else {
            Err("Reader input must use its already adopted canonical inbox".into())
        };
    }
    let expected: Vec<&str> = std::iter::once("role")
        .chain(request.material_ids.iter().map(String::as_str))
        .collect();
    let mut completed = BTreeSet::new();
    let mut current: Option<(String, u64, String, usize, String)> = None;
    for text in &response.fragments {
        let f: Fragment =
            serde_json::from_str(text).map_err(|_| "Invalid primary material fragment")?;
        if f.schema != "lax-context-material-fragment/v1"
            || f.operation_id != response.admission_operation_id
            || f.revision == 0
            || f.content.is_empty()
            || !f.content.is_ascii()
            || f.content.len() > 3072
            || !(1..=98304).contains(&f.total_bytes)
            || f.sha256.len() != 64
            || !f
                .sha256
                .bytes()
                .all(|x| x.is_ascii_digit() || (b'a'..=b'f').contains(&x))
        {
            return Err("Invalid complete primary material metadata".into());
        }
        if current.is_none() {
            if expected.get(completed.len()).copied() != Some(f.reference.as_str()) || f.offset != 0
            {
                return Err("Primary role/material order or first offset changed".into());
            }
            current = Some((
                f.reference.clone(),
                f.revision,
                f.sha256.clone(),
                f.total_bytes,
                String::new(),
            ));
        }
        let (reference, revision, sha, bytes, content) =
            current.as_mut().expect("current material");
        if *reference != f.reference
            || *revision != f.revision
            || *sha != f.sha256
            || *bytes != f.total_bytes
            || f.offset != content.len()
        {
            return Err("Primary material cut changed or fragments are not contiguous".into());
        }
        content.push_str(&f.content);
        if content.len() > *bytes {
            return Err("Primary material exceeds its original byte count".into());
        }
        if content.len() == *bytes {
            if format!("{:x}", Sha256::digest(content.as_bytes())) != *sha
                || serde_json::from_str::<serde_json::Value>(content).is_err()
            {
                return Err("Primary material digest or JSON differs".into());
            }
            completed.insert(reference.clone());
            current = None;
        }
    }
    if current.is_some() || completed.len() != expected.len() {
        return Err("Complete current role and every captured material are required".into());
    }
    Ok(response
        .fragments
        .iter()
        .map(|text| ResponseItemEnvelope {
            item: ResponseItem::FunctionCallOutput {
                id: None,
                call_id: None,
                namespace: Some("hollywood".into()),
                name: Some("context_material".into()),
                output: FunctionCallOutputPayload::from_text(text.clone()),
                internal_chat_message_metadata_passthrough: None,
            },
            metadata: Some(CodexHarnessMetadata {
                history_truncation_token_limit: Some(8192),
                ..Default::default()
            }),
        })
        .collect())
}

#[cfg(test)]
#[path = "primary_context_input_tests.rs"]
mod tests;
