use codex_protocol::protocol::HollywoodInputMessage;
use codex_protocol::protocol::HollywoodSyntheticBrief;
use codex_utils_output_truncation::approx_token_count;
use pretty_assertions::assert_eq;

use super::HollywoodMessage;
use crate::context::ContextualUserFragment;

#[test]
fn renders_compact_task_envelope_for_hollywood_obligation() {
    let message = HollywoodInputMessage {
        message_id: 42,
        room: "task/losangelex/fix-polling".to_string(),
        sender_id: "peer-agent".to_string(),
        body: "Please take the test slice.".to_string(),
        mentions: vec!["losangelex".to_string(), "room".to_string()],
        attention: Some("focused".to_string()),
        message_kind: Some("direct".to_string()),
        obligation: Some("obligation".to_string()),
        synthetic_brief: Some(HollywoodSyntheticBrief {
            wake_reason: Some("hollywood_message".to_string()),
            semantic_kind: Some("direct".to_string()),
            coordination_policy: Some("split_work".to_string()),
            coordination_phase: Some("execution".to_string()),
            coordination_role: Some("collaborator".to_string()),
            coordination_epoch: Some(7),
            summary: Some("Peer needs the test slice covered.".to_string()),
            facts: vec!["Tests are unclaimed.".to_string()],
            suggested_actions: vec!["Claim the test slice.".to_string()],
            stay_silent_if_no_actionable_delta: false,
        }),
        requires_response: true,
    };

    let rendered = HollywoodMessage::new(&message).render();

    assert_eq!(
        rendered,
        concat!(
            "<hollywood_message>\n",
            "Message Type: HOLLYWOOD_OBLIGATION\n",
            "Coordination path: hollywood:task/losangelex/fix-polling#42\n",
            "Room: task/losangelex/fix-polling\n",
            "Message id: 42\n",
            "Sender: peer-agent\n",
            "Kind: direct\n",
            "Attention: focused\n",
            "Response required: yes\n",
            "Mentions: losangelex, room\n",
            "Wake reason: hollywood_message\n",
            "Semantic kind: direct\n",
            "Coordination policy: split_work\n",
            "Coordination phase: execution\n",
            "Coordination role: collaborator\n",
            "Coordination epoch: 7\n",
            "Summary:\n",
            "Peer needs the test slice covered.\n",
            "Facts:\n",
            "- Tests are unclaimed.\n",
            "Suggested actions:\n",
            "- Claim the test slice.\n",
            "Payload:\n",
            "Please take the test slice.\n",
            "</hollywood_message>",
        )
    );
}

#[test]
fn skips_duplicate_summary_for_app_server_brief() {
    let message = HollywoodInputMessage {
        message_id: 9,
        room: "repo/losangelex".to_string(),
        sender_id: "peer-agent".to_string(),
        body: "Status update only.".to_string(),
        mentions: Vec::new(),
        attention: Some("broad".to_string()),
        message_kind: Some("broadcast".to_string()),
        obligation: Some("attention".to_string()),
        synthetic_brief: Some(HollywoodSyntheticBrief {
            wake_reason: Some("hollywood_message".to_string()),
            semantic_kind: Some("broadcast".to_string()),
            coordination_policy: None,
            coordination_phase: None,
            coordination_role: None,
            coordination_epoch: None,
            summary: Some("Status update only.".to_string()),
            facts: Vec::new(),
            suggested_actions: Vec::new(),
            stay_silent_if_no_actionable_delta: true,
        }),
        requires_response: false,
    };

    let rendered = HollywoodMessage::new(&message).render();

    assert!(rendered.contains("Message Type: HOLLYWOOD_ATTENTION"));
    assert!(rendered.contains("Response required: no"));
    assert!(rendered.contains("Stay silent if no actionable delta: yes"));
    assert!(!rendered.contains("Summary:\nStatus update only."));
    assert!(!rendered.contains("synthetic_brief"));
}

#[test]
fn truncates_unbounded_payload_sections() {
    let long_text = "coordinate this ".repeat(2_000);
    let message = HollywoodInputMessage {
        message_id: 100,
        room: "repo/losangelex".to_string(),
        sender_id: "peer-agent".to_string(),
        body: long_text.clone(),
        mentions: Vec::new(),
        attention: Some("focused".to_string()),
        message_kind: Some("direct".to_string()),
        obligation: Some("obligation".to_string()),
        synthetic_brief: Some(HollywoodSyntheticBrief {
            wake_reason: Some("hollywood_message".to_string()),
            semantic_kind: Some("direct".to_string()),
            coordination_policy: Some("dual_command_lease".to_string()),
            coordination_phase: Some("execution".to_string()),
            coordination_role: Some("collaborator".to_string()),
            coordination_epoch: Some(2),
            summary: Some("distinct summary ".repeat(1_000)),
            facts: vec![long_text.clone(); 8],
            suggested_actions: vec![long_text; 8],
            stay_silent_if_no_actionable_delta: false,
        }),
        requires_response: true,
    };

    let rendered = HollywoodMessage::new(&message).render();

    assert!(approx_token_count(&rendered) < 1_000);
    assert!(rendered.contains("- ...4 more"));
}
