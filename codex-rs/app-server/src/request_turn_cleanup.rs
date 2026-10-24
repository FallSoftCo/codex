//! Correlate callback retirement with the native turn that owns the request.
use codex_app_server_protocol::ServerRequest;

#[derive(Clone, Copy)]
pub(crate) enum TurnRequestCleanup<'a> {
    All,
    Starting(&'a str),
    Ending(&'a str),
}

impl TurnRequestCleanup<'_> {
    pub(crate) fn cancels(self, request: &ServerRequest) -> bool {
        let turn = match request {
            // Maintenance/recovery references an old turn as provenance, but
            // does not belong to it. Only whole-session cleanup may retire it.
            ServerRequest::ContextWindowIdleInstalled { .. }
            | ServerRequest::ContextWindowReconcile { .. } => {
                return matches!(self, Self::All);
            }
            ServerRequest::ContextInput { params, .. } => Some(params.turn_id.as_str()),
            ServerRequest::ContextWindowRefill { params, .. } => Some(params.turn_id.as_str()),
            ServerRequest::ContextWindowInstalled { params, .. } => Some(params.turn_id.as_str()),
            ServerRequest::CommandExecutionRequestApproval { params, .. } => {
                Some(params.turn_id.as_str())
            }
            ServerRequest::FileChangeRequestApproval { params, .. } => {
                Some(params.turn_id.as_str())
            }
            ServerRequest::ToolRequestUserInput { params, .. } => Some(params.turn_id.as_str()),
            ServerRequest::PermissionsRequestApproval { params, .. } => {
                Some(params.turn_id.as_str())
            }
            ServerRequest::DynamicToolCall { params, .. } => Some(params.turn_id.as_str()),
            ServerRequest::McpServerElicitationRequest { params, .. } => params.turn_id.as_deref(),
            ServerRequest::ChatgptAuthTokensRefresh { .. }
            | ServerRequest::AttestationGenerate { .. }
            | ServerRequest::CurrentTimeRead { .. }
            | ServerRequest::ApplyPatchApproval { .. }
            | ServerRequest::ExecCommandApproval { .. } => None,
        };
        match self {
            Self::All => true,
            Self::Starting(current) => turn != Some(current),
            // Uncorrelated legacy requests retain the prior retirement behavior.
            Self::Ending(ended) => turn.is_none_or(|turn| turn == ended),
        }
    }
}
