use anyhow::Result;
use chrono::DateTime;
use chrono::Utc;
use codex_protocol::ThreadId;

pub const DEFAULT_COORDINATION_LEASE_SECONDS: i64 = 14_400;

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CoordinationTaskKind {
    General,
    Implementation,
    Review,
    Investigation,
    Qa,
    Handoff,
}

impl CoordinationTaskKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::General => "general",
            Self::Implementation => "implementation",
            Self::Review => "review",
            Self::Investigation => "investigation",
            Self::Qa => "qa",
            Self::Handoff => "handoff",
        }
    }

    pub fn parse(value: &str) -> Result<Self> {
        match value {
            "general" => Ok(Self::General),
            "implementation" => Ok(Self::Implementation),
            "review" => Ok(Self::Review),
            "investigation" => Ok(Self::Investigation),
            "qa" => Ok(Self::Qa),
            "handoff" => Ok(Self::Handoff),
            _ => Err(anyhow::anyhow!("invalid coordination task kind: {value}")),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CoordinationTaskStatus {
    Open,
    Awarded,
    Active,
    Blocked,
    Done,
    Yielded,
    Cancelled,
}

impl CoordinationTaskStatus {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Open => "open",
            Self::Awarded => "awarded",
            Self::Active => "active",
            Self::Blocked => "blocked",
            Self::Done => "done",
            Self::Yielded => "yielded",
            Self::Cancelled => "cancelled",
        }
    }

    pub fn parse(value: &str) -> Result<Self> {
        match value {
            "open" => Ok(Self::Open),
            "awarded" => Ok(Self::Awarded),
            "active" => Ok(Self::Active),
            "blocked" => Ok(Self::Blocked),
            "done" => Ok(Self::Done),
            "yielded" => Ok(Self::Yielded),
            "cancelled" => Ok(Self::Cancelled),
            _ => Err(anyhow::anyhow!("invalid coordination task status: {value}")),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CoordinationActKind {
    OpenTask,
    Accept,
    Done,
    Handoff,
    Yield,
}

impl CoordinationActKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::OpenTask => "open_task",
            Self::Accept => "accept",
            Self::Done => "done",
            Self::Handoff => "handoff",
            Self::Yield => "yield",
        }
    }

    pub fn parse(value: &str) -> Result<Self> {
        match value {
            "open_task" => Ok(Self::OpenTask),
            "accept" => Ok(Self::Accept),
            "done" => Ok(Self::Done),
            "handoff" => Ok(Self::Handoff),
            "yield" => Ok(Self::Yield),
            _ => Err(anyhow::anyhow!("invalid coordination act kind: {value}")),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct CoordinationTask {
    pub id: String,
    pub creator_thread_id: String,
    pub owner_thread_id: Option<String>,
    pub team_id: Option<String>,
    pub room: Option<String>,
    pub kind: CoordinationTaskKind,
    pub status: CoordinationTaskStatus,
    pub summary: String,
    pub details: String,
    pub requested_capability: Option<String>,
    pub blocked_reason: Option<String>,
    pub dependency_task_ids: Vec<String>,
    pub blocked_dependency_task_ids: Vec<String>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
    pub completed_at: Option<DateTime<Utc>>,
    pub lease_expires_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct CoordinationAct {
    pub id: String,
    pub task_id: Option<String>,
    pub actor_thread_id: String,
    pub kind: CoordinationActKind,
    pub summary: Option<String>,
    pub payload_json: String,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CoordinationTaskCreateParams {
    pub id: String,
    pub creator_thread_id: ThreadId,
    pub owner_thread_id: Option<ThreadId>,
    pub team_id: Option<String>,
    pub room: Option<String>,
    pub kind: CoordinationTaskKind,
    pub summary: String,
    pub details: String,
    pub requested_capability: Option<String>,
    pub dependency_task_ids: Vec<String>,
    pub act_id: String,
    pub act_summary: Option<String>,
    pub act_payload_json: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CoordinationTaskTransitionOutcome {
    pub task: CoordinationTask,
    pub act: CoordinationAct,
    pub unblocked_tasks: Vec<CoordinationTask>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CoordinationTaskListFilter {
    pub owner_thread_id: Option<ThreadId>,
    pub creator_thread_id: Option<ThreadId>,
    pub statuses: Vec<CoordinationTaskStatus>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CoordinationTaskAcceptParams {
    pub task_id: String,
    pub actor_thread_id: ThreadId,
    pub lease_seconds: i64,
    pub act_id: String,
    pub act_summary: Option<String>,
    pub act_payload_json: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CoordinationTaskDoneParams {
    pub task_id: String,
    pub actor_thread_id: ThreadId,
    pub act_id: String,
    pub act_summary: Option<String>,
    pub act_payload_json: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CoordinationTaskHandoffParams {
    pub task_id: String,
    pub actor_thread_id: ThreadId,
    pub new_owner_thread_id: ThreadId,
    pub act_id: String,
    pub act_summary: Option<String>,
    pub act_payload_json: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CoordinationTaskYieldParams {
    pub task_id: String,
    pub actor_thread_id: ThreadId,
    pub act_id: String,
    pub act_summary: Option<String>,
    pub act_payload_json: String,
}

#[derive(Debug, sqlx::FromRow)]
pub(crate) struct CoordinationTaskRow {
    pub(crate) id: String,
    pub(crate) creator_thread_id: String,
    pub(crate) owner_thread_id: Option<String>,
    pub(crate) team_id: Option<String>,
    pub(crate) room: Option<String>,
    pub(crate) task_kind: String,
    pub(crate) status: String,
    pub(crate) summary: String,
    pub(crate) details: String,
    pub(crate) requested_capability: Option<String>,
    pub(crate) blocked_reason: Option<String>,
    pub(crate) created_at: i64,
    pub(crate) updated_at: i64,
    pub(crate) completed_at: Option<i64>,
    pub(crate) lease_expires_at: Option<i64>,
}

#[derive(Debug, sqlx::FromRow)]
pub(crate) struct CoordinationActRow {
    pub(crate) id: String,
    pub(crate) task_id: Option<String>,
    pub(crate) actor_thread_id: String,
    pub(crate) act_kind: String,
    pub(crate) summary: Option<String>,
    pub(crate) payload_json: String,
    pub(crate) created_at: i64,
}

impl TryFrom<CoordinationActRow> for CoordinationAct {
    type Error = anyhow::Error;

    fn try_from(value: CoordinationActRow) -> Result<Self, Self::Error> {
        Ok(Self {
            id: value.id,
            task_id: value.task_id,
            actor_thread_id: value.actor_thread_id,
            kind: CoordinationActKind::parse(value.act_kind.as_str())?,
            summary: value.summary,
            payload_json: value.payload_json,
            created_at: epoch_seconds_to_datetime(value.created_at)?,
        })
    }
}

pub(crate) fn epoch_seconds_to_datetime(value: i64) -> Result<DateTime<Utc>> {
    DateTime::from_timestamp(value, 0)
        .ok_or_else(|| anyhow::anyhow!("invalid epoch seconds: {value}"))
}
