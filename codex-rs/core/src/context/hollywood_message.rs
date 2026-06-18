use codex_protocol::protocol::HollywoodInputMessage;
use codex_protocol::protocol::HollywoodSyntheticBrief;
use codex_utils_output_truncation::TruncationPolicy;
use codex_utils_output_truncation::truncate_text;

use super::ContextualUserFragment;

const HOLLYWOOD_MESSAGE_BODY_MAX_TOKENS: usize = 350;
const HOLLYWOOD_BRIEF_SUMMARY_MAX_TOKENS: usize = 120;
const HOLLYWOOD_BRIEF_ITEM_MAX_TOKENS: usize = 40;
const HOLLYWOOD_BRIEF_ITEM_LIMIT: usize = 4;

#[derive(Debug, Clone, PartialEq)]
pub(crate) struct HollywoodMessage {
    pub(crate) message_id: i64,
    pub(crate) room: String,
    pub(crate) sender_id: String,
    pub(crate) mentions: Vec<String>,
    pub(crate) attention: Option<String>,
    pub(crate) message_kind: Option<String>,
    pub(crate) obligation: Option<String>,
    pub(crate) body: String,
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
            attention: message.attention.clone(),
            message_kind: message.message_kind.clone(),
            obligation: message.obligation.clone(),
            body: message.body.clone(),
            synthetic_brief: message.synthetic_brief.clone(),
            requires_response: message.requires_response,
        }
    }

    fn message_type(&self) -> &'static str {
        match self.obligation.as_deref() {
            Some("obligation") => "HOLLYWOOD_OBLIGATION",
            Some("attention") => "HOLLYWOOD_ATTENTION",
            _ => "HOLLYWOOD_MESSAGE",
        }
    }

    fn response_required(&self) -> &'static str {
        if self.requires_response { "yes" } else { "no" }
    }

    fn truncated_body(&self) -> String {
        truncate_text(
            &self.body,
            TruncationPolicy::Tokens(HOLLYWOOD_MESSAGE_BODY_MAX_TOKENS),
        )
    }

    fn push_optional_line(output: &mut String, label: &str, value: Option<&str>) {
        if let Some(value) = value.filter(|value| !value.trim().is_empty()) {
            output.push_str(label);
            output.push_str(": ");
            output.push_str(value);
            output.push('\n');
        }
    }

    fn push_brief_list(output: &mut String, label: &str, values: &[String]) {
        if values.is_empty() {
            return;
        }

        output.push_str(label);
        output.push_str(":\n");
        for value in values.iter().take(HOLLYWOOD_BRIEF_ITEM_LIMIT) {
            let value = truncate_text(
                value,
                TruncationPolicy::Tokens(HOLLYWOOD_BRIEF_ITEM_MAX_TOKENS),
            );
            output.push_str("- ");
            output.push_str(value.trim());
            output.push('\n');
        }
        if values.len() > HOLLYWOOD_BRIEF_ITEM_LIMIT {
            output.push_str("- ...");
            output.push_str(&(values.len() - HOLLYWOOD_BRIEF_ITEM_LIMIT).to_string());
            output.push_str(" more\n");
        }
    }

    fn push_synthetic_brief(&self, output: &mut String) {
        let Some(brief) = self.synthetic_brief.as_ref() else {
            return;
        };

        Self::push_optional_line(output, "Wake reason", brief.wake_reason.as_deref());
        Self::push_optional_line(output, "Semantic kind", brief.semantic_kind.as_deref());
        Self::push_optional_line(
            output,
            "Coordination policy",
            brief.coordination_policy.as_deref(),
        );
        Self::push_optional_line(
            output,
            "Coordination phase",
            brief.coordination_phase.as_deref(),
        );
        Self::push_optional_line(
            output,
            "Coordination role",
            brief.coordination_role.as_deref(),
        );
        if let Some(epoch) = brief.coordination_epoch {
            output.push_str("Coordination epoch: ");
            output.push_str(&epoch.to_string());
            output.push('\n');
        }
        if brief.stay_silent_if_no_actionable_delta {
            output.push_str("Stay silent if no actionable delta: yes\n");
        }
        if let Some(summary) = brief
            .summary
            .as_deref()
            .filter(|summary| !summary.trim().is_empty())
            .filter(|summary| summary.trim() != self.body.trim())
        {
            let summary = truncate_text(
                summary,
                TruncationPolicy::Tokens(HOLLYWOOD_BRIEF_SUMMARY_MAX_TOKENS),
            );
            output.push_str("Summary:\n");
            output.push_str(summary.trim());
            output.push('\n');
        }
        Self::push_brief_list(output, "Facts", &brief.facts);
        Self::push_brief_list(output, "Suggested actions", &brief.suggested_actions);
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
        let mut output = String::new();
        output.push('\n');
        output.push_str("Message Type: ");
        output.push_str(self.message_type());
        output.push('\n');
        output.push_str("Coordination path: hollywood:");
        output.push_str(&self.room);
        output.push('#');
        output.push_str(&self.message_id.to_string());
        output.push('\n');
        output.push_str("Room: ");
        output.push_str(&self.room);
        output.push('\n');
        output.push_str("Message id: ");
        output.push_str(&self.message_id.to_string());
        output.push('\n');
        output.push_str("Sender: ");
        output.push_str(&self.sender_id);
        output.push('\n');
        Self::push_optional_line(&mut output, "Kind", self.message_kind.as_deref());
        Self::push_optional_line(&mut output, "Attention", self.attention.as_deref());
        output.push_str("Response required: ");
        output.push_str(self.response_required());
        output.push('\n');
        if !self.mentions.is_empty() {
            output.push_str("Mentions: ");
            output.push_str(&self.mentions.join(", "));
            output.push('\n');
        }
        self.push_synthetic_brief(&mut output);
        output.push_str("Payload:\n");
        output.push_str(self.truncated_body().trim());
        output.push('\n');
        output
    }
}

#[cfg(test)]
#[path = "hollywood_message_tests.rs"]
mod tests;
