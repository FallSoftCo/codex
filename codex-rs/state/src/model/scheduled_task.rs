use anyhow::Result;
use chrono::DateTime;
use chrono::Utc;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ScheduledTaskKind {
    Once,
    Interval,
}

impl ScheduledTaskKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Once => "once",
            Self::Interval => "interval",
        }
    }

    pub fn parse(value: &str) -> Result<Self> {
        match value {
            "once" => Ok(Self::Once),
            "interval" => Ok(Self::Interval),
            _ => Err(anyhow::anyhow!("invalid scheduled task kind: {value}")),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ScheduledTaskRunStatus {
    Running,
    Completed,
    Failed,
}

impl ScheduledTaskRunStatus {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Running => "running",
            Self::Completed => "completed",
            Self::Failed => "failed",
        }
    }

    pub fn parse(value: &str) -> Result<Self> {
        match value {
            "running" => Ok(Self::Running),
            "completed" => Ok(Self::Completed),
            "failed" => Ok(Self::Failed),
            _ => Err(anyhow::anyhow!(
                "invalid scheduled task run status: {value}"
            )),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ScheduledTask {
    pub id: String,
    pub thread_id: String,
    pub title: String,
    pub prompt: String,
    pub kind: ScheduledTaskKind,
    pub next_run_at: DateTime<Utc>,
    pub interval_seconds: Option<i64>,
    pub enabled: bool,
    pub requires_response: bool,
    pub last_run_turn_id: Option<String>,
    pub last_run_status: Option<ScheduledTaskRunStatus>,
    pub last_error: Option<String>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ScheduledTaskRun {
    pub id: String,
    pub scheduled_task_id: String,
    pub thread_id: String,
    pub turn_id: Option<String>,
    pub scheduled_for: DateTime<Utc>,
    pub status: ScheduledTaskRunStatus,
    pub summary: Option<String>,
    pub error: Option<String>,
    pub started_at: DateTime<Utc>,
    pub finished_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ScheduledTaskCreateParams {
    pub id: String,
    pub thread_id: String,
    pub title: String,
    pub prompt: String,
    pub kind: ScheduledTaskKind,
    pub next_run_at: DateTime<Utc>,
    pub interval_seconds: Option<i64>,
    pub requires_response: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ClaimedScheduledTask {
    pub id: String,
    pub thread_id: String,
    pub title: String,
    pub prompt: String,
    pub kind: ScheduledTaskKind,
    pub scheduled_for: DateTime<Utc>,
    pub interval_seconds: Option<i64>,
    pub requires_response: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RunningScheduledTaskRun {
    pub id: String,
    pub scheduled_task_id: String,
    pub thread_id: String,
    pub turn_id: String,
    pub started_at: DateTime<Utc>,
}

#[derive(Debug, sqlx::FromRow)]
pub(crate) struct ScheduledTaskRow {
    pub(crate) id: String,
    pub(crate) thread_id: String,
    pub(crate) title: String,
    pub(crate) prompt: String,
    pub(crate) schedule_kind: String,
    pub(crate) next_run_at: i64,
    pub(crate) interval_seconds: Option<i64>,
    pub(crate) enabled: i64,
    pub(crate) requires_response: i64,
    pub(crate) last_run_turn_id: Option<String>,
    pub(crate) last_run_status: Option<String>,
    pub(crate) last_error: Option<String>,
    pub(crate) created_at: i64,
    pub(crate) updated_at: i64,
}

impl TryFrom<ScheduledTaskRow> for ScheduledTask {
    type Error = anyhow::Error;

    fn try_from(value: ScheduledTaskRow) -> Result<Self, Self::Error> {
        Ok(Self {
            id: value.id,
            thread_id: value.thread_id,
            title: value.title,
            prompt: value.prompt,
            kind: ScheduledTaskKind::parse(value.schedule_kind.as_str())?,
            next_run_at: epoch_seconds_to_datetime(value.next_run_at)?,
            interval_seconds: value.interval_seconds,
            enabled: value.enabled != 0,
            requires_response: value.requires_response != 0,
            last_run_turn_id: value.last_run_turn_id,
            last_run_status: value
                .last_run_status
                .as_deref()
                .map(ScheduledTaskRunStatus::parse)
                .transpose()?,
            last_error: value.last_error,
            created_at: epoch_seconds_to_datetime(value.created_at)?,
            updated_at: epoch_seconds_to_datetime(value.updated_at)?,
        })
    }
}

#[derive(Debug, sqlx::FromRow)]
pub(crate) struct ScheduledTaskRunRow {
    pub(crate) id: String,
    pub(crate) scheduled_task_id: String,
    pub(crate) thread_id: String,
    pub(crate) turn_id: Option<String>,
    pub(crate) scheduled_for: i64,
    pub(crate) status: String,
    pub(crate) summary: Option<String>,
    pub(crate) error: Option<String>,
    pub(crate) started_at: i64,
    pub(crate) finished_at: Option<i64>,
}

impl TryFrom<ScheduledTaskRunRow> for ScheduledTaskRun {
    type Error = anyhow::Error;

    fn try_from(value: ScheduledTaskRunRow) -> Result<Self, Self::Error> {
        Ok(Self {
            id: value.id,
            scheduled_task_id: value.scheduled_task_id,
            thread_id: value.thread_id,
            turn_id: value.turn_id,
            scheduled_for: epoch_seconds_to_datetime(value.scheduled_for)?,
            status: ScheduledTaskRunStatus::parse(value.status.as_str())?,
            summary: value.summary,
            error: value.error,
            started_at: epoch_seconds_to_datetime(value.started_at)?,
            finished_at: value
                .finished_at
                .map(epoch_seconds_to_datetime)
                .transpose()?,
        })
    }
}

fn epoch_seconds_to_datetime(value: i64) -> Result<DateTime<Utc>> {
    DateTime::from_timestamp(value, 0)
        .ok_or_else(|| anyhow::anyhow!("invalid epoch seconds: {value}"))
}
