use anyhow::Result;
use chrono::DateTime;
use chrono::Utc;
use codex_protocol::ThreadId;
use std::path::PathBuf;

pub const DEFAULT_COLLABORATIVE_EDIT_PLAN_LEASE_SECONDS: i64 = 3_600;

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct CollaborativeEditPlan {
    pub id: String,
    pub actor_thread_id: String,
    pub room: Option<String>,
    pub file_path: PathBuf,
    pub edit_slice: String,
    pub intent: String,
    pub peers: Vec<String>,
    pub handoff: Option<String>,
    pub integrator: Option<String>,
    pub report_back: Option<String>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
    pub lease_expires_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CollaborativeEditPlanCreateParams {
    pub id: String,
    pub actor_thread_id: ThreadId,
    pub room: Option<String>,
    pub file_path: PathBuf,
    pub edit_slice: String,
    pub intent: String,
    pub peers: Vec<String>,
    pub handoff: Option<String>,
    pub integrator: Option<String>,
    pub report_back: Option<String>,
    pub lease_seconds: i64,
}

#[derive(Debug, sqlx::FromRow)]
pub(crate) struct CollaborativeEditPlanRow {
    pub(crate) id: String,
    pub(crate) actor_thread_id: String,
    pub(crate) room: Option<String>,
    pub(crate) file_path: String,
    pub(crate) edit_slice: String,
    pub(crate) intent: String,
    pub(crate) peers_json: String,
    pub(crate) handoff: Option<String>,
    pub(crate) integrator: Option<String>,
    pub(crate) report_back: Option<String>,
    pub(crate) created_at: i64,
    pub(crate) updated_at: i64,
    pub(crate) lease_expires_at: i64,
}

impl TryFrom<CollaborativeEditPlanRow> for CollaborativeEditPlan {
    type Error = anyhow::Error;

    fn try_from(value: CollaborativeEditPlanRow) -> Result<Self, Self::Error> {
        Ok(Self {
            id: value.id,
            actor_thread_id: value.actor_thread_id,
            room: value.room,
            file_path: PathBuf::from(value.file_path),
            edit_slice: value.edit_slice,
            intent: value.intent,
            peers: serde_json::from_str(value.peers_json.as_str())?,
            handoff: value.handoff,
            integrator: value.integrator,
            report_back: value.report_back,
            created_at: epoch_seconds_to_datetime(value.created_at)?,
            updated_at: epoch_seconds_to_datetime(value.updated_at)?,
            lease_expires_at: epoch_seconds_to_datetime(value.lease_expires_at)?,
        })
    }
}

fn epoch_seconds_to_datetime(value: i64) -> Result<DateTime<Utc>> {
    DateTime::from_timestamp(value, 0)
        .ok_or_else(|| anyhow::anyhow!("invalid epoch seconds: {value}"))
}
