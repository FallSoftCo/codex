use codex_protocol::AgentPath;
use codex_protocol::protocol::AgentStatus;
use codex_protocol::protocol::HollywoodInputMessage;
use codex_utils_output_truncation::approx_token_count;

use super::COMPLETION_MESSAGE_MAX_TOKENS;
use super::ERROR_NEXT_ACTION;
use super::format_inter_agent_completion_message;
use super::hollywood_obligation_instruction;

#[test]
fn error_completion_message_stays_below_manual_review_threshold() {
    let message = format_inter_agent_completion_message(
        AgentPath::root(),
        AgentPath::try_from("/root/worker").expect("valid agent path"),
        &AgentStatus::Errored("stream disconnected ".repeat(1_000)),
    )
    .expect("error status should produce a completion message");

    assert!(approx_token_count(&message) < COMPLETION_MESSAGE_MAX_TOKENS);
    assert!(message.contains(ERROR_NEXT_ACTION));
}

#[test]
fn obligation_instruction_generated_for_actionable_hollywood_message() {
    let message = HollywoodInputMessage {
        message_id: 1,
        room: "main".to_string(),
        sender_id: "peer".to_string(),
        body: "claim this".to_string(),
        mentions: vec![],
        attention: Some("focused".to_string()),
        message_kind: Some("direct".to_string()),
        obligation: Some("obligation".to_string()),
        synthetic_brief: None,
        requires_response: true,
    };

    let instruction = hollywood_obligation_instruction(&message).expect("instruction should exist");

    assert!(instruction.contains("Hollywood coordination obligation"));
    assert!(instruction.contains("direct"));
    assert!(instruction.contains("peer"));
}

#[test]
fn attention_instruction_discourages_routine_acknowledgments() {
    let message = HollywoodInputMessage {
        message_id: 2,
        room: "main".to_string(),
        sender_id: "peer".to_string(),
        body: "ack".to_string(),
        mentions: vec![],
        attention: Some("focused".to_string()),
        message_kind: Some("direct".to_string()),
        obligation: Some("attention".to_string()),
        synthetic_brief: None,
        requires_response: false,
    };

    let instruction = hollywood_obligation_instruction(&message).expect("instruction should exist");

    assert!(instruction.contains("Keep it internal"));
    assert!(instruction.contains("do not send a routine acknowledgment"));
}

#[test]
fn hollywood_system_attention_stays_internal() {
    let message = HollywoodInputMessage {
        message_id: 0,
        room: "main".to_string(),
        sender_id: "hollywood-system".to_string(),
        body: "Autonomous Hollywood follow-up".to_string(),
        mentions: vec![],
        attention: Some("focused".to_string()),
        message_kind: Some("direct".to_string()),
        obligation: Some("attention".to_string()),
        synthetic_brief: None,
        requires_response: false,
    };

    let instruction = hollywood_obligation_instruction(&message).expect("instruction should exist");

    assert!(instruction.contains("Keep it internal"));
    assert!(instruction.contains("runtime coordination context"));
}
