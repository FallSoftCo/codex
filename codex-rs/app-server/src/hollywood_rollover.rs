#![allow(dead_code)]

use crate::hollywood::HollywoodConfig;
use crate::hollywood::hollywood_identities;
use crate::hollywood::hollywood_session_status_from_thread_status;
use crate::thread_state::ThreadStateManager;
use crate::thread_status::ThreadWatchManager;
use chrono::DateTime;
use chrono::Duration;
use chrono::Utc;
use codex_app_server_protocol::HollywoodSessionStatus;
use codex_core::read_session_meta_line;
use codex_protocol::ThreadId;
use codex_rollout::state_db::StateDbHandle;
use reqwest::Client;
use serde::Deserialize;
use std::collections::HashSet;
use std::path::Path;
use std::path::PathBuf;

const HOLLYWOOD_REGISTRY_STALE_AFTER: Duration = Duration::seconds(90);

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub(crate) struct RollingDeployAssessment {
    pub(crate) startup_notice: Option<String>,
    pub(crate) peer_notices: Vec<RollingDeployPeerNotice>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct RollingDeployPeerNotice {
    pub(crate) thread_id: ThreadId,
    pub(crate) body: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct RollingDeploySession {
    thread_id: ThreadId,
    cli_version: String,
    room: String,
    cwd: PathBuf,
    identities: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct RollingDeployPeer {
    thread_id: ThreadId,
    cli_version: String,
    room: String,
    cwd: PathBuf,
    status: HollywoodSessionStatus,
    identities: Vec<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
struct ParsedCliVersion {
    major: u64,
    minor: u64,
    patch: u64,
}

#[derive(Debug, Deserialize)]
struct HollywoodRegistryListResponse {
    entries: Vec<HollywoodRegistryEntry>,
}

#[derive(Debug, Deserialize)]
struct HollywoodRegistryEntry {
    session_id: String,
    room: String,
    attached: bool,
    cwd: Option<String>,
    rollout_path: Option<String>,
    status: String,
    identities: Vec<String>,
    updated_at: Option<String>,
    last_heartbeat_at: Option<String>,
}

#[allow(clippy::too_many_arguments)]
pub(crate) async fn assess_rolling_deploy(
    state_db: &StateDbHandle,
    thread_state_manager: &ThreadStateManager,
    thread_watch_manager: &ThreadWatchManager,
    current_thread_id: ThreadId,
    current_cwd: &Path,
    current_thread_name: Option<&str>,
    config: &HollywoodConfig,
    current_cli_version: &str,
) -> RollingDeployAssessment {
    let mut peers = collect_local_peers(
        state_db,
        thread_state_manager,
        thread_watch_manager,
        current_thread_id,
        current_cwd,
        config,
    )
    .await;
    let mut seen_peer_ids = peers
        .iter()
        .map(|peer| peer.thread_id)
        .collect::<HashSet<_>>();
    match collect_registry_peers(config, current_thread_id, current_cwd).await {
        Ok(registry_peers) => {
            for peer in registry_peers {
                if seen_peer_ids.insert(peer.thread_id) {
                    peers.push(peer);
                }
            }
        }
        Err(err) => {
            tracing::debug!(
                current_thread_id = %current_thread_id,
                room = config.room,
                "failed to load Hollywood registry peers for rolling deploy assessment: {err}"
            );
        }
    }

    build_assessment(
        RollingDeploySession {
            thread_id: current_thread_id,
            cli_version: current_cli_version.to_string(),
            room: config.room.clone(),
            cwd: current_cwd.to_path_buf(),
            identities: hollywood_identities(current_thread_id, current_thread_name),
        },
        peers,
    )
}

async fn collect_local_peers(
    state_db: &StateDbHandle,
    thread_state_manager: &ThreadStateManager,
    thread_watch_manager: &ThreadWatchManager,
    current_thread_id: ThreadId,
    current_cwd: &Path,
    config: &HollywoodConfig,
) -> Vec<RollingDeployPeer> {
    let peer_thread_ids = thread_state_manager
        .thread_ids()
        .await
        .into_iter()
        .filter(|thread_id| *thread_id != current_thread_id)
        .collect::<Vec<_>>();
    if peer_thread_ids.is_empty() {
        return Vec::new();
    }

    let loaded_statuses = thread_watch_manager
        .loaded_statuses_for_threads(
            peer_thread_ids
                .iter()
                .map(ToString::to_string)
                .collect::<Vec<_>>(),
        )
        .await;

    let mut peers = Vec::new();
    for peer_thread_id in peer_thread_ids {
        let Ok(Some(metadata)) = state_db.get_thread(peer_thread_id).await else {
            continue;
        };
        let Some(hollywood) = metadata.hollywood.as_ref() else {
            continue;
        };
        if hollywood.room != config.room || metadata.cwd.as_path() != current_cwd {
            continue;
        }

        let status = loaded_statuses
            .get(&peer_thread_id.to_string())
            .map(hollywood_session_status_from_thread_status)
            .unwrap_or(HollywoodSessionStatus::Idle);
        peers.push(RollingDeployPeer {
            thread_id: peer_thread_id,
            cli_version: metadata.cli_version,
            room: hollywood.room.clone(),
            cwd: metadata.cwd,
            status,
            identities: hollywood_identities(
                peer_thread_id,
                (!metadata.title.trim().is_empty()).then_some(metadata.title.as_str()),
            ),
        });
    }

    peers
}

async fn collect_registry_peers(
    config: &HollywoodConfig,
    current_thread_id: ThreadId,
    current_cwd: &Path,
) -> Result<Vec<RollingDeployPeer>, String> {
    let url = format!("{}/hollywood/v1/registry", config.url.trim_end_matches('/'));
    let response = Client::new()
        .get(&url)
        .query(&[("room", config.room.as_str()), ("limit", "1000")])
        .send()
        .await
        .map_err(|err| format!("Hollywood registry read failed: {err}"))?
        .error_for_status()
        .map_err(|err| format!("Hollywood registry read failed: {err}"))?
        .json::<HollywoodRegistryListResponse>()
        .await
        .map_err(|err| format!("Hollywood registry response parse failed: {err}"))?;

    let mut peers = Vec::new();
    for entry in response.entries {
        let Some(peer) = peer_from_registry_entry(entry, current_thread_id, current_cwd).await
        else {
            continue;
        };
        peers.push(peer);
    }
    Ok(peers)
}

async fn peer_from_registry_entry(
    entry: HollywoodRegistryEntry,
    current_thread_id: ThreadId,
    current_cwd: &Path,
) -> Option<RollingDeployPeer> {
    if !entry.attached || entry.room.is_empty() {
        return None;
    }
    if !registry_entry_is_fresh(&entry, &Utc::now()) {
        return None;
    }

    let thread_id = ThreadId::from_string(entry.session_id.as_str()).ok()?;
    if thread_id == current_thread_id {
        return None;
    }

    let cwd = PathBuf::from(entry.cwd?);
    if cwd != current_cwd {
        return None;
    }

    let cli_version = read_registry_cli_version(entry.rollout_path.as_deref()).await?;
    Some(RollingDeployPeer {
        thread_id,
        cli_version,
        room: entry.room,
        cwd,
        status: hollywood_status_from_registry(entry.status.as_str())?,
        identities: entry.identities,
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

async fn read_registry_cli_version(rollout_path: Option<&str>) -> Option<String> {
    let rollout_path = Path::new(rollout_path?);
    let session_meta = read_session_meta_line(rollout_path).await.ok()?;
    (!session_meta.meta.cli_version.is_empty()).then_some(session_meta.meta.cli_version)
}

fn hollywood_status_from_registry(status: &str) -> Option<HollywoodSessionStatus> {
    match status {
        "idle" => Some(HollywoodSessionStatus::Idle),
        "active" => Some(HollywoodSessionStatus::Active),
        "waiting" => Some(HollywoodSessionStatus::Waiting),
        "blocked" => Some(HollywoodSessionStatus::Blocked),
        "persisted" => Some(HollywoodSessionStatus::Persisted),
        _ => None,
    }
}

fn build_assessment(
    current: RollingDeploySession,
    peers: Vec<RollingDeployPeer>,
) -> RollingDeployAssessment {
    let Some(current_version) = parse_cli_version(current.cli_version.as_str()) else {
        return RollingDeployAssessment::default();
    };

    let mut older_peers = Vec::new();
    let mut newer_peers = Vec::new();
    for peer in peers {
        if peer.room != current.room || peer.cwd != current.cwd {
            continue;
        }
        let Some(peer_version) = parse_cli_version(peer.cli_version.as_str()) else {
            continue;
        };
        if peer_version < current_version {
            older_peers.push(peer);
        } else if peer_version > current_version {
            newer_peers.push(peer);
        }
    }

    older_peers.sort_by(|left, right| {
        compare_cli_versions(left.cli_version.as_str(), right.cli_version.as_str())
            .then_with(|| left.thread_id.to_string().cmp(&right.thread_id.to_string()))
    });
    newer_peers.sort_by(|left, right| {
        compare_cli_versions(right.cli_version.as_str(), left.cli_version.as_str())
            .then_with(|| left.thread_id.to_string().cmp(&right.thread_id.to_string()))
    });

    if older_peers.is_empty() && newer_peers.is_empty() {
        return RollingDeployAssessment::default();
    }

    let mut sections = Vec::new();
    if !older_peers.is_empty() {
        let mut section = format!(
            "Rolling deploy notice: you are running Losangelex v{} and older attached peer sessions exist in the same Hollywood room and cwd. Prefer a takeover instead of starting parallel work.\nOlder peer sessions:",
            current.cli_version
        );
        for peer in &older_peers {
            section.push('\n');
            section.push_str(format!("- {}", describe_peer(peer)).as_str());
        }
        section.push_str(
            "\nAsk those older peers for a concise handoff covering exact owned files, current status, and blockers. After you take over, send a room update naming which session(s) you superseded.",
        );
        sections.push(section);
    }
    if !newer_peers.is_empty() {
        let mut section = format!(
            "Rolling deploy notice: newer attached peer sessions already exist in the same Hollywood room and cwd than your Losangelex v{} session. Unless the user explicitly keeps you active, avoid claiming new scope and be ready to hand work off.\nNewer peer sessions:",
            current.cli_version
        );
        for peer in &newer_peers {
            section.push('\n');
            section.push_str(format!("- {}", describe_peer(peer)).as_str());
        }
        section.push_str(
            "\nIf you still own in-flight work, send the newer peer session(s) a concise handoff with exact owned files, current status, and blockers before yielding.",
        );
        sections.push(section);
    }

    let current_identities = current.identities.join(", ");
    let peer_notices = older_peers
        .into_iter()
        .map(|peer| RollingDeployPeerNotice {
            thread_id: peer.thread_id,
            body: format!(
                "Rolling deploy notice: newer Losangelex session [{}] on v{} attached to the same Hollywood room `{}` and cwd `{}`. If you are idle or can safely yield, send it a concise handoff covering exact owned files, current status, and blockers, then avoid claiming new scope. If you still need to stay active, explicitly state why and what scope remains yours.",
                current_identities,
                current.cli_version,
                current.room,
                current.cwd.display(),
            ),
        })
        .collect();

    RollingDeployAssessment {
        startup_notice: Some(sections.join("\n\n")),
        peer_notices,
    }
}

fn describe_peer(peer: &RollingDeployPeer) -> String {
    format!(
        "{} | v{} | {}",
        display_identity(peer),
        peer.cli_version,
        display_status(peer.status),
    )
}

fn display_identity(peer: &RollingDeployPeer) -> String {
    match peer.identities.get(1) {
        Some(alias) => format!("{} ({alias})", peer.thread_id),
        None => peer.thread_id.to_string(),
    }
}

fn display_status(status: HollywoodSessionStatus) -> &'static str {
    match status {
        HollywoodSessionStatus::Idle => "idle",
        HollywoodSessionStatus::Active => "active",
        HollywoodSessionStatus::Waiting => "waiting",
        HollywoodSessionStatus::Blocked => "blocked",
        HollywoodSessionStatus::Persisted => "persisted",
    }
}

fn compare_cli_versions(left: &str, right: &str) -> std::cmp::Ordering {
    match (parse_cli_version(left), parse_cli_version(right)) {
        (Some(left), Some(right)) => left.cmp(&right),
        _ => left.cmp(right),
    }
}

fn parse_cli_version(value: &str) -> Option<ParsedCliVersion> {
    let normalized = value.trim().split(['-', '+']).next()?;
    let mut parts = normalized.split('.');
    let major = parts.next()?.parse().ok()?;
    let minor = parts.next()?.parse().ok()?;
    let patch = parts.next()?.parse().ok()?;
    Some(ParsedCliVersion {
        major,
        minor,
        patch,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use pretty_assertions::assert_eq;

    fn thread_id(value: &str) -> ThreadId {
        ThreadId::from_string(value).expect("valid thread id")
    }

    fn peer(
        peer_thread_id: &str,
        cli_version: &str,
        status: HollywoodSessionStatus,
        alias: &str,
    ) -> RollingDeployPeer {
        RollingDeployPeer {
            thread_id: thread_id(peer_thread_id),
            cli_version: cli_version.to_string(),
            room: "repo/ozzz".to_string(),
            cwd: PathBuf::from("/home/ai/Development/ozzz"),
            status,
            identities: vec![peer_thread_id.to_string(), alias.to_string()],
        }
    }

    fn registry_entry(last_heartbeat_at: Option<&str>) -> HollywoodRegistryEntry {
        HollywoodRegistryEntry {
            session_id: "019dad46-de5d-79a2-a8e1-c3592ac34db1".to_string(),
            room: "repo/ozzz".to_string(),
            attached: true,
            cwd: Some("/home/ai/Development/ozzz".to_string()),
            rollout_path: None,
            status: "idle".to_string(),
            identities: vec!["sid-peer".to_string()],
            updated_at: None,
            last_heartbeat_at: last_heartbeat_at.map(ToOwned::to_owned),
        }
    }

    #[test]
    fn newer_session_gets_takeover_notice_and_peer_messages() {
        let assessment = build_assessment(
            RollingDeploySession {
                thread_id: thread_id("019dad47-8a2f-7940-afc2-ff4f968e7e93"),
                cli_version: "0.121.0".to_string(),
                room: "repo/ozzz".to_string(),
                cwd: PathBuf::from("/home/ai/Development/ozzz"),
                identities: vec![
                    "019dad47-8a2f-7940-afc2-ff4f968e7e93".to_string(),
                    "sid-newer-agent".to_string(),
                ],
            },
            vec![
                peer(
                    "019dad46-de5d-79a2-a8e1-c3592ac34db1",
                    "0.120.0",
                    HollywoodSessionStatus::Idle,
                    "sid-older-agent",
                ),
                peer(
                    "019dad48-de5d-79a2-a8e1-c3592ac34db2",
                    "0.121.0",
                    HollywoodSessionStatus::Active,
                    "sid-same-agent",
                ),
            ],
        );

        let startup_notice = assessment
            .startup_notice
            .expect("expected startup notice for newer session");
        assert!(startup_notice.contains("older attached peer sessions"));
        assert!(startup_notice.contains("v0.120.0"));
        assert!(!startup_notice.contains("sid-same-agent"));
        assert_eq!(assessment.peer_notices.len(), 1);
        assert!(assessment.peer_notices[0].body.contains("sid-newer-agent"));
    }

    #[test]
    fn older_session_gets_yield_notice_without_peer_messages() {
        let assessment = build_assessment(
            RollingDeploySession {
                thread_id: thread_id("019dad46-de5d-79a2-a8e1-c3592ac34db1"),
                cli_version: "0.120.0".to_string(),
                room: "repo/ozzz".to_string(),
                cwd: PathBuf::from("/home/ai/Development/ozzz"),
                identities: vec![
                    "019dad46-de5d-79a2-a8e1-c3592ac34db1".to_string(),
                    "sid-older-agent".to_string(),
                ],
            },
            vec![peer(
                "019dad47-8a2f-7940-afc2-ff4f968e7e93",
                "0.121.0",
                HollywoodSessionStatus::Active,
                "sid-newer-agent",
            )],
        );

        let startup_notice = assessment
            .startup_notice
            .expect("expected startup notice for older session");
        assert!(startup_notice.contains("newer attached peer sessions already exist"));
        assert!(startup_notice.contains("sid-newer-agent"));
        assert!(assessment.peer_notices.is_empty());
    }

    #[test]
    fn unparsable_versions_do_not_trigger_rollover() {
        let assessment = build_assessment(
            RollingDeploySession {
                thread_id: thread_id("019dad46-de5d-79a2-a8e1-c3592ac34db1"),
                cli_version: "dev-build".to_string(),
                room: "repo/ozzz".to_string(),
                cwd: PathBuf::from("/home/ai/Development/ozzz"),
                identities: vec![
                    "019dad46-de5d-79a2-a8e1-c3592ac34db1".to_string(),
                    "sid-dev-agent".to_string(),
                ],
            },
            vec![peer(
                "019dad47-8a2f-7940-afc2-ff4f968e7e93",
                "0.121.0",
                HollywoodSessionStatus::Active,
                "sid-newer-agent",
            )],
        );

        assert_eq!(assessment, RollingDeployAssessment::default());
    }

    #[test]
    fn registry_entry_freshness_requires_recent_heartbeat() {
        let now = Utc::now();
        let fresh = registry_entry(Some((now - Duration::seconds(30)).to_rfc3339().as_str()));
        let stale = registry_entry(Some((now - Duration::minutes(10)).to_rfc3339().as_str()));
        let missing = registry_entry(None);

        assert!(registry_entry_is_fresh(&fresh, &now));
        assert!(!registry_entry_is_fresh(&stale, &now));
        assert!(!registry_entry_is_fresh(&missing, &now));
    }
}
