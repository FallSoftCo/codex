use chrono::DateTime;
use chrono::Duration;
use chrono::Utc;
use futures::SinkExt;
use futures::StreamExt;
use reqwest::Client;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use serde_json::json;
use std::collections::HashSet;
use std::env;
use std::fs;
use std::time::Duration as StdDuration;
use tokio::net::TcpStream;
use tokio::time::timeout;
use tokio_tungstenite::MaybeTlsStream;
use tokio_tungstenite::WebSocketStream;
use tokio_tungstenite::connect_async;
use tokio_tungstenite::tungstenite::Message;

use crate::function_tool::FunctionCallError;
use crate::hollywood::HollywoodSessionConfig;
use crate::hollywood::canonicalize_agent_identity;
use crate::hollywood::canonicalize_hollywood_identity;
use crate::hollywood::identities as hollywood_identities;
use crate::hollywood::live_identity_matches_target;
use crate::hollywood::parse_agent_mentions;
use crate::tools::context::FunctionToolOutput;
use crate::tools::context::ToolInvocation;
use crate::tools::context::ToolPayload;
use crate::tools::context::boxed_tool_output;
use crate::tools::handlers::parse_arguments;
use crate::tools::losangelex_spec::create_hollywood_read_tool;
use crate::tools::losangelex_spec::create_hollywood_send_tool;
use crate::tools::losangelex_spec::create_hollywood_status_tool;
use crate::tools::losangelex_spec::create_hollywood_team_member_update_tool;
use crate::tools::losangelex_spec::create_hollywood_team_status_tool;
use crate::tools::losangelex_spec::create_hollywood_team_up_tool;
use crate::tools::losangelex_spec::create_losangelex_team_launch_tool;
use crate::tools::registry::ToolExecutor;
use codex_tools::ToolName;
use codex_tools::ToolSpec;

pub struct HollywoodStatusHandler;
pub struct HollywoodReadHandler;
pub struct HollywoodSendHandler;
pub struct HollywoodTeamUpHandler;
pub struct HollywoodTeamStatusHandler;
pub struct HollywoodTeamMemberUpdateHandler;
pub struct LosangelexTeamLaunchHandler;

const HOLLYWOOD_REGISTRY_STALE_AFTER: Duration = Duration::seconds(90);
const HOLLYWOOD_ROOM_CONTRACT_VERSION: &str = "losangelex-room/v2";
const LOSANGELEX_APP_SERVER_URL_ENV_VAR: &str = "LOSANGELEX_APP_SERVER_URL";
const LOSANGELEX_APP_SERVER_STATE_FILE_ENV_VAR: &str = "LOSANGELEX_APP_SERVER_STATE_FILE";
const MAX_TEAM_LAUNCH_AGENTS: usize = 8;
const MAX_TEAM_LAUNCH_AGENT_NAME_CHARS: usize = 80;
const MAX_TEAM_LAUNCH_TASK_CHARS: usize = 8_000;
const APP_SERVER_REQUEST_TIMEOUT: StdDuration = StdDuration::from_secs(120);
const LOSANGELEX_TEAM_TASK_GUIDANCE: &str = "Losangelex team communication expectation:
- Hollywood is the shared working room for this team, not just an emergency channel.
- Before starting your lane, send one concise Hollywood message in your own voice saying what you are taking up and when you expect to report back.
- If you change direction, become blocked, need attention, or finish, send a concise Hollywood update before or alongside your final answer.
- These work-state messages are not chatter; they are how teammates know the team is active.

Dependency-aware communication expectation:
- If your lane verifies, summarizes, reviews, or integrates another lane, do not finalize from stale assumptions.
- Before finishing dependency-sensitive work, read recent Hollywood updates and inspect the relevant workspace files after the producing lane has had a chance to report.
- If the dependency has not reported yet, wait briefly or state exactly what evidence you used and what remains uncertain.
- Your finish message should name the dependency evidence you relied on when another lane affects your result.
";

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
    to: Option<String>,
    broadcast: Option<bool>,
    response_policy: Option<String>,
}

#[derive(Deserialize)]
struct HollywoodTeamUpArgs {
    purpose: String,
    room: Option<String>,
    task_room: Option<String>,
    team_id: Option<String>,
    targets: Vec<String>,
}

#[derive(Deserialize)]
struct HollywoodTeamStatusArgs {
    room: Option<String>,
    limit: Option<u32>,
}

#[derive(Deserialize)]
struct HollywoodTeamMemberUpdateArgs {
    team_id: String,
    session_id: Option<String>,
    role: Option<String>,
    state: Option<String>,
    joined_room: Option<String>,
    task: Option<String>,
    scope: Option<String>,
}

#[derive(Deserialize)]
struct LosangelexTeamLaunchArgs {
    agents: Vec<LosangelexPeerLaunchSpec>,
    workspace: Option<String>,
    room: Option<String>,
    observed_rooms: Option<Vec<String>>,
    wake_rooms: Option<Vec<String>>,
    attention_mode: Option<String>,
    model: Option<String>,
    model_provider: Option<String>,
    start_turns: Option<bool>,
}

#[derive(Clone, Deserialize)]
struct LosangelexPeerLaunchSpec {
    name: String,
    task: String,
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
    service_version: Option<String>,
    schema_version: Option<i64>,
    room_contract_version: Option<String>,
    room_contract_compatible: Option<bool>,
    error: Option<String>,
}

#[derive(Deserialize, Default)]
struct HollywoodHealthResponse {
    #[serde(default)]
    service_version: Option<String>,
    #[serde(default)]
    schema_version: Option<i64>,
    #[serde(default)]
    room_contract_version: Option<String>,
}

#[derive(Serialize)]
struct HollywoodReadResult {
    url: String,
    room: String,
    identities: Vec<String>,
    peers: Vec<HollywoodPeerSummary>,
    peer_registry_error: Option<String>,
    messages: serde_json::Value,
}

#[derive(Serialize)]
struct HollywoodPeerSummary {
    session_id: String,
    identities: Vec<String>,
    status: Option<String>,
    session_kind: Option<String>,
    attention_mode: Option<String>,
    updated_at: Option<String>,
    last_heartbeat_at: Option<String>,
}

#[derive(Serialize)]
struct HollywoodSendResult {
    url: String,
    room: String,
    sender_id: String,
    recipient_id: Option<String>,
    message_kind: String,
    response_policy: Option<String>,
    text: String,
    ok: bool,
}

#[derive(Serialize)]
struct HollywoodTeamUpResult {
    url: String,
    room: String,
    team: serde_json::Value,
    ok: bool,
    error: Option<String>,
}

#[derive(Serialize)]
struct HollywoodTeamStatusResult {
    url: String,
    room: String,
    teams: serde_json::Value,
}

#[derive(Serialize)]
struct HollywoodTeamMemberUpdateResult {
    url: String,
    member: serde_json::Value,
}

#[derive(Serialize)]
struct LosangelexTeamLaunchResult {
    ok: bool,
    error: Option<String>,
    app_server_url: String,
    workspace: String,
    hollywood: LosangelexTeamLaunchHollywoodResult,
    start_turns: bool,
    agents: Vec<LaunchedLosangelexPeer>,
}

#[derive(Serialize)]
struct LosangelexTeamLaunchHollywoodResult {
    url: String,
    room: String,
    observed_rooms: Vec<String>,
    wake_rooms: Vec<String>,
    attention_mode: String,
}

#[derive(Serialize)]
struct LaunchedLosangelexPeer {
    name: String,
    thread_id: String,
    turn_started: bool,
}

#[derive(Deserialize)]
struct AppServerStateFile {
    websocket_url: Option<String>,
}

#[derive(Deserialize)]
struct HollywoodRegistryListResponse {
    entries: Vec<HollywoodRegistryEntry>,
}

#[derive(Deserialize, Default)]
struct HollywoodRegistryEntry {
    session_id: String,
    attached: bool,
    identities: Vec<String>,
    status: Option<String>,
    session_kind: Option<String>,
    attention_mode: Option<String>,
    updated_at: Option<String>,
    last_heartbeat_at: Option<String>,
}

async fn hollywood_config_for_session(
    session: &crate::session::session::Session,
) -> Option<HollywoodSessionConfig> {
    session.hollywood_session_config().await
}

impl ToolExecutor<ToolInvocation> for HollywoodStatusHandler {
    fn tool_name(&self) -> ToolName {
        ToolName::new(None, "hollywood_status".to_string())
    }

    fn spec(&self) -> ToolSpec {
        create_hollywood_status_tool()
    }

    fn handle(&self, invocation: ToolInvocation) -> codex_tools::ToolExecutorFuture<'_> {
        Box::pin(async move {
            let output = async {
                let config = hollywood_config_for_session(invocation.session.as_ref()).await;
                let thread_name = invocation.session.thread_name().await;
                let identities =
                    hollywood_identities(invocation.session.thread_id(), thread_name.as_deref());
                let result = if let Some(config) = config {
                    let health_url =
                        format!("{}/hollywood/v1/health", config.url.trim_end_matches('/'));
                    match Client::new().get(health_url).send().await {
                        Ok(response) => {
                            let reachable = response.status().is_success();
                            let health = response.json::<HollywoodHealthResponse>().await.ok();
                            let room_contract_version = health
                                .as_ref()
                                .and_then(|value| value.room_contract_version.clone());
                            HollywoodStatusResult {
                                configured: true,
                                reachable,
                                url: Some(config.url),
                                room: Some(config.room),
                                attention_mode: Some(config.attention_mode),
                                identities,
                                can_read: true,
                                can_send: true,
                                service_version: health
                                    .as_ref()
                                    .and_then(|value| value.service_version.clone()),
                                schema_version: health
                                    .as_ref()
                                    .and_then(|value| value.schema_version),
                                room_contract_version: room_contract_version.clone(),
                                room_contract_compatible: room_contract_version
                                    .as_ref()
                                    .map(|value| value == HOLLYWOOD_ROOM_CONTRACT_VERSION),
                                error: None,
                            }
                        }
                        Err(err) => HollywoodStatusResult {
                            configured: true,
                            reachable: false,
                            url: Some(config.url),
                            room: Some(config.room),
                            attention_mode: Some(config.attention_mode),
                            identities,
                            can_read: true,
                            can_send: true,
                            service_version: None,
                            schema_version: None,
                            room_contract_version: None,
                            room_contract_compatible: None,
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
                        service_version: None,
                        schema_version: None,
                        room_contract_version: None,
                        room_contract_compatible: None,
                        error: Some("Hollywood is not configured for this session.".to_string()),
                    }
                };

                Ok(FunctionToolOutput::from_text(
                    serde_json::to_string_pretty(&result).unwrap_or_else(|err| {
                        format!("failed to serialize hollywood status: {err}")
                    }),
                    Some(true),
                ))
            }
            .await?;
            Ok(boxed_tool_output(output))
        })
    }
}

impl ToolExecutor<ToolInvocation> for HollywoodReadHandler {
    fn tool_name(&self) -> ToolName {
        ToolName::new(None, "hollywood_read".to_string())
    }

    fn spec(&self) -> ToolSpec {
        create_hollywood_read_tool()
    }

    fn handle(&self, invocation: ToolInvocation) -> codex_tools::ToolExecutorFuture<'_> {
        Box::pin(async move {
            let output = async {
                let args = parse_function_args::<HollywoodReadArgs>(&invocation.payload)?;
                let Some(config) = hollywood_config_for_session(invocation.session.as_ref()).await
                else {
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
                        FunctionCallError::RespondToModel(format!(
                            "Hollywood response parse failed: {err}"
                        ))
                    })?;
                let thread_name = invocation.session.thread_name().await;
                let self_session_id = invocation.session.thread_id().to_string();
                let (peers, peer_registry_error) =
                    match fetch_registry_entries(&config, &room).await {
                        Ok(entries) => (
                            entries
                                .into_iter()
                                .filter(|entry| entry.session_id != self_session_id)
                                .map(|entry| HollywoodPeerSummary {
                                    session_id: entry.session_id,
                                    identities: entry.identities,
                                    status: entry.status,
                                    session_kind: entry.session_kind,
                                    attention_mode: entry.attention_mode,
                                    updated_at: entry.updated_at,
                                    last_heartbeat_at: entry.last_heartbeat_at,
                                })
                                .collect(),
                            None,
                        ),
                        Err(err) => (Vec::new(), Some(err)),
                    };

                let result = HollywoodReadResult {
                    url: config.url,
                    room,
                    identities: hollywood_identities(
                        invocation.session.thread_id(),
                        thread_name.as_deref(),
                    ),
                    peers,
                    peer_registry_error,
                    messages: response,
                };

                Ok(FunctionToolOutput::from_text(
                    serde_json::to_string_pretty(&result)
                        .unwrap_or_else(|err| format!("failed to serialize hollywood read: {err}")),
                    Some(true),
                ))
            }
            .await?;
            Ok(boxed_tool_output(output))
        })
    }
}

impl ToolExecutor<ToolInvocation> for LosangelexTeamLaunchHandler {
    fn tool_name(&self) -> ToolName {
        ToolName::new(None, "losangelex_team_launch".to_string())
    }

    fn spec(&self) -> ToolSpec {
        create_losangelex_team_launch_tool()
    }

    fn handle(&self, invocation: ToolInvocation) -> codex_tools::ToolExecutorFuture<'_> {
        Box::pin(async move {
            let output = async {
                let mut args =
                    parse_function_args::<LosangelexTeamLaunchArgs>(&invocation.payload)?;
                let Some(config) = hollywood_config_for_session(invocation.session.as_ref()).await
                else {
                    return Err(FunctionCallError::RespondToModel(
                        "Hollywood is not configured for this session.".to_string(),
                    ));
                };

                validate_peer_launch_specs(&args.agents)
                    .map_err(FunctionCallError::RespondToModel)?;
                let app_server_url = resolve_losangelex_app_server_url()
                    .map_err(FunctionCallError::RespondToModel)?;
                let workspace = args.workspace.take().unwrap_or_else(|| {
                    invocation
                        .turn
                        .environments
                        .single_local_environment_cwd()
                        .unwrap_or_else(|| invocation.turn.config.cwd.clone())
                        .to_string_lossy()
                        .into_owned()
                });
                let room = args.room.take().unwrap_or_else(|| config.room.clone());
                let observed_rooms = args
                    .observed_rooms
                    .take()
                    .unwrap_or_else(|| config.observed_rooms.clone());
                let wake_rooms = args
                    .wake_rooms
                    .take()
                    .unwrap_or_else(|| config.wake_rooms.clone());
                let attention_mode =
                    normalize_attention_mode(args.attention_mode.as_deref(), &config)
                        .map_err(FunctionCallError::RespondToModel)?;
                let start_turns = args.start_turns.unwrap_or(true);
                let mut client = AppServerJsonRpcClient::connect(&app_server_url)
                    .await
                    .map_err(FunctionCallError::RespondToModel)?;
                client
                    .initialize()
                    .await
                    .map_err(FunctionCallError::RespondToModel)?;

                let mut launched = Vec::with_capacity(args.agents.len());
                let mut error = None;
                for peer in &args.agents {
                    match launch_losangelex_peer(
                        &mut client,
                        PeerLaunchRequest {
                            peer,
                            workspace: &workspace,
                            hollywood_url: &config.url,
                            room: &room,
                            observed_rooms: &observed_rooms,
                            wake_rooms: &wake_rooms,
                            attention_mode: &attention_mode,
                            model: args.model.as_deref(),
                            model_provider: args.model_provider.as_deref(),
                            start_turns,
                        },
                    )
                    .await
                    {
                        Ok(peer) => launched.push(peer),
                        Err(err) => {
                            error = Some(err);
                            break;
                        }
                    }
                }

                let ok = error.is_none();
                let result = LosangelexTeamLaunchResult {
                    ok,
                    error,
                    app_server_url,
                    workspace,
                    hollywood: LosangelexTeamLaunchHollywoodResult {
                        url: config.url,
                        room,
                        observed_rooms,
                        wake_rooms,
                        attention_mode,
                    },
                    start_turns,
                    agents: launched,
                };

                Ok(FunctionToolOutput::from_text(
                    serde_json::to_string_pretty(&result).unwrap_or_else(|err| {
                        format!("failed to serialize losangelex team launch: {err}")
                    }),
                    Some(ok),
                ))
            }
            .await?;
            Ok(boxed_tool_output(output))
        })
    }
}

impl ToolExecutor<ToolInvocation> for HollywoodSendHandler {
    fn tool_name(&self) -> ToolName {
        ToolName::new(None, "hollywood_send".to_string())
    }

    fn spec(&self) -> ToolSpec {
        create_hollywood_send_tool(/*state_db_available*/ false)
    }

    fn handle(&self, invocation: ToolInvocation) -> codex_tools::ToolExecutorFuture<'_> {
        Box::pin(async move {
            let output = async {
                let args = parse_function_args::<HollywoodSendArgs>(&invocation.payload)?;
                let Some(config) = hollywood_config_for_session(invocation.session.as_ref()).await
                else {
                    return Err(FunctionCallError::RespondToModel(
                        "Hollywood is not configured for this session.".to_string(),
                    ));
                };

                let target_identities = resolve_target_identities(&args);
                let room = select_send_room(&config, &args, &target_identities)
                    .await
                    .map_err(FunctionCallError::RespondToModel)?;
                let sender_id = invocation.session.thread_id().to_string();
                let url = format!("{}/hollywood/v1/messages", config.url.trim_end_matches('/'));
                let recipient_id = args.to.as_deref().and_then(canonicalize_hollywood_identity);
                let text = args.text.clone();
                let response_policy = args.response_policy.clone();
                let message_kind = if args.broadcast.unwrap_or(false) {
                    "broadcast".to_string()
                } else if recipient_id.is_some() {
                    "direct".to_string()
                } else {
                    "ambient".to_string()
                };

                Client::new()
                    .post(&url)
                    .json(&json!({
                        "room": room,
                        "sender_id": sender_id,
                        "recipient_id": recipient_id,
                        "message_kind": message_kind,
                        "response_policy": response_policy,
                        "body": text,
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

                invocation
                    .session
                    .mark_hollywood_send_for_turn(&invocation.turn.sub_id, &room)
                    .await;

                let result = HollywoodSendResult {
                    url: config.url,
                    room,
                    sender_id,
                    recipient_id,
                    message_kind,
                    response_policy,
                    text,
                    ok: true,
                };

                Ok(FunctionToolOutput::from_text(
                    serde_json::to_string_pretty(&result)
                        .unwrap_or_else(|err| format!("failed to serialize hollywood send: {err}")),
                    Some(true),
                ))
            }
            .await?;
            Ok(boxed_tool_output(output))
        })
    }
}

impl ToolExecutor<ToolInvocation> for HollywoodTeamUpHandler {
    fn tool_name(&self) -> ToolName {
        ToolName::new(None, "hollywood_team_up".to_string())
    }

    fn spec(&self) -> ToolSpec {
        create_hollywood_team_up_tool()
    }

    fn handle(&self, invocation: ToolInvocation) -> codex_tools::ToolExecutorFuture<'_> {
        Box::pin(async move {
            let output = async {
        let args = parse_function_args::<HollywoodTeamUpArgs>(&invocation.payload)?;
        let Some(config) = hollywood_config_for_session(invocation.session.as_ref()).await else {
            return Err(FunctionCallError::RespondToModel(
                "Hollywood is not configured for this session.".to_string(),
            ));
        };

        if args.targets.is_empty() {
            return Err(FunctionCallError::RespondToModel(
                "hollywood_team_up requires at least one target session id.".to_string(),
            ));
        }

        let room = args.room.unwrap_or_else(|| "main".to_string());
        let members = args
            .targets
            .iter()
            .filter_map(|target| canonicalize_agent_identity(target))
            .map(|session_id| {
                json!({
                    "session_id": session_id,
                    "role": "member",
                    "state": "pending",
                })
            })
            .collect::<Vec<_>>();

        let url = format!("{}/hollywood/v1/teams", config.url.trim_end_matches('/'));
        let response = match Client::new()
            .post(&url)
            .json(&json!({
                "team_id": args.team_id,
                "room": room,
                "task_room": args.task_room,
                "purpose": args.purpose,
                "leader_session_id": invocation.session.thread_id().to_string(),
                "members": members,
            }))
            .send()
            .await
        {
            Ok(response) => response,
            Err(err) => {
                let result = HollywoodTeamUpResult {
                    url: config.url,
                    room,
                    team: json!(null),
                    ok: false,
                    error: Some(format!("Hollywood team create failed: {err}")),
                };
                return Ok(FunctionToolOutput::from_text(
                    serde_json::to_string_pretty(&result).unwrap_or_else(|serialize_err| {
                        format!(
                            "{{\"ok\":false,\"error\":\"Hollywood team create failed: {err}; serialization failed: {serialize_err}\"}}"
                        )
                    }),
                    Some(false),
                ));
            }
        };
        let response = match response.error_for_status() {
            Ok(response) => response,
            Err(err) => {
                let result = HollywoodTeamUpResult {
                    url: config.url,
                    room,
                    team: json!(null),
                    ok: false,
                    error: Some(format!("Hollywood team create failed: {err}")),
                };
                return Ok(FunctionToolOutput::from_text(
                    serde_json::to_string_pretty(&result).unwrap_or_else(|serialize_err| {
                        format!(
                            "{{\"ok\":false,\"error\":\"Hollywood team create failed: {err}; serialization failed: {serialize_err}\"}}"
                        )
                    }),
                    Some(false),
                ));
            }
        };
        let response = match response.json::<serde_json::Value>().await {
            Ok(response) => response,
            Err(err) => {
                let result = HollywoodTeamUpResult {
                    url: config.url,
                    room,
                    team: json!(null),
                    ok: false,
                    error: Some(format!("Hollywood team response parse failed: {err}")),
                };
                return Ok(FunctionToolOutput::from_text(
                    serde_json::to_string_pretty(&result).unwrap_or_else(|serialize_err| {
                        format!(
                            "{{\"ok\":false,\"error\":\"Hollywood team response parse failed: {err}; serialization failed: {serialize_err}\"}}"
                        )
                    }),
                    Some(false),
                ));
            }
        };

        let result = HollywoodTeamUpResult {
            url: config.url,
            room,
            team: response,
            ok: true,
            error: None,
        };

        Ok(FunctionToolOutput::from_text(
            serde_json::to_string_pretty(&result)
                .unwrap_or_else(|err| format!("failed to serialize hollywood team create: {err}")),
            Some(true),
        ))
        }
            .await?;
            Ok(boxed_tool_output(output))
        })
    }
}

impl ToolExecutor<ToolInvocation> for HollywoodTeamStatusHandler {
    fn tool_name(&self) -> ToolName {
        ToolName::new(None, "hollywood_team_status".to_string())
    }

    fn spec(&self) -> ToolSpec {
        create_hollywood_team_status_tool()
    }

    fn handle(&self, invocation: ToolInvocation) -> codex_tools::ToolExecutorFuture<'_> {
        Box::pin(async move {
            let output = async {
                let args = parse_function_args::<HollywoodTeamStatusArgs>(&invocation.payload)?;
                let Some(config) = hollywood_config_for_session(invocation.session.as_ref()).await
                else {
                    return Err(FunctionCallError::RespondToModel(
                        "Hollywood is not configured for this session.".to_string(),
                    ));
                };

                let room = args.room.unwrap_or_else(|| config.room.clone());
                let limit = args.limit.unwrap_or(20).clamp(1, 100);
                let url = format!("{}/hollywood/v1/teams", config.url.trim_end_matches('/'));
                let response = Client::new()
                    .get(&url)
                    .query(&[("room", room.as_str()), ("limit", &limit.to_string())])
                    .send()
                    .await
                    .map_err(|err| {
                        FunctionCallError::RespondToModel(format!(
                            "Hollywood team read failed: {err}"
                        ))
                    })?
                    .error_for_status()
                    .map_err(|err| {
                        FunctionCallError::RespondToModel(format!(
                            "Hollywood team read failed: {err}"
                        ))
                    })?
                    .json::<serde_json::Value>()
                    .await
                    .map_err(|err| {
                        FunctionCallError::RespondToModel(format!(
                            "Hollywood team response parse failed: {err}"
                        ))
                    })?;

                let result = HollywoodTeamStatusResult {
                    url: config.url,
                    room,
                    teams: response,
                };

                Ok(FunctionToolOutput::from_text(
                    serde_json::to_string_pretty(&result).unwrap_or_else(|err| {
                        format!("failed to serialize hollywood team read: {err}")
                    }),
                    Some(true),
                ))
            }
            .await?;
            Ok(boxed_tool_output(output))
        })
    }
}

impl ToolExecutor<ToolInvocation> for HollywoodTeamMemberUpdateHandler {
    fn tool_name(&self) -> ToolName {
        ToolName::new(None, "hollywood_team_member_update".to_string())
    }

    fn spec(&self) -> ToolSpec {
        create_hollywood_team_member_update_tool()
    }

    fn handle(&self, invocation: ToolInvocation) -> codex_tools::ToolExecutorFuture<'_> {
        Box::pin(async move {
            let output = async {
                let args =
                    parse_function_args::<HollywoodTeamMemberUpdateArgs>(&invocation.payload)?;
                let Some(config) = hollywood_config_for_session(invocation.session.as_ref()).await
                else {
                    return Err(FunctionCallError::RespondToModel(
                        "Hollywood is not configured for this session.".to_string(),
                    ));
                };

                let session_id = match args.session_id.as_deref() {
                    Some(value) => resolve_team_member_session_id(&config, value).await?,
                    None => invocation.session.thread_id().to_string(),
                };

                let url = format!(
                    "{}/hollywood/v1/team-members",
                    config.url.trim_end_matches('/')
                );
                let response = Client::new()
                    .post(&url)
                    .json(&json!({
                        "team_id": args.team_id,
                        "session_id": session_id,
                        "role": args.role,
                        "state": args.state,
                        "joined_room": args.joined_room,
                        "task": args.task,
                        "scope": args.scope,
                    }))
                    .send()
                    .await
                    .map_err(|err| {
                        FunctionCallError::RespondToModel(format!(
                            "Hollywood team member update failed: {err}"
                        ))
                    })?
                    .error_for_status()
                    .map_err(|err| {
                        FunctionCallError::RespondToModel(format!(
                            "Hollywood team member update failed: {err}"
                        ))
                    })?
                    .json::<serde_json::Value>()
                    .await
                    .map_err(|err| {
                        FunctionCallError::RespondToModel(format!(
                            "Hollywood team member response parse failed: {err}"
                        ))
                    })?;

                let result = HollywoodTeamMemberUpdateResult {
                    url: config.url,
                    member: response,
                };

                Ok(FunctionToolOutput::from_text(
                    serde_json::to_string_pretty(&result).unwrap_or_else(|err| {
                        format!("failed to serialize hollywood team member update: {err}")
                    }),
                    Some(true),
                ))
            }
            .await?;
            Ok(boxed_tool_output(output))
        })
    }
}

struct PeerLaunchRequest<'a> {
    peer: &'a LosangelexPeerLaunchSpec,
    workspace: &'a str,
    hollywood_url: &'a str,
    room: &'a str,
    observed_rooms: &'a [String],
    wake_rooms: &'a [String],
    attention_mode: &'a str,
    model: Option<&'a str>,
    model_provider: Option<&'a str>,
    start_turns: bool,
}

struct AppServerJsonRpcClient {
    websocket: WebSocketStream<MaybeTlsStream<TcpStream>>,
    next_id: u64,
}

impl AppServerJsonRpcClient {
    async fn connect(app_server_url: &str) -> Result<Self, String> {
        let (websocket, _) = connect_async(app_server_url)
            .await
            .map_err(|err| format!("failed to connect to Losangelex app-server: {err}"))?;
        Ok(Self {
            websocket,
            next_id: 1,
        })
    }

    async fn initialize(&mut self) -> Result<(), String> {
        self.request(
            "initialize",
            json!({
                "clientInfo": {
                    "name": "losangelex-team-launch",
                    "title": "Losangelex Team Launch Tool",
                    "version": "0.1",
                },
                "capabilities": {
                    "experimentalApi": true,
                },
            }),
        )
        .await?;
        self.notification("initialized", json!({})).await
    }

    async fn notification(&mut self, method: &str, params: Value) -> Result<(), String> {
        self.send_json(json!({
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }))
        .await
    }

    async fn request(&mut self, method: &str, params: Value) -> Result<Value, String> {
        let request_id = self.next_id;
        self.next_id += 1;
        self.send_json(json!({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }))
        .await?;

        loop {
            let message = timeout(APP_SERVER_REQUEST_TIMEOUT, self.websocket.next())
                .await
                .map_err(|_| {
                    format!("timed out waiting for Losangelex app-server response to {method}")
                })?
                .ok_or_else(|| {
                    format!("Losangelex app-server websocket closed before {method} completed")
                })?
                .map_err(|err| format!("Losangelex app-server websocket read failed: {err}"))?;
            let Some(text) = websocket_message_text(message)? else {
                continue;
            };
            let response = serde_json::from_str::<Value>(&text).map_err(|err| {
                format!("Losangelex app-server returned invalid JSON for {method}: {err}")
            })?;
            if response.get("id") != Some(&json!(request_id)) {
                continue;
            }
            if let Some(error) = response.get("error") {
                return Err(format!("{method} failed: {error}"));
            }
            return Ok(response.get("result").cloned().unwrap_or(Value::Null));
        }
    }

    async fn send_json(&mut self, value: Value) -> Result<(), String> {
        self.websocket
            .send(Message::Text(value.to_string().into()))
            .await
            .map_err(|err| format!("Losangelex app-server websocket write failed: {err}"))
    }
}

async fn launch_losangelex_peer(
    client: &mut AppServerJsonRpcClient,
    request: PeerLaunchRequest<'_>,
) -> Result<LaunchedLosangelexPeer, String> {
    let thread = client
        .request("thread/start", thread_start_params(&request))
        .await?;
    let thread_id = thread
        .pointer("/thread/id")
        .and_then(Value::as_str)
        .ok_or_else(|| "thread/start response did not include thread.id".to_string())?
        .to_string();

    client
        .request(
            "thread/name/set",
            json!({
                "threadId": thread_id.as_str(),
                "name": request.peer.name.as_str(),
            }),
        )
        .await?;
    client
        .request(
            "thread/hollywood/attach",
            json!({
                "threadId": thread_id.as_str(),
                "url": request.hollywood_url,
                "room": request.room,
                "observedRooms": request.observed_rooms,
                "wakeRooms": request.wake_rooms,
                "attention": {
                    "mode": request.attention_mode,
                    "includeAtAll": true,
                    "includeAtRoom": true,
                },
            }),
        )
        .await?;
    if request.start_turns {
        let task_text = launched_peer_task_prompt(request.peer.task.as_str());
        client
            .request(
                "turn/start",
                json!({
                    "threadId": thread_id.as_str(),
                    "input": [
                        {
                            "type": "text",
                            "text": task_text.as_str(),
                        }
                    ],
                }),
            )
            .await?;
    }

    Ok(LaunchedLosangelexPeer {
        name: request.peer.name.clone(),
        thread_id,
        turn_started: request.start_turns,
    })
}

fn launched_peer_task_prompt(task: &str) -> String {
    if task.contains("Losangelex team communication expectation:") {
        return task.to_string();
    }
    format!("{LOSANGELEX_TEAM_TASK_GUIDANCE}\n{task}")
}

fn thread_start_params(request: &PeerLaunchRequest<'_>) -> Value {
    let mut params = json!({
        "cwd": request.workspace,
        "approvalPolicy": "never",
        "sandbox": "danger-full-access",
        "serviceName": "losangelex-team",
    });
    if let Some(model) = request.model {
        params["model"] = Value::String(model.to_string());
    }
    if let Some(model_provider) = request.model_provider {
        params["modelProvider"] = Value::String(model_provider.to_string());
    }
    params
}

fn websocket_message_text(message: Message) -> Result<Option<String>, String> {
    match message {
        Message::Text(text) => Ok(Some(text.to_string())),
        Message::Binary(bytes) => String::from_utf8(bytes.to_vec())
            .map(Some)
            .map_err(|err| format!("Losangelex app-server returned non-UTF8 binary JSON: {err}")),
        Message::Ping(_) | Message::Pong(_) | Message::Frame(_) => Ok(None),
        Message::Close(_) => Err("Losangelex app-server websocket closed".to_string()),
    }
}

fn validate_peer_launch_specs(peers: &[LosangelexPeerLaunchSpec]) -> Result<(), String> {
    if peers.is_empty() {
        return Err("losangelex_team_launch requires at least one agent.".to_string());
    }
    if peers.len() > MAX_TEAM_LAUNCH_AGENTS {
        return Err(format!(
            "losangelex_team_launch accepts at most {MAX_TEAM_LAUNCH_AGENTS} agents per call."
        ));
    }
    for peer in peers {
        if peer.name.trim().is_empty() {
            return Err("losangelex_team_launch agent names must be non-empty.".to_string());
        }
        if peer.name.chars().count() > MAX_TEAM_LAUNCH_AGENT_NAME_CHARS {
            return Err(format!(
                "losangelex_team_launch agent name `{}` is too long; max is {MAX_TEAM_LAUNCH_AGENT_NAME_CHARS} characters.",
                peer.name
            ));
        }
        if peer.task.trim().is_empty() {
            return Err(format!(
                "losangelex_team_launch task for `{}` must be non-empty.",
                peer.name
            ));
        }
        if peer.task.chars().count() > MAX_TEAM_LAUNCH_TASK_CHARS {
            return Err(format!(
                "losangelex_team_launch task for `{}` is too long; max is {MAX_TEAM_LAUNCH_TASK_CHARS} characters.",
                peer.name
            ));
        }
    }
    Ok(())
}

fn normalize_attention_mode(
    requested: Option<&str>,
    config: &HollywoodSessionConfig,
) -> Result<String, String> {
    let mode = requested
        .unwrap_or(config.attention_mode.as_str())
        .to_lowercase();
    match mode.as_str() {
        "focused" | "ambient" | "broad" => Ok(mode),
        _ => Err(format!(
            "invalid Hollywood attention mode `{mode}`; expected focused, ambient, or broad."
        )),
    }
}

fn resolve_losangelex_app_server_url() -> Result<String, String> {
    if let Ok(value) = env::var(LOSANGELEX_APP_SERVER_URL_ENV_VAR)
        && !value.trim().is_empty()
    {
        return Ok(value);
    }

    let state_file = match env::var(LOSANGELEX_APP_SERVER_STATE_FILE_ENV_VAR) {
        Ok(value) if !value.trim().is_empty() => std::path::PathBuf::from(value),
        _ => codex_utils_home_dir::find_codex_home()
            .map_err(|err| format!("failed to resolve CODEX_HOME for app-server state: {err}"))?
            .join("losangelex")
            .join("current-app-server.json")
            .into(),
    };
    let text = fs::read_to_string(&state_file).map_err(|err| {
        format!(
            "{LOSANGELEX_APP_SERVER_URL_ENV_VAR} is not set and app-server state file {} could not be read: {err}",
            state_file.display()
        )
    })?;
    let state = serde_json::from_str::<AppServerStateFile>(&text).map_err(|err| {
        format!(
            "failed to parse app-server state file {}: {err}",
            state_file.display()
        )
    })?;
    state
        .websocket_url
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| {
            format!(
                "app-server state file {} does not contain websocket_url",
                state_file.display()
            )
        })
}

fn resolve_target_identities(args: &HollywoodSendArgs) -> Vec<String> {
    let mut identities = Vec::new();
    let mut seen = HashSet::new();

    if let Some(recipient) = args.to.as_deref().and_then(canonicalize_hollywood_identity) {
        seen.insert(recipient.clone());
        identities.push(recipient);
    }

    for identity in parse_agent_mentions(&args.text) {
        if seen.insert(identity.clone()) {
            identities.push(identity);
        }
    }

    identities
}

async fn select_room_for_targets(
    config: &HollywoodSessionConfig,
    target_identities: &[String],
) -> Result<String, String> {
    if target_identities.is_empty() {
        return Ok(config.room.clone());
    }

    for room in prioritized_candidate_rooms(config) {
        let entries = fetch_registry_entries(config, &room).await?;
        if all_targets_present(target_identities, &entries) {
            return Ok(room);
        }
    }

    Ok("main".to_string())
}

async fn select_send_room(
    config: &HollywoodSessionConfig,
    args: &HollywoodSendArgs,
    target_identities: &[String],
) -> Result<String, String> {
    if let Some(room) = args.room.clone() {
        return Ok(room);
    }
    if !config.room.is_empty() {
        return Ok(config.room.clone());
    }
    select_room_for_targets(config, target_identities).await
}

fn prioritized_candidate_rooms(config: &HollywoodSessionConfig) -> Vec<String> {
    let mut rooms = Vec::new();
    let mut seen = HashSet::new();
    for room in std::iter::once(config.room.as_str())
        .chain(config.observed_rooms.iter().map(String::as_str))
        .chain(std::iter::once("main"))
    {
        if !room.is_empty() && seen.insert(room.to_string()) {
            rooms.push(room.to_string());
        }
    }
    rooms
}

async fn fetch_registry_entries(
    config: &HollywoodSessionConfig,
    room: &str,
) -> Result<Vec<HollywoodRegistryEntry>, String> {
    let url = format!("{}/hollywood/v1/registry", config.url.trim_end_matches('/'));
    Client::new()
        .get(&url)
        .query(&[("room", room), ("limit", "1000")])
        .send()
        .await
        .map_err(|err| format!("Hollywood registry read failed: {err}"))?
        .error_for_status()
        .map_err(|err| format!("Hollywood registry read failed: {err}"))?
        .json::<HollywoodRegistryListResponse>()
        .await
        .map_err(|err| format!("Hollywood registry response parse failed: {err}"))
        .map(|response| {
            let now = Utc::now();
            response
                .entries
                .into_iter()
                .filter(|entry| registry_entry_is_fresh(entry, &now))
                .collect()
        })
}

fn all_targets_present(target_identities: &[String], entries: &[HollywoodRegistryEntry]) -> bool {
    target_identities.iter().all(|target| {
        resolve_live_session_id_from_entries(entries, target)
            .ok()
            .flatten()
            .is_some()
    })
}

async fn resolve_team_member_session_id(
    config: &HollywoodSessionConfig,
    value: &str,
) -> Result<String, FunctionCallError> {
    if let Some(session_id) = canonicalize_agent_identity(value) {
        return Ok(session_id);
    }
    let identity = canonicalize_hollywood_identity(value).ok_or_else(|| {
        FunctionCallError::RespondToModel(
            "invalid session_id for hollywood_team_member_update".to_string(),
        )
    })?;

    for room in prioritized_candidate_rooms(config) {
        let entries = fetch_registry_entries(config, &room)
            .await
            .map_err(FunctionCallError::RespondToModel)?;
        match resolve_live_session_id_from_entries(&entries, &identity)
            .map_err(FunctionCallError::RespondToModel)?
        {
            Some(session_id) => return Ok(session_id),
            None => continue,
        }
    }

    Err(FunctionCallError::RespondToModel(format!(
        "unknown live Hollywood agent `{value}`"
    )))
}

fn resolve_live_session_id_from_entries(
    entries: &[HollywoodRegistryEntry],
    target: &str,
) -> Result<Option<String>, String> {
    let matches = entries
        .iter()
        .filter(|entry| entry.attached)
        .filter(|entry| {
            entry.session_id == target
                || entry
                    .identities
                    .iter()
                    .any(|identity| live_identity_matches_target(identity, target))
        })
        .map(|entry| entry.session_id.clone())
        .collect::<Vec<_>>();

    match matches.len() {
        0 => Ok(None),
        1 => Ok(matches.into_iter().next()),
        _ => Err(format!(
            "Hollywood identity `{target}` is ambiguous across live sessions: {}",
            matches.join(", ")
        )),
    }
}

fn registry_entry_is_fresh(entry: &HollywoodRegistryEntry, now: &DateTime<Utc>) -> bool {
    let cutoff = *now - HOLLYWOOD_REGISTRY_STALE_AFTER;
    let heartbeat_at = entry
        .last_heartbeat_at
        .as_deref()
        .or(entry.updated_at.as_deref());
    heartbeat_at
        .and_then(parse_registry_timestamp)
        .is_some_and(|heartbeat_at| heartbeat_at >= cutoff)
}

fn parse_registry_timestamp(value: &str) -> Option<DateTime<Utc>> {
    DateTime::parse_from_rfc3339(value)
        .ok()
        .map(|parsed| parsed.with_timezone(&Utc))
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

#[cfg(test)]
mod tests {
    use super::*;
    use pretty_assertions::assert_eq;

    fn send_args(text: &str, to: Option<&str>) -> HollywoodSendArgs {
        HollywoodSendArgs {
            text: text.to_string(),
            room: None,
            to: to.map(ToOwned::to_owned),
            broadcast: None,
            response_policy: None,
        }
    }

    #[test]
    fn resolve_target_identities_keeps_named_and_session_id_mentions() {
        let args = send_args(
            "ping @sid-agor-cp2j-755r-fcup-xtau-5phv-we and @scout-agent",
            Some("scout-agent"),
        );

        assert_eq!(
            resolve_target_identities(&args),
            vec![
                "scout-agent".to_string(),
                "019d113f-49ff-7b12-8a8f-bcc14ebcf5b1".to_string(),
            ]
        );
    }

    #[test]
    fn all_targets_present_requires_attached_registry_entries() {
        let entries = vec![
            HollywoodRegistryEntry {
                session_id: "019d113f-49ff-7b12-8a8f-bcc14ebcf5b1".to_string(),
                attached: true,
                identities: vec!["sid-agor-cp2j-755r-fcup-xtau-5phv-we".to_string()],
                updated_at: None,
                last_heartbeat_at: Some(Utc::now().to_rfc3339()),
                ..Default::default()
            },
            HollywoodRegistryEntry {
                session_id: "019d0000-0000-7000-8000-000000000000".to_string(),
                attached: false,
                identities: vec![],
                updated_at: None,
                last_heartbeat_at: Some(Utc::now().to_rfc3339()),
                ..Default::default()
            },
        ];

        assert!(all_targets_present(
            &["019d113f-49ff-7b12-8a8f-bcc14ebcf5b1".to_string()],
            &entries
        ));
        assert!(!all_targets_present(
            &["019d0000-0000-7000-8000-000000000000".to_string()],
            &entries
        ));
    }

    #[test]
    fn resolve_live_session_id_from_entries_matches_generated_runtime_suffix() {
        let entries = vec![HollywoodRegistryEntry {
            session_id: "019d113f-49ff-7b12-8a8f-bcc14ebcf5b1".to_string(),
            attached: true,
            identities: vec!["james-7c45ba".to_string()],
            updated_at: None,
            last_heartbeat_at: Some(Utc::now().to_rfc3339()),
            ..Default::default()
        }];

        assert_eq!(
            resolve_live_session_id_from_entries(&entries, "james").expect("lookup should succeed"),
            Some("019d113f-49ff-7b12-8a8f-bcc14ebcf5b1".to_string())
        );
    }

    #[test]
    fn resolve_live_session_id_from_entries_matches_benchmark_runtime_prefix() {
        let entries = vec![HollywoodRegistryEntry {
            session_id: "019d113f-49ff-7b12-8a8f-bcc14ebcf5b1".to_string(),
            attached: true,
            identities: vec!["marble-db-agent1-7c45ba".to_string()],
            updated_at: None,
            last_heartbeat_at: Some(Utc::now().to_rfc3339()),
            ..Default::default()
        }];

        assert_eq!(
            resolve_live_session_id_from_entries(&entries, "agent1")
                .expect("lookup should succeed"),
            Some("019d113f-49ff-7b12-8a8f-bcc14ebcf5b1".to_string())
        );
    }

    #[test]
    fn resolve_live_session_id_from_entries_rejects_ambiguous_generated_runtime_suffixes() {
        let entries = vec![
            HollywoodRegistryEntry {
                session_id: "019d113f-49ff-7b12-8a8f-bcc14ebcf5b1".to_string(),
                attached: true,
                identities: vec!["james-7c45ba".to_string()],
                updated_at: None,
                last_heartbeat_at: Some(Utc::now().to_rfc3339()),
                ..Default::default()
            },
            HollywoodRegistryEntry {
                session_id: "019d0000-0000-7000-8000-000000000000".to_string(),
                attached: true,
                identities: vec!["james-91ab22".to_string()],
                updated_at: None,
                last_heartbeat_at: Some(Utc::now().to_rfc3339()),
                ..Default::default()
            },
        ];

        let error = resolve_live_session_id_from_entries(&entries, "james")
            .expect_err("ambiguous runtime suffixes should fail");
        assert!(error.contains("ambiguous across live sessions"));
    }

    #[test]
    fn resolve_live_session_id_from_entries_rejects_ambiguous_benchmark_runtime_prefixes() {
        let entries = vec![
            HollywoodRegistryEntry {
                session_id: "019d113f-49ff-7b12-8a8f-bcc14ebcf5b1".to_string(),
                attached: true,
                identities: vec!["marble-db-agent1-7c45ba".to_string()],
                updated_at: None,
                last_heartbeat_at: Some(Utc::now().to_rfc3339()),
                ..Default::default()
            },
            HollywoodRegistryEntry {
                session_id: "019d0000-0000-7000-8000-000000000000".to_string(),
                attached: true,
                identities: vec!["silo-agent1-91ab22".to_string()],
                updated_at: None,
                last_heartbeat_at: Some(Utc::now().to_rfc3339()),
                ..Default::default()
            },
        ];

        let error = resolve_live_session_id_from_entries(&entries, "agent1")
            .expect_err("ambiguous benchmark runtime prefixes should fail");
        assert!(error.contains("ambiguous across live sessions"));
    }

    #[test]
    fn registry_entry_freshness_ignores_stale_attached_entries() {
        let now = Utc::now();
        let fresh = HollywoodRegistryEntry {
            session_id: "019d113f-49ff-7b12-8a8f-bcc14ebcf5b1".to_string(),
            attached: true,
            identities: vec!["sid-fresh".to_string()],
            updated_at: None,
            last_heartbeat_at: Some((now - Duration::seconds(15)).to_rfc3339()),
            ..Default::default()
        };
        let stale = HollywoodRegistryEntry {
            session_id: "019d113f-49ff-7b12-8a8f-bcc14ebcf5b1".to_string(),
            attached: true,
            identities: vec!["sid-stale".to_string()],
            updated_at: None,
            last_heartbeat_at: Some((now - Duration::minutes(10)).to_rfc3339()),
            ..Default::default()
        };

        assert!(registry_entry_is_fresh(&fresh, &now));
        assert!(!registry_entry_is_fresh(&stale, &now));
    }

    #[tokio::test]
    async fn select_send_room_defaults_direct_messages_to_attached_room() {
        let config = HollywoodSessionConfig {
            url: "http://127.0.0.1:8765".to_string(),
            room: "repo/losangelex".to_string(),
            observed_rooms: vec!["main".to_string()],
            wake_rooms: Vec::new(),
            attention_mode: "focused".to_string(),
        };
        let args = send_args("ping @tony", Some("tony"));

        let room = select_send_room(&config, &args, &resolve_target_identities(&args))
            .await
            .expect("room selection should succeed");

        assert_eq!(room, "repo/losangelex");
    }

    #[test]
    fn validate_peer_launch_specs_enforces_bounds() {
        assert!(validate_peer_launch_specs(&[]).is_err());

        let valid_peer = LosangelexPeerLaunchSpec {
            name: "reviewer".to_string(),
            task: "Review the patch and report issues in Hollywood.".to_string(),
        };
        assert_eq!(
            validate_peer_launch_specs(std::slice::from_ref(&valid_peer)),
            Ok(())
        );

        let too_many = vec![valid_peer; MAX_TEAM_LAUNCH_AGENTS + 1];
        let err = validate_peer_launch_specs(&too_many).expect_err("too many peers should fail");
        assert!(err.contains("at most"));
    }

    #[test]
    fn normalize_attention_mode_defaults_to_current_config() {
        let config = HollywoodSessionConfig {
            url: "http://127.0.0.1:8765".to_string(),
            room: "repo/losangelex".to_string(),
            observed_rooms: vec!["main".to_string()],
            wake_rooms: vec!["repo/losangelex".to_string()],
            attention_mode: "Focused".to_string(),
        };

        assert_eq!(
            normalize_attention_mode(None, &config).expect("default attention mode"),
            "focused"
        );
        assert_eq!(
            normalize_attention_mode(Some("BROAD"), &config).expect("explicit attention mode"),
            "broad"
        );
        assert!(normalize_attention_mode(Some("loud"), &config).is_err());
    }

    #[test]
    fn thread_start_params_match_losangelex_team_launcher_defaults() {
        let peer = LosangelexPeerLaunchSpec {
            name: "qa".to_string(),
            task: "Run focused verification.".to_string(),
        };
        let request = PeerLaunchRequest {
            peer: &peer,
            workspace: "/workspace/losangelex",
            hollywood_url: "http://127.0.0.1:8765",
            room: "repo/losangelex",
            observed_rooms: &["main".to_string()],
            wake_rooms: &["repo/losangelex".to_string()],
            attention_mode: "focused",
            model: Some("gpt-5.5"),
            model_provider: Some("openai"),
            start_turns: true,
        };

        assert_eq!(
            thread_start_params(&request),
            json!({
                "cwd": "/workspace/losangelex",
                "approvalPolicy": "never",
                "sandbox": "danger-full-access",
                "serviceName": "losangelex-team",
                "model": "gpt-5.5",
                "modelProvider": "openai",
            })
        );
    }

    #[test]
    fn launched_peer_task_prompt_adds_team_communication_expectations() {
        let prompt = launched_peer_task_prompt("Run focused verification.");

        assert!(prompt.starts_with("Losangelex team communication expectation:"));
        assert!(prompt.contains("Hollywood is the shared working room"));
        assert!(prompt.contains("These work-state messages are not chatter"));
        assert!(prompt.contains("Dependency-aware communication expectation:"));
        assert!(prompt.contains("do not finalize from stale assumptions"));
        assert!(prompt.contains("Your finish message should name the dependency evidence"));
        assert!(prompt.ends_with("Run focused verification."));
    }

    #[test]
    fn launched_peer_task_prompt_does_not_duplicate_prepared_guidance() {
        let task = format!("{LOSANGELEX_TEAM_TASK_GUIDANCE}\nRun focused verification.");

        assert_eq!(launched_peer_task_prompt(&task), task);
    }
}
