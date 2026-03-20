use codex_app_server_protocol::HollywoodAttentionMode;
use codex_app_server_protocol::HollywoodAttentionSettings;
use codex_app_server_protocol::HollywoodMessage;
use codex_app_server_protocol::HollywoodMessageAttention;
use codex_protocol::ThreadId;
use reqwest::Client;
use serde::Deserialize;
use std::time::Duration;
use std::time::Instant;
use uuid::Uuid;

const HOLLYWOOD_CONTEXT_OPEN_TAG: &str = "<hollywood_context>";
const HOLLYWOOD_CONTEXT_CLOSE_TAG: &str = "</hollywood_context>";

pub(crate) const DEFAULT_HOLLYWOOD_URL: &str = "http://127.0.0.1:8765";
pub(crate) const DEFAULT_HOLLYWOOD_ROOM: &str = "main";
pub(crate) const HOLLYWOOD_POLL_INTERVAL: Duration = Duration::from_millis(1500);
pub(crate) const HOLLYWOOD_AUTONOMOUS_COOLDOWN: Duration = Duration::from_secs(2);
const HOLLYWOOD_PAGE_LIMIT: i64 = 100;
const BASE32_ALPHABET: &[u8; 32] = b"abcdefghijklmnopqrstuvwxyz234567";

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct HollywoodConfig {
    pub(crate) url: String,
    pub(crate) room: String,
    pub(crate) attention: HollywoodAttentionSettings,
}

impl Default for HollywoodConfig {
    fn default() -> Self {
        Self {
            url: DEFAULT_HOLLYWOOD_URL.to_string(),
            room: DEFAULT_HOLLYWOOD_ROOM.to_string(),
            attention: HollywoodAttentionSettings::default(),
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub(crate) struct HollywoodRuntimeState {
    config: Option<HollywoodConfig>,
    last_seen_message_id: i64,
    start_from_latest: bool,
    recent_activity_at: Option<Instant>,
    last_turn_started_at: Option<Instant>,
    autonomous_turn_pending: bool,
}

impl HollywoodRuntimeState {
    pub(crate) fn attach(&mut self, config: HollywoodConfig) {
        self.config = Some(config);
        self.last_seen_message_id = 0;
        self.start_from_latest = true;
        self.recent_activity_at = None;
        self.last_turn_started_at = None;
        self.autonomous_turn_pending = false;
    }

    pub(crate) fn detach(&mut self) {
        self.config = None;
        self.last_seen_message_id = 0;
        self.start_from_latest = false;
        self.recent_activity_at = None;
        self.last_turn_started_at = None;
        self.autonomous_turn_pending = false;
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

    pub(crate) fn last_seen_message_id(&self) -> i64 {
        self.last_seen_message_id
    }

    pub(crate) fn set_last_seen_message_id(&mut self, message_id: i64) {
        self.last_seen_message_id = message_id;
    }

    pub(crate) fn take_start_from_latest(&mut self) -> bool {
        let value = self.start_from_latest;
        self.start_from_latest = false;
        value
    }

    pub(crate) fn note_message_activity(&mut self, now: Instant) {
        self.recent_activity_at = Some(now);
    }

    pub(crate) fn note_turn_started(&mut self, now: Instant) {
        self.last_turn_started_at = Some(now);
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
}

#[derive(Debug, Deserialize)]
struct HollywoodApiMessage {
    id: i64,
    room: String,
    sender_id: Option<String>,
    recipient_id: Option<String>,
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
    after_id: i64,
    thread_id: ThreadId,
) -> Result<HollywoodPollResult, String> {
    let response = fetch_messages(client, config, after_id, HOLLYWOOD_PAGE_LIMIT).await?;
    let identities = hollywood_identities(thread_id);
    let messages = response
        .messages
        .into_iter()
        .filter_map(|message| classify_message(message, &identities, &config.attention))
        .collect();
    Ok(HollywoodPollResult {
        messages,
        last_id: response.last_id,
    })
}

pub(crate) fn format_hollywood_context_message(
    thread_id: ThreadId,
    config: &HollywoodConfig,
) -> String {
    let payload_json = serde_json::json!({
        "attached": true,
        "meaning": "Hollywood is the local inter-agent room and messaging system in this runtime, not a physical place.",
        "url": config.url,
        "room": config.room,
        "attention_mode": config.attention.mode,
        "include_at_all": config.attention.include_at_all,
        "include_at_room": config.attention.include_at_room,
        "identities": hollywood_identities(thread_id),
    })
    .to_string();
    format!("{HOLLYWOOD_CONTEXT_OPEN_TAG}\n{payload_json}\n{HOLLYWOOD_CONTEXT_CLOSE_TAG}")
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
) -> Option<HollywoodClassifiedMessage> {
    let mentions = parse_mentions(&message.body);
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
    let at_all = mentions.iter().any(|mention| mention == "all");
    let at_room = mentions.iter().any(|mention| mention == "room");
    let broadcast_match =
        (attention.include_at_all && at_all) || (attention.include_at_room && at_room);

    let attention_class = if mentioned || broadcast_match {
        HollywoodMessageAttention::Focused
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
            body: message.body,
            created_at: message.created_at,
            mentions,
        },
        attention: attention_class,
        mentioned,
        self_authored,
    })
}

fn hollywood_identities(thread_id: ThreadId) -> Vec<String> {
    let raw = thread_id.to_string();
    let mut identities = vec![normalize_identity(&raw)];
    if let Ok(uuid) = Uuid::parse_str(&raw) {
        identities.push(session_id_to_alias(uuid));
    }
    identities
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

fn parse_mentions(body: &str) -> Vec<String> {
    let mut mentions = Vec::new();
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
        if idx > start {
            mentions.push(normalize_identity(&body[start..idx]));
        }
    }
    mentions
}

fn normalize_identity(value: &str) -> String {
    value.trim().trim_start_matches('@').to_ascii_lowercase()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_message(body: &str, sender_id: Option<&str>) -> HollywoodApiMessage {
        HollywoodApiMessage {
            id: 42,
            room: "main".to_string(),
            sender_id: sender_id.map(ToOwned::to_owned),
            recipient_id: None,
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
        )
        .expect("mention should pass focused filter");

        assert!(classified.mentioned);
        assert_eq!(classified.attention, HollywoodMessageAttention::Focused);
        assert_eq!(
            classified.notification_message.mentions,
            vec!["sid-agoq-pgas-3b3m-hkas-nyzd-mn5k-le".to_string()]
        );
    }

    #[test]
    fn focused_mode_drops_unmentioned_room_chatter() {
        let message = sample_message("ambient room chatter", Some("peer"));
        let classified = classify_message(
            message,
            &identities(),
            &HollywoodAttentionSettings::default(),
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
        )
        .expect("broad mode should keep self-authored message");

        assert!(classified.self_authored);
        assert_eq!(classified.attention, HollywoodMessageAttention::Broad);
    }

    #[test]
    fn focused_mode_keeps_self_authored_messages_as_ambient() {
        let message = sample_message("hello room", Some("sid-agoq-pgas-3b3m-hkas-nyzd-mn5k-le"));
        let classified = classify_message(
            message,
            &identities(),
            &HollywoodAttentionSettings::default(),
        )
        .expect("focused mode should keep self-authored messages for room activity tracking");

        assert!(classified.self_authored);
        assert_eq!(classified.attention, HollywoodMessageAttention::Ambient);
    }

    #[test]
    fn autonomous_turn_requires_activity_after_last_turn_start() {
        let mut state = HollywoodRuntimeState::default();
        state.attach(HollywoodConfig::default());
        let now = Instant::now();
        state.note_turn_started(now);
        state.note_message_activity(now - Duration::from_secs(1));
        assert!(!state.should_start_autonomous_turn(now + Duration::from_secs(3)));
        state.note_message_activity(now + Duration::from_secs(1));
        assert!(state.should_start_autonomous_turn(now + Duration::from_secs(3)));
    }

    #[test]
    fn session_id_alias_matches_expected_format() {
        let uuid = Uuid::parse_str("019d0798-12d8-76c3-a812-6e323637aa59").expect("valid uuid");

        assert_eq!(
            session_id_to_alias(uuid),
            "sid-agoq-pgas-3b3m-hkas-nyzd-mn5k-le"
        );
    }
}
