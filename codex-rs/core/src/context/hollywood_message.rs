use codex_protocol::protocol::HollywoodInputMessage;
use codex_protocol::protocol::HollywoodSyntheticBrief;

use super::ContextualUserFragment;

#[derive(Debug, Clone, PartialEq)]
pub(crate) struct HollywoodMessage {
    pub(crate) message_id: i64,
    pub(crate) room: String,
    pub(crate) sender_id: String,
    pub(crate) mentions: Vec<String>,
    pub(crate) body: String,
    pub(crate) attention: Option<String>,
    pub(crate) message_kind: Option<String>,
    pub(crate) obligation: Option<String>,
    pub(crate) synthetic_brief: Option<HollywoodSyntheticBrief>,
    pub(crate) requires_response: bool,
}

impl HollywoodMessage {
    pub(crate) const ROLE: &'static str = "developer";
    const START_MARKER: &'static str = "<hollywood_message>";
    const END_MARKER: &'static str = "</hollywood_message>";

    pub(crate) fn new(message: &HollywoodInputMessage) -> Self {
        Self {
            message_id: message.message_id,
            room: message.room.clone(),
            sender_id: message.sender_id.clone(),
            mentions: message.mentions.clone(),
            body: message.body.clone(),
            attention: message.attention.clone(),
            message_kind: message.message_kind.clone(),
            obligation: message.obligation.clone(),
            synthetic_brief: message.synthetic_brief.clone(),
            requires_response: message.requires_response,
        }
    }

    fn instruction(&self) -> Option<String> {
        if self.sender_id == "hollywood-system" {
            return match self.obligation.as_deref() {
                Some("attention") => Some(
                    "Internal Hollywood runtime coordination context was attached to this turn. Keep it internal unless it materially changes the task or requires a concrete coordination action."
                        .to_string(),
                ),
                _ => None,
            };
        }

        match self.obligation.as_deref() {
            Some("obligation") => Some(format!(
                "Hollywood coordination obligation: a {} message in room `{}` from `{}` needs explicit analysis and, if relevant, a concrete response, claim, join, handoff, or action. Do not silently ignore it.",
                self.message_kind.as_deref().unwrap_or("contextual"),
                self.room,
                self.sender_id,
            )),
            Some("attention") => Some(format!(
                "Hollywood attention update: inspect the attached Hollywood message from `{}` in room `{}`. Keep it internal unless it materially changes your work or requires a concrete coordination action; do not send a routine acknowledgment by default.",
                self.sender_id, self.room,
            )),
            _ => None,
        }
    }
}

impl ContextualUserFragment for HollywoodMessage {
    fn role(&self) -> &'static str {
        Self::ROLE
    }

    fn markers(&self) -> (&'static str, &'static str) {
        (Self::START_MARKER, Self::END_MARKER)
    }

    fn type_markers() -> (&'static str, &'static str) {
        (Self::START_MARKER, Self::END_MARKER)
    }

    fn body(&self) -> String {
        format!(
            "\n{}",
            serde_json::json!({
                "instruction": self.instruction(),
                "message_id": self.message_id,
                "room": self.room,
                "sender_id": self.sender_id,
                "mentions": self.mentions,
                "body": self.body,
                "attention": self.attention,
                "message_kind": self.message_kind,
                "obligation": self.obligation,
                "synthetic_brief": self.synthetic_brief,
                "requires_response": self.requires_response,
            })
        )
    }
}
