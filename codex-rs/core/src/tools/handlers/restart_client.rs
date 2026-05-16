use crate::function_tool::FunctionCallError;
use crate::tools::context::FunctionToolOutput;
use crate::tools::context::ToolInvocation;
use crate::tools::context::ToolOutput;
use crate::tools::context::ToolPayload;
use crate::tools::context::boxed_tool_output;
use crate::tools::handlers::parse_arguments;
use crate::tools::registry::ToolExecutor;
use codex_protocol::protocol::SessionSource;
use codex_tools::ToolName;
use serde::Deserialize;
use serde::Serialize;

const RESTART_CLIENT_TOOL_NAME: &str = "restart_client";

pub struct RestartClientHandler;

#[derive(Debug, Default, Deserialize)]
struct RestartClientArgs {
    reason: Option<String>,
}

#[derive(Debug, Serialize)]
struct RestartClientResult {
    status: &'static str,
    thread_id: String,
    reason: Option<String>,
}

#[async_trait::async_trait]
impl ToolExecutor<ToolInvocation> for RestartClientHandler {
    fn tool_name(&self) -> ToolName {
        ToolName::new(None, RESTART_CLIENT_TOOL_NAME.to_string())
    }

    async fn handle(
        &self,
        invocation: ToolInvocation,
    ) -> Result<Box<dyn ToolOutput>, FunctionCallError> {
        let output = async {
            let ToolInvocation {
                session,
                turn,
                payload,
                ..
            } = invocation;

            let arguments = match payload {
                ToolPayload::Function { arguments } => arguments,
                _ => {
                    return Err(FunctionCallError::RespondToModel(format!(
                        "{RESTART_CLIENT_TOOL_NAME} handler received unsupported payload"
                    )));
                }
            };

            if matches!(turn.session_source, SessionSource::SubAgent(_)) {
                return Err(FunctionCallError::RespondToModel(
                    "restart_client can only be used by the root thread".to_string(),
                ));
            }

            let args: RestartClientArgs = parse_arguments(&arguments)?;
            session
                .request_client_restart(turn.as_ref(), args.reason.clone())
                .await;

            let content = serde_json::to_string(&RestartClientResult {
                status: "requested",
                thread_id: session.conversation_id.to_string(),
                reason: args.reason,
            })
            .map_err(|err| {
                FunctionCallError::Fatal(format!(
                    "failed to serialize {RESTART_CLIENT_TOOL_NAME} response: {err}"
                ))
            })?;

            Ok(FunctionToolOutput::from_text(content, Some(true)))
        }
        .await?;
        Ok(boxed_tool_output(output))
    }
}

#[cfg(test)]
#[path = "restart_client_tests.rs"]
mod tests;
