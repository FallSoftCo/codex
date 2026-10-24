//! Exact retained native evidence validation before any history replacement.
//! Source permissions are checked by Hollywood/the enrolled host. These strings
//! are data only; they never dispatch tools, restore roles, or authorize replay.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::io;

use codex_history::ResponseItemEnvelope;
use codex_protocol::context_refill::*;
use codex_protocol::models::ResponseItem;
use serde::Deserialize;
use serde_json::Value;
use sha2::Digest;
use sha2::Sha256;

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Fragment {
    schema: String,
    sha256: String,
    total_bytes: usize,
    offset: usize,
    content: String,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Bundle {
    schema: String,
    agent_id: String,
    context_id: String,
    purpose: ContextRefillPurpose,
    native_thread: String,
    selection_revision: u64,
    canonical_snapshot_sha256: String,
    entries: Vec<Entry>,
}

#[derive(Deserialize)]
#[serde(untagged)]
enum Entry {
    Available(Available),
    Unavailable(Unavailable),
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Available {
    reference: String,
    metadata: Value,
    payload: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Unavailable {
    reference: String,
    access: String,
    reason: String,
}

fn require(valid: bool) -> io::Result<()> {
    if valid {
        Ok(())
    } else {
        Err(io::Error::other("invalid retained native evidence packet"))
    }
}

fn hash(value: &[u8]) -> String {
    format!("{:x}", Sha256::digest(value))
}

/// The legacy validator continues rejecting retained fragments. Only an explicit
/// per-connection retained-evidence policy calls this validator.
pub(crate) fn validate(
    request: &ContextWindowRefillParams,
    response: &ContextWindowRefillResponse,
    prefix: &[ResponseItemEnvelope],
) -> io::Result<Vec<ResponseItemEnvelope>> {
    require(request.purpose == ContextRefillPurpose::Writer)?;
    require(response.items.len() <= 256 && serde_json::to_vec(&response.items)?.len() <= 1048576)?;
    let first = response
        .items
        .iter()
        .position(|x| x["name"] == "retained_actions")
        .ok_or_else(|| io::Error::other("missing selected native evidence bundle"))?;
    let mut base = response.clone();
    base.items.truncate(first);
    let mut result = crate::context_refill::validate_response(request, &base)?;
    let mut data = String::new();
    let mut digest = None;
    let mut total = None;
    for value in &response.items[first..] {
        let object = value
            .as_object()
            .ok_or_else(|| io::Error::other("non-data evidence item"))?;
        require(
            object.len() == 4
                && value["type"] == "function_call_output"
                && value["namespace"] == "lax"
                && value["name"] == "retained_actions",
        )?;
        let output = value["output"]
            .as_str()
            .ok_or_else(|| io::Error::other("non-string evidence"))?;
        require(output.len() <= 16384)?;
        let fragment: Fragment = serde_json::from_str(output)?;
        require(
            fragment.schema == "lax-retained-native-actions-fragment/v1"
                && fragment.offset == data.len()
                && fragment.total_bytes <= 98304
                && !fragment.content.is_empty()
                && fragment.content.len() <= 3072
                && fragment.content.is_ascii()
                && total.is_none_or(|n| n == fragment.total_bytes)
                && digest.as_ref().is_none_or(|s| s == &fragment.sha256),
        )?;
        total = Some(fragment.total_bytes);
        digest = Some(fragment.sha256);
        require(data.len() + fragment.content.len() <= 98304)?;
        data.push_str(&fragment.content);
        let item: ResponseItem = serde_json::from_value(value.clone())?;
        result.push(ResponseItemEnvelope::new(item));
    }
    require(total == Some(data.len()) && digest == Some(hash(data.as_bytes())))?;
    let mut canonical = String::new();
    let mut descriptor_bytes = 0;
    for value in &base.items {
        let fragment: Value = serde_json::from_str(value["output"].as_str().unwrap_or_default())?;
        let content = fragment["content"]
            .as_str()
            .ok_or_else(|| io::Error::other("missing original fragment"))?;
        if value["name"] == "context_refill" {
            canonical.push_str(content);
        } else {
            descriptor_bytes += content.len();
        }
    }
    require(
        canonical.len() <= 98304
            && descriptor_bytes <= 16384
            && canonical.len() + descriptor_bytes + data.len() <= 262144,
    )?;
    let content: Value = serde_json::from_str(&canonical)?;
    let bundle: Bundle = serde_json::from_str(&data)?;
    require(
        bundle.schema == "lax-retained-native-actions/v1"
            && bundle.purpose == ContextRefillPurpose::Writer
            && bundle.context_id == request.context_id
            && bundle.native_thread == request.thread_id
            && bundle.canonical_snapshot_sha256 == response.snapshot_sha256
            && bundle.selection_revision == response.selection_revision
            && content["purpose"] == "writer"
            && content["contextId"] == request.context_id
            && content["nativeThread"] == request.thread_id
            && content["agentId"] == bundle.agent_id
            && content["selection"]["selectionRevision"].as_u64()
                == Some(response.selection_revision),
    )?;
    let marks = content["selection"]["marks"]
        .as_array()
        .ok_or_else(|| io::Error::other("missing original selection"))?;
    require(marks.len() <= 16)?;
    let mut references = BTreeSet::new();
    let mut selected = BTreeMap::new();
    for mark in marks {
        let reference = mark["reference"]
            .as_str()
            .ok_or_else(|| io::Error::other("missing reference"))?;
        require(references.insert(reference))?;
        if let Some(metadata) = mark.get("native_action") {
            const FIELDS: [&str; 16] = [
                "schema",
                "reference",
                "authorityId",
                "agentId",
                "contextId",
                "hostId",
                "nativeThread",
                "nativeTurn",
                "itemId",
                "scopeId",
                "materialId",
                "sourceRequestId",
                "deliveryId",
                "sha256",
                "payloadBytes",
                "pinSha256",
            ];
            require(
                metadata.as_object().is_some_and(|m| {
                    m.len() == FIELDS.len() && FIELDS.iter().all(|k| m.contains_key(*k))
                }) && metadata["schema"] == "lax-native-action-pin-metadata/v1",
            )?;
            for key in [
                "authorityId",
                "agentId",
                "contextId",
                "hostId",
                "materialId",
                "sourceRequestId",
                "deliveryId",
            ] {
                let value = metadata[key]
                    .as_str()
                    .ok_or_else(|| io::Error::other("missing original UUID"))?;
                require(uuid::Uuid::parse_str(value).is_ok_and(|id| id.to_string() == value))?;
            }
            for key in ["sha256", "pinSha256"] {
                let value = metadata[key]
                    .as_str()
                    .ok_or_else(|| io::Error::other("missing exact digest"))?;
                require(
                    value.len() == 64
                        && value
                            .bytes()
                            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)),
                )?;
            }
            for key in ["nativeTurn", "itemId", "scopeId"] {
                let value = metadata[key]
                    .as_str()
                    .ok_or_else(|| io::Error::other("missing original identity"))?;
                require(!value.is_empty() && value.len() <= 128 && !value.contains('/'))?;
            }
            require(
                reference.starts_with("exec:")
                    && reference.len() == 41
                    && uuid::Uuid::parse_str(&reference[5..]).is_ok()
                    && metadata["reference"] == reference
                    && metadata["contextId"] == request.context_id
                    && metadata["agentId"] == bundle.agent_id
                    && metadata["nativeThread"] == request.thread_id,
            )?;
            selected.insert(reference, metadata);
        }
    }
    require(selected.len() <= 8 && bundle.entries.len() == selected.len())?;
    let records = content["records"]
        .as_array()
        .ok_or_else(|| io::Error::other("missing original records"))?;
    let mut indexed = BTreeMap::new();
    for record in records {
        let reference = record["reference"]
            .as_str()
            .ok_or_else(|| io::Error::other("missing record reference"))?;
        require(indexed.insert(reference, record).is_none())?;
    }
    require(
        indexed
            .get("role")
            .is_some_and(|x| x.get("content").is_some() && x.get("access").is_none()),
    )?;
    let mandatory = content["nextMaterialIds"]
        .as_array()
        .ok_or_else(|| io::Error::other("missing next inputs"))?;
    for identity in mandatory {
        let id = identity
            .as_str()
            .ok_or_else(|| io::Error::other("invalid next input"))?;
        require(
            indexed
                .get(id)
                .is_some_and(|x| x.get("content").is_some() && x.get("access").is_none()),
        )?;
    }
    let mut previous = None;
    let mut raw_bytes = 0;
    for entry in &bundle.entries {
        let reference = match entry {
            Entry::Available(x) => &x.reference,
            Entry::Unavailable(x) => &x.reference,
        };
        require(previous.is_none_or(|s: &String| s < reference))?;
        previous = Some(reference);
        let metadata = selected
            .get(reference.as_str())
            .ok_or_else(|| io::Error::other("unselected native item"))?;
        let record = indexed
            .get(reference.as_str())
            .ok_or_else(|| io::Error::other("missing selected native record"))?;
        match entry {
            Entry::Unavailable(value) => {
                require(
                    value.access == "unavailable"
                        && matches!(
                            value.reason.as_str(),
                            "original_source_not_authorized" | "original_host_pin_missing"
                        ),
                )?;
            }
            Entry::Available(value) => {
                require(
                    value.metadata == **metadata
                        && record["content"]["nativeAction"] == value.metadata
                        && !value.payload.is_empty()
                        && value.payload.len() <= 32768
                        && value.payload.is_ascii()
                        && value.metadata["payloadBytes"].as_u64()
                            == Some(value.payload.len() as u64)
                        && value.metadata["sha256"] == hash(value.payload.as_bytes()),
                )?;
                let item: Value = serde_json::from_str(&value.payload)?;
                require(
                    item["id"] == value.metadata["itemId"]
                        && matches!(
                            item["type"].as_str(),
                            Some(
                                "commandExecution"
                                    | "fileChange"
                                    | "dynamicToolCall"
                                    | "mcpToolCall"
                            )
                        )
                        && matches!(
                            item["status"].as_str(),
                            Some("completed" | "failed" | "declined" | "cancelled" | "interrupted")
                        ),
                )?;
                raw_bytes += value.payload.len();
                require(raw_bytes <= 65536)?;
            }
        }
    }
    // Count the exact core-owned prefix together with the decoded canonical
    // snapshot, descriptor and evidence bundle. The host cannot budget or
    // supply this prefix. This remains pure preparation: no history/receipt
    // write, task admission, cancellation or provider request occurs here.
    let prefix_bytes = prefix.iter().try_fold(0usize, |bytes, item| {
        Ok::<_, io::Error>(bytes + serde_json::to_vec(&item.item)?.len())
    })?;
    require(canonical.len() + descriptor_bytes + data.len() + prefix_bytes <= 262144)?;
    let mut replacement = prefix.to_vec();
    replacement.extend(result);
    require(replacement.len() <= 256)?;
    for item in &replacement {
        require(serde_json::to_vec(&item.item)?.len() <= 32768)?;
    }
    let wire_items: Vec<_> = replacement.iter().map(|entry| &entry.item).collect();
    require(serde_json::to_vec(&wire_items)?.len() <= 1048576)?;
    Ok(replacement)
}

#[cfg(test)]
#[path = "context_retained_actions_tests.rs"]
mod tests;
