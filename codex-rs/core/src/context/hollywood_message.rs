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
    pub(crate) synthetic_brief: Option<HollywoodSyntheticBrief>,
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
            synthetic_brief: message.synthetic_brief.clone(),
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
                "message_id": self.message_id,
                "room": self.room,
                "sender_id": self.sender_id,
                "mentions": self.mentions,
                "body": self.body,
                "synthetic_brief": self.synthetic_brief,
            })
        )
    }
}
