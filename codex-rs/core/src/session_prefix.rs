use codex_protocol::models::ContentItem;
use codex_protocol::models::ResponseInputItem;
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

pub(crate) fn hollywood_response_input_items(
    message: &HollywoodInputMessage,
) -> Vec<ResponseInputItem> {
    let mut items = Vec::new();
    if let Some(instruction) = hollywood_obligation_instruction(message) {
        items.push(ResponseInputItem::Message {
            role: "developer".to_string(),
            content: vec![ContentItem::InputText { text: instruction }],
        });
    }
    if let Some(instruction) = hollywood_synthetic_brief_instruction(message) {
        items.push(ResponseInputItem::Message {
            role: "developer".to_string(),
            content: vec![ContentItem::InputText { text: instruction }],
        });
    }
    items.push(ResponseInputItem::Message {
        role: HollywoodMessage::ROLE.to_string(),
        content: vec![ContentItem::InputText {
            text: format_hollywood_message(message),
        }],
    });
    items
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

fn hollywood_synthetic_brief_instruction(message: &HollywoodInputMessage) -> Option<String> {
    let brief = message.synthetic_brief.as_ref()?;
    let mut lines = vec!["Hollywood synthetic coordination brief:".to_string()];

    if let Some(wake_reason) = brief.wake_reason.as_deref() {
        lines.push(format!("- wake reason: `{wake_reason}`"));
    }
    if let Some(semantic_kind) = brief.semantic_kind.as_deref() {
        lines.push(format!("- semantic kind: `{semantic_kind}`"));
    }
    if let Some(coordination_policy) = brief.coordination_policy.as_deref() {
        lines.push(format!("- coordination policy: `{coordination_policy}`"));
    }
    if let Some(coordination_phase) = brief.coordination_phase.as_deref() {
        lines.push(format!("- coordination phase: `{coordination_phase}`"));
    }
    if let Some(coordination_role) = brief.coordination_role.as_deref() {
        lines.push(format!("- your coordination role: `{coordination_role}`"));
    }
    if let Some(coordination_epoch) = brief.coordination_epoch {
        lines.push(format!("- policy epoch: `{coordination_epoch}`"));
    }
    if let Some(summary) = brief.summary.as_deref() {
        lines.push(format!("- summary: {summary}"));
    }
    for fact in &brief.facts {
        lines.push(format!("- fact: {fact}"));
    }
    if !brief.suggested_actions.is_empty() {
        lines.push("- valid next moves:".to_string());
        for action in &brief.suggested_actions {
            lines.push(format!("  - {action}"));
        }
    }
    if brief.stay_silent_if_no_actionable_delta {
        lines.push(
            "- if this brief does not materially change your owned work or create a real obligation, stay silent instead of sending a routine acknowledgment."
                .to_string(),
        );
    }

    Some(lines.join("\n"))
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

    #[test]
    fn synthetic_brief_instruction_mentions_wake_reason_and_silence_guidance() {
        let message = HollywoodInputMessage {
            message_id: 7,
            room: "repo/ozzz".to_string(),
            sender_id: "ray".to_string(),
            body: "Ray owns the browser lane; no clean lane for Duggs.".to_string(),
            mentions: vec![],
            attention: Some("broadcast".to_string()),
            message_kind: Some("broadcast".to_string()),
            obligation: Some("attention".to_string()),
            synthetic_brief: Some(codex_protocol::protocol::HollywoodSyntheticBrief {
                wake_reason: Some("semantic_delta".to_string()),
                semantic_kind: Some("scope_update".to_string()),
                coordination_policy: Some("dual_command_lease".to_string()),
                coordination_phase: Some("execution".to_string()),
                coordination_role: Some("executor".to_string()),
                coordination_epoch: Some(4),
                summary: Some(
                    "A peer ownership update may affect your available lane.".to_string(),
                ),
                facts: vec![
                    "message came from `ray` in `repo/ozzz`".to_string(),
                    "no exact unclaimed scope is visible yet".to_string(),
                ],
                suggested_actions: vec![
                    "check whether your owned scope changed".to_string(),
                    "stay silent if there is still no clean lane".to_string(),
                ],
                stay_silent_if_no_actionable_delta: true,
            }),
            requires_response: false,
        };

        let instruction =
            hollywood_synthetic_brief_instruction(&message).expect("instruction should exist");

        assert!(instruction.contains("Hollywood synthetic coordination brief"));
        assert!(instruction.contains("semantic_delta"));
        assert!(instruction.contains("scope_update"));
        assert!(instruction.contains("dual_command_lease"));
        assert!(instruction.contains("execution"));
        assert!(instruction.contains("executor"));
        assert!(instruction.contains("policy epoch"));
        assert!(instruction.contains("stay silent"));
    }
}
