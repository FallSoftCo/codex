use codex_protocol::protocol::AgentStatus;
use codex_protocol::protocol::HollywoodInputMessage;

use crate::context::ContextualUserFragment;
use crate::context::HollywoodMessage;
use crate::context::SubagentNotification;

// Helpers for model-visible session state markers that are injected as
// contextual messages rather than user task input.

// TODO(jif) unify with structured schema
pub(crate) fn format_subagent_notification_message(
    agent_reference: &str,
    status: &AgentStatus,
) -> String {
    SubagentNotification::new(agent_reference, status.clone()).render()
}

pub(crate) fn format_subagent_context_line(
    agent_reference: &str,
    agent_nickname: Option<&str>,
) -> String {
    match agent_nickname.filter(|nickname| !nickname.is_empty()) {
        Some(agent_nickname) => format!("- {agent_reference}: {agent_nickname}"),
        None => format!("- {agent_reference}"),
    }
}

pub(crate) fn format_hollywood_message(message: &HollywoodInputMessage) -> String {
    HollywoodMessage::new(message).render()
}

pub(crate) fn hollywood_obligation_instruction(message: &HollywoodInputMessage) -> Option<String> {
    if message.sender_id == "hollywood-system" {
        return match message.obligation.as_deref() {
            Some("attention") => Some(
                "Internal Hollywood runtime coordination context was attached to this turn. Keep it internal unless it materially changes the task or requires a concrete coordination action."
                    .to_string(),
            ),
            _ => None,
        };
    }

    match message.obligation.as_deref() {
        Some("obligation") => Some(format!(
            "Hollywood coordination obligation: a {} message in room `{}` from `{}` needs explicit analysis and, if relevant, a concrete response, claim, join, handoff, or action. Do not silently ignore it.",
            message.message_kind.as_deref().unwrap_or("contextual"),
            message.room,
            message.sender_id,
        )),
        Some("attention") => Some(format!(
            "Hollywood attention update: inspect the attached Hollywood message from `{}` in room `{}`. Keep it internal unless it materially changes your work or requires a concrete coordination action; do not send a routine acknowledgment by default.",
            message.sender_id, message.room,
        )),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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

        let instruction =
            hollywood_obligation_instruction(&message).expect("instruction should exist");

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

        let instruction =
            hollywood_obligation_instruction(&message).expect("instruction should exist");

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

        let instruction =
            hollywood_obligation_instruction(&message).expect("instruction should exist");

        assert!(instruction.contains("Keep it internal"));
        assert!(instruction.contains("runtime coordination context"));
    }
}
