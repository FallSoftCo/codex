use reqwest::Client;
use serde::Deserialize;
use serde::Serialize;
use serde_json::json;

use crate::function_tool::FunctionCallError;
use crate::hollywood::HollywoodSessionConfig;
use crate::hollywood::identities as hollywood_identities;
use crate::tools::context::FunctionToolOutput;
use crate::tools::context::ToolInvocation;
use crate::tools::context::ToolPayload;
use crate::tools::handlers::parse_arguments;
use crate::tools::registry::ToolHandler;
use crate::tools::registry::ToolKind;

pub struct HollywoodStatusHandler;
pub struct HollywoodReadHandler;
pub struct HollywoodSendHandler;

#[derive(Deserialize)]
struct HollywoodReadArgs {
    room: Option<String>,
    after_id: Option<i64>,
    limit: Option<u32>,
}

#[derive(Deserialize)]
struct HollywoodSendArgs {
    text: String,
    room: Option<String>,
}

#[derive(Serialize)]
struct HollywoodStatusResult {
    configured: bool,
    reachable: bool,
    url: Option<String>,
    room: Option<String>,
    attention_mode: Option<String>,
    identities: Vec<String>,
    can_read: bool,
    can_send: bool,
    error: Option<String>,
}

#[derive(Serialize)]
struct HollywoodReadResult {
    url: String,
    room: String,
    identities: Vec<String>,
    messages: serde_json::Value,
}

#[derive(Serialize)]
struct HollywoodSendResult {
    url: String,
    room: String,
    sender_id: String,
    text: String,
    ok: bool,
}

impl ToolHandler for HollywoodStatusHandler {
    type Output = FunctionToolOutput;

    fn kind(&self) -> ToolKind {
        ToolKind::Function
    }

    async fn handle(&self, invocation: ToolInvocation) -> Result<Self::Output, FunctionCallError> {
        let config = HollywoodSessionConfig::from_env();
        let identities = hollywood_identities(invocation.session.conversation_id);
        let result = if let Some(config) = config {
            let health_url = format!("{}/hollywood/v1/health", config.url.trim_end_matches('/'));
            match Client::new().get(health_url).send().await {
                Ok(response) => HollywoodStatusResult {
                    configured: true,
                    reachable: response.status().is_success(),
                    url: Some(config.url),
                    room: Some(config.room),
                    attention_mode: Some(config.attention_mode),
                    identities,
                    can_read: true,
                    can_send: true,
                    error: None,
                },
                Err(err) => HollywoodStatusResult {
                    configured: true,
                    reachable: false,
                    url: Some(config.url),
                    room: Some(config.room),
                    attention_mode: Some(config.attention_mode),
                    identities,
                    can_read: true,
                    can_send: true,
                    error: Some(err.to_string()),
                },
            }
        } else {
            HollywoodStatusResult {
                configured: false,
                reachable: false,
                url: None,
                room: None,
                attention_mode: None,
                identities,
                can_read: false,
                can_send: false,
                error: Some("Hollywood is not configured for this session.".to_string()),
            }
        };

        Ok(FunctionToolOutput::from_text(
            serde_json::to_string_pretty(&result)
                .unwrap_or_else(|err| format!("failed to serialize hollywood status: {err}")),
            Some(true),
        ))
    }
}

impl ToolHandler for HollywoodReadHandler {
    type Output = FunctionToolOutput;

    fn kind(&self) -> ToolKind {
        ToolKind::Function
    }

    async fn handle(&self, invocation: ToolInvocation) -> Result<Self::Output, FunctionCallError> {
        let args = parse_function_args::<HollywoodReadArgs>(&invocation.payload)?;
        let Some(config) = HollywoodSessionConfig::from_env() else {
            return Err(FunctionCallError::RespondToModel(
                "Hollywood is not configured for this session.".to_string(),
            ));
        };

        let room = args.room.unwrap_or_else(|| config.room.clone());
        let after_id = args.after_id.unwrap_or(0);
        let limit = args.limit.unwrap_or(20).clamp(1, 100);
        let url = format!("{}/hollywood/v1/messages", config.url.trim_end_matches('/'));

        let response = Client::new()
            .get(&url)
            .query(&[
                ("room", room.as_str()),
                ("after_id", &after_id.to_string()),
                ("limit", &limit.to_string()),
            ])
            .send()
            .await
            .map_err(|err| {
                FunctionCallError::RespondToModel(format!("Hollywood read failed: {err}"))
            })?
            .error_for_status()
            .map_err(|err| {
                FunctionCallError::RespondToModel(format!("Hollywood read failed: {err}"))
            })?
            .json::<serde_json::Value>()
            .await
            .map_err(|err| {
                FunctionCallError::RespondToModel(format!("Hollywood response parse failed: {err}"))
            })?;

        let result = HollywoodReadResult {
            url: config.url,
            room,
            identities: hollywood_identities(invocation.session.conversation_id),
            messages: response,
        };

        Ok(FunctionToolOutput::from_text(
            serde_json::to_string_pretty(&result)
                .unwrap_or_else(|err| format!("failed to serialize hollywood read: {err}")),
            Some(true),
        ))
    }
}

impl ToolHandler for HollywoodSendHandler {
    type Output = FunctionToolOutput;

    fn kind(&self) -> ToolKind {
        ToolKind::Function
    }

    async fn handle(&self, invocation: ToolInvocation) -> Result<Self::Output, FunctionCallError> {
        let args = parse_function_args::<HollywoodSendArgs>(&invocation.payload)?;
        let Some(config) = HollywoodSessionConfig::from_env() else {
            return Err(FunctionCallError::RespondToModel(
                "Hollywood is not configured for this session.".to_string(),
            ));
        };

        let room = args.room.unwrap_or_else(|| config.room.clone());
        let sender_id = invocation.session.conversation_id.to_string();
        let url = format!("{}/hollywood/v1/messages", config.url.trim_end_matches('/'));

        Client::new()
            .post(&url)
            .json(&json!({
                "room": room,
                "sender_id": sender_id,
                "body": args.text,
            }))
            .send()
            .await
            .map_err(|err| {
                FunctionCallError::RespondToModel(format!("Hollywood send failed: {err}"))
            })?
            .error_for_status()
            .map_err(|err| {
                FunctionCallError::RespondToModel(format!("Hollywood send failed: {err}"))
            })?;

        let result = HollywoodSendResult {
            url: config.url,
            room,
            sender_id,
            text: args.text,
            ok: true,
        };

        Ok(FunctionToolOutput::from_text(
            serde_json::to_string_pretty(&result)
                .unwrap_or_else(|err| format!("failed to serialize hollywood send: {err}")),
            Some(true),
        ))
    }
}

fn parse_function_args<T>(payload: &ToolPayload) -> Result<T, FunctionCallError>
where
    T: for<'de> Deserialize<'de>,
{
    match payload {
        ToolPayload::Function { arguments } => parse_arguments(arguments),
        _ => Err(FunctionCallError::RespondToModel(
            "hollywood handler received unsupported payload".to_string(),
        )),
    }
}
