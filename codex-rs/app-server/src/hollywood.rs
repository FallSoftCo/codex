use codex_app_server_protocol::HollywoodAttentionMode;
use codex_app_server_protocol::HollywoodAttentionSettings;
use codex_app_server_protocol::HollywoodMessage;
use codex_app_server_protocol::HollywoodMessageAttention;
use codex_app_server_protocol::HollywoodMessageKind;
use codex_app_server_protocol::HollywoodResponsePolicy;
use codex_app_server_protocol::HollywoodSessionAttachOptions;
use codex_app_server_protocol::HollywoodSessionDiagnostics;
use codex_app_server_protocol::HollywoodSessionState;
use codex_app_server_protocol::HollywoodSessionStatus;
use codex_app_server_protocol::ThreadStatus;
use codex_core::CodexThread;
use codex_core::coordination_identity_from_thread_name;
use codex_core::default_hollywood_observed_rooms;
use codex_core::default_hollywood_room_for_cwd;
use codex_core::parse_agent_mentions;
use codex_protocol::ThreadId;
use codex_protocol::protocol::HollywoodSessionMeta;
use codex_protocol::protocol::HollywoodSyntheticBrief;
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
pub(crate) const HOLLYWOOD_ROOM_CONTRACT_VERSION: &str = "losangelex-room/v2";
pub(crate) const HOLLYWOOD_POLL_INTERVAL: Duration = Duration::from_millis(1500);
pub(crate) const HOLLYWOOD_AUTONOMOUS_COOLDOWN: Duration = Duration::from_secs(2);
pub(crate) const HOLLYWOOD_STARTUP_GRACE_PERIOD: Duration = Duration::from_secs(5);
pub(crate) const HOLLYWOOD_REGISTRY_SYNC_INTERVAL: Duration = Duration::from_secs(15);
const HOLLYWOOD_PAGE_LIMIT: i64 = 100;
const HOLLYWOOD_PENDING_WAKE_LIMIT: usize = 8;
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
    snapshot: Option<HollywoodRoomSnapshot>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub(crate) struct HollywoodRuntimeState {
    config: Option<HollywoodConfig>,
    room_states: HashMap<String, HollywoodRoomState>,
    attached_at: Option<Instant>,
    startup_turn_pending: bool,
    last_turn_started_at: Option<Instant>,
    autonomous_turn_pending: bool,
    pending_semantic_wakes: Vec<HollywoodPendingSemanticWake>,
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
        self.attached_at = Some(Instant::now());
        if let Some(config) = &self.config {
            for room in config.all_rooms() {
                self.room_states.insert(
                    room,
                    HollywoodRoomState {
                        last_seen_message_id: 0,
                        start_from_latest: true,
                        ..HollywoodRoomState::default()
                    },
                );
            }
        }
        self.startup_turn_pending = true;
        self.last_turn_started_at = None;
        self.autonomous_turn_pending = false;
        self.pending_semantic_wakes.clear();
        self.registry_session_kind = Some(session_kind.into());
        self.registry_resumed_from = resumed_from;
        self.last_registry_sync_at = None;
        self.last_registry_status = None;
    }

    pub(crate) fn detach(&mut self) {
        self.config = None;
        self.room_states.clear();
        self.attached_at = None;
        self.startup_turn_pending = false;
        self.last_turn_started_at = None;
        self.autonomous_turn_pending = false;
        self.pending_semantic_wakes.clear();
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

    pub(crate) fn note_room_snapshot(
        &mut self,
        room: &str,
        snapshot: Option<&HollywoodRoomSnapshot>,
        last_id: i64,
    ) -> bool {
        let Some(snapshot) = snapshot else {
            return false;
        };
        let state = self.room_states.entry(room.to_string()).or_default();
        let changed = state
            .snapshot
            .as_ref()
            .is_some_and(|value| value != snapshot);
        state.snapshot = Some(snapshot.clone());
        if changed {
            state.last_seen_message_id = last_id;
            state.start_from_latest = false;
        }
        changed
    }

    pub(crate) fn take_start_from_latest(&mut self, room: &str) -> bool {
        let state = self.room_states.entry(room.to_string()).or_default();
        let value = state.start_from_latest;
        state.start_from_latest = false;
        value
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

    pub(crate) fn room_snapshot(&self, room: &str) -> Option<HollywoodRoomSnapshot> {
        self.room_states
            .get(room)
            .and_then(|state| state.snapshot.clone())
    }

    pub(crate) fn reconcile_idle_autonomous_turn_pending(
        &mut self,
        status: &ThreadStatus,
        has_active_turn: bool,
    ) {
        if self.autonomous_turn_pending
            && matches!(status, ThreadStatus::Idle)
            && !has_active_turn
            && self.pending_semantic_wakes.is_empty()
        {
            self.autonomous_turn_pending = false;
        }
    }

    pub(crate) fn should_start_startup_turn(&self, now: Instant) -> bool {
        if self.config.is_none() || !self.startup_turn_pending || self.autonomous_turn_pending {
            return false;
        }

        self.attached_at.is_some_and(|attached_at| {
            now.duration_since(attached_at) >= HOLLYWOOD_STARTUP_GRACE_PERIOD
        })
    }

    pub(crate) fn clear_startup_turn_pending(&mut self) {
        self.startup_turn_pending = false;
    }

    pub(crate) fn mark_startup_turn_pending(&mut self) {
        self.startup_turn_pending = true;
    }

    pub(crate) fn startup_turn_pending(&self) -> bool {
        self.startup_turn_pending
    }

    pub(crate) fn autonomous_turn_pending(&self) -> bool {
        self.autonomous_turn_pending
    }

    pub(crate) fn pending_semantic_wake_count(&self) -> usize {
        self.pending_semantic_wakes.len()
    }

    pub(crate) fn queue_semantic_wake(&mut self, wake: HollywoodPendingSemanticWake) {
        if let Some(existing) = self
            .pending_semantic_wakes
            .iter_mut()
            .find(|existing| existing.dedupe_key == wake.dedupe_key)
        {
            *existing = wake;
            return;
        }
        self.pending_semantic_wakes.push(wake);
        if self.pending_semantic_wakes.len() > HOLLYWOOD_PENDING_WAKE_LIMIT {
            let overflow = self.pending_semantic_wakes.len() - HOLLYWOOD_PENDING_WAKE_LIMIT;
            self.pending_semantic_wakes.drain(0..overflow);
        }
    }

    pub(crate) fn take_pending_semantic_wakes(&mut self) -> Vec<HollywoodPendingSemanticWake> {
        std::mem::take(&mut self.pending_semantic_wakes)
    }

    pub(crate) fn restore_pending_semantic_wakes(
        &mut self,
        mut wakes: Vec<HollywoodPendingSemanticWake>,
    ) {
        for wake in wakes.drain(..) {
            self.queue_semantic_wake(wake);
        }
    }

    pub(crate) fn should_start_autonomous_turn(&self, now: Instant) -> bool {
        if self.config.is_none()
            || self.autonomous_turn_pending
            || self.pending_semantic_wakes.is_empty()
        {
            return false;
        }

        if let Some(last_turn_started_at) = self.last_turn_started_at
            && now.duration_since(last_turn_started_at) < HOLLYWOOD_AUTONOMOUS_COOLDOWN
        {
            return false;
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
struct HollywoodApiRoomState {
    room: String,
    state_version: i64,
    contract_version: String,
    #[serde(default)]
    coordination_policy: Option<String>,
    #[serde(default)]
    coordination_phase: Option<String>,
    #[serde(default = "default_coordination_epoch")]
    coordination_epoch: i64,
    #[serde(default)]
    leader_session_id: Option<String>,
    #[serde(default)]
    verifier_session_id: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct HollywoodRoomSnapshot {
    pub(crate) room: String,
    pub(crate) state_version: i64,
    pub(crate) contract_version: String,
    pub(crate) coordination_policy: Option<String>,
    pub(crate) coordination_phase: Option<String>,
    pub(crate) coordination_epoch: i64,
    pub(crate) leader_session_id: Option<String>,
    pub(crate) verifier_session_id: Option<String>,
}

#[derive(Debug, Deserialize)]
struct HollywoodMessagesResponse {
    messages: Vec<HollywoodApiMessage>,
    last_id: i64,
    #[serde(default)]
    room_state: Option<HollywoodApiRoomState>,
}

#[derive(Debug, Deserialize)]
struct HollywoodRoomsResponse {
    rooms: Vec<HollywoodApiRoomState>,
}

#[derive(Debug)]
pub(crate) struct HollywoodPollResult {
    pub(crate) messages: Vec<HollywoodClassifiedMessage>,
    pub(crate) last_id: i64,
    pub(crate) room_state: Option<HollywoodRoomSnapshot>,
}

#[derive(Debug)]
pub(crate) struct HollywoodClassifiedMessage {
    pub(crate) notification_message: HollywoodMessage,
    pub(crate) attention: HollywoodMessageAttention,
    pub(crate) mentioned: bool,
    pub(crate) self_authored: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct HollywoodPendingSemanticWake {
    pub(crate) dedupe_key: String,
    pub(crate) room: String,
    pub(crate) brief: HollywoodSyntheticBrief,
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
    thread_name: Option<&str>,
) -> Result<HollywoodPollResult, String> {
    let mut room_config = config.clone();
    room_config.room = room.to_string();
    let response = fetch_messages(client, &room_config, after_id, HOLLYWOOD_PAGE_LIMIT).await?;
    let identities = hollywood_identities(thread_id, thread_name);
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
        room_state: response.room_state.map(|room_state| HollywoodRoomSnapshot {
            room: room_state.room,
            state_version: room_state.state_version,
            contract_version: room_state.contract_version,
            coordination_policy: room_state.coordination_policy,
            coordination_phase: room_state.coordination_phase,
            coordination_epoch: room_state.coordination_epoch,
            leader_session_id: room_state.leader_session_id,
            verifier_session_id: room_state.verifier_session_id,
        }),
    })
}

pub(crate) async fn fetch_room_state(
    client: &Client,
    config: &HollywoodConfig,
    room: &str,
) -> Result<Option<HollywoodRoomSnapshot>, String> {
    let url = format!("{}/hollywood/v1/rooms", config.url.trim_end_matches('/'));
    let response = client
        .get(url)
        .query(&[("room", room), ("limit", "1")])
        .send()
        .await
        .map_err(|err| format!("Hollywood room-state request failed: {err}"))?
        .error_for_status()
        .map_err(|err| format!("Hollywood room-state request failed: {err}"))?
        .json::<HollywoodRoomsResponse>()
        .await
        .map_err(|err| format!("Hollywood room-state response parse failed: {err}"))?;

    Ok(response
        .rooms
        .into_iter()
        .next()
        .map(|room_state| HollywoodRoomSnapshot {
            room: room_state.room,
            state_version: room_state.state_version,
            contract_version: room_state.contract_version,
            coordination_policy: room_state.coordination_policy,
            coordination_phase: room_state.coordination_phase,
            coordination_epoch: room_state.coordination_epoch,
            leader_session_id: room_state.leader_session_id,
            verifier_session_id: room_state.verifier_session_id,
        }))
}

pub(crate) async fn upsert_registry(
    client: &Client,
    config: &HollywoodConfig,
    request: &HollywoodRegistryUpsertRequest,
) -> Result<(), String> {
    let url = format!("{}/hollywood/v1/registry", config.url.trim_end_matches('/'));
    let response = client
        .post(url)
        .json(request)
        .send()
        .await
        .map_err(|err| format!("Hollywood registry request failed: {err}"))?;
    if let Err(err) = response.error_for_status_ref() {
        let body = response.text().await.unwrap_or_default();
        let detail = if body.trim().is_empty() {
            err.to_string()
        } else {
            format!("{err}: {body}")
        };
        return Err(format!("Hollywood registry request failed: {detail}"));
    }
    Ok(())
}

fn durable_coordination_guidance(state_db_available: bool) -> &'static str {
    if state_db_available {
        "When room discussion becomes a real assignment, acceptance, handoff, dependency, or completion, record that durable commitment with coordination_act so Losangelex can survive idle gaps, restart, and rolling deploy."
    } else {
        "This session does not currently expose durable coordination tools, so do not call coordination_act; keep Hollywood ownership updates current and treat them as best-effort until durable coordination returns."
    }
}

fn durable_coordination_handshake_guidance(state_db_available: bool) -> &'static str {
    if state_db_available {
        "When a room discussion becomes a real assignment, acceptance, handoff, dependency, or completion, record that durable commitment with `coordination_act` so the coordination survives idle gaps, restart, and rolling deploy."
    } else {
        "This session does not currently expose durable coordination tools, so do not call `coordination_act`; keep Hollywood ownership updates current and treat them as best-effort until durable coordination returns."
    }
}

pub(crate) fn startup_announces_presence(config: &HollywoodConfig) -> bool {
    !matches!(config.attention.mode, HollywoodAttentionMode::Focused)
}

pub(crate) fn format_hollywood_context_message(
    thread_id: ThreadId,
    thread_name: Option<&str>,
    config: &HollywoodConfig,
    state_db_available: bool,
) -> String {
    let agent_name = normalized_thread_name(thread_name);
    let coordination_identity = agent_name
        .as_deref()
        .and_then(coordination_identity_from_thread_name);
    let wake_rooms = config
        .effective_wake_rooms()
        .into_iter()
        .collect::<Vec<_>>();
    let announce_presence = startup_announces_presence(config);
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
        "agent_name": agent_name,
        "coordination_identity": coordination_identity,
        "identities": hollywood_identities(thread_id, thread_name),
        "startup_protocol": {
            "announce_presence": announce_presence,
            "read_recent_room_context": true,
            "ask_user_for_tasking_when_unassigned": false,
            "relay_assigned_scope_to_room": true,
            "check_existing_scope_claims_before_editing": true,
            "claim_exact_paths_or_modules_before_editing": true,
            "avoid_overlapping_edits_until_resolved": true,
            "relay_material_conclusions_to_room": true,
        },
        "broadcast_guidance": [
            "Use sparse explicit room-wide broadcasts for presence, scope changes, blockers, handoffs, major completion updates, and discovery-oriented coordination. Explicit broadcasts can wake idle attached agents.",
            "Use @mentions for direct requests, replies, and anything that should reliably wake another agent.",
            "When you claim scope, make it concrete: name exact files, modules, directories, or narrow globs, and update or relinquish that claim when it changes.",
            "If another agent already owns an overlapping path, do not edit that path until the overlap is resolved in Hollywood.",
            "When the user asks you to work with teammates, peers, or other existing agents, use Hollywood coordination with attached Losangelex agents first and reserve new subagents for parallelizing your own currently owned work into bounded sidecar tasks.",
            "If you finish startup unassigned, stay available and wait for explicit tasking instead of asking the user an open-ended readiness question.",
            durable_coordination_guidance(state_db_available),
            "When you reach a concrete diagnosis, decision, or verification result that materially affects peer work, send a concise room update so other agents and the user-facing session can converge on the same conclusion.",
            "If another agent posts an explicit final QA or room-closure signal saying the gate is green and the room can stand down, do not run redundant local confirmation or send another closure update unless you still own unresolved exact scope or were directly asked to verify. End your current turn promptly instead.",
            "If autonomous Hollywood follow-up finds no new state to report, prefer no user-facing follow-up at all; if one is needed, keep it to a compact status tag rather than a full explanation.",
        ],
    })
    .to_string();
    format!("{HOLLYWOOD_CONTEXT_OPEN_TAG}\n{payload_json}\n{HOLLYWOOD_CONTEXT_CLOSE_TAG}")
}

pub(crate) fn startup_handshake_message(
    thread_id: ThreadId,
    thread_name: Option<&str>,
    config: &HollywoodConfig,
    state_db_available: bool,
) -> String {
    let identities = hollywood_identities(thread_id, thread_name).join(", ");
    let announce_presence = startup_announces_presence(config);
    let name_guidance = match normalized_thread_name(thread_name) {
        Some(agent_name) => match coordination_identity_from_thread_name(&agent_name) {
            Some(coordination_identity) => format!(
                " Your launch-time assistant name is `{agent_name}` and your additive Hollywood coordination alias is `@{coordination_identity}`; treat that name as part of your teamwork identity and respond when peers use it."
            ),
            None => format!(
                " Your launch-time assistant name is `{agent_name}`; treat it as part of your teamwork identity."
            ),
        },
        None => String::new(),
    };
    let observed = if config.observed_rooms.is_empty() {
        String::new()
    } else {
        format!(
            " You are also observing rooms [{}].",
            config.observed_rooms.join(", ")
        )
    };
    let startup_guidance = if announce_presence {
        "Before doing substantive work, send one short explicit room-wide broadcast announcing that you are online, your current repo or cwd if known, and whether you are available or already assigned. Then read recent room traffic once to orient yourself and check for existing scope claims."
    } else {
        "Before doing substantive work, read recent room traffic once to orient yourself and check for existing scope claims. In focused mode, do not send a startup presence broadcast by default. If you already own active scope, need to re-establish a handoff after reconnect or rolling deploy, or receive concrete user tasking, send one concise room update naming the exact scope or status that changed."
    };
    format!(
        "Startup protocol: you have just attached to the local Hollywood primary room `{}` as session identities [{}].{}{} {} If you do not yet have a concrete user-assigned task after startup, stay available and wait for explicit tasking instead of asking the user an open-ended readiness question. After the user gives you concrete tasking, send one concise room update relaying your assigned scope or ownership so other agents can coordinate. Make scope claims concrete by naming exact files, modules, directories, or narrow globs you own; if another agent already owns an overlapping path, do not edit that path until the overlap is resolved in Hollywood. When the user asks you to work with teammates, peers, or other existing agents, coordinate with the already attached Hollywood sessions first and reserve new subagents for parallelizing your own currently owned work into bounded sidecar subtasks. {} When your scope changes or you hand work off, send a follow-up update reflecting the new ownership. When you reach a concrete diagnosis, decision, or verification result that materially affects peer work, send a concise room update before or alongside your user-facing answer so other sessions can converge on the same conclusion. If another agent later posts an explicit final QA or room-closure signal saying the gate is green and the room can stand down, do not run redundant local confirmation or send another closure update unless you still own unresolved exact scope or were directly asked to verify; end your turn promptly instead. If autonomous Hollywood follow-up later finds no new state to report, do not send a user-facing no-op message; stay silent unless something changed, and if you must acknowledge room state, keep it to a compact status tag. Use explicit room-wide broadcasts sparingly for presence, scope changes, blockers, handoffs, major completion updates, material conclusions that peers should know, and discovery-oriented coordination where any relevant idle agent should notice. Use @mentions for direct requests, replies, and anything that should reliably get another agent's attention. If you see an unmentioned room message that is plainly about your current repo, ownership, or specialized domain, proactively reply even without being @mentioned.",
        config.room,
        identities,
        observed,
        name_guidance,
        startup_guidance,
        durable_coordination_handshake_guidance(state_db_available),
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

fn default_coordination_epoch() -> i64 {
    1
}

pub(crate) fn hollywood_identities(thread_id: ThreadId, thread_name: Option<&str>) -> Vec<String> {
    let raw = thread_id.to_string();
    let mut identities = vec![normalize_identity(&raw)];
    let mut seen = HashSet::from([identities[0].clone()]);
    if let Ok(uuid) = Uuid::parse_str(&raw) {
        let alias = session_id_to_alias(uuid);
        if seen.insert(alias.clone()) {
            identities.push(alias);
        }
    }
    if let Some(named_identity) = thread_name.and_then(coordination_identity_from_thread_name)
        && seen.insert(named_identity.clone())
    {
        identities.push(named_identity);
    }
    identities
}

fn normalized_thread_name(thread_name: Option<&str>) -> Option<String> {
    thread_name.and_then(codex_core::util::normalize_thread_name)
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
    thread_name: Option<&str>,
    config: &HollywoodConfig,
    runtime_state: &HollywoodRuntimeState,
    status: HollywoodSessionStatus,
    diagnostics: HollywoodSessionDiagnostics,
) -> HollywoodSessionState {
    HollywoodSessionState {
        attached: true,
        url: config.url.clone(),
        primary_room: config.room.clone(),
        observed_rooms: config.observed_rooms.clone(),
        wake_rooms: config.effective_wake_rooms().into_iter().collect(),
        attention: config.attention.clone(),
        identities: hollywood_identities(thread_id, thread_name),
        session_kind: runtime_state.registry_session_kind().map(ToOwned::to_owned),
        resumed_from: runtime_state.registry_resumed_from().map(ToOwned::to_owned),
        status,
        diagnostics: Some(diagnostics),
    }
}

pub(crate) fn hollywood_session_state_from_persisted(
    thread_id: ThreadId,
    thread_name: Option<&str>,
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
        identities: hollywood_identities(thread_id, thread_name),
        session_kind: None,
        resumed_from: None,
        status: HollywoodSessionStatus::Persisted,
        diagnostics: None,
    })
}

pub(crate) fn hollywood_session_diagnostics_from_runtime(
    runtime_state: &HollywoodRuntimeState,
    active_turn: Option<&codex_app_server_protocol::Turn>,
    outstanding_obligation_count: usize,
) -> HollywoodSessionDiagnostics {
    HollywoodSessionDiagnostics {
        current_turn_open: active_turn.is_some(),
        active_turn_id: active_turn.map(|turn| turn.id.clone()),
        active_turn_started_at: active_turn.and_then(|turn| turn.started_at),
        active_turn_item_count: active_turn
            .map(|turn| turn.items.len())
            .unwrap_or(0)
            .try_into()
            .unwrap_or(u32::MAX),
        startup_turn_pending: runtime_state.startup_turn_pending(),
        autonomous_turn_pending: runtime_state.autonomous_turn_pending(),
        pending_semantic_wake_count: runtime_state
            .pending_semantic_wake_count()
            .try_into()
            .unwrap_or(u32::MAX),
        outstanding_obligation_count: outstanding_obligation_count.try_into().unwrap_or(u32::MAX),
    }
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
    thread_name: Option<&str>,
) -> HollywoodRegistryUpsertRequest {
    let snapshot = thread.config_snapshot().await;
    let cwd = snapshot.cwd.display().to_string();
    let thread_name = thread_name.or(snapshot.thread_name.as_deref());
    HollywoodRegistryUpsertRequest {
        session_id: thread_id.to_string(),
        room: config.room.clone(),
        attached: true,
        cwd: Some(cwd),
        repo_name: repo_name_from_cwd(snapshot.cwd.as_path()),
        attention_mode: hollywood_attention_mode_name(config.attention.mode),
        identities: hollywood_identities(thread_id, thread_name),
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

    fn named_identities() -> Vec<String> {
        let mut identities = identities();
        identities.push("scout-agent".to_string());
        identities
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
    fn focused_mode_keeps_named_mentions() {
        let message = sample_message("ping @scout-agent", Some("peer"));
        let classified = classify_message(
            message,
            &named_identities(),
            &HollywoodAttentionSettings::default(),
            true,
        )
        .expect("named mention should pass focused filter");

        assert!(classified.mentioned);
        assert_eq!(classified.attention, HollywoodMessageAttention::Focused);
        assert_eq!(
            classified.notification_message.mentions,
            vec!["scout-agent".to_string()]
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
    fn autonomous_turn_requires_pending_semantic_wake_after_last_turn_start() {
        let mut state = HollywoodRuntimeState::default();
        state.attach(HollywoodConfig::default(), "attached", None);
        let now = Instant::now();
        state.note_turn_started(now);
        assert!(!state.should_start_autonomous_turn(now + Duration::from_secs(3)));
        state.queue_semantic_wake(HollywoodPendingSemanticWake {
            dedupe_key: "message:42".to_string(),
            room: "main".to_string(),
            brief: HollywoodSyntheticBrief {
                wake_reason: Some("semantic_delta".to_string()),
                semantic_kind: Some("scope_update".to_string()),
                coordination_policy: None,
                coordination_phase: None,
                coordination_role: None,
                coordination_epoch: None,
                summary: Some("A peer ownership change may affect your lane.".to_string()),
                facts: Vec::new(),
                suggested_actions: vec!["check whether your scope changed".to_string()],
                stay_silent_if_no_actionable_delta: true,
            },
        });
        assert!(state.should_start_autonomous_turn(now + Duration::from_secs(3)));
    }

    #[test]
    fn attach_marks_startup_turn_pending_until_first_turn_starts() {
        let mut state = HollywoodRuntimeState::default();
        state.attach(HollywoodConfig::default(), "attached", None);
        let now = Instant::now();

        assert!(!state.should_start_startup_turn(now));
        assert!(state.should_start_startup_turn(now + HOLLYWOOD_STARTUP_GRACE_PERIOD));

        state.note_turn_started(now + Duration::from_secs(1));

        assert!(!state.should_start_startup_turn(now + HOLLYWOOD_STARTUP_GRACE_PERIOD));
    }

    #[test]
    fn runtime_session_state_includes_live_diagnostics() {
        let thread_id =
            ThreadId::from_string("019d0798-12d8-76c3-a812-6e323637aa59").expect("valid thread");
        let mut runtime = HollywoodRuntimeState::default();
        runtime.attach(HollywoodConfig::default(), "attached", None);
        runtime.mark_autonomous_turn_pending();
        runtime.queue_semantic_wake(HollywoodPendingSemanticWake {
            dedupe_key: "message:42".to_string(),
            room: "repo/losangelex".to_string(),
            brief: HollywoodSyntheticBrief {
                wake_reason: Some("semantic_delta".to_string()),
                semantic_kind: Some("assignment".to_string()),
                coordination_policy: None,
                coordination_phase: None,
                coordination_role: None,
                coordination_epoch: None,
                summary: Some("A direct assignment needs attention.".to_string()),
                facts: Vec::new(),
                suggested_actions: vec!["accept or decline explicitly".to_string()],
                stay_silent_if_no_actionable_delta: false,
            },
        });
        let turn = codex_app_server_protocol::Turn {
            id: "turn-live".to_string(),
            items: vec![codex_app_server_protocol::ThreadItem::UserMessage {
                id: "item-1".to_string(),
                content: Vec::new(),
            }],
            items_view: codex_app_server_protocol::TurnItemsView::Full,
            status: codex_app_server_protocol::TurnStatus::InProgress,
            error: None,
            started_at: Some(1_714_008_400),
            completed_at: None,
            duration_ms: None,
        };

        let state = hollywood_session_state_from_runtime(
            thread_id,
            Some("Scout Agent"),
            &HollywoodConfig::default(),
            &runtime,
            HollywoodSessionStatus::Active,
            hollywood_session_diagnostics_from_runtime(&runtime, Some(&turn), 3),
        );

        let diagnostics = state.diagnostics.expect("live diagnostics");
        assert!(diagnostics.current_turn_open);
        assert_eq!(diagnostics.active_turn_id.as_deref(), Some("turn-live"));
        assert_eq!(diagnostics.active_turn_started_at, Some(1_714_008_400));
        assert_eq!(diagnostics.active_turn_item_count, 1);
        assert!(diagnostics.startup_turn_pending);
        assert!(diagnostics.autonomous_turn_pending);
        assert_eq!(diagnostics.pending_semantic_wake_count, 1);
        assert_eq!(diagnostics.outstanding_obligation_count, 3);
    }

    #[test]
    fn reconcile_idle_autonomous_turn_pending_clears_stale_flag() {
        let mut state = HollywoodRuntimeState::default();
        state.attach(HollywoodConfig::default(), "attached", None);
        state.mark_autonomous_turn_pending();

        state.reconcile_idle_autonomous_turn_pending(&ThreadStatus::Idle, false);

        assert!(!state.autonomous_turn_pending());
    }

    #[test]
    fn reconcile_idle_autonomous_turn_pending_keeps_real_pending_wakes() {
        let mut state = HollywoodRuntimeState::default();
        state.attach(HollywoodConfig::default(), "attached", None);
        state.mark_autonomous_turn_pending();
        state.queue_semantic_wake(HollywoodPendingSemanticWake {
            dedupe_key: "message:42".to_string(),
            room: "repo/losangelex".to_string(),
            brief: HollywoodSyntheticBrief {
                wake_reason: Some("semantic_delta".to_string()),
                semantic_kind: Some("assignment".to_string()),
                coordination_policy: None,
                coordination_phase: None,
                coordination_role: None,
                coordination_epoch: None,
                summary: Some("A direct assignment needs attention.".to_string()),
                facts: Vec::new(),
                suggested_actions: vec!["accept or decline explicitly".to_string()],
                stay_silent_if_no_actionable_delta: false,
            },
        });

        state.reconcile_idle_autonomous_turn_pending(&ThreadStatus::Idle, false);

        assert!(state.autonomous_turn_pending());
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
    fn hollywood_identities_append_named_identity_after_session_aliases() {
        let thread_id =
            ThreadId::from_string("019d0798-12d8-76c3-a812-6e323637aa59").expect("valid thread");

        assert_eq!(
            hollywood_identities(thread_id, Some("Scout Agent")),
            vec![
                "019d0798-12d8-76c3-a812-6e323637aa59".to_string(),
                "sid-agoq-pgas-3b3m-hkas-nyzd-mn5k-le".to_string(),
                "scout-agent".to_string(),
            ]
        );
    }

    #[test]
    fn startup_handshake_message_prefers_waiting_for_tasking() {
        let thread_id =
            ThreadId::from_string("019d0798-12d8-76c3-a812-6e323637aa59").expect("valid thread");
        let message = startup_handshake_message(
            thread_id,
            Some("Scout Agent"),
            &HollywoodConfig::default(),
            true,
        );

        assert!(message.contains("wait for explicit tasking"));
        assert!(!message.contains("ask the user what they want you to work on"));
        assert!(message.contains("do not send a startup presence broadcast by default"));
    }

    #[test]
    fn startup_handshake_message_for_ambient_attach_keeps_presence_broadcast() {
        let thread_id =
            ThreadId::from_string("019d0798-12d8-76c3-a812-6e323637aa59").expect("valid thread");
        let message = startup_handshake_message(
            thread_id,
            Some("Scout Agent"),
            &HollywoodConfig {
                attention: HollywoodAttentionSettings {
                    mode: HollywoodAttentionMode::Ambient,
                    include_at_all: true,
                    include_at_room: true,
                },
                ..HollywoodConfig::default()
            },
            true,
        );

        assert!(message.contains("send one short explicit room-wide broadcast announcing"));
    }

    #[test]
    fn focused_hollywood_context_marks_presence_announcement_optional() {
        let thread_id =
            ThreadId::from_string("019d0798-12d8-76c3-a812-6e323637aa59").expect("valid thread");
        let message = format_hollywood_context_message(
            thread_id,
            Some("Scout Agent"),
            &HollywoodConfig::default(),
            true,
        );

        assert!(message.contains("\"announce_presence\":false"));
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

    #[test]
    fn first_room_snapshot_does_not_reset_cursor() {
        let mut runtime = HollywoodRuntimeState::default();
        let changed = runtime.note_room_snapshot(
            "repo/losangelex",
            Some(&HollywoodRoomSnapshot {
                room: "repo/losangelex".to_string(),
                state_version: 1,
                contract_version: HOLLYWOOD_ROOM_CONTRACT_VERSION.to_string(),
                coordination_policy: Some("leader_award".to_string()),
                coordination_phase: Some("execution".to_string()),
                coordination_epoch: 1,
                leader_session_id: Some("leader".to_string()),
                verifier_session_id: Some("verifier".to_string()),
            }),
            42,
        );

        assert!(!changed);
        assert_eq!(runtime.last_seen_message_id("repo/losangelex"), 0);
    }

    #[test]
    fn room_snapshot_state_change_resets_cursor() {
        let mut runtime = HollywoodRuntimeState::default();
        runtime.set_last_seen_message_id("repo/losangelex", 7);
        assert!(!runtime.note_room_snapshot(
            "repo/losangelex",
            Some(&HollywoodRoomSnapshot {
                room: "repo/losangelex".to_string(),
                state_version: 1,
                contract_version: HOLLYWOOD_ROOM_CONTRACT_VERSION.to_string(),
                coordination_policy: Some("leader_award".to_string()),
                coordination_phase: Some("execution".to_string()),
                coordination_epoch: 1,
                leader_session_id: Some("leader".to_string()),
                verifier_session_id: Some("verifier".to_string()),
            }),
            7,
        ));

        let changed = runtime.note_room_snapshot(
            "repo/losangelex",
            Some(&HollywoodRoomSnapshot {
                room: "repo/losangelex".to_string(),
                state_version: 2,
                contract_version: HOLLYWOOD_ROOM_CONTRACT_VERSION.to_string(),
                coordination_policy: Some("kanban_pull".to_string()),
                coordination_phase: Some("stabilization".to_string()),
                coordination_epoch: 2,
                leader_session_id: Some("leader".to_string()),
                verifier_session_id: Some("verifier".to_string()),
            }),
            99,
        );

        assert!(changed);
        assert_eq!(runtime.last_seen_message_id("repo/losangelex"), 99);
    }
}
