use chrono::DateTime;
use chrono::Duration;
use chrono::Utc;
use reqwest::Client;
use serde::Deserialize;
use serde::Serialize;
use serde_json::json;
use std::collections::HashSet;

use crate::function_tool::FunctionCallError;
use crate::hollywood::HollywoodSessionConfig;
use crate::hollywood::canonicalize_agent_identity;
use crate::hollywood::canonicalize_hollywood_identity;
use crate::hollywood::identities as hollywood_identities;
use crate::hollywood::parse_agent_mentions;
use crate::tools::context::FunctionToolOutput;
use crate::tools::context::ToolInvocation;
use crate::tools::context::ToolPayload;
use crate::tools::handlers::parse_arguments;
use crate::tools::registry::ToolHandler;
use crate::tools::registry::ToolKind;

pub struct HollywoodStatusHandler;
pub struct HollywoodReadHandler;
pub struct HollywoodSendHandler;
pub struct HollywoodTeamUpHandler;
pub struct HollywoodTeamStatusHandler;
pub struct HollywoodTeamMemberUpdateHandler;

const HOLLYWOOD_REGISTRY_STALE_AFTER: Duration = Duration::seconds(90);

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

#[derive(Deserialize)]
struct HollywoodRegistryListResponse {
    entries: Vec<HollywoodRegistryEntry>,
}

#[derive(Deserialize)]
struct HollywoodRegistryEntry {
    session_id: String,
    attached: bool,
    identities: Vec<String>,
    updated_at: Option<String>,
    last_heartbeat_at: Option<String>,
}
impl ToolHandler for HollywoodStatusHandler {
    type Output = FunctionToolOutput;

    fn kind(&self) -> ToolKind {
        ToolKind::Function
    }

    async fn handle(&self, invocation: ToolInvocation) -> Result<Self::Output, FunctionCallError> {
        let config = HollywoodSessionConfig::from_env();
        let thread_name = invocation.session.thread_name().await;
        let identities =
            hollywood_identities(invocation.session.conversation_id, thread_name.as_deref());
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
        let thread_name = invocation.session.thread_name().await;

        let result = HollywoodReadResult {
            url: config.url,
            room,
            identities: hollywood_identities(
                invocation.session.conversation_id,
                thread_name.as_deref(),
            ),
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

        let target_identities = resolve_target_identities(&args);
        let room = match args.room.clone() {
            Some(room) => room,
            None => select_room_for_targets(&config, &target_identities)
                .await
                .map_err(FunctionCallError::RespondToModel)?,
        };
        let sender_id = invocation.session.conversation_id.to_string();
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
}

impl ToolHandler for HollywoodTeamUpHandler {
    type Output = FunctionToolOutput;

    fn kind(&self) -> ToolKind {
        ToolKind::Function
    }

    async fn handle(&self, invocation: ToolInvocation) -> Result<Self::Output, FunctionCallError> {
        let args = parse_function_args::<HollywoodTeamUpArgs>(&invocation.payload)?;
        let Some(config) = HollywoodSessionConfig::from_env() else {
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
        let response = Client::new()
            .post(&url)
            .json(&json!({
                "team_id": args.team_id,
                "room": room,
                "task_room": args.task_room,
                "purpose": args.purpose,
                "leader_session_id": invocation.session.conversation_id.to_string(),
                "members": members,
            }))
            .send()
            .await
            .map_err(|err| {
                FunctionCallError::RespondToModel(format!("Hollywood team create failed: {err}"))
            })?
            .error_for_status()
            .map_err(|err| {
                FunctionCallError::RespondToModel(format!("Hollywood team create failed: {err}"))
            })?
            .json::<serde_json::Value>()
            .await
            .map_err(|err| {
                FunctionCallError::RespondToModel(format!(
                    "Hollywood team response parse failed: {err}"
                ))
            })?;

        let result = HollywoodTeamUpResult {
            url: config.url,
            room,
            team: response,
        };

        Ok(FunctionToolOutput::from_text(
            serde_json::to_string_pretty(&result)
                .unwrap_or_else(|err| format!("failed to serialize hollywood team create: {err}")),
            Some(true),
        ))
    }
}

impl ToolHandler for HollywoodTeamStatusHandler {
    type Output = FunctionToolOutput;

    fn kind(&self) -> ToolKind {
        ToolKind::Function
    }

    async fn handle(&self, invocation: ToolInvocation) -> Result<Self::Output, FunctionCallError> {
        let args = parse_function_args::<HollywoodTeamStatusArgs>(&invocation.payload)?;
        let Some(config) = HollywoodSessionConfig::from_env() else {
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
                FunctionCallError::RespondToModel(format!("Hollywood team read failed: {err}"))
            })?
            .error_for_status()
            .map_err(|err| {
                FunctionCallError::RespondToModel(format!("Hollywood team read failed: {err}"))
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
            serde_json::to_string_pretty(&result)
                .unwrap_or_else(|err| format!("failed to serialize hollywood team read: {err}")),
            Some(true),
        ))
    }
}

impl ToolHandler for HollywoodTeamMemberUpdateHandler {
    type Output = FunctionToolOutput;

    fn kind(&self) -> ToolKind {
        ToolKind::Function
    }

    async fn handle(&self, invocation: ToolInvocation) -> Result<Self::Output, FunctionCallError> {
        let args = parse_function_args::<HollywoodTeamMemberUpdateArgs>(&invocation.payload)?;
        let Some(config) = HollywoodSessionConfig::from_env() else {
            return Err(FunctionCallError::RespondToModel(
                "Hollywood is not configured for this session.".to_string(),
            ));
        };

        let session_id = match args.session_id.as_deref() {
            Some(value) => canonicalize_agent_identity(value).ok_or_else(|| {
                FunctionCallError::RespondToModel(
                    "invalid session_id for hollywood_team_member_update".to_string(),
                )
            })?,
            None => invocation.session.conversation_id.to_string(),
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
        entries.iter().any(|entry| {
            entry.attached
                && (entry.session_id == *target
                    || entry.identities.iter().any(|identity| identity == target))
        })
    })
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
            },
            HollywoodRegistryEntry {
                session_id: "019d0000-0000-7000-8000-000000000000".to_string(),
                attached: false,
                identities: vec![],
                updated_at: None,
                last_heartbeat_at: Some(Utc::now().to_rfc3339()),
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
    fn registry_entry_freshness_ignores_stale_attached_entries() {
        let now = Utc::now();
        let fresh = HollywoodRegistryEntry {
            session_id: "019d113f-49ff-7b12-8a8f-bcc14ebcf5b1".to_string(),
            attached: true,
            identities: vec!["sid-fresh".to_string()],
            updated_at: None,
            last_heartbeat_at: Some((now - Duration::seconds(15)).to_rfc3339()),
        };
        let stale = HollywoodRegistryEntry {
            session_id: "019d113f-49ff-7b12-8a8f-bcc14ebcf5b1".to_string(),
            attached: true,
            identities: vec!["sid-stale".to_string()],
            updated_at: None,
            last_heartbeat_at: Some((now - Duration::minutes(10)).to_rfc3339()),
        };

        assert!(registry_entry_is_fresh(&fresh, &now));
        assert!(!registry_entry_is_fresh(&stale, &now));
    }
}
