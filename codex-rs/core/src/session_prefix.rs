use codex_protocol::AgentPath;
use codex_protocol::protocol::AgentStatus;
#[cfg(test)]
use codex_protocol::protocol::HollywoodInputMessage;
use codex_utils_output_truncation::TruncationPolicy;
use codex_utils_output_truncation::truncate_text;

use crate::context::ContextualUserFragment;
use crate::context::InterAgentCompletionMessage;
use crate::context::SubagentNotification;

const COMPLETION_MESSAGE_MAX_TOKENS: usize = 1_000;
const COMPLETION_MESSAGE_ENVELOPE_TOKEN_RESERVE: usize = 100;
const ERROR_MAX_TOKENS: usize =
    COMPLETION_MESSAGE_MAX_TOKENS - COMPLETION_MESSAGE_ENVELOPE_TOKEN_RESERVE;
const ERROR_NEXT_ACTION: &str = "This agent's turn failed. If you still need this agent, use the available collaboration tools to give it another task.";

// Helpers for model-visible session state markers that are stored in user-role
// messages but are not user intent.

// TODO(jif) unify with structured schema
pub(crate) fn format_subagent_notification_message(
    agent_reference: &str,
    status: &AgentStatus,
) -> String {
    SubagentNotification::new(agent_reference, status.clone()).render()
}

pub(crate) fn format_inter_agent_completion_message(
    task_name: AgentPath,
    sender: AgentPath,
    status: &AgentStatus,
) -> Option<String> {
    let payload = match status {
        AgentStatus::Completed(Some(message)) => message.clone(),
        AgentStatus::Completed(None) => String::new(),
        AgentStatus::Errored(error) => {
            let error = truncate_text(error, TruncationPolicy::Tokens(ERROR_MAX_TOKENS));
            format!("Agent errored: {error}\n\n{ERROR_NEXT_ACTION}")
        }
        AgentStatus::Shutdown => "Agent shut down.".to_string(),
        AgentStatus::NotFound => "Agent was not found.".to_string(),
        AgentStatus::PendingInit | AgentStatus::Running | AgentStatus::Interrupted => return None,
    };
    Some(InterAgentCompletionMessage::new(task_name, sender, payload).render())
}

#[cfg(test)]
#[path = "session_prefix_tests.rs"]
mod tests;

pub(crate) fn format_subagent_context_line(
    agent_reference: &str,
    agent_nickname: Option<&str>,
) -> String {
    match agent_nickname.filter(|nickname| !nickname.is_empty()) {
        Some(agent_nickname) => format!("- {agent_reference}: {agent_nickname}"),
        None => format!("- {agent_reference}"),
    }
}

#[cfg(test)]
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
