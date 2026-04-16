use crate::shell::Shell;
use crate::shell::ShellType;
use crate::tools::handlers::HollywoodReadHandler;
use crate::tools::handlers::HollywoodSendHandler;
use crate::tools::handlers::HollywoodStatusHandler;
use crate::tools::handlers::HollywoodTeamMemberUpdateHandler;
use crate::tools::handlers::HollywoodTeamStatusHandler;
use crate::tools::handlers::HollywoodTeamUpHandler;
use crate::tools::handlers::agent_jobs::BatchJobHandler;
use crate::tools::handlers::multi_agents_common::DEFAULT_WAIT_TIMEOUT_MS;
use crate::tools::handlers::multi_agents_common::MAX_WAIT_TIMEOUT_MS;
use crate::tools::handlers::multi_agents_common::MIN_WAIT_TIMEOUT_MS;
use crate::tools::registry::ToolRegistryBuilder;
use codex_mcp::ToolInfo;
use codex_protocol::dynamic_tools::DynamicToolSpec;
use codex_tools::DiscoverableTool;
use codex_tools::JsonSchema;
use codex_tools::ResponsesApiTool;
use codex_tools::ToolHandlerKind;
use codex_tools::ToolRegistryPlanDeferredTool;
use codex_tools::ToolRegistryPlanParams;
use codex_tools::ToolSpec;
use codex_tools::ToolUserShellType;
use codex_tools::ToolsConfig;
use codex_tools::WaitAgentTimeoutOptions;
use codex_tools::build_tool_registry_plan;
use std::collections::BTreeMap;
use std::collections::HashMap;
use std::sync::Arc;

pub(crate) fn tool_user_shell_type(user_shell: &Shell) -> ToolUserShellType {
    match user_shell.shell_type {
        ShellType::Zsh => ToolUserShellType::Zsh,
        ShellType::Bash => ToolUserShellType::Bash,
        ShellType::PowerShell => ToolUserShellType::PowerShell,
        ShellType::Sh => ToolUserShellType::Sh,
        ShellType::Cmd => ToolUserShellType::Cmd,
    }
}

fn create_hollywood_status_tool() -> ToolSpec {
    ToolSpec::Function(ResponsesApiTool {
        name: "hollywood_status".to_string(),
        description: "Check whether Hollywood is configured and reachable for this session. Use this when you need to know whether you can coordinate with other existing attached agents through the local Hollywood room before considering `spawn_agent`."
            .to_string(),
        strict: false,
        defer_loading: None,
        parameters: JsonSchema::object(
            BTreeMap::new(),
            Some(Vec::new()),
            Some(false.into()),
        ),
        output_schema: None,
    })
}

fn create_hollywood_read_tool() -> ToolSpec {
    let properties = BTreeMap::from([
        (
            "room".to_string(),
            JsonSchema::string(Some(
                "Optional room to read from. Defaults to the configured Hollywood room."
                    .to_string(),
            )),
        ),
        (
            "after_id".to_string(),
            JsonSchema::number(Some(
                "Optional message id cursor. When provided, only newer messages are returned."
                    .to_string(),
            )),
        ),
        (
            "limit".to_string(),
            JsonSchema::number(Some(
                "Optional maximum number of messages to return. Defaults to 20, max 100."
                    .to_string(),
            )),
        ),
    ]);
    ToolSpec::Function(ResponsesApiTool {
        name: "hollywood_read".to_string(),
        description: "Read messages from the configured Hollywood room. Use this when you need explicit room context beyond the ambient runtime stream."
            .to_string(),
        strict: false,
        defer_loading: None,
        parameters: JsonSchema::object(properties, Some(Vec::new()), Some(false.into())),
        output_schema: None,
    })
}

fn create_hollywood_send_tool() -> ToolSpec {
    let properties = BTreeMap::from([
        (
            "text".to_string(),
            JsonSchema::string(Some(
                "Message body to send to Hollywood. Use @mentions when you need another agent's attention."
                    .to_string(),
            )),
        ),
        (
            "room".to_string(),
            JsonSchema::string(Some(
                "Optional room override. Defaults to the configured Hollywood room.".to_string(),
            )),
        ),
        (
            "to".to_string(),
            JsonSchema::string(Some(
                "Optional direct recipient session id or alias. When omitted, the message goes to the room."
                    .to_string(),
            )),
        ),
        (
            "broadcast".to_string(),
            JsonSchema::boolean(Some(
                "When true, mark this as an explicit room-wide broadcast that should wake idle attached agents."
                    .to_string(),
            )),
        ),
        (
            "response_policy".to_string(),
            JsonSchema::string(Some(
                "Optional reply contract for the message: `required`, `optional`, or `none`. Use `none` for acknowledgements or informational updates that should not trigger a reply."
                    .to_string(),
            )),
        ),
    ]);
    ToolSpec::Function(ResponsesApiTool {
        name: "hollywood_send".to_string(),
        description: "Send a message to Hollywood as this agent. Use this to coordinate with other existing attached agents through the local Hollywood room; prefer this over `spawn_agent` when the user asks for peer coordination rather than new delegated workers."
            .to_string(),
        strict: false,
        defer_loading: None,
        parameters: JsonSchema::object(
            properties,
            Some(vec!["text".to_string()]),
            Some(false.into()),
        ),
        output_schema: None,
    })
}

fn create_hollywood_team_up_tool() -> ToolSpec {
    let properties = BTreeMap::from([
        (
            "purpose".to_string(),
            JsonSchema::string(Some("Shared purpose for the team.".to_string())),
        ),
        (
            "targets".to_string(),
            JsonSchema::array(
                JsonSchema::string(Some("Target session id or alias.".to_string())),
                Some("Sessions to invite onto the team.".to_string()),
            ),
        ),
        (
            "room".to_string(),
            JsonSchema::string(Some(
                "Optional control room for the team record. Defaults to main.".to_string(),
            )),
        ),
        (
            "task_room".to_string(),
            JsonSchema::string(Some(
                "Optional working room members should join after accepting.".to_string(),
            )),
        ),
        (
            "team_id".to_string(),
            JsonSchema::string(Some("Optional explicit team id.".to_string())),
        ),
    ]);

    ToolSpec::Function(ResponsesApiTool {
        name: "hollywood_team_up".to_string(),
        description: "Create a structured Hollywood team with a leader, purpose, and invited member sessions. Use this when you need to form an explicit working group rather than relying on room chat alone.".to_string(),
        strict: false,
        defer_loading: None,
        parameters: JsonSchema::object(
            properties,
            Some(vec!["purpose".to_string(), "targets".to_string()]),
            Some(false.into()),
        ),
        output_schema: None,
    })
}

fn create_hollywood_team_status_tool() -> ToolSpec {
    let properties = BTreeMap::from([
        (
            "room".to_string(),
            JsonSchema::string(Some(
                "Optional room to inspect. Defaults to the configured Hollywood room.".to_string(),
            )),
        ),
        (
            "limit".to_string(),
            JsonSchema::number(Some(
                "Maximum number of teams to return. Defaults to 20.".to_string(),
            )),
        ),
    ]);

    ToolSpec::Function(ResponsesApiTool {
        name: "hollywood_team_status".to_string(),
        description: "Inspect structured Hollywood teams and member state for a room. Use this to understand invites, leaders, roles, and which sessions have joined or acknowledged.".to_string(),
        strict: false,
        defer_loading: None,
        parameters: JsonSchema::object(properties, Some(Vec::new()), Some(false.into())),
        output_schema: None,
    })
}

fn create_hollywood_team_member_update_tool() -> ToolSpec {
    let properties = BTreeMap::from([
        (
            "team_id".to_string(),
            JsonSchema::string(Some("Team id to update.".to_string())),
        ),
        (
            "session_id".to_string(),
            JsonSchema::string(Some(
                "Optional session id or alias to update. Defaults to this session.".to_string(),
            )),
        ),
        (
            "role".to_string(),
            JsonSchema::string(Some(
                "Optional updated role, for example leader, member, reviewer, observer.".to_string(),
            )),
        ),
        (
            "state".to_string(),
            JsonSchema::string(Some(
                "Optional updated team state, for example pending, accepted, joined, active, declined, deferred, timed_out.".to_string(),
            )),
        ),
        (
            "joined_room".to_string(),
            JsonSchema::string(Some(
                "Optional joined working room for this member.".to_string(),
            )),
        ),
        (
            "task".to_string(),
            JsonSchema::string(Some("Optional current task summary for this member.".to_string())),
        ),
        (
            "scope".to_string(),
            JsonSchema::string(Some(
                "Optional scope or ownership summary for this member.".to_string(),
            )),
        ),
    ]);

    ToolSpec::Function(ResponsesApiTool {
        name: "hollywood_team_member_update".to_string(),
        description: "Update structured team-member state in Hollywood. Use this to accept or decline invites, mark joined/active state, and record claimed scope.".to_string(),
        strict: false,
        defer_loading: None,
        parameters: JsonSchema::object(
            properties,
            Some(vec!["team_id".to_string()]),
            Some(false.into()),
        ),
        output_schema: None,
    })
}

pub(crate) fn build_specs_with_discoverable_tools(
    config: &ToolsConfig,
    mcp_tools: Option<HashMap<String, rmcp::model::Tool>>,
    app_tools: Option<HashMap<String, ToolInfo>>,
    discoverable_tools: Option<Vec<DiscoverableTool>>,
    dynamic_tools: &[DynamicToolSpec],
) -> ToolRegistryBuilder {
    use crate::tools::handlers::ApplyPatchHandler;
    use crate::tools::handlers::CodeModeExecuteHandler;
    use crate::tools::handlers::CodeModeWaitHandler;
    use crate::tools::handlers::DynamicToolHandler;
    use crate::tools::handlers::JsReplHandler;
    use crate::tools::handlers::JsReplResetHandler;
    use crate::tools::handlers::ListDirHandler;
    use crate::tools::handlers::McpHandler;
    use crate::tools::handlers::McpResourceHandler;
    use crate::tools::handlers::PlanHandler;
    use crate::tools::handlers::RequestPermissionsHandler;
    use crate::tools::handlers::RequestUserInputHandler;
    use crate::tools::handlers::ShellCommandHandler;
    use crate::tools::handlers::ShellHandler;
    use crate::tools::handlers::TestSyncHandler;
    use crate::tools::handlers::ToolSearchHandler;
    use crate::tools::handlers::ToolSuggestHandler;
    use crate::tools::handlers::UnifiedExecHandler;
    use crate::tools::handlers::ViewImageHandler;
    use crate::tools::handlers::WatcherHandler;
    use crate::tools::handlers::multi_agents::CloseAgentHandler;
    use crate::tools::handlers::multi_agents::ResumeAgentHandler;
    use crate::tools::handlers::multi_agents::SendInputHandler;
    use crate::tools::handlers::multi_agents::SpawnAgentHandler;
    use crate::tools::handlers::multi_agents::WaitAgentHandler;
    use crate::tools::handlers::multi_agents_v2::CloseAgentHandler as CloseAgentHandlerV2;
    use crate::tools::handlers::multi_agents_v2::FollowupTaskHandler as FollowupTaskHandlerV2;
    use crate::tools::handlers::multi_agents_v2::ListAgentsHandler as ListAgentsHandlerV2;
    use crate::tools::handlers::multi_agents_v2::SendMessageHandler as SendMessageHandlerV2;
    use crate::tools::handlers::multi_agents_v2::SpawnAgentHandler as SpawnAgentHandlerV2;
    use crate::tools::handlers::multi_agents_v2::WaitAgentHandler as WaitAgentHandlerV2;

    let mut builder = ToolRegistryBuilder::new();
    let app_tool_sources = app_tools.as_ref().map(|app_tools| {
        app_tools
            .values()
            .map(|tool| ToolRegistryPlanDeferredTool {
                tool_name: tool.callable_name.as_str(),
                tool_namespace: tool.callable_namespace.as_str(),
                server_name: tool.server_name.as_str(),
                connector_name: tool.connector_name.as_deref(),
                connector_description: tool.connector_description.as_deref(),
            })
            .collect::<Vec<_>>()
    });
    let default_agent_type_description =
        crate::agent::role::spawn_tool_spec::build(&std::collections::BTreeMap::new());
    let plan = build_tool_registry_plan(
        config,
        ToolRegistryPlanParams {
            mcp_tools: mcp_tools.as_ref(),
            deferred_mcp_tools: app_tool_sources.as_deref(),
            tool_namespaces: None,
            discoverable_tools: discoverable_tools.as_deref(),
            dynamic_tools,
            default_agent_type_description: &default_agent_type_description,
            wait_agent_timeouts: WaitAgentTimeoutOptions {
                default_timeout_ms: DEFAULT_WAIT_TIMEOUT_MS,
                min_timeout_ms: MIN_WAIT_TIMEOUT_MS,
                max_timeout_ms: MAX_WAIT_TIMEOUT_MS,
            },
        },
    );
    let shell_handler = Arc::new(ShellHandler);
    let unified_exec_handler = Arc::new(UnifiedExecHandler);
    let plan_handler = Arc::new(PlanHandler);
    let apply_patch_handler = Arc::new(ApplyPatchHandler);
    let dynamic_tool_handler = Arc::new(DynamicToolHandler);
    let view_image_handler = Arc::new(ViewImageHandler);
    let mcp_handler = Arc::new(McpHandler);
    let mcp_resource_handler = Arc::new(McpResourceHandler);
    let shell_command_handler = Arc::new(ShellCommandHandler::from(config.shell_command_backend));
    let request_permissions_handler = Arc::new(RequestPermissionsHandler);
    let request_user_input_handler = Arc::new(RequestUserInputHandler {
        default_mode_request_user_input: config.default_mode_request_user_input,
    });
    let mut tool_search_handler = None;
    let tool_suggest_handler = Arc::new(ToolSuggestHandler);
    let code_mode_handler = Arc::new(CodeModeExecuteHandler);
    let code_mode_wait_handler = Arc::new(CodeModeWaitHandler);
    let js_repl_handler = Arc::new(JsReplHandler);
    let js_repl_reset_handler = Arc::new(JsReplResetHandler);

    for spec in plan.specs {
        if spec.supports_parallel_tool_calls {
            builder.push_spec_with_parallel_support(
                spec.spec, /*supports_parallel_tool_calls*/ true,
            );
        } else {
            builder.push_spec(spec.spec);
        }
    }

    for handler in plan.handlers {
        match handler.kind {
            ToolHandlerKind::AgentJobs => {
                builder.register_handler(handler.name, Arc::new(BatchJobHandler));
            }
            ToolHandlerKind::ApplyPatch => {
                builder.register_handler(handler.name, apply_patch_handler.clone());
            }
            ToolHandlerKind::CloseAgentV1 => {
                builder.register_handler(handler.name, Arc::new(CloseAgentHandler));
            }
            ToolHandlerKind::CloseAgentV2 => {
                builder.register_handler(handler.name, Arc::new(CloseAgentHandlerV2));
            }
            ToolHandlerKind::CodeModeExecute => {
                builder.register_handler(handler.name, code_mode_handler.clone());
            }
            ToolHandlerKind::CodeModeWait => {
                builder.register_handler(handler.name, code_mode_wait_handler.clone());
            }
            ToolHandlerKind::DynamicTool => {
                builder.register_handler(handler.name, dynamic_tool_handler.clone());
            }
            ToolHandlerKind::FollowupTaskV2 => {
                builder.register_handler(handler.name, Arc::new(FollowupTaskHandlerV2));
            }
            ToolHandlerKind::JsRepl => {
                builder.register_handler(handler.name, js_repl_handler.clone());
            }
            ToolHandlerKind::JsReplReset => {
                builder.register_handler(handler.name, js_repl_reset_handler.clone());
            }
            ToolHandlerKind::ListAgentsV2 => {
                builder.register_handler(handler.name, Arc::new(ListAgentsHandlerV2));
            }
            ToolHandlerKind::ListDir => {
                builder.register_handler(handler.name, Arc::new(ListDirHandler));
            }
            ToolHandlerKind::Mcp => {
                builder.register_handler(handler.name, mcp_handler.clone());
            }
            ToolHandlerKind::McpResource => {
                builder.register_handler(handler.name, mcp_resource_handler.clone());
            }
            ToolHandlerKind::Plan => {
                builder.register_handler(handler.name, plan_handler.clone());
            }
            ToolHandlerKind::RequestPermissions => {
                builder.register_handler(handler.name, request_permissions_handler.clone());
            }
            ToolHandlerKind::RequestUserInput => {
                builder.register_handler(handler.name, request_user_input_handler.clone());
            }
            ToolHandlerKind::ResumeAgentV1 => {
                builder.register_handler(handler.name, Arc::new(ResumeAgentHandler));
            }
            ToolHandlerKind::SendInputV1 => {
                builder.register_handler(handler.name, Arc::new(SendInputHandler));
            }
            ToolHandlerKind::SendMessageV2 => {
                builder.register_handler(handler.name, Arc::new(SendMessageHandlerV2));
            }
            ToolHandlerKind::Shell => {
                builder.register_handler(handler.name, shell_handler.clone());
            }
            ToolHandlerKind::ShellCommand => {
                builder.register_handler(handler.name, shell_command_handler.clone());
            }
            ToolHandlerKind::SpawnAgentV1 => {
                builder.register_handler(handler.name, Arc::new(SpawnAgentHandler));
            }
            ToolHandlerKind::SpawnAgentV2 => {
                builder.register_handler(handler.name, Arc::new(SpawnAgentHandlerV2));
            }
            ToolHandlerKind::TestSync => {
                builder.register_handler(handler.name, Arc::new(TestSyncHandler));
            }
            ToolHandlerKind::ToolSearch => {
                if tool_search_handler.is_none() {
                    tool_search_handler = app_tools
                        .as_ref()
                        .map(|app_tools| Arc::new(ToolSearchHandler::new(app_tools.clone())));
                }
                if let Some(tool_search_handler) = tool_search_handler.as_ref() {
                    builder.register_handler(handler.name, tool_search_handler.clone());
                }
            }
            ToolHandlerKind::ToolSuggest => {
                builder.register_handler(handler.name, tool_suggest_handler.clone());
            }
            ToolHandlerKind::UnifiedExec => {
                builder.register_handler(handler.name, unified_exec_handler.clone());
            }
            ToolHandlerKind::ViewImage => {
                builder.register_handler(handler.name, view_image_handler.clone());
            }
            ToolHandlerKind::Watcher => {
                builder.register_handler(handler.name, Arc::new(WatcherHandler));
            }
            ToolHandlerKind::WaitAgentV1 => {
                builder.register_handler(handler.name, Arc::new(WaitAgentHandler));
            }
            ToolHandlerKind::WaitAgentV2 => {
                builder.register_handler(handler.name, Arc::new(WaitAgentHandlerV2));
            }
        }
    }

    if !cfg!(test)
        && config.hollywood_tools_enabled
        && crate::hollywood::HollywoodSessionConfig::from_env().is_some()
    {
        builder.push_spec(create_hollywood_status_tool());
        builder.push_spec(create_hollywood_read_tool());
        builder.push_spec(create_hollywood_send_tool());
        builder.push_spec(create_hollywood_team_up_tool());
        builder.push_spec(create_hollywood_team_status_tool());
        builder.push_spec(create_hollywood_team_member_update_tool());
        builder.register_handler("hollywood_status", Arc::new(HollywoodStatusHandler));
        builder.register_handler("hollywood_read", Arc::new(HollywoodReadHandler));
        builder.register_handler("hollywood_send", Arc::new(HollywoodSendHandler));
        builder.register_handler("hollywood_team_up", Arc::new(HollywoodTeamUpHandler));
        builder.register_handler(
            "hollywood_team_status",
            Arc::new(HollywoodTeamStatusHandler),
        );
        builder.register_handler(
            "hollywood_team_member_update",
            Arc::new(HollywoodTeamMemberUpdateHandler),
        );
    }
    builder
}

#[cfg(test)]
#[path = "spec_tests.rs"]
mod tests;
