use codex_git_utils::get_git_repo_root;
use codex_protocol::ThreadId;
use codex_protocol::protocol::HollywoodSessionMeta;
#[cfg(test)]
use serde::Deserialize;
use serde::Serialize;
use std::collections::HashSet;
use std::env;
use std::path::Path;
use std::sync::LazyLock;
use std::sync::RwLock;
use uuid::Uuid;

const DEFAULT_HOLLYWOOD_URL: &str = "http://127.0.0.1:8765";
const DEFAULT_HOLLYWOOD_ROOM: &str = "main";
#[cfg(test)]
const COLLABORATION_FIRST_DEBUG_ENV_VAR: &str = "LOSANGELEX_COLLABORATION_FIRST_DEBUG";
#[cfg(test)]
const COLLABORATIVE_EDITING_GUIDANCE: &str = "Treat same-file work as a collaboration opportunity, not a reason to abandon parallelism. If another agent owns or needs an overlapping file, coordinate a collaborative edit plan in Hollywood before editing: name the file, slice/function/section, intended hunk, edit order or handoff, integrator, and report-back point. Reread the file and current diff immediately before patching, keep hunks narrow, and after applying broadcast the exact slice changed plus any merge risk. If a durable path claim blocks you, ask the owner to apply your proposed patch, hand off or release the claim, or agree on a serial handoff instead of silently doing unrelated work.";
const BASE32_ALPHABET: &[u8; 32] = b"abcdefghijklmnopqrstuvwxyz234567";

static HOLLYWOOD_SESSION_CONFIG_OVERRIDE: LazyLock<RwLock<Option<Option<HollywoodSessionConfig>>>> =
    LazyLock::new(|| RwLock::new(None));

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub(crate) struct HollywoodSessionConfig {
    pub(crate) url: String,
    pub(crate) room: String,
    pub(crate) observed_rooms: Vec<String>,
    pub(crate) wake_rooms: Vec<String>,
    pub(crate) attention_mode: String,
}

#[cfg(test)]
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub(crate) struct HollywoodSemanticContext {
    pub(crate) attached: bool,
    pub(crate) url: String,
    pub(crate) room: String,
    pub(crate) observed_rooms: Vec<String>,
    pub(crate) wake_rooms: Vec<String>,
    pub(crate) attention_mode: String,
    pub(crate) agent_name: Option<String>,
    pub(crate) coordination_identity: Option<String>,
    pub(crate) identities: Vec<String>,
}

#[cfg(test)]
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub(crate) struct HollywoodRuntimeContext {
    pub(crate) tools: Vec<String>,
    pub(crate) startup_protocol: Vec<String>,
    pub(crate) broadcast_guidance: Vec<String>,
}

#[cfg(test)]
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub(crate) struct HollywoodEnvironmentContext {
    pub(crate) semantic: HollywoodSemanticContext,
    pub(crate) runtime: HollywoodRuntimeContext,
}

impl HollywoodSessionConfig {
    pub(crate) fn from_env() -> Option<Self> {
        let override_config = HOLLYWOOD_SESSION_CONFIG_OVERRIDE
            .read()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone();
        if let Some(override_config) = override_config {
            return override_config;
        }

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

pub(crate) fn disable_hollywood_from_env_for_tests() {
    *HOLLYWOOD_SESSION_CONFIG_OVERRIDE
        .write()
        .unwrap_or_else(std::sync::PoisonError::into_inner) = Some(None);
}

pub fn default_hollywood_room_for_cwd(cwd: &Path) -> String {
    get_git_repo_root(cwd)
        .and_then(|repo_root| {
            repo_root
                .file_name()
                .map(|value| value.to_string_lossy().into_owned())
        })
        .map(|repo_name| format!("repo/{}", hollywood_room_slug(&repo_name)))
        .filter(|room| room != "repo/")
        .unwrap_or_else(|| DEFAULT_HOLLYWOOD_ROOM.to_string())
}

pub fn default_hollywood_observed_rooms(
    primary_room: &str,
    observed_rooms: Vec<String>,
) -> Vec<String> {
    let mut rooms = Vec::new();
    let mut seen = HashSet::new();

    for room in observed_rooms {
        if !room.is_empty() && seen.insert(room.clone()) {
            rooms.push(room);
        }
    }

    if primary_room != DEFAULT_HOLLYWOOD_ROOM && seen.insert(DEFAULT_HOLLYWOOD_ROOM.to_string()) {
        rooms.push(DEFAULT_HOLLYWOOD_ROOM.to_string());
    }

    rooms
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

#[cfg(test)]
fn semantic_context(
    config: &HollywoodSessionConfig,
    thread_id: ThreadId,
    thread_name: Option<&str>,
) -> HollywoodSemanticContext {
    let agent_name = crate::util::normalize_thread_name(thread_name.unwrap_or_default());
    let coordination_identity = agent_name
        .as_deref()
        .and_then(coordination_identity_from_thread_name);
    HollywoodSemanticContext {
        attached: true,
        url: config.url.clone(),
        room: config.room.clone(),
        observed_rooms: config.observed_rooms.clone(),
        wake_rooms: effective_wake_rooms(config),
        attention_mode: config.attention_mode.clone(),
        agent_name,
        coordination_identity,
        identities: identities(thread_id, thread_name),
    }
}

#[cfg(test)]
fn durable_coordination_guidance(state_db_available: bool) -> String {
    if state_db_available {
        "When room discussion becomes a real assignment, acceptance, handoff, dependency, or completion, record that durable commitment with `coordination_act` so Losangelex can survive idle gaps, restart, and rolling deploy.".to_string()
    } else {
        "This session does not currently expose durable coordination tools, so do not call `coordination_act`; keep Hollywood ownership updates current and treat them as best-effort until durable coordination returns.".to_string()
    }
}

#[cfg(test)]
fn runtime_context(
    config: &HollywoodSessionConfig,
    state_db_available: bool,
) -> HollywoodRuntimeContext {
    let mut startup_protocol = Vec::new();
    if config.attention_mode != "focused" {
        startup_protocol.push("announce_presence".to_string());
    }
    startup_protocol.extend([
        "read_recent_room_context".to_string(),
        "ask_user_for_tasking_when_unassigned".to_string(),
        "relay_assigned_scope_to_room".to_string(),
        "check_existing_scope_claims_before_editing".to_string(),
        "claim_exact_paths_or_modules_before_editing".to_string(),
        "avoid_blind_overlapping_edits".to_string(),
        "same_file_collaboration_allowed_with_explicit_plan".to_string(),
        "resolve_overlapping_edits_with_collaborative_edit_plan".to_string(),
        "use_hollywood_first_for_peer_coordination".to_string(),
        "start_app_server_hosted_peers_with_losangelex_team_launch_for_user_requested_team"
            .to_string(),
        "do_not_substitute_codex_subagents_for_losangelex_team".to_string(),
        "reserve_subagents_for_parallelizing_owned_work".to_string(),
    ]);
    let collaboration_first_debug = env_flag_enabled(COLLABORATION_FIRST_DEBUG_ENV_VAR);
    if collaboration_first_debug {
        startup_protocol.extend([
            "evaluate_peer_collaboration_before_substantive_work".to_string(),
            "inspect_attached_peers_with_hollywood_read_before_solo_decision".to_string(),
            "collaborate_when_peer_help_reduces_effort_risk_or_uncertainty".to_string(),
            "self_owned_coordination_is_not_peer_collaboration".to_string(),
            "solo_execution_is_for_small_local_or_unsplittable_work".to_string(),
        ]);
    }
    let mut broadcast_guidance = vec![
        "Use sparse explicit room-wide broadcasts for presence, scope changes, blockers, handoffs, major completion updates, and discovery-oriented coordination. Explicit broadcasts can wake idle attached agents.".to_string(),
        "Use @mentions for direct requests, replies, and anything that should reliably wake another agent.".to_string(),
        "When you claim scope, make it concrete: name exact files, modules, directories, or narrow globs, and update or relinquish that claim when it changes.".to_string(),
        COLLABORATIVE_EDITING_GUIDANCE.to_string(),
        "When the user asks you to work with teammates, peers, or other existing agents, use Hollywood coordination with attached Losangelex agents first.".to_string(),
        "When the user asks you to form or start a Losangelex team and suitable peers are not already attached, call `losangelex_team_launch` to start app-server-hosted Losangelex peer sessions; do not substitute Codex subagents for that team request.".to_string(),
        "Reserve Codex subagents only for parallelizing your own currently owned work into bounded sidecar tasks.".to_string(),
        durable_coordination_guidance(state_db_available),
    ];
    if collaboration_first_debug {
        broadcast_guidance.extend([
            "Debug collaboration-first policy: before substantive work, decide whether an existing or new Losangelex peer would make the directive easier, faster, safer, or better verified.".to_string(),
            "Debug collaboration-first policy: collaboration is peer-to-peer and role-flexible; any session may ask for help, split work, verify another session, hand off context, or integrate, without treating the current respondent as a permanent leader.".to_string(),
            "Debug collaboration-first policy: for work that is not clearly tiny and local, call `hollywood_read` before claiming or editing; use its attached `peers` roster plus recent messages to decide whether to request peer help.".to_string(),
            "Debug collaboration-first policy: a self-owned `coordination_act` open/accept/done records ownership but is not peer collaboration by itself; for cross-surface, risky, uncertain, or verification-heavy work, ask a peer for a narrow lane with `hollywood_send` @mention/direct request or assign a narrow durable task to a specific peer before claiming all scope yourself.".to_string(),
            "Debug collaboration-first policy: if peers are attached but no one responds after a brief wait, continue solo on unblocked scope and leave a concise room update explaining that fallback.".to_string(),
            "Debug collaboration-first policy: prefer solo execution only for small, clearly local, or unsplittable tasks; for naturally parallel, cross-surface, risky, uncertain, or verification-heavy work, coordinate through Hollywood or start app-server-hosted Losangelex peers.".to_string(),
        ]);
    }
    HollywoodRuntimeContext {
        tools: vec![
            "hollywood_status".to_string(),
            "hollywood_read".to_string(),
            "losangelex_team_launch".to_string(),
            "hollywood_send".to_string(),
            "hollywood_team_up".to_string(),
            "hollywood_team_status".to_string(),
            "hollywood_team_member_update".to_string(),
        ],
        startup_protocol,
        broadcast_guidance,
    }
}

#[cfg(test)]
fn env_flag_enabled(name: &str) -> bool {
    env::var(name)
        .as_deref()
        .map(|value| matches!(value, "1" | "true" | "TRUE" | "yes" | "on"))
        .unwrap_or(false)
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

fn hollywood_room_slug(value: &str) -> String {
    let mut slug = String::new();
    let mut last_was_separator = false;

    for ch in value.chars() {
        let lower = ch.to_ascii_lowercase();
        if lower.is_ascii_alphanumeric() {
            slug.push(lower);
            last_was_separator = false;
        } else if !last_was_separator && !slug.is_empty() {
            slug.push('-');
            last_was_separator = true;
        }
    }

    slug.trim_matches('-').to_string()
}

#[cfg(test)]
fn effective_wake_rooms(config: &HollywoodSessionConfig) -> Vec<String> {
    if config.wake_rooms.is_empty() {
        vec![config.room.clone()]
    } else {
        config.wake_rooms.clone()
    }
}

pub(crate) fn identities(thread_id: ThreadId, thread_name: Option<&str>) -> Vec<String> {
    let raw = thread_id.to_string();
    let mut values = vec![normalize_identity(&raw)];
    let mut seen = HashSet::from([values[0].clone()]);
    if let Ok(uuid) = Uuid::parse_str(&raw) {
        let alias = session_id_to_alias(uuid);
        if seen.insert(alias.clone()) {
            values.push(alias);
        }
    }
    if let Some(named_identity) = thread_name.and_then(coordination_identity_from_thread_name)
        && seen.insert(named_identity.clone())
    {
        values.push(named_identity);
    }
    values
}

pub fn normalize_identity(value: &str) -> String {
    value.trim().trim_start_matches('@').to_ascii_lowercase()
}

pub fn coordination_identity_from_thread_name(name: &str) -> Option<String> {
    let normalized = hollywood_room_slug(name);
    if normalized.is_empty() || matches!(normalized.as_str(), "all" | "room") {
        None
    } else {
        Some(normalized)
    }
}

pub fn live_identity_matches_target(value: &str, target: &str) -> bool {
    let normalized_value = normalize_identity(value);
    let normalized_target = normalize_identity(target);
    if normalized_value == normalized_target {
        return true;
    }
    generated_runtime_identity_base(&normalized_value).is_some_and(|runtime_base| {
        runtime_base == normalized_target
            || runtime_base.ends_with(&format!("-{normalized_target}"))
    })
}

fn generated_runtime_identity_base(value: &str) -> Option<&str> {
    let (runtime_base, suffix) = value.rsplit_once('-')?;
    is_generated_runtime_identity_suffix(suffix).then_some(runtime_base)
}

fn is_generated_runtime_identity_suffix(value: &str) -> bool {
    let len = value.len();
    (4..=16).contains(&len) && value.chars().all(|ch| ch.is_ascii_hexdigit())
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
        if let Some(identity) = canonicalize_hollywood_identity(&body[start..idx])
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

pub fn canonicalize_hollywood_identity(value: &str) -> Option<String> {
    let normalized = normalize_identity(value);
    if normalized.is_empty() || matches!(normalized.as_str(), "all" | "room") {
        return None;
    }
    if let Some(session_id) = canonicalize_agent_identity(&normalized) {
        Some(session_id)
    } else {
        Some(normalized)
    }
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
        let value = match BASE32_ALPHABET
            .iter()
            .position(|candidate| *candidate == byte)
        {
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
    use std::fs;

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
    fn coordination_identity_from_thread_name_slugifies_and_rejects_reserved_values() {
        assert_eq!(
            coordination_identity_from_thread_name("Scout Agent"),
            Some("scout-agent".to_string())
        );
        assert_eq!(coordination_identity_from_thread_name(" @room "), None);
        assert_eq!(coordination_identity_from_thread_name("room"), None);
        assert_eq!(coordination_identity_from_thread_name("   "), None);
    }

    #[test]
    fn parse_agent_mentions_keeps_named_and_session_identities() {
        let mentions = parse_agent_mentions(
            "@all ping @room @sid-agor-cp2j-755r-fcup-xtau-5phv-we and @scout-agent",
        );

        assert_eq!(
            mentions,
            vec![
                "019d113f-49ff-7b12-8a8f-bcc14ebcf5b1".to_string(),
                "scout-agent".to_string(),
            ]
        );
    }

    #[test]
    fn live_identity_matches_target_accepts_exact_and_generated_runtime_suffixes() {
        assert!(live_identity_matches_target("james", "james"));
        assert!(live_identity_matches_target("james-7c45ba", "james"));
        assert!(live_identity_matches_target(
            "marble-db-agent1-7c45ba",
            "agent1"
        ));
        assert!(live_identity_matches_target(
            "silo-agent-002-5b254e",
            "agent-002"
        ));
        assert!(!live_identity_matches_target("james-proof", "james"));
        assert!(!live_identity_matches_target("jameson-7c45ba", "james"));
        assert!(!live_identity_matches_target(
            "marble-db-agent10-7c45ba",
            "agent1"
        ));
    }

    #[test]
    fn default_hollywood_room_for_cwd_uses_repo_slug() {
        let temp_dir = tempfile::tempdir().expect("tempdir");
        let repo_root = temp_dir.path().join("Los Angeles Lex");
        fs::create_dir_all(&repo_root).expect("create repo root");
        fs::write(repo_root.join(".git"), "gitdir: here\n").expect("create git root");
        fs::create_dir_all(repo_root.join("nested/worktree")).expect("create nested path");

        assert_eq!(
            default_hollywood_room_for_cwd(repo_root.join("nested/worktree").as_path()),
            "repo/los-angeles-lex"
        );
    }

    #[test]
    fn default_hollywood_observed_rooms_adds_main_for_repo_rooms() {
        assert_eq!(
            default_hollywood_observed_rooms("repo/losangelex", vec!["repo/other".to_string()]),
            vec!["repo/other".to_string(), "main".to_string()]
        );
    }

    #[test]
    fn default_hollywood_observed_rooms_keeps_main_deduplicated() {
        assert_eq!(
            default_hollywood_observed_rooms("main", vec!["main".to_string()]),
            vec!["main".to_string()]
        );
    }

    #[test]
    fn environment_context_splits_semantic_and_runtime_lanes() {
        let config = HollywoodSessionConfig {
            url: "http://127.0.0.1:8765".to_string(),
            room: "repo/losangelex".to_string(),
            observed_rooms: vec!["main".to_string()],
            wake_rooms: vec![],
            attention_mode: "focused".to_string(),
        };
        let thread_id = ThreadId::default();

        let context = HollywoodEnvironmentContext {
            semantic: semantic_context(&config, thread_id, Some("Scout Agent")),
            runtime: runtime_context(&config, /*state_db_available*/ true),
        };

        assert_eq!(context.semantic.room, "repo/losangelex");
        assert_eq!(context.semantic.agent_name.as_deref(), Some("Scout Agent"));
        assert_eq!(
            context.semantic.coordination_identity.as_deref(),
            Some("scout-agent")
        );
        assert_eq!(
            context.semantic.wake_rooms,
            vec!["repo/losangelex".to_string()]
        );
        assert!(
            context
                .semantic
                .identities
                .contains(&"scout-agent".to_string())
        );
        assert!(
            context
                .runtime
                .tools
                .contains(&"hollywood_send".to_string())
        );
        assert!(
            !context
                .runtime
                .startup_protocol
                .contains(&"announce_presence".to_string())
        );
        assert!(
            context
                .runtime
                .startup_protocol
                .contains(&"use_hollywood_first_for_peer_coordination".to_string())
        );
        assert!(
            context
                .runtime
                .startup_protocol
                .contains(
                    &"start_app_server_hosted_peers_with_losangelex_team_launch_for_user_requested_team"
                        .to_string()
                )
        );
        assert!(
            context
                .runtime
                .startup_protocol
                .contains(&"do_not_substitute_codex_subagents_for_losangelex_team".to_string())
        );
        assert!(
            context
                .runtime
                .startup_protocol
                .contains(&"reserve_subagents_for_parallelizing_owned_work".to_string())
        );
        assert!(
            context
                .runtime
                .startup_protocol
                .contains(&"avoid_blind_overlapping_edits".to_string())
        );
        assert!(
            context
                .runtime
                .startup_protocol
                .contains(&"same_file_collaboration_allowed_with_explicit_plan".to_string())
        );
        assert!(
            context
                .runtime
                .startup_protocol
                .contains(&"resolve_overlapping_edits_with_collaborative_edit_plan".to_string())
        );
        assert!(
            context
                .runtime
                .broadcast_guidance
                .iter()
                .any(|guidance| guidance.contains("same-file work as a collaboration opportunity"))
        );
    }

    #[test]
    fn ambient_environment_context_keeps_presence_startup_protocol() {
        let config = HollywoodSessionConfig {
            url: "http://127.0.0.1:8765".to_string(),
            room: "repo/losangelex".to_string(),
            observed_rooms: vec!["main".to_string()],
            wake_rooms: vec![],
            attention_mode: "ambient".to_string(),
        };

        let context = runtime_context(&config, /*state_db_available*/ true);

        assert!(
            context
                .startup_protocol
                .contains(&"announce_presence".to_string())
        );
    }
}
