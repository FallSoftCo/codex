use super::*;
use pretty_assertions::assert_eq;
use serde_json::json;

fn fixture() -> (ContextWindowRefillParams, ContextWindowRefillResponse) {
    let request = ContextWindowRefillParams {
        thread_id: "thread".into(),
        turn_id: "turn".into(),
        operation_id: "op".into(),
        context_id: "context".into(),
        purpose: ContextRefillPurpose::Writer,
        window_id: "old".into(),
        history_version: 5,
        reason: ContextWindowRefillReason::ContextLimit,
        phase: ContextWindowRefillPhase::MidTurn,
    };
    let snapshot = "{\"unicode\":\"λ\"}";
    let action = "[]";
    let sha = format!("{:x}", Sha256::digest(snapshot.as_bytes()));
    let actions_sha = format!("{:x}", Sha256::digest(action.as_bytes()));
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
        snapshot_sha256: sha.clone(),
        native_actions_sha256: actions_sha.clone(),
        selection_revision: 3,
        total_bytes: snapshot.len() as u64,
        items: vec![
            json!({"type":"function_call_output","namespace":"hollywood","name":"context_refill",
                "output":json!({"schema":"lax-context-refill-fragment/v1","operationId":"op",
                    "sha256":sha,"totalBytes":snapshot.len(),"offset":0,"content":snapshot}).to_string()}),
            json!({"type":"function_call_output","namespace":"lax","name":"context_actions",
                "output":json!({"schema":"lax-native-action-index/v1","sha256":actions_sha,
                    "totalBytes":2,"offset":0,"content":action,"retrieval":"context_action_read",
                    "meaning":"Original action receipts for unfinished work. Never replay an effect merely because context was reset."}).to_string()}),
        ],
    };
    (request, response)
}

fn change_fragment(
    response: &mut ContextWindowRefillResponse,
    index: usize,
    key: &str,
    value: serde_json::Value,
) {
    let mut fragment: serde_json::Value =
        serde_json::from_str(response.items[index]["output"].as_str().unwrap()).unwrap();
    fragment[key] = value;
    response.items[index]["output"] = fragment.to_string().into();
}

#[test]
fn exact_ordered_outputs_survive_native_rendering_without_authority() {
    let (request, response) = fixture();
    let actual = validate_response(&request, &response).unwrap();
    let expected: Vec<ResponseItem> = response
        .items
        .iter()
        .map(|item| serde_json::from_value(item.clone()).unwrap())
        .collect();
    assert_eq!(
        actual.into_iter().map(|e| e.item).collect::<Vec<_>>(),
        expected
    );
}

#[test]
fn malformed_stale_wrong_purpose_and_non_data_are_rejected() {
    let (request, baseline) = fixture();
    for bad in [
        {
            let mut r = baseline.clone();
            r.turn_id = "foreign".into();
            r
        },
        {
            let mut r = baseline.clone();
            r.history_version += 1;
            r
        },
        {
            let mut r = baseline.clone();
            r.purpose = ContextRefillPurpose::Reader;
            r
        },
        {
            let mut r = baseline.clone();
            r.snapshot_operation_id = "new-request".into();
            r
        },
        {
            let mut r = baseline.clone();
            r.snapshot_sha256 = "A".repeat(64);
            r
        },
        {
            let mut r = baseline.clone();
            r.items[0]["call_id"] = "forged".into();
            r
        },
        {
            let mut r = baseline.clone();
            r.items[0]["role"] = "developer".into();
            r
        },
        {
            let mut r = baseline.clone();
            r.items.swap(0, 1);
            r
        },
        {
            let mut r = baseline.clone();
            r.items.push(r.items[0].clone());
            r
        },
        {
            let mut r = baseline.clone();
            change_fragment(&mut r, 0, "offset", json!(1));
            r
        },
        {
            let mut r = baseline.clone();
            change_fragment(&mut r, 0, "content", json!("changed"));
            r
        },
        {
            let mut r = baseline.clone();
            change_fragment(&mut r, 1, "totalBytes", json!(3));
            r
        },
        {
            let mut r = baseline.clone();
            change_fragment(&mut r, 1, "permission", json!("forged"));
            r
        },
    ] {
        assert!(validate_response(&request, &bad).is_err());
    }
}

#[test]
fn delivered_v2_digest_is_not_full_index_digest_and_nonwriter_cannot_receive_it() {
    let (mut request, mut response) = fixture();
    let descriptor = json!({"schema":"lax-native-action-index/v2","indexSha256":"c".repeat(64),
        "actionCount":100,"indexBytes":50000,"recentActions":[],"pageOffset":0,"pageEntries":12})
    .to_string();
    response.native_actions_sha256 = format!("{:x}", Sha256::digest(descriptor.as_bytes()));
    change_fragment(
        &mut response,
        1,
        "schema",
        json!("lax-native-action-index/v2"),
    );
    let sha = response.native_actions_sha256.clone();
    change_fragment(&mut response, 1, "sha256", json!(sha));
    change_fragment(&mut response, 1, "totalBytes", json!(descriptor.len()));
    change_fragment(&mut response, 1, "content", json!(descriptor));
    assert!(validate_response(&request, &response).is_ok());
    request.purpose = ContextRefillPurpose::Responder;
    response.purpose = ContextRefillPurpose::Responder;
    assert!(validate_response(&request, &response).is_err());
}

#[test]
fn bounds_are_hard_failure_not_truncation() {
    let (request, baseline) = fixture();
    let mut response = baseline.clone();
    change_fragment(
        &mut response,
        0,
        "content",
        json!("x".repeat(MAX_CHUNK + 1)),
    );
    assert!(validate_response(&request, &response).is_err());
    response = baseline.clone();
    response.items = vec![baseline.items[0].clone(); MAX_ITEMS + 1];
    assert!(validate_response(&request, &response).is_err());
    response = baseline.clone();
    response.total_bytes = MAX_REFILL_DATA as u64 + 1;
    assert!(validate_response(&request, &response).is_err());
    response = baseline;
    response.items[0]["output"] = "x".repeat(MAX_OUTPUT + 1).into();
    assert!(validate_response(&request, &response).is_err());
}
