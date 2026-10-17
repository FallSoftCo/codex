//! Native peer input: a Hollywood event is neither human input nor a tool result.
//! Authentication remains at the private transport and Hollywood API boundary.

use super::turn_processor::TurnRequestProcessor;
use super::*;
use codex_app_server_protocol::HollywoodAgentMessageParams;
use codex_app_server_protocol::HollywoodAgentMessageResponse;
use codex_protocol::ResponseItemId;
use codex_protocol::models::AgentMessageInputContent;

impl TurnRequestProcessor {
    pub(crate) async fn hollywood_agent_message(
        &self,
        request_id: ConnectionRequestId,
        params: HollywoodAgentMessageParams,
        app_server_client_name: Option<String>,
        app_server_client_version: Option<String>,
    ) -> Result<Option<ClientResponsePayload>, JSONRPCErrorError> {
        let (params, item) = model_input(params)?;
        let response = self
            .turn_start_inner(
                request_id,
                params,
                app_server_client_name,
                app_server_client_version,
                Some(item),
            )
            .await?;
        Ok(Some(
            HollywoodAgentMessageResponse {
                turn: response.turn,
            }
            .into(),
        ))
    }
}

fn identity(value: &str, field: &str) -> Result<String, JSONRPCErrorError> {
    uuid::Uuid::parse_str(value)
        .map(|value| value.to_string())
        .map_err(|_| invalid_request(format!("Invalid Hollywood {field}")))
}

fn model_input(
    params: HollywoodAgentMessageParams,
) -> Result<(TurnStartParams, ResponseItem), JSONRPCErrorError> {
    if params.body.is_empty() || params.body.chars().count() > 6000 {
        return Err(invalid_request(
            "Hollywood peer message body must contain 1 to 6000 characters",
        ));
    }
    let authority = identity(&params.authority_id, "authorityId")?;
    let room = identity(&params.room_id, "roomId")?;
    let event = identity(&params.event_id, "eventId")?;
    let author = identity(&params.author_id, "authorId")?;
    let recipient = identity(&params.recipient_id, "recipientId")?;
    let source = params
        .source_event_id
        .as_deref()
        .map(|value| identity(value, "sourceEventId"))
        .transpose()?;
    // Hollywood owns execution admission. Its bounded work-review policy may
    // address the owner with an event carrying that same authenticated author.
    // This private input transport must preserve, not reinterpret, that identity.
    let content = serde_json::json!({
        "authorityId": authority,
        "roomId": room,
        "eventId": event,
        "sourceEventId": source,
        "audience": params.audience,
        "kind": params.kind,
        "expectsReply": params.expects_reply,
        "body": params.body,
    });
    let item = ResponseItem::AgentMessage {
        id: Some(ResponseItemId::with_suffix("amsg", event)),
        author,
        recipient,
        content: vec![AgentMessageInputContent::InputText {
            text: content.to_string(),
        }],
        internal_chat_message_metadata_passthrough: None,
    };
    Ok((
        TurnStartParams {
            thread_id: params.thread_id,
            turn_trigger: Some("hollywood.agent_message".to_string()),
            ..Default::default()
        },
        item,
    ))
}
