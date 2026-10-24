use super::LaxContextContract;
use codex_protocol::inference_completion::InferenceCompletionPolicy;
use pretty_assertions::assert_eq;

#[test]
fn model_owned_clients_keep_model_context_contract() {
    let contract = LaxContextContract::for_tools(InferenceCompletionPolicy::Model, |_| true);
    assert_eq!(contract.guidance, None);
    assert_eq!(contract.reminder, None);
    assert_eq!(contract.fallback, None);
}

#[test]
fn incomplete_material_interface_does_not_adopt_lax_contract() {
    let contract = LaxContextContract::for_tools(InferenceCompletionPolicy::HostTool, |name| {
        name != "context_material_read"
    });
    assert_eq!(contract.guidance, None);
}

#[test]
fn host_contract_mentions_only_exposed_context_tools() {
    let contract = LaxContextContract::for_tools(InferenceCompletionPolicy::HostTool, |name| {
        matches!(name, "context_read" | "context_material_read")
    });
    let guidance = contract.guidance.expect("installed material contract");
    assert!(guidance.contains("`context_material_read`"));
    for absent in [
        "`notes`",
        "`history`",
        "`get_context_remaining`",
        "`context_selection`",
        "`request_context_rebuild`",
        "`context_action_read`",
        "`context_writer_evidence_read`",
    ] {
        assert!(!guidance.contains(absent), "{absent}");
    }
    assert!(contract.reminder.is_some());
    assert!(contract.fallback.is_some());
}

#[test]
fn reader_and_writer_evidence_tools_are_distinct() {
    let reader = LaxContextContract::for_tools(InferenceCompletionPolicy::HostTool, |name| {
        matches!(
            name,
            "context_read" | "context_material_read" | "context_writer_evidence_read"
        )
    })
    .guidance
    .expect("reader material contract");
    assert!(reader.contains("`context_writer_evidence_read`"));
    assert!(!reader.contains("`context_action_read`"));
    let writer = LaxContextContract::for_tools(InferenceCompletionPolicy::HostTool, |name| {
        matches!(
            name,
            "context_read"
                | "context_material_read"
                | "context_action_read"
                | "request_context_rebuild"
        )
    })
    .guidance
    .expect("writer material contract");
    assert!(writer.contains("`context_action_read`"));
    assert!(writer.contains("`request_context_rebuild`"));
    assert!(!writer.contains("`context_writer_evidence_read`"));
}
