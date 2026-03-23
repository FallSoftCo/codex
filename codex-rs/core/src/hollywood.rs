use codex_protocol::ThreadId;
use codex_protocol::protocol::HollywoodSessionMeta;
use serde::Deserialize;
use serde::Serialize;
use std::collections::HashSet;
use std::env;
use uuid::Uuid;

const DEFAULT_HOLLYWOOD_URL: &str = "http://127.0.0.1:8765";
const DEFAULT_HOLLYWOOD_ROOM: &str = "main";
const BASE32_ALPHABET: &[u8; 32] = b"abcdefghijklmnopqrstuvwxyz234567";

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub(crate) struct HollywoodSessionConfig {
    pub(crate) url: String,
    pub(crate) room: String,
    pub(crate) observed_rooms: Vec<String>,
    pub(crate) wake_rooms: Vec<String>,
    pub(crate) attention_mode: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub(crate) struct HollywoodEnvironmentContext {
    pub(crate) attached: bool,
    pub(crate) url: String,
    pub(crate) room: String,
    pub(crate) observed_rooms: Vec<String>,
    pub(crate) wake_rooms: Vec<String>,
    pub(crate) attention_mode: String,
    pub(crate) identities: Vec<String>,
    pub(crate) tools: Vec<String>,
    pub(crate) startup_protocol: Vec<String>,
    pub(crate) broadcast_guidance: Vec<String>,
}

impl HollywoodSessionConfig {
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

        let room = env::var("HOLLYWOOD_ROOM").unwrap_or_else(|_| DEFAULT_HOLLYWOOD_ROOM.to_string());
        let observed_rooms = parse_room_list(env::var("HOLLYWOOD_OBSERVED_ROOMS").ok());
        let wake_rooms = parse_room_list(env::var("HOLLYWOOD_WAKE_ROOMS").ok());
        Some(Self {
            url: env::var("HOLLYWOOD_URL").unwrap_or_else(|_| DEFAULT_HOLLYWOOD_URL.to_string()),
            room,
            observed_rooms,
            wake_rooms,
            attention_mode: env::var("HOLLYWOOD_ATTENTION_MODE")
                .unwrap_or_else(|_| "focused".to_string())
                .to_ascii_lowercase(),
        })
    }
}

impl From<HollywoodSessionConfig> for HollywoodSessionMeta {
    fn from(value: HollywoodSessionConfig) -> Self {
        Self {
            url: value.url,
            room: value.room,
            observed_rooms: value.observed_rooms,
            wake_rooms: value.wake_rooms,
            attention_mode: value.attention_mode,
            include_at_all: true,
            include_at_room: true,
        }
    }
}

pub(crate) fn environment_context(thread_id: ThreadId) -> Option<HollywoodEnvironmentContext> {
    let config = HollywoodSessionConfig::from_env()?;
    let wake_rooms = effective_wake_rooms(&config);
    Some(HollywoodEnvironmentContext {
        attached: true,
        url: config.url,
        room: config.room,
        observed_rooms: config.observed_rooms,
        wake_rooms,
        attention_mode: config.attention_mode,
        identities: identities(thread_id),
        tools: vec![
            "hollywood_status".to_string(),
            "hollywood_read".to_string(),
            "hollywood_send".to_string(),
            "hollywood_team_up".to_string(),
            "hollywood_team_status".to_string(),
            "hollywood_team_member_update".to_string(),
        ],
        startup_protocol: vec![
            "announce_presence".to_string(),
            "read_recent_room_context".to_string(),
            "ask_user_for_tasking_when_unassigned".to_string(),
            "relay_assigned_scope_to_room".to_string(),
        ],
        broadcast_guidance: vec![
            "Use sparse explicit room-wide broadcasts for presence, scope changes, blockers, handoffs, major completion updates, and discovery-oriented coordination. Explicit broadcasts can wake idle attached agents.".to_string(),
            "Use @mentions for direct requests, replies, and anything that should reliably wake another agent.".to_string(),
        ],
    })
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

fn effective_wake_rooms(config: &HollywoodSessionConfig) -> Vec<String> {
    if config.wake_rooms.is_empty() {
        vec![config.room.clone()]
    } else {
        config.wake_rooms.clone()
    }
}

pub(crate) fn identities(thread_id: ThreadId) -> Vec<String> {
    let raw = thread_id.to_string();
    let mut values = vec![normalize_identity(&raw)];
    if let Ok(uuid) = Uuid::parse_str(&raw) {
        values.push(session_id_to_alias(uuid));
    }
    values
}

pub fn normalize_identity(value: &str) -> String {
    value.trim().trim_start_matches('@').to_ascii_lowercase()
}

pub fn parse_agent_mentions(body: &str) -> Vec<String> {
    let mut mentions = Vec::new();
    let mut seen = HashSet::new();
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
        if idx <= start {
            continue;
        }
        if let Some(identity) = canonicalize_agent_identity(&body[start..idx])
            && seen.insert(identity.clone())
        {
            mentions.push(identity);
        }
    }
    mentions
}

pub fn canonicalize_agent_identity(value: &str) -> Option<String> {
    let normalized = normalize_identity(value);
    if normalized.is_empty() {
        return None;
    }
    if let Ok(uuid) = Uuid::parse_str(&normalized) {
        return Some(uuid.to_string());
    }
    alias_to_session_id(&normalized)
}

fn alias_to_session_id(alias: &str) -> Option<String> {
    let normalized = normalize_identity(alias);
    let payload = normalized.strip_prefix("sid-")?.replace('-', "");
    if payload.is_empty() {
        return None;
    }

    let mut buffer: u32 = 0;
    let mut bits: u8 = 0;
    let mut bytes = Vec::new();

    for byte in payload.bytes() {
        let value = match BASE32_ALPHABET.iter().position(|candidate| *candidate == byte) {
            Some(index) => index as u8,
            None => return None,
        };
        buffer = (buffer << 5) | u32::from(value);
        bits += 5;
        while bits >= 8 {
            bits -= 8;
            bytes.push(((buffer >> bits) & 0xff) as u8);
        }
    }

    if bytes.len() != 16 {
        return None;
    }
    Some(Uuid::from_slice(&bytes).ok()?.to_string())
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn canonicalize_agent_identity_accepts_uuid_and_alias() {
        let session_id = "019d113f-49ff-7b12-8a8f-bcc14ebcf5b1";
        let alias = "sid-agor-cp2j-755r-fcup-xtau-5phv-we";

        assert_eq!(
            canonicalize_agent_identity(session_id),
            Some(session_id.to_string())
        );
        assert_eq!(
            canonicalize_agent_identity(alias),
            Some(session_id.to_string())
        );
    }

    #[test]
    fn parse_agent_mentions_keeps_only_real_agent_identities() {
        let mentions = parse_agent_mentions(
            "@all ping @room @sid-agor-cp2j-755r-fcup-xtau-5phv-we and @not-an-agent",
        );

        assert_eq!(mentions, vec!["019d113f-49ff-7b12-8a8f-bcc14ebcf5b1".to_string()]);
    }
}
