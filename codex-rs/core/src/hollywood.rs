use codex_protocol::ThreadId;
use serde::Deserialize;
use serde::Serialize;
use std::env;
use uuid::Uuid;

const DEFAULT_HOLLYWOOD_URL: &str = "http://127.0.0.1:8765";
const DEFAULT_HOLLYWOOD_ROOM: &str = "main";
const BASE32_ALPHABET: &[u8; 32] = b"abcdefghijklmnopqrstuvwxyz234567";

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub(crate) struct HollywoodSessionConfig {
    pub(crate) url: String,
    pub(crate) room: String,
    pub(crate) attention_mode: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub(crate) struct HollywoodEnvironmentContext {
    pub(crate) attached: bool,
    pub(crate) url: String,
    pub(crate) room: String,
    pub(crate) attention_mode: String,
    pub(crate) identities: Vec<String>,
    pub(crate) tools: Vec<String>,
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

        Some(Self {
            url: env::var("HOLLYWOOD_URL").unwrap_or_else(|_| DEFAULT_HOLLYWOOD_URL.to_string()),
            room: env::var("HOLLYWOOD_ROOM").unwrap_or_else(|_| DEFAULT_HOLLYWOOD_ROOM.to_string()),
            attention_mode: env::var("HOLLYWOOD_ATTENTION_MODE")
                .unwrap_or_else(|_| "focused".to_string())
                .to_ascii_lowercase(),
        })
    }
}

pub(crate) fn environment_context(thread_id: ThreadId) -> Option<HollywoodEnvironmentContext> {
    let config = HollywoodSessionConfig::from_env()?;
    Some(HollywoodEnvironmentContext {
        attached: true,
        url: config.url,
        room: config.room,
        attention_mode: config.attention_mode,
        identities: identities(thread_id),
        tools: vec![
            "hollywood_status".to_string(),
            "hollywood_read".to_string(),
            "hollywood_send".to_string(),
        ],
    })
}

pub(crate) fn identities(thread_id: ThreadId) -> Vec<String> {
    let raw = thread_id.to_string();
    let mut values = vec![normalize_identity(&raw)];
    if let Ok(uuid) = Uuid::parse_str(&raw) {
        values.push(session_id_to_alias(uuid));
    }
    values
}

fn normalize_identity(value: &str) -> String {
    value.trim().trim_start_matches('@').to_ascii_lowercase()
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
