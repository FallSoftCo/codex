use codex_app_server_protocol::HollywoodAttentionMode;
use codex_app_server_protocol::HollywoodAttentionSettings;
use codex_app_server_protocol::HollywoodMessage;
use codex_app_server_protocol::HollywoodMessageAttention;
use codex_app_server_protocol::HollywoodMessageKind;
use codex_app_server_protocol::HollywoodResponsePolicy;
use codex_app_server_protocol::HollywoodSessionAttachOptions;
use codex_app_server_protocol::HollywoodSessionState;
use codex_app_server_protocol::HollywoodSessionStatus;
use codex_app_server_protocol::ThreadStatus;
use codex_core::CodexThread;
use codex_core::default_hollywood_observed_rooms;
use codex_core::default_hollywood_room_for_cwd;
use codex_core::parse_agent_mentions;
use codex_protocol::ThreadId;
use codex_protocol::protocol::HollywoodSessionMeta;
use reqwest::Client;
use serde::Deserialize;
use serde::Serialize;
use std::collections::HashMap;
use std::collections::HashSet;
use std::env;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;
use uuid::Uuid;

const HOLLYWOOD_CONTEXT_OPEN_TAG: &str = "<hollywood_context>";
const HOLLYWOOD_CONTEXT_CLOSE_TAG: &str = "</hollywood_context>";

pub(crate) const DEFAULT_HOLLYWOOD_URL: &str = "http://127.0.0.1:8765";
pub(crate) const DEFAULT_HOLLYWOOD_ROOM: &str = "main";
pub(crate) const HOLLYWOOD_POLL_INTERVAL: Duration = Duration::from_millis(1500);
pub(crate) const HOLLYWOOD_AUTONOMOUS_COOLDOWN: Duration = Duration::from_secs(2);
pub(crate) const HOLLYWOOD_REGISTRY_SYNC_INTERVAL: Duration = Duration::from_secs(15);
const HOLLYWOOD_PAGE_LIMIT: i64 = 100;
const BASE32_ALPHABET: &[u8; 32] = b"abcdefghijklmnopqrstuvwxyz234567";

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct HollywoodConfig {
    pub(crate) url: String,
    pub(crate) room: String,
    pub(crate) observed_rooms: Vec<String>,
    pub(crate) wake_rooms: Vec<String>,
    pub(crate) attention: HollywoodAttentionSettings,
}

impl HollywoodConfig {
    pub(crate) fn from_env() -> Option<Self> {
        let auto_attach = env::var("HOLLYWOOD_AUTO_ATTACH").ok();
        let has_explicit_config =
            env::var("HOLLYWOOD_URL").is_ok() || env::var("HOLLYWOOD_ROOM").is_ok();
        let enabled = auto_attach
            .as_deref()
            .map(|value| matches!(value, "1" | "true" | "TRUE" | "yes" | "on"))
            .unwrap_or(has_explicit_config);
        if !enabled {
            return None;
        }

        let mode = match env::var("HOLLYWOOD_ATTENTION_MODE")
            .unwrap_or_else(|_| "focused".to_string())
            .to_ascii_lowercase()
            .as_str()
        {
            "ambient" => HollywoodAttentionMode::Ambient,
            "broad" => HollywoodAttentionMode::Broad,
            _ => HollywoodAttentionMode::Focused,
        };

        let room = env::var("HOLLYWOOD_ROOM")
            .ok()
            .or_else(|| {
                env::current_dir()
                    .ok()
                    .map(|cwd| default_hollywood_room_for_cwd(cwd.as_path()))
            })
            .unwrap_or_else(|| DEFAULT_HOLLYWOOD_ROOM.to_string());
        let observed_rooms = default_hollywood_observed_rooms(
            &room,
            parse_room_list(env::var("HOLLYWOOD_OBSERVED_ROOMS").ok()),
        );
        Some(Self {
            url: env::var("HOLLYWOOD_URL").unwrap_or_else(|_| DEFAULT_HOLLYWOOD_URL.to_string()),
            room,
            observed_rooms,
            wake_rooms: parse_room_list(env::var("HOLLYWOOD_WAKE_ROOMS").ok()),
            attention: HollywoodAttentionSettings {
                mode,
                include_at_all: true,
                include_at_room: true,
            },
        })
    }
}

impl From<&HollywoodConfig> for HollywoodSessionMeta {
    fn from(value: &HollywoodConfig) -> Self {
        Self {
            url: value.url.clone(),
            room: value.room.clone(),
            observed_rooms: value.observed_rooms.clone(),
            wake_rooms: value.wake_rooms.clone(),
            attention_mode: hollywood_attention_mode_name(value.attention.mode),
            include_at_all: value.attention.include_at_all,
            include_at_room: value.attention.include_at_room,
        }
    }
}

impl TryFrom<&HollywoodSessionMeta> for HollywoodConfig {
    type Error = String;

    fn try_from(value: &HollywoodSessionMeta) -> Result<Self, Self::Error> {
        let mode = match value.attention_mode.to_ascii_lowercase().as_str() {
            "focused" => HollywoodAttentionMode::Focused,
            "ambient" => HollywoodAttentionMode::Ambient,
            "broad" => HollywoodAttentionMode::Broad,
            other => {
                return Err(format!("unsupported Hollywood attention mode `{other}`"));
            }
        };
        Ok(Self {
            url: value.url.clone(),
            room: value.room.clone(),
            observed_rooms: value.observed_rooms.clone(),
            wake_rooms: value.wake_rooms.clone(),
            attention: HollywoodAttentionSettings {
                mode,
                include_at_all: value.include_at_all,
                include_at_room: value.include_at_room,
            },
        })
    }
}

impl From<&HollywoodSessionAttachOptions> for HollywoodConfig {
    fn from(value: &HollywoodSessionAttachOptions) -> Self {
        let room = value
            .room
            .clone()
            .unwrap_or_else(|| DEFAULT_HOLLYWOOD_ROOM.to_string());
        Self {
            url: value
                .url
                .clone()
                .unwrap_or_else(|| DEFAULT_HOLLYWOOD_URL.to_string()),
            room: room.clone(),
            observed_rooms: default_hollywood_observed_rooms(&room, value.observed_rooms.clone()),
            wake_rooms: value.wake_rooms.clone(),
            attention: value.attention.clone().unwrap_or_default(),
        }
    }
}

impl Default for HollywoodConfig {
    fn default() -> Self {
        Self {
            url: DEFAULT_HOLLYWOOD_URL.to_string(),
            room: DEFAULT_HOLLYWOOD_ROOM.to_string(),
            observed_rooms: Vec::new(),
            wake_rooms: Vec::new(),
            attention: HollywoodAttentionSettings::default(),
        }
    }
}

impl HollywoodConfig {
    pub(crate) fn all_rooms(&self) -> Vec<String> {
        let mut seen = HashSet::new();
        let mut rooms = Vec::new();
        for room in std::iter::once(&self.room).chain(self.observed_rooms.iter()) {
            if !room.is_empty() && seen.insert(room.clone()) {
                rooms.push(room.clone());
            }
        }
        rooms
    }

    pub(crate) fn effective_wake_rooms(&self) -> HashSet<String> {
        let wake_rooms = if self.wake_rooms.is_empty() {
            vec![self.room.clone()]
        } else {
            self.wake_rooms.clone()
        };
        wake_rooms
            .into_iter()
            .filter(|room| !room.is_empty())
            .collect()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub(crate) struct HollywoodRoomState {
    last_seen_message_id: i64,
    start_from_latest: bool,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub(crate) struct HollywoodRuntimeState {
    config: Option<HollywoodConfig>,
    room_states: HashMap<String, HollywoodRoomState>,
    startup_turn_pending: bool,
    recent_activity_at: Option<Instant>,
    last_turn_started_at: Option<Instant>,
    autonomous_turn_pending: bool,
    registry_session_kind: Option<String>,
    registry_resumed_from: Option<String>,
    last_registry_sync_at: Option<Instant>,
    last_registry_status: Option<String>,
}

impl HollywoodRuntimeState {
    pub(crate) fn attach(
        &mut self,
        config: HollywoodConfig,
        session_kind: impl Into<String>,
        resumed_from: Option<String>,
    ) {
        self.config = Some(config);
        self.room_states.clear();
        if let Some(config) = &self.config {
            for room in config.all_rooms() {
                self.room_states.insert(
                    room,
                    HollywoodRoomState {
                        last_seen_message_id: 0,
                        start_from_latest: true,
                    },
                );
            }
        }
        self.startup_turn_pending = true;
        self.recent_activity_at = None;
        self.last_turn_started_at = None;
        self.autonomous_turn_pending = false;
        self.registry_session_kind = Some(session_kind.into());
        self.registry_resumed_from = resumed_from;
        self.last_registry_sync_at = None;
        self.last_registry_status = None;
    }

    pub(crate) fn detach(&mut self) {
        self.config = None;
        self.room_states.clear();
        self.startup_turn_pending = false;
        self.recent_activity_at = None;
        self.last_turn_started_at = None;
        self.autonomous_turn_pending = false;
        self.registry_session_kind = None;
        self.registry_resumed_from = None;
        self.last_registry_sync_at = None;
        self.last_registry_status = None;
    }

    pub(crate) fn set_attention(&mut self, attention: HollywoodAttentionSettings) -> bool {
        let Some(config) = self.config.as_mut() else {
            return false;
        };
        config.attention = attention;
        true
    }

    pub(crate) fn config(&self) -> Option<HollywoodConfig> {
        self.config.clone()
    }

    pub(crate) fn last_seen_message_id(&self, room: &str) -> i64 {
        self.room_states
            .get(room)
            .map(|state| state.last_seen_message_id)
            .unwrap_or(0)
    }

    pub(crate) fn set_last_seen_message_id(&mut self, room: &str, message_id: i64) {
        let state = self.room_states.entry(room.to_string()).or_default();
        state.last_seen_message_id = message_id;
    }

    pub(crate) fn prime_room_from_latest(&mut self, room: &str, message_id: i64) {
        let state = self.room_states.entry(room.to_string()).or_default();
        state.last_seen_message_id = message_id;
        state.start_from_latest = false;
    }

    pub(crate) fn take_start_from_latest(&mut self, room: &str) -> bool {
        let state = self.room_states.entry(room.to_string()).or_default();
        let value = state.start_from_latest;
        state.start_from_latest = false;
        value
    }

    pub(crate) fn note_message_activity(&mut self, now: Instant) {
        self.recent_activity_at = Some(now);
    }

    pub(crate) fn note_turn_started(&mut self, now: Instant) {
        self.last_turn_started_at = Some(now);
        self.startup_turn_pending = false;
        self.autonomous_turn_pending = false;
    }

    pub(crate) fn note_turn_finished(&mut self) {
        self.autonomous_turn_pending = false;
    }

    pub(crate) fn mark_autonomous_turn_pending(&mut self) {
        self.autonomous_turn_pending = true;
    }

    pub(crate) fn clear_autonomous_turn_pending(&mut self) {
        self.autonomous_turn_pending = false;
    }

    pub(crate) fn should_start_startup_turn(&self) -> bool {
        self.config.is_some() && self.startup_turn_pending && !self.autonomous_turn_pending
    }

    pub(crate) fn clear_startup_turn_pending(&mut self) {
        self.startup_turn_pending = false;
    }

    pub(crate) fn mark_startup_turn_pending(&mut self) {
        self.startup_turn_pending = true;
    }

    pub(crate) fn should_start_autonomous_turn(&self, now: Instant) -> bool {
        if self.config.is_none() || self.autonomous_turn_pending {
            return false;
        }

        let Some(recent_activity_at) = self.recent_activity_at else {
            return false;
        };

        if let Some(last_turn_started_at) = self.last_turn_started_at {
            if recent_activity_at <= last_turn_started_at {
                return false;
            }
            if now.duration_since(last_turn_started_at) < HOLLYWOOD_AUTONOMOUS_COOLDOWN {
                return false;
            }
        }

        true
    }

    pub(crate) fn registry_session_kind(&self) -> Option<&str> {
        self.registry_session_kind.as_deref()
    }

    pub(crate) fn registry_resumed_from(&self) -> Option<&str> {
        self.registry_resumed_from.as_deref()
    }

    pub(crate) fn should_sync_registry(&self, now: Instant, status: &str) -> bool {
        if self.config.is_none() {
            return false;
        }
        if self.last_registry_status.as_deref() != Some(status) {
            return true;
        }
        match self.last_registry_sync_at {
            None => true,
            Some(last) => now.duration_since(last) >= HOLLYWOOD_REGISTRY_SYNC_INTERVAL,
        }
    }

    pub(crate) fn note_registry_synced(&mut self, now: Instant, status: String) {
        self.last_registry_sync_at = Some(now);
        self.last_registry_status = Some(status);
    }
}

#[derive(Debug, Serialize)]
pub(crate) struct HollywoodRegistryUpsertRequest {
    pub(crate) session_id: String,
    pub(crate) room: String,
    pub(crate) attached: bool,
    pub(crate) cwd: Option<String>,
    pub(crate) repo_name: Option<String>,
    pub(crate) attention_mode: String,
    pub(crate) identities: Vec<String>,
    pub(crate) session_kind: String,
    pub(crate) resumed_from: Option<String>,
    pub(crate) ephemeral: bool,
    pub(crate) rollout_path: Option<String>,
    pub(crate) status: String,
}

#[derive(Debug, Deserialize)]
struct HollywoodApiMessage {
    id: i64,
    room: String,
    sender_id: Option<String>,
    recipient_id: Option<String>,
    #[serde(default)]
    message_kind: HollywoodMessageKind,
    #[serde(default)]
    response_policy: HollywoodResponsePolicy,
    body: String,
    created_at: String,
}

#[derive(Debug, Deserialize)]
struct HollywoodMessagesResponse {
    messages: Vec<HollywoodApiMessage>,
    last_id: i64,
}

#[derive(Debug)]
pub(crate) struct HollywoodPollResult {
    pub(crate) messages: Vec<HollywoodClassifiedMessage>,
    pub(crate) last_id: i64,
}

#[derive(Debug)]
pub(crate) struct HollywoodClassifiedMessage {
    pub(crate) notification_message: HollywoodMessage,
    pub(crate) attention: HollywoodMessageAttention,
    pub(crate) mentioned: bool,
    pub(crate) self_authored: bool,
}

pub(crate) async fn prime_from_latest(
    client: &Client,
    config: &HollywoodConfig,
) -> Result<i64, String> {
    let mut after_id = 0_i64;
    loop {
        let response = fetch_messages(client, config, after_id, HOLLYWOOD_PAGE_LIMIT).await?;
        if response.last_id <= after_id || response.messages.len() < HOLLYWOOD_PAGE_LIMIT as usize {
            return Ok(response.last_id);
        }
        after_id = response.last_id;
    }
}

pub(crate) async fn poll_messages(
    client: &Client,
    config: &HollywoodConfig,
    room: &str,
    after_id: i64,
    thread_id: ThreadId,
) -> Result<HollywoodPollResult, String> {
    let mut room_config = config.clone();
    room_config.room = room.to_string();
    let response = fetch_messages(client, &room_config, after_id, HOLLYWOOD_PAGE_LIMIT).await?;
    let identities = hollywood_identities(thread_id);
    let room_can_wake = config.effective_wake_rooms().contains(room);
    let messages = response
        .messages
        .into_iter()
        .filter_map(|message| {
            classify_message(message, &identities, &config.attention, room_can_wake)
        })
        .collect();
    Ok(HollywoodPollResult {
        messages,
        last_id: response.last_id,
    })
}

pub(crate) async fn upsert_registry(
    client: &Client,
    config: &HollywoodConfig,
    request: &HollywoodRegistryUpsertRequest,
) -> Result<(), String> {
    let url = format!("{}/hollywood/v1/registry", config.url.trim_end_matches('/'));
    client
        .post(url)
        .json(request)
        .send()
        .await
        .map_err(|err| format!("Hollywood registry request failed: {err}"))?
        .error_for_status()
        .map_err(|err| format!("Hollywood registry request failed: {err}"))?;
    Ok(())
}

pub(crate) fn format_hollywood_context_message(
    thread_id: ThreadId,
    config: &HollywoodConfig,
) -> String {
    let wake_rooms = config
        .effective_wake_rooms()
        .into_iter()
        .collect::<Vec<_>>();
    let payload_json = serde_json::json!({
        "attached": true,
        "meaning": "Hollywood is the local inter-agent room and messaging system in this runtime, not a physical place.",
        "url": config.url,
        "room": config.room,
        "observed_rooms": config.observed_rooms.clone(),
        "wake_rooms": wake_rooms,
        "attention_mode": config.attention.mode,
        "include_at_all": config.attention.include_at_all,
        "include_at_room": config.attention.include_at_room,
        "identities": hollywood_identities(thread_id),
        "startup_protocol": {
            "announce_presence": true,
            "read_recent_room_context": true,
            "ask_user_for_tasking_when_unassigned": true,
            "relay_assigned_scope_to_room": true,
            "relay_material_conclusions_to_room": true,
        },
        "broadcast_guidance": [
            "Use sparse explicit room-wide broadcasts for presence, scope changes, blockers, handoffs, major completion updates, and discovery-oriented coordination. Explicit broadcasts can wake idle attached agents.",
            "Use @mentions for direct requests, replies, and anything that should reliably wake another agent.",
            "When you reach a concrete diagnosis, decision, or verification result that materially affects peer work, send a concise room update so other agents and the user-facing session can converge on the same conclusion.",
            "If autonomous Hollywood follow-up finds no new state to report, prefer no user-facing follow-up at all; if one is needed, keep it to a compact status tag rather than a full explanation.",
        ],
    })
    .to_string();
    format!("{HOLLYWOOD_CONTEXT_OPEN_TAG}\n{payload_json}\n{HOLLYWOOD_CONTEXT_CLOSE_TAG}")
}

pub(crate) fn startup_handshake_message(thread_id: ThreadId, config: &HollywoodConfig) -> String {
    let identities = hollywood_identities(thread_id).join(", ");
    let observed = if config.observed_rooms.is_empty() {
        String::new()
    } else {
        format!(
            " You are also observing rooms [{}].",
            config.observed_rooms.join(", ")
        )
    };
    format!(
        "Startup protocol: you have just attached to the local Hollywood primary room `{}` as session identities [{}].{} Before doing substantive work, send one short explicit room-wide broadcast announcing that you are online, your current repo or cwd if known, and whether you are available or already assigned. Then read recent room traffic once to orient yourself. If you do not yet have a concrete user-assigned task, ask the user what they want you to work on. After the user gives you concrete tasking, send one concise room update relaying your assigned scope or ownership so other agents can coordinate. When you reach a concrete diagnosis, decision, or verification result that materially affects peer work, send a concise room update before or alongside your user-facing answer so other sessions can converge on the same conclusion. If autonomous Hollywood follow-up later finds no new state to report, do not send a user-facing no-op message; stay silent unless something changed, and if you must acknowledge room state, keep it to a compact status tag. Use explicit room-wide broadcasts sparingly for presence, scope changes, blockers, handoffs, major completion updates, material conclusions that peers should know, and discovery-oriented coordination where any relevant idle agent should notice. Use @mentions for direct requests, replies, and anything that should reliably get another agent's attention. If you see an unmentioned room message that is plainly about your current repo, ownership, or specialized domain, proactively reply even without being @mentioned.",
        config.room, identities, observed
    )
}

async fn fetch_messages(
    client: &Client,
    config: &HollywoodConfig,
    after_id: i64,
    limit: i64,
) -> Result<HollywoodMessagesResponse, String> {
    let url = format!("{}/hollywood/v1/messages", config.url.trim_end_matches('/'));
    client
        .get(url)
        .query(&[
            ("room", config.room.as_str()),
            ("after_id", &after_id.to_string()),
            ("limit", &limit.to_string()),
        ])
        .send()
        .await
        .map_err(|err| format!("Hollywood request failed: {err}"))?
        .error_for_status()
        .map_err(|err| format!("Hollywood request failed: {err}"))?
        .json::<HollywoodMessagesResponse>()
        .await
        .map_err(|err| format!("Hollywood response parse failed: {err}"))
}

fn classify_message(
    message: HollywoodApiMessage,
    identities: &[String],
    attention: &HollywoodAttentionSettings,
    room_can_wake: bool,
) -> Option<HollywoodClassifiedMessage> {
    let mentions = parse_agent_mentions(&message.body);
    let self_authored = message
        .sender_id
        .as_ref()
        .map(|sender| {
            let normalized = normalize_identity(sender);
            identities
                .iter()
                .any(|identity| normalized == normalize_identity(identity))
        })
        .unwrap_or(false);

    let mentioned = mentions.iter().any(|mention| {
        identities
            .iter()
            .any(|identity| mention == &normalize_identity(identity))
    });
    let at_all = has_special_mention(&message.body, "all");
    let at_room = has_special_mention(&message.body, "room");
    let broadcast_match =
        (attention.include_at_all && at_all) || (attention.include_at_room && at_room);

    let direct_match =
        message.recipient_id.is_some() || message.message_kind == HollywoodMessageKind::Direct;
    let explicit_broadcast = message.message_kind == HollywoodMessageKind::Broadcast;

    let attention_class = if direct_match || mentioned || broadcast_match {
        if room_can_wake {
            HollywoodMessageAttention::Focused
        } else {
            HollywoodMessageAttention::Ambient
        }
    } else if explicit_broadcast {
        if room_can_wake {
            HollywoodMessageAttention::Broadcast
        } else {
            HollywoodMessageAttention::Ambient
        }
    } else {
        match attention.mode {
            HollywoodAttentionMode::Focused => {
                if self_authored {
                    HollywoodMessageAttention::Ambient
                } else {
                    return None;
                }
            }
            HollywoodAttentionMode::Ambient => HollywoodMessageAttention::Ambient,
            HollywoodAttentionMode::Broad => HollywoodMessageAttention::Broad,
        }
    };

    Some(HollywoodClassifiedMessage {
        notification_message: HollywoodMessage {
            id: message.id,
            room: message.room,
            sender_id: message.sender_id,
            recipient_id: message.recipient_id,
            message_kind: message.message_kind,
            response_policy: message.response_policy,
            body: message.body,
            created_at: message.created_at,
            mentions,
        },
        attention: attention_class,
        mentioned,
        self_authored,
    })
}

pub(crate) fn hollywood_identities(thread_id: ThreadId) -> Vec<String> {
    let raw = thread_id.to_string();
    let mut identities = vec![normalize_identity(&raw)];
    if let Ok(uuid) = Uuid::parse_str(&raw) {
        identities.push(session_id_to_alias(uuid));
    }
    identities
}

fn parse_room_list(value: Option<String>) -> Vec<String> {
    value
        .unwrap_or_default()
        .split(',')
        .map(str::trim)
        .filter(|room| !room.is_empty())
        .map(ToOwned::to_owned)
        .collect()
}

pub(crate) fn hollywood_session_status_from_thread_status(
    status: &ThreadStatus,
) -> HollywoodSessionStatus {
    match status {
        ThreadStatus::NotLoaded | ThreadStatus::Idle => HollywoodSessionStatus::Idle,
        ThreadStatus::SystemError => HollywoodSessionStatus::Blocked,
        ThreadStatus::Active { active_flags } => {
            if active_flags.iter().any(|flag| {
                matches!(
                    flag,
                    codex_app_server_protocol::ThreadActiveFlag::WaitingOnApproval
                        | codex_app_server_protocol::ThreadActiveFlag::WaitingOnUserInput
                )
            }) {
                HollywoodSessionStatus::Waiting
            } else {
                HollywoodSessionStatus::Active
            }
        }
    }
}

pub(crate) fn hollywood_session_state_from_runtime(
    thread_id: ThreadId,
    config: &HollywoodConfig,
    runtime_state: &HollywoodRuntimeState,
    status: HollywoodSessionStatus,
) -> HollywoodSessionState {
    HollywoodSessionState {
        attached: true,
        url: config.url.clone(),
        primary_room: config.room.clone(),
        observed_rooms: config.observed_rooms.clone(),
        wake_rooms: config.effective_wake_rooms().into_iter().collect(),
        attention: config.attention.clone(),
        identities: hollywood_identities(thread_id),
        session_kind: runtime_state.registry_session_kind().map(ToOwned::to_owned),
        resumed_from: runtime_state.registry_resumed_from().map(ToOwned::to_owned),
        status,
    }
}

pub(crate) fn hollywood_session_state_from_persisted(
    thread_id: ThreadId,
    persisted: &HollywoodSessionMeta,
) -> Option<HollywoodSessionState> {
    let config = HollywoodConfig::try_from(persisted).ok()?;
    let wake_rooms = config.effective_wake_rooms().into_iter().collect();
    Some(HollywoodSessionState {
        attached: false,
        url: config.url,
        primary_room: config.room,
        observed_rooms: config.observed_rooms,
        wake_rooms,
        attention: config.attention,
        identities: hollywood_identities(thread_id),
        session_kind: None,
        resumed_from: None,
        status: HollywoodSessionStatus::Persisted,
    })
}

pub(crate) fn thread_status_name(status: &ThreadStatus) -> String {
    match status {
        ThreadStatus::NotLoaded => "unknown".to_string(),
        ThreadStatus::Idle => "idle".to_string(),
        ThreadStatus::SystemError => "blocked".to_string(),
        ThreadStatus::Active { active_flags } => {
            if active_flags.is_empty() {
                "active".to_string()
            } else if active_flags.iter().any(|flag| {
                matches!(
                    flag,
                    codex_app_server_protocol::ThreadActiveFlag::WaitingOnApproval
                        | codex_app_server_protocol::ThreadActiveFlag::WaitingOnUserInput
                )
            }) {
                "waiting".to_string()
            } else {
                "active".to_string()
            }
        }
    }
}

pub(crate) async fn build_registry_upsert_request(
    thread_id: ThreadId,
    thread: &CodexThread,
    config: &HollywoodConfig,
    runtime_state: &HollywoodRuntimeState,
    status: &ThreadStatus,
) -> HollywoodRegistryUpsertRequest {
    let snapshot = thread.config_snapshot().await;
    let cwd = snapshot.cwd.display().to_string();
    HollywoodRegistryUpsertRequest {
        session_id: thread_id.to_string(),
        room: config.room.clone(),
        attached: true,
        cwd: Some(cwd),
        repo_name: repo_name_from_cwd(snapshot.cwd.as_path()),
        attention_mode: hollywood_attention_mode_name(config.attention.mode),
        identities: hollywood_identities(thread_id),
        session_kind: runtime_state
            .registry_session_kind()
            .unwrap_or("attached")
            .to_string(),
        resumed_from: runtime_state.registry_resumed_from().map(ToOwned::to_owned),
        ephemeral: snapshot.ephemeral,
        rollout_path: thread.rollout_path().map(|path| path.display().to_string()),
        status: thread_status_name(status),
    }
}

fn repo_name_from_cwd(path: &Path) -> Option<String> {
    path.file_name()
        .map(|name| name.to_string_lossy().to_string())
        .filter(|name| !name.is_empty())
}

fn session_id_to_alias(session_id: Uuid) -> String {
    let mut encoded = String::new();
    let mut buffer: u32 = 0;
    let mut bits: u8 = 0;
    for byte in session_id.as_bytes() {
        buffer = (buffer << 8) | u32::from(*byte);
        bits += 8;
        while bits >= 5 {
            bits -= 5;
            let index = ((buffer >> bits) & 0x1f) as usize;
            encoded.push(BASE32_ALPHABET[index] as char);
        }
    }
    if bits > 0 {
        let index = ((buffer << (5 - bits)) & 0x1f) as usize;
        encoded.push(BASE32_ALPHABET[index] as char);
    }

    let chunks = encoded
        .as_bytes()
        .chunks(4)
        .map(|chunk| std::str::from_utf8(chunk).unwrap_or_default())
        .collect::<Vec<_>>();
    format!("sid-{}", chunks.join("-"))
}

fn has_special_mention(body: &str, expected: &str) -> bool {
    let bytes = body.as_bytes();
    let mut idx = 0;
    while idx < bytes.len() {
        if bytes[idx] != b'@' {
            idx += 1;
            continue;
        }
        idx += 1;
        let start = idx;
        while idx < bytes.len() {
            let ch = bytes[idx] as char;
            if ch.is_ascii_alphanumeric() || matches!(ch, '-' | '_' | '.') {
                idx += 1;
            } else {
                break;
            }
        }
        if idx > start && normalize_identity(&body[start..idx]) == expected {
            return true;
        }
    }
    false
}

fn normalize_identity(value: &str) -> String {
    value.trim().trim_start_matches('@').to_ascii_lowercase()
}

fn hollywood_attention_mode_name(mode: HollywoodAttentionMode) -> String {
    match mode {
        HollywoodAttentionMode::Focused => "focused".to_string(),
        HollywoodAttentionMode::Ambient => "ambient".to_string(),
        HollywoodAttentionMode::Broad => "broad".to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serial_test::serial;

    struct EnvGuard {
        key: &'static str,
        value: Option<String>,
    }

    impl EnvGuard {
        fn set(key: &'static str, value: Option<&str>) -> Self {
            let prior = std::env::var(key).ok();
            match value {
                Some(value) => unsafe {
                    std::env::set_var(key, value);
                },
                None => unsafe {
                    std::env::remove_var(key);
                },
            }
            Self { key, value: prior }
        }
    }

    impl Drop for EnvGuard {
        fn drop(&mut self) {
            match self.value.as_deref() {
                Some(value) => unsafe {
                    std::env::set_var(self.key, value);
                },
                None => unsafe {
                    std::env::remove_var(self.key);
                },
            }
        }
    }

    fn sample_message(body: &str, sender_id: Option<&str>) -> HollywoodApiMessage {
        HollywoodApiMessage {
            id: 42,
            room: "main".to_string(),
            sender_id: sender_id.map(ToOwned::to_owned),
            recipient_id: None,
            message_kind: HollywoodMessageKind::Ambient,
            response_policy: HollywoodResponsePolicy::Optional,
            body: body.to_string(),
            created_at: "2026-03-19T20:00:00Z".to_string(),
        }
    }

    fn identities() -> Vec<String> {
        vec![
            "019d0798-12d8-76c3-a812-6e323637aa59".to_string(),
            "sid-agoq-pgas-3b3m-hkas-nyzd-mn5k-le".to_string(),
        ]
    }

    #[test]
    fn focused_mode_keeps_direct_mentions() {
        let message = sample_message("ping @sid-agoq-pgas-3b3m-hkas-nyzd-mn5k-le", Some("peer"));
        let classified = classify_message(
            message,
            &identities(),
            &HollywoodAttentionSettings::default(),
            true,
        )
        .expect("mention should pass focused filter");

        assert!(classified.mentioned);
        assert_eq!(classified.attention, HollywoodMessageAttention::Focused);
        assert_eq!(
            classified.notification_message.mentions,
            vec!["019d0798-12d8-76c3-a812-6e323637aa59".to_string()]
        );
    }

    #[test]
    fn focused_mode_drops_unmentioned_room_chatter() {
        let message = sample_message("ambient room chatter", Some("peer"));
        let classified = classify_message(
            message,
            &identities(),
            &HollywoodAttentionSettings::default(),
            true,
        );

        assert!(classified.is_none());
    }

    #[test]
    fn ambient_mode_keeps_unmentioned_room_chatter_as_ambient() {
        let message = sample_message("ambient room chatter", Some("peer"));
        let classified = classify_message(
            message,
            &identities(),
            &HollywoodAttentionSettings {
                mode: HollywoodAttentionMode::Ambient,
                ..HollywoodAttentionSettings::default()
            },
            true,
        )
        .expect("ambient mode should keep room chatter");

        assert!(!classified.mentioned);
        assert_eq!(classified.attention, HollywoodMessageAttention::Ambient);
    }

    #[test]
    fn at_all_promotes_message_in_focused_mode() {
        let message = sample_message("attention @all", Some("peer"));
        let classified = classify_message(
            message,
            &identities(),
            &HollywoodAttentionSettings::default(),
            true,
        )
        .expect("@all should be actionable");

        assert!(!classified.mentioned);
        assert_eq!(classified.attention, HollywoodMessageAttention::Focused);
    }

    #[test]
    fn self_authored_detection_matches_alias() {
        let message = sample_message("hello room", Some("sid-agoq-pgas-3b3m-hkas-nyzd-mn5k-le"));
        let classified = classify_message(
            message,
            &identities(),
            &HollywoodAttentionSettings {
                mode: HollywoodAttentionMode::Broad,
                ..HollywoodAttentionSettings::default()
            },
            true,
        )
        .expect("broad mode should keep self-authored message");

        assert!(classified.self_authored);
        assert_eq!(classified.attention, HollywoodMessageAttention::Broad);
    }

    #[test]
    fn focused_mode_keeps_explicit_broadcasts() {
        let mut message = sample_message("room-wide discovery ping", Some("peer"));
        message.message_kind = HollywoodMessageKind::Broadcast;
        let classified = classify_message(
            message,
            &identities(),
            &HollywoodAttentionSettings::default(),
            true,
        )
        .expect("explicit broadcast should pass focused filter");

        assert_eq!(classified.attention, HollywoodMessageAttention::Broadcast);
        assert_eq!(
            classified.notification_message.message_kind,
            HollywoodMessageKind::Broadcast
        );
    }

    #[test]
    fn focused_messages_in_non_wake_rooms_downgrade_to_ambient() {
        let message = sample_message("ping @sid-agoq-pgas-3b3m-hkas-nyzd-mn5k-le", Some("peer"));
        let classified = classify_message(
            message,
            &identities(),
            &HollywoodAttentionSettings::default(),
            false,
        )
        .expect("observed-room mention should still be visible");

        assert!(classified.mentioned);
        assert_eq!(classified.attention, HollywoodMessageAttention::Ambient);
    }

    #[test]
    fn explicit_broadcasts_in_non_wake_rooms_downgrade_to_ambient() {
        let mut message = sample_message("room-wide discovery ping", Some("peer"));
        message.message_kind = HollywoodMessageKind::Broadcast;
        let classified = classify_message(
            message,
            &identities(),
            &HollywoodAttentionSettings::default(),
            false,
        )
        .expect("observed-room broadcasts should still be visible");

        assert_eq!(classified.attention, HollywoodMessageAttention::Ambient);
        assert_eq!(
            classified.notification_message.message_kind,
            HollywoodMessageKind::Broadcast
        );
    }

    #[test]
    fn focused_mode_keeps_self_authored_messages_as_ambient() {
        let message = sample_message("hello room", Some("sid-agoq-pgas-3b3m-hkas-nyzd-mn5k-le"));
        let classified = classify_message(
            message,
            &identities(),
            &HollywoodAttentionSettings::default(),
            true,
        )
        .expect("focused mode should keep self-authored messages for room activity tracking");

        assert!(classified.self_authored);
        assert_eq!(classified.attention, HollywoodMessageAttention::Ambient);
    }

    #[test]
    fn autonomous_turn_requires_activity_after_last_turn_start() {
        let mut state = HollywoodRuntimeState::default();
        state.attach(HollywoodConfig::default(), "attached", None);
        let now = Instant::now();
        state.note_turn_started(now);
        state.note_message_activity(now - Duration::from_secs(1));
        assert!(!state.should_start_autonomous_turn(now + Duration::from_secs(3)));
        state.note_message_activity(now + Duration::from_secs(1));
        assert!(state.should_start_autonomous_turn(now + Duration::from_secs(3)));
    }

    #[test]
    fn attach_marks_startup_turn_pending_until_first_turn_starts() {
        let mut state = HollywoodRuntimeState::default();
        state.attach(HollywoodConfig::default(), "attached", None);

        assert!(state.should_start_startup_turn());

        state.note_turn_started(Instant::now());

        assert!(!state.should_start_startup_turn());
    }

    #[test]
    fn session_id_alias_matches_expected_format() {
        let uuid = Uuid::parse_str("019d0798-12d8-76c3-a812-6e323637aa59").expect("valid uuid");

        assert_eq!(
            session_id_to_alias(uuid),
            "sid-agoq-pgas-3b3m-hkas-nyzd-mn5k-le"
        );
    }

    #[test]
    #[serial]
    fn hollywood_config_from_env_uses_defaults_and_attention_mode() {
        let _auto_attach = EnvGuard::set("HOLLYWOOD_AUTO_ATTACH", Some("1"));
        let _url = EnvGuard::set("HOLLYWOOD_URL", None);
        let _room = EnvGuard::set("HOLLYWOOD_ROOM", None);
        let _mode = EnvGuard::set("HOLLYWOOD_ATTENTION_MODE", Some("ambient"));

        let config = HollywoodConfig::from_env().expect("Hollywood config should load");

        assert_eq!(config.url, DEFAULT_HOLLYWOOD_URL);
        assert_eq!(config.room, "repo/losangelex");
        assert_eq!(config.observed_rooms, vec!["main".to_string()]);
        assert_eq!(config.attention.mode, HollywoodAttentionMode::Ambient);
        assert!(config.attention.include_at_all);
        assert!(config.attention.include_at_room);
    }

    #[test]
    fn attach_options_default_main_observation_for_repo_room() {
        let config = HollywoodConfig::from(&HollywoodSessionAttachOptions {
            url: None,
            room: Some("repo/losangelex".to_string()),
            observed_rooms: Vec::new(),
            wake_rooms: Vec::new(),
            attention: None,
        });

        assert_eq!(config.observed_rooms, vec!["main".to_string()]);
    }

    #[test]
    fn persisted_hollywood_session_meta_round_trips_into_runtime_config() {
        let persisted = HollywoodSessionMeta {
            url: "http://127.0.0.1:9000".to_string(),
            room: "agents".to_string(),
            observed_rooms: vec!["main".to_string()],
            wake_rooms: vec!["agents".to_string()],
            attention_mode: "broad".to_string(),
            include_at_all: false,
            include_at_room: true,
        };

        let config = HollywoodConfig::try_from(&persisted).expect("persisted config should parse");
        let round_trip = HollywoodSessionMeta::from(&config);

        assert_eq!(config.url, persisted.url);
        assert_eq!(config.room, persisted.room);
        assert_eq!(config.attention.mode, HollywoodAttentionMode::Broad);
        assert_eq!(round_trip, persisted);
    }

    #[test]
    fn effective_wake_rooms_default_to_primary_room_only() {
        let config = HollywoodConfig {
            room: "task-room".to_string(),
            observed_rooms: vec!["main".to_string()],
            wake_rooms: Vec::new(),
            ..HollywoodConfig::default()
        };

        assert_eq!(
            config.effective_wake_rooms(),
            HashSet::from(["task-room".to_string()])
        );
    }
}
