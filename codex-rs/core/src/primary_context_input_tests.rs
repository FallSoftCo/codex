use super::*;
use codex_protocol::context_input::ContextInputParams;
use codex_protocol::context_input::ContextInputResponse;
use codex_protocol::context_refill::ContextRefillPurpose;
use codex_protocol::models::FunctionCallOutputBody;
use serde_json::json;

fn fixture() -> (ContextInputParams, ContextInputResponse) {
    let request = ContextInputParams {
        thread_id: "thread".into(),
        turn_id: "turn".into(),
        operation_id: "operation".into(),
        context_id: "context".into(),
        purpose: ContextRefillPurpose::Writer,
        material_ids: vec!["work".into()],
    };
    let admission = "context-begin:turn";
    let mut fragments = Vec::new();
    for (reference, content) in [
        ("role", json!({"role":"writer"}).to_string()),
        ("work", json!({"value":"x".repeat(7000)}).to_string()),
    ] {
        let digest = format!("{:x}", Sha256::digest(content.as_bytes()));
        for (n, chunk) in content.as_bytes().chunks(3072).enumerate() {
            fragments.push(
                json!({"schema":"lax-context-material-fragment/v1",
                "operationId":admission,"reference":reference,"revision":2,"sha256":digest,
                "totalBytes":content.len(),"offset":n*3072,
                "content":std::str::from_utf8(chunk).unwrap()})
                .to_string(),
            );
        }
    }
    let response = ContextInputResponse {
        thread_id: request.thread_id.clone(),
        turn_id: request.turn_id.clone(),
        operation_id: request.operation_id.clone(),
        context_id: request.context_id.clone(),
        purpose: request.purpose.clone(),
        material_ids: request.material_ids.clone(),
        admission_operation_id: admission.into(),
        fragments,
    };
    (request, response)
}

#[test]
fn complete_multi_fragment_packet_is_recorded_exactly() {
    let (request, response) = fixture();
    let items = validate(&request, &response).unwrap();
    assert_eq!(items.len(), response.fragments.len());
    let values: Vec<_> = items
        .into_iter()
        .map(|i| match i.item {
            ResponseItem::FunctionCallOutput {
                namespace,
                name,
                output,
                ..
            } => {
                assert_eq!(namespace.as_deref(), Some("hollywood"));
                assert_eq!(name.as_deref(), Some("context_material"));
                let FunctionCallOutputBody::Text(t) = output.body else {
                    panic!("text data required")
                };
                t
            }
            _ => panic!("not data"),
        })
        .collect();
    assert_eq!(values, response.fragments);
}

#[test]
fn partial_reordered_or_changed_cut_is_not_accepted() {
    let (request, response) = fixture();
    let mut partial = response.clone();
    partial.fragments.pop();
    assert!(validate(&request, &partial).is_err());
    let mut reordered = response.clone();
    reordered.fragments.swap(1, 2);
    assert!(validate(&request, &reordered).is_err());
    let mut changed = response;
    changed.context_id = "other".into();
    assert!(validate(&request, &changed).is_err());
}
