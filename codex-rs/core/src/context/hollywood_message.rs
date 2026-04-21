use codex_protocol::protocol::HollywoodInputMessage;

use super::ContextualUserFragment;

#[derive(Debug, Clone, PartialEq)]
pub(crate) struct HollywoodMessage {
    pub(crate) message_id: i64,
    pub(crate) room: String,
    pub(crate) sender_id: String,
    pub(crate) mentions: Vec<String>,
    pub(crate) body: String,
}

impl HollywoodMessage {
    pub(crate) fn new(message: &HollywoodInputMessage) -> Self {
        Self {
            message_id: message.message_id,
            room: message.room.clone(),
            sender_id: message.sender_id.clone(),
            mentions: message.mentions.clone(),
            body: message.body.clone(),
        }
    }
}

impl ContextualUserFragment for HollywoodMessage {
    const ROLE: &'static str = "user";
    const START_MARKER: &'static str = "<hollywood_message>";
    const END_MARKER: &'static str = "</hollywood_message>";

    fn body(&self) -> String {
        format!(
            "\n{}",
            serde_json::json!({
                "message_id": self.message_id,
                "room": self.room,
                "sender_id": self.sender_id,
                "mentions": self.mentions,
                "body": self.body,
            })
        )
    }
}
