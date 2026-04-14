use anyhow::Result;
use chrono::DateTime;
use chrono::Utc;

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
pub enum TaskWatchStatus {
    Active,
    Completed,
    Stopped,
    BlockedEnvironment,
}

impl TaskWatchStatus {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Active => "active",
            Self::Completed => "completed",
            Self::Stopped => "stopped",
            Self::BlockedEnvironment => "blocked_environment",
        }
    }

    pub fn parse(value: &str) -> Result<Self> {
        match value {
            "active" => Ok(Self::Active),
            "completed" => Ok(Self::Completed),
            "stopped" => Ok(Self::Stopped),
            "blocked_environment" => Ok(Self::BlockedEnvironment),
            _ => Err(anyhow::anyhow!("invalid task watch status: {value}")),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
pub enum TaskWatchRunStatus {
    Running,
    Completed,
    Failed,
}

impl TaskWatchRunStatus {
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
            _ => Err(anyhow::anyhow!("invalid task watch run status: {value}")),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct TaskWatch {
    pub id: String,
    pub thread_id: String,
    pub title: String,
    pub objective: String,
    pub prompt: String,
    pub cadence_seconds: i64,
    pub next_check_at: DateTime<Utc>,
    pub max_checks: Option<i64>,
    pub check_count: i64,
    pub requires_response: bool,
    pub status: TaskWatchStatus,
    pub last_decision: Option<String>,
    pub last_observation: Option<String>,
    pub last_run_turn_id: Option<String>,
    pub last_run_status: Option<TaskWatchRunStatus>,
    pub last_error: Option<String>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
    pub stopped_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct TaskWatchRun {
    pub id: String,
    pub task_watch_id: String,
    pub thread_id: String,
    pub turn_id: Option<String>,
    pub scheduled_for: DateTime<Utc>,
    pub status: TaskWatchRunStatus,
    pub summary: Option<String>,
    pub error: Option<String>,
    pub started_at: DateTime<Utc>,
    pub finished_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TaskWatchCreateParams {
    pub id: String,
    pub thread_id: String,
    pub title: String,
    pub objective: String,
    pub prompt: String,
    pub cadence_seconds: i64,
    pub next_check_at: DateTime<Utc>,
    pub max_checks: Option<i64>,
    pub requires_response: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TaskWatchUpdateParams {
    pub id: String,
    pub cadence_seconds: Option<i64>,
    pub next_check_at: Option<DateTime<Utc>>,
    pub max_checks: Option<i64>,
    pub last_decision: Option<String>,
    pub last_observation: Option<String>,
    pub status: Option<TaskWatchStatus>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ClaimedTaskWatch {
    pub id: String,
    pub thread_id: String,
    pub title: String,
    pub objective: String,
    pub prompt: String,
    pub cadence_seconds: i64,
    pub scheduled_for: DateTime<Utc>,
    pub max_checks: Option<i64>,
    pub check_count: i64,
    pub requires_response: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RunningTaskWatchRun {
    pub id: String,
    pub task_watch_id: String,
    pub thread_id: String,
    pub turn_id: String,
    pub started_at: DateTime<Utc>,
}

#[derive(Debug, sqlx::FromRow)]
pub(crate) struct TaskWatchRow {
    pub(crate) id: String,
    pub(crate) thread_id: String,
    pub(crate) title: String,
    pub(crate) objective: String,
    pub(crate) prompt: String,
    pub(crate) cadence_seconds: i64,
    pub(crate) next_check_at: i64,
    pub(crate) max_checks: Option<i64>,
    pub(crate) check_count: i64,
    pub(crate) requires_response: i64,
    pub(crate) status: String,
    pub(crate) last_decision: Option<String>,
    pub(crate) last_observation: Option<String>,
    pub(crate) last_run_turn_id: Option<String>,
    pub(crate) last_run_status: Option<String>,
    pub(crate) last_error: Option<String>,
    pub(crate) created_at: i64,
    pub(crate) updated_at: i64,
    pub(crate) stopped_at: Option<i64>,
}

impl TryFrom<TaskWatchRow> for TaskWatch {
    type Error = anyhow::Error;

    fn try_from(value: TaskWatchRow) -> Result<Self, Self::Error> {
        Ok(Self {
            id: value.id,
            thread_id: value.thread_id,
            title: value.title,
            objective: value.objective,
            prompt: value.prompt,
            cadence_seconds: value.cadence_seconds,
            next_check_at: epoch_seconds_to_datetime(value.next_check_at)?,
            max_checks: value.max_checks,
            check_count: value.check_count,
            requires_response: value.requires_response != 0,
            status: TaskWatchStatus::parse(value.status.as_str())?,
            last_decision: value.last_decision,
            last_observation: value.last_observation,
            last_run_turn_id: value.last_run_turn_id,
            last_run_status: value
                .last_run_status
                .as_deref()
                .map(TaskWatchRunStatus::parse)
                .transpose()?,
            last_error: value.last_error,
            created_at: epoch_seconds_to_datetime(value.created_at)?,
            updated_at: epoch_seconds_to_datetime(value.updated_at)?,
            stopped_at: value
                .stopped_at
                .map(epoch_seconds_to_datetime)
                .transpose()?,
        })
    }
}

#[derive(Debug, sqlx::FromRow)]
pub(crate) struct TaskWatchRunRow {
    pub(crate) id: String,
    pub(crate) task_watch_id: String,
    pub(crate) thread_id: String,
    pub(crate) turn_id: Option<String>,
    pub(crate) scheduled_for: i64,
    pub(crate) status: String,
    pub(crate) summary: Option<String>,
    pub(crate) error: Option<String>,
    pub(crate) started_at: i64,
    pub(crate) finished_at: Option<i64>,
}

impl TryFrom<TaskWatchRunRow> for TaskWatchRun {
    type Error = anyhow::Error;

    fn try_from(value: TaskWatchRunRow) -> Result<Self, Self::Error> {
        Ok(Self {
            id: value.id,
            task_watch_id: value.task_watch_id,
            thread_id: value.thread_id,
            turn_id: value.turn_id,
            scheduled_for: epoch_seconds_to_datetime(value.scheduled_for)?,
            status: TaskWatchRunStatus::parse(value.status.as_str())?,
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
