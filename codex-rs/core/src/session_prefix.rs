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
        "body": message.body,
    })
    .to_string();
    HOLLYWOOD_MESSAGE_FRAGMENT.wrap(payload_json)
}
