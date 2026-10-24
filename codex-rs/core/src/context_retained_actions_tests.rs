//! Mechanical native packet checks. No provider/model outcome is claimed.
use super::*;
use pretty_assertions::assert_eq;
use serde_json::json;

fn fixture(payload_bytes: usize) -> (ContextWindowRefillParams, ContextWindowRefillResponse) {
    let context = "11111111-1111-4111-8111-111111111111";
    let agent = "22222222-2222-4222-8222-222222222222";
    let reference = "exec:33333333-3333-4333-8333-333333333333";
    let mut item = json!({"type":"commandExecution","id":"exec-original","status":"completed","aggregatedOutput":""});
    let overhead = item.to_string().len();
    item["aggregatedOutput"] = Value::String("x".repeat(payload_bytes - overhead));
    let payload = item.to_string();
    assert_eq!(payload.len(), payload_bytes);
    let metadata = json!({"schema":"lax-native-action-pin-metadata/v1","reference":reference,
        "authorityId":agent,"agentId":agent,"contextId":context,"hostId":agent,
        "nativeThread":"thread","nativeTurn":"original-turn","itemId":"exec-original","scopeId":"original-scope",
        "materialId":agent,"sourceRequestId":agent,"deliveryId":agent,
        "sha256":hash(payload.as_bytes()),"payloadBytes":payload.len(),"pinSha256":"a".repeat(64)});
    let content = json!({"schema":"lax-context-rebuild/v1","agentId":agent,"contextId":context,
        "purpose":"writer","nativeThread":"thread","selection":{"selectionRevision":3,
            "marks":[{"reference":reference,"native_action":metadata}]},
        "nextMaterialIds":["work"],"records":[{"reference":"role","content":{"role":"writer"}},
            {"reference":"work","content":{"objective":"original accepted objective"}},
            {"reference":reference,"content":{"nativeAction":metadata}}]});
    let encoded = content.to_string();
    let snapshot_sha = hash(encoded.as_bytes());
    let bundle = json!({"schema":"lax-retained-native-actions/v1","agentId":agent,
        "contextId":context,"purpose":"writer","nativeThread":"thread","selectionRevision":3,
        "canonicalSnapshotSha256":snapshot_sha,
        "entries":[{"reference":reference,"metadata":metadata,"payload":payload}]})
    .to_string();
    let request = ContextWindowRefillParams {
        thread_id: "thread".into(),
        turn_id: "turn".into(),
        operation_id: "op".into(),
        context_id: context.into(),
        purpose: ContextRefillPurpose::Writer,
        window_id: "old".into(),
        history_version: 5,
        reason: ContextWindowRefillReason::ContextLimit,
        phase: ContextWindowRefillPhase::MidTurn,
    };
    let mut items = Vec::new();
    for (offset, chunk) in encoded.as_bytes().chunks(3072).enumerate() {
        items.push(
            json!({"type":"function_call_output","namespace":"hollywood","name":"context_refill",
            "output":json!({"schema":"lax-context-refill-fragment/v1","operationId":"op",
                "sha256":snapshot_sha,"totalBytes":encoded.len(),"offset":offset*3072,
                "content":std::str::from_utf8(chunk).unwrap()}).to_string()}),
        );
    }
    items.push(json!({"type":"function_call_output","namespace":"lax","name":"context_actions",
        "output":json!({"schema":"lax-native-action-index/v1","sha256":hash(b"[]"),"offset":0,
            "totalBytes":2,"content":"[]","retrieval":"context_action_read",
            "meaning":"Original action receipts for unfinished work. Never replay an effect merely because context was reset."}).to_string()}));
    for (offset, chunk) in bundle.as_bytes().chunks(3072).enumerate() {
        items.push(
            json!({"type":"function_call_output","namespace":"lax","name":"retained_actions",
            "output":json!({"schema":"lax-retained-native-actions-fragment/v1",
                "sha256":hash(bundle.as_bytes()),"totalBytes":bundle.len(),"offset":offset*3072,
                "content":std::str::from_utf8(chunk).unwrap()}).to_string()}),
        );
    }
    let response = ContextWindowRefillResponse {
        thread_id: request.thread_id.clone(),
        turn_id: request.turn_id.clone(),
        operation_id: request.operation_id.clone(),
        context_id: request.context_id.clone(),
        purpose: request.purpose.clone(),
        window_id: request.window_id.clone(),
        history_version: request.history_version,
        snapshot_operation_id: request.operation_id.clone(),
        snapshot_read_point: "cut".into(),
        snapshot_sha256: snapshot_sha,
        native_actions_sha256: hash(b"[]"),
        selection_revision: 3,
        total_bytes: encoded.len() as u64,
        items,
    };
    (request, response)
}

#[test]
fn complete_native_items_are_data_and_legacy_cannot_silently_accept_them() {
    let (request, response) = fixture(512);
    let actual = validate(&request, &response, &[]).unwrap();
    let expected: Vec<ResponseItem> = response
        .items
        .iter()
        .map(|x| serde_json::from_value(x.clone()).unwrap())
        .collect();
    assert_eq!(
        actual.into_iter().map(|x| x.item).collect::<Vec<_>>(),
        expected
    );
    assert!(crate::context_refill::validate_response(&request, &response).is_err());
}

#[test]
fn whole_item_exact_limit_passes_and_limit_plus_one_refuses() {
    let (request, response) = fixture(32768);
    assert!(validate(&request, &response, &[]).is_ok());
    let (request, response) = fixture(32769);
    assert!(validate(&request, &response, &[]).is_err());
}

#[test]
fn incomplete_reordered_changed_and_wrong_purpose_packets_are_rejected() {
    let (request, response) = fixture(8192);
    assert!(validate(&request, &response, &[]).is_ok());
    let mut broken = response.clone();
    broken.items.pop();
    assert!(validate(&request, &broken, &[]).is_err());
    let mut broken = response.clone();
    let index = broken
        .items
        .iter()
        .position(|x| x["name"] == "retained_actions")
        .unwrap();
    broken.items.swap(index, index + 1);
    assert!(validate(&request, &broken, &[]).is_err());
    let mut broken = response.clone();
    let mut f: Value =
        serde_json::from_str(broken.items[index]["output"].as_str().unwrap()).unwrap();
    f["content"] = Value::String("tampered".into());
    broken.items[index]["output"] = f.to_string().into();
    assert!(validate(&request, &broken, &[]).is_err());
    let mut wrong = request;
    wrong.purpose = ContextRefillPurpose::Reader;
    assert!(validate(&wrong, &response, &[]).is_err());
}

#[test]
fn missing_current_role_and_cross_context_metadata_are_rejected_even_with_fresh_outer_hashes() {
    let (request, mut response) = fixture(512);
    // Rebuild only the canonical section/hash; retained bundle keeps the old cut.
    let first = response
        .items
        .iter()
        .position(|x| x["name"] == "retained_actions")
        .unwrap();
    let mut f: Value = serde_json::from_str(response.items[0]["output"].as_str().unwrap()).unwrap();
    let mut cut: Value = serde_json::from_str(f["content"].as_str().unwrap()).unwrap();
    cut["records"]
        .as_array_mut()
        .unwrap()
        .retain(|x| x["reference"] != "role");
    let encoded = cut.to_string();
    let sha = hash(encoded.as_bytes());
    f["content"] = encoded.clone().into();
    f["sha256"] = sha.clone().into();
    f["totalBytes"] = encoded.len().into();
    response.snapshot_sha256 = sha;
    response.total_bytes = encoded.len() as u64;
    response.items[0]["output"] = f.to_string().into();
    // Keep the outer bundle/cut hashes valid so this tests mandatory role
    // validation, rather than merely a stale checksum.
    let original: String = response.items[first..]
        .iter()
        .map(|x| {
            let f: Value = serde_json::from_str(x["output"].as_str().unwrap()).unwrap();
            f["content"].as_str().unwrap().to_string()
        })
        .collect();
    let mut bundle: Value = serde_json::from_str(&original).unwrap();
    bundle["canonicalSnapshotSha256"] = response.snapshot_sha256.clone().into();
    let encoded = bundle.to_string();
    response.items.truncate(first);
    for (offset, chunk) in encoded.as_bytes().chunks(3072).enumerate() {
        response.items.push(
            json!({"type":"function_call_output","namespace":"lax","name":"retained_actions",
            "output":json!({"schema":"lax-retained-native-actions-fragment/v1",
                "sha256":hash(encoded.as_bytes()),"totalBytes":encoded.len(),"offset":offset*3072,
                "content":std::str::from_utf8(chunk).unwrap()}).to_string()}),
        );
    }
    assert!(validate(&request, &response, &[]).is_err());
    // Native validates the original context binding independently of item hashes.
    let (mut wrong, response) = fixture(512);
    wrong.context_id = "44444444-4444-4444-8444-444444444444".into();
    assert!(validate(&wrong, &response, &[]).is_err());
    assert!(first > 0);
}

fn prefix_item(serialized_bytes: usize) -> ResponseItemEnvelope {
    let mut value = json!({"type":"message","role":"developer",
        "content":[{"type":"input_text","text":""}]});
    let empty: ResponseItem = serde_json::from_value(value.clone()).unwrap();
    let overhead = serde_json::to_vec(&empty).unwrap().len();
    value["content"][0]["text"] = "x".repeat(serialized_bytes - overhead).into();
    let item: ResponseItem = serde_json::from_value(value).unwrap();
    assert_eq!(serde_json::to_vec(&item).unwrap().len(), serialized_bytes);
    ResponseItemEnvelope::new(item)
}

#[test]
fn core_prefix_is_preserved_and_counts_toward_each_item_limit() {
    let (request, response) = fixture(512);
    let exact = prefix_item(/*serialized_bytes*/ 32768);
    let actual = validate(&request, &response, std::slice::from_ref(&exact)).unwrap();
    assert_eq!(actual[0], exact);
    assert_eq!(actual.len(), response.items.len() + 1);
    let oversized = prefix_item(/*serialized_bytes*/ 32769);
    assert!(validate(&request, &response, &[oversized]).is_err());
}

#[test]
fn core_prefix_and_retained_fragments_share_the_total_item_limit() {
    let (request, response) = fixture(512);
    let item = prefix_item(/*serialized_bytes*/ 128);
    let mut prefix = vec![item.clone(); 256 - response.items.len()];
    let exact = validate(&request, &response, &prefix).unwrap();
    assert_eq!(exact.len(), 256);
    assert_eq!(&exact[..prefix.len()], prefix.as_slice());
    prefix.push(item);
    assert!(validate(&request, &response, &prefix).is_err());
}

#[test]
fn core_prefix_consumes_the_same_decoded_budget_as_selected_evidence() {
    let (request, response) = fixture(512);
    let data_bytes: usize = response
        .items
        .iter()
        .map(|item| {
            let fragment: Value = serde_json::from_str(item["output"].as_str().unwrap()).unwrap();
            fragment["content"].as_str().unwrap().len()
        })
        .sum();
    let prefix_bytes = 262144 - data_bytes;
    let mut prefix = Vec::new();
    let mut remaining = prefix_bytes;
    while remaining > 32768 {
        prefix.push(prefix_item(/*serialized_bytes*/ 32768));
        remaining -= 32768;
    }
    prefix.push(prefix_item(remaining));
    let exact = validate(&request, &response, &prefix).unwrap();
    assert_eq!(&exact[..prefix.len()], prefix.as_slice());
    *prefix.last_mut().unwrap() = prefix_item(remaining + 1);
    assert!(validate(&request, &response, &prefix).is_err());
}

#[test]
fn native_tool_prefix_and_retained_data_keep_distinct_item_bounds() {
    let tools: ResponseItem = serde_json::from_str(include_str!(
        "../assets/lax-native-tools-retention-r320.json"
    ))
    .unwrap();
    let prefix = vec![ResponseItemEnvelope::new(tools.clone())];
    let (request, response) = fixture(32768);
    let replacement = validate(&request, &response, &prefix).unwrap();
    assert_eq!(replacement[0].item, tools);
    let (request, oversized_data) = fixture(32769);
    assert!(validate(&request, &oversized_data, &prefix).is_err());
}
