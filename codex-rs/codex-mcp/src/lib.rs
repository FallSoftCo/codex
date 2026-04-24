pub(crate) mod mcp;
pub(crate) mod mcp_connection_manager;
pub(crate) mod mcp_tool_names;

pub use mcp::CODEX_APPS_MCP_SERVER_NAME;
pub use mcp::McpAuthStatusEntry;
pub use mcp::McpConfig;
pub use mcp::McpManager;
pub use mcp::McpOAuthLoginConfig;
pub use mcp::McpOAuthLoginSupport;
pub use mcp::McpOAuthScopesSource;
pub use mcp::McpServerStatusSnapshot;
pub use mcp::McpSnapshotDetail;
pub use mcp::ResolvedMcpOAuthScopes;
pub use mcp::ToolPluginProvenance;
pub use mcp::canonical_mcp_server_key;
pub use mcp::collect_mcp_server_status_snapshot;
pub use mcp::collect_mcp_server_status_snapshot_with_detail;
pub use mcp::collect_mcp_snapshot;
pub use mcp::collect_mcp_snapshot_from_manager;
pub use mcp::collect_mcp_snapshot_from_manager_with_detail;
pub use mcp::collect_mcp_snapshot_with_detail;
pub use mcp::collect_missing_mcp_dependencies;
pub use mcp::compute_auth_statuses;
pub use mcp::configured_mcp_servers;
pub use mcp::discover_supported_scopes;
pub use mcp::effective_mcp_servers;
pub use mcp::group_tools_by_server;
pub use mcp::mcp_permission_prompt_is_auto_approved;
pub use mcp::oauth_login_support;
pub use mcp::qualified_mcp_tool_name_prefix;
pub use mcp::read_mcp_resource;
pub use mcp::resolve_oauth_scopes;
pub use mcp::should_retry_without_scopes;
pub use mcp::split_qualified_tool_name;
pub use mcp::tool_plugin_provenance;
pub use mcp::with_codex_apps_mcp;
pub use mcp_connection_manager::CodexAppsToolsCacheKey;
pub use mcp_connection_manager::DEFAULT_STARTUP_TIMEOUT;
pub use mcp_connection_manager::MCP_SANDBOX_STATE_META_CAPABILITY;
pub use mcp_connection_manager::McpConnectionManager;
pub use mcp_connection_manager::McpRuntimeEnvironment;
pub use mcp_connection_manager::SandboxState;
pub use mcp_connection_manager::ToolInfo;
pub use mcp_connection_manager::codex_apps_tools_cache_key;
pub use mcp_connection_manager::declared_openai_file_input_param_names;
pub use mcp_connection_manager::filter_non_codex_apps_mcp_tools_only;

pub fn effective_mcp_servers_with_authorization_header(
    config: &McpConfig,
    auth: Option<&codex_login::CodexAuth>,
    _authorization_header_value: Option<&str>,
) -> std::collections::HashMap<String, codex_config::McpServerConfig> {
    mcp::effective_mcp_servers(config, auth)
}

pub fn with_codex_apps_mcp_with_authorization_header(
    servers: std::collections::HashMap<String, codex_config::McpServerConfig>,
    auth: Option<&codex_login::CodexAuth>,
    _authorization_header_value: Option<&str>,
    config: &McpConfig,
) -> std::collections::HashMap<String, codex_config::McpServerConfig> {
    mcp::with_codex_apps_mcp(servers, auth, config)
}

pub async fn collect_mcp_snapshot_with_detail_and_authorization_header(
    config: &McpConfig,
    auth: Option<&codex_login::CodexAuth>,
    submit_id: String,
    runtime_environment: McpRuntimeEnvironment,
    detail: McpSnapshotDetail,
    _authorization_header_value: Option<&str>,
) -> codex_protocol::protocol::McpListToolsResponseEvent {
    mcp::collect_mcp_snapshot_with_detail(config, auth, submit_id, runtime_environment, detail)
        .await
}

pub async fn collect_mcp_server_status_snapshot_with_detail_and_authorization_header(
    config: &McpConfig,
    auth: Option<&codex_login::CodexAuth>,
    submit_id: String,
    runtime_environment: McpRuntimeEnvironment,
    detail: McpSnapshotDetail,
    _authorization_header_value: Option<&str>,
) -> McpServerStatusSnapshot {
    mcp::collect_mcp_server_status_snapshot_with_detail(
        config,
        auth,
        submit_id,
        runtime_environment,
        detail,
    )
    .await
}
