use codex_protocol::protocol::AgentStatus;
use codex_protocol::protocol::HollywoodInputMessage;

/// Helpers for model-visible session state markers that are stored in user-role
/// messages but are not user intent.
use crate::contextual_user_message::HOLLYWOOD_MESSAGE_FRAGMENT;
use crate::contextual_user_message::SUBAGENT_NOTIFICATION_FRAGMENT;

// TODO(jif) unify with structured schema
pub(crate) fn format_subagent_notification_message(
    agent_reference: &str,
    status: &AgentStatus,
) -> String {
    let payload_json = serde_json::json!({
        "agent_path": agent_reference,
        "status": status,
    })
    .to_string();
    SUBAGENT_NOTIFICATION_FRAGMENT.wrap(payload_json)
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
    let payload_json = serde_json::json!({
        "message_id": message.message_id,
        "room": message.room,
        "sender_id": message.sender_id,
        "mentions": message.mentions,
        "attention": message.attention,
        "message_kind": message.message_kind,
        "obligation": message.obligation,
        "requires_response": message.requires_response,
        "body": message.body,
    })
    .to_string();
    HOLLYWOOD_MESSAGE_FRAGMENT.wrap(payload_json)
}

pub(crate) fn hollywood_obligation_instruction(message: &HollywoodInputMessage) -> Option<String> {
    if message.sender_id == "hollywood-system" {
        return None;
    }

    match message.obligation.as_deref() {
        Some("obligation") => Some(format!(
            "Hollywood coordination obligation: a {} message in room `{}` from `{}` needs explicit analysis and, if relevant, a concrete response, claim, join, handoff, or action. Do not silently ignore it.",
            message.message_kind.as_deref().unwrap_or("contextual"),
            message.room,
            message.sender_id,
        )),
        Some("attention") => Some(format!(
            "Hollywood attention update: inspect the attached Hollywood message from `{}` in room `{}` and decide whether it changes your current work or requires a concise follow-up.",
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
            requires_response: true,
        };

        let instruction =
            hollywood_obligation_instruction(&message).expect("instruction should exist");

        assert!(instruction.contains("Hollywood coordination obligation"));
        assert!(instruction.contains("direct"));
        assert!(instruction.contains("peer"));
    }
}
