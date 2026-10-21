//! Bounded context delivered by an original dynamic-tool callback, never the steer queue.
use crate::function_tool::FunctionCallError;
use crate::session::session::Session;
use crate::session::turn_context::TurnContext;
use codex_history::CodexHarnessMetadata;
use codex_history::ResponseItemEnvelope;
use codex_protocol::models::FunctionCallOutputPayload;
use codex_protocol::models::ResponseItem;
use codex_tools::ToolName;

/// Validates the complete batch before recording any part of it.
pub(super) async fn record(
    session: &Session,
    turn: &TurnContext,
    tool: &ToolName,
    fragments: &[String],
) -> Result<(), FunctionCallError> {
    if fragments.len() > 32
        || fragments
            .iter()
            .any(|text| text.is_empty() || !text.is_ascii() || text.len() > 8192)
        || fragments.iter().map(String::len).sum::<usize>() > 262144
    {
        return Err(FunctionCallError::RespondToModel(
            "dynamic context exceeds32 ASCII fragments of8192 bytes each".to_string(),
        ));
    }
    if fragments.is_empty() {
        return Ok(());
    }
    let items = fragments
        .iter()
        .map(|text| ResponseItemEnvelope {
            item: ResponseItem::FunctionCallOutput {
                id: None,
                call_id: None,
                namespace: tool.namespace.clone(),
                name: Some(tool.name.clone()),
                output: FunctionCallOutputPayload::from_text(text.clone()),
                internal_chat_message_metadata_passthrough: None,
            },
            metadata: Some(CodexHarnessMetadata {
                // ASCII byte cap bounds worst-case tokens; ordinary outputs keep their policy.
                history_truncation_token_limit: Some(8192),
                ..Default::default()
            }),
        })
        .collect();
    session.try_record_tool_context(turn, items).await.map_err(|error| {
        FunctionCallError::Fatal(format!("dynamic context durability is unknown; do not replay the original callback: {error}"))
    })
}
