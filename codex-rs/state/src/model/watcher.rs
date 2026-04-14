use anyhow::Result;
use chrono::DateTime;
use chrono::Utc;

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
pub enum WatcherTriggerKind {
    ProcessExit,
    AgentCompletion,
}

impl WatcherTriggerKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::ProcessExit => "process_exit",
            Self::AgentCompletion => "agent_completion",
        }
    }

    pub fn parse(value: &str) -> Result<Self> {
        match value {
            "process_exit" => Ok(Self::ProcessExit),
            "agent_completion" => Ok(Self::AgentCompletion),
            _ => Err(anyhow::anyhow!("invalid watcher trigger kind: {value}")),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
pub enum WatcherAgentCompletionCondition {
    Final,
    Completed,
    Successful,
}

impl WatcherAgentCompletionCondition {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Final => "final",
            Self::Completed => "completed",
            Self::Successful => "successful",
        }
    }

    pub fn parse(value: &str) -> Result<Self> {
        match value {
            "final" => Ok(Self::Final),
            "completed" => Ok(Self::Completed),
            "successful" => Ok(Self::Successful),
            _ => Err(anyhow::anyhow!(
                "invalid agent completion condition: {value}"
            )),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
pub enum WatcherStatus {
    Armed,
    Triggered,
    BlockedEnvironment,
    Stopped,
}

impl WatcherStatus {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Armed => "armed",
            Self::Triggered => "triggered",
            Self::BlockedEnvironment => "blocked_environment",
            Self::Stopped => "stopped",
        }
    }

    pub fn parse(value: &str) -> Result<Self> {
        match value {
            "armed" => Ok(Self::Armed),
            "triggered" => Ok(Self::Triggered),
            "blocked_environment" => Ok(Self::BlockedEnvironment),
            "stopped" => Ok(Self::Stopped),
            _ => Err(anyhow::anyhow!("invalid watcher status: {value}")),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
pub enum WatcherRunStatus {
    Running,
    Completed,
    Failed,
}

impl WatcherRunStatus {
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
            _ => Err(anyhow::anyhow!("invalid watcher run status: {value}")),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct Watcher {
    pub id: String,
    pub thread_id: String,
    pub title: String,
    pub prompt: String,
    pub trigger_kind: WatcherTriggerKind,
    pub process_id: Option<i32>,
    pub target_thread_id: Option<String>,
    pub agent_completion_condition: Option<WatcherAgentCompletionCondition>,
    pub timeout_at: Option<DateTime<Utc>>,
    pub requires_response: bool,
    pub status: WatcherStatus,
    pub last_run_turn_id: Option<String>,
    pub last_run_status: Option<WatcherRunStatus>,
    pub last_error: Option<String>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct WatcherRun {
    pub id: String,
    pub watcher_id: String,
    pub thread_id: String,
    pub turn_id: Option<String>,
    pub trigger_fired_at: DateTime<Utc>,
    pub status: WatcherRunStatus,
    pub summary: Option<String>,
    pub error: Option<String>,
    pub started_at: DateTime<Utc>,
    pub finished_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WatcherCreateParams {
    pub id: String,
    pub thread_id: String,
    pub title: String,
    pub prompt: String,
    pub trigger_kind: WatcherTriggerKind,
    pub process_id: Option<i32>,
    pub target_thread_id: Option<String>,
    pub agent_completion_condition: Option<WatcherAgentCompletionCondition>,
    pub timeout_at: Option<DateTime<Utc>>,
    pub requires_response: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ClaimedWatcher {
    pub id: String,
    pub thread_id: String,
    pub title: String,
    pub prompt: String,
    pub trigger_kind: WatcherTriggerKind,
    pub process_id: Option<i32>,
    pub target_thread_id: Option<String>,
    pub agent_completion_condition: Option<WatcherAgentCompletionCondition>,
    pub timeout_at: Option<DateTime<Utc>>,
    pub requires_response: bool,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RunningWatcherRun {
    pub id: String,
    pub watcher_id: String,
    pub thread_id: String,
    pub turn_id: String,
    pub started_at: DateTime<Utc>,
}

#[derive(Debug, sqlx::FromRow)]
pub(crate) struct WatcherRow {
    pub(crate) id: String,
    pub(crate) thread_id: String,
    pub(crate) title: String,
    pub(crate) prompt: String,
    pub(crate) trigger_kind: String,
    pub(crate) process_id: Option<i32>,
    pub(crate) target_thread_id: Option<String>,
    pub(crate) completion_condition: Option<String>,
    pub(crate) timeout_at: Option<i64>,
    pub(crate) requires_response: i64,
    pub(crate) status: String,
    pub(crate) last_run_turn_id: Option<String>,
    pub(crate) last_run_status: Option<String>,
    pub(crate) last_error: Option<String>,
    pub(crate) created_at: i64,
    pub(crate) updated_at: i64,
}

impl TryFrom<WatcherRow> for Watcher {
    type Error = anyhow::Error;

    fn try_from(value: WatcherRow) -> Result<Self, Self::Error> {
        Ok(Self {
            id: value.id,
            thread_id: value.thread_id,
            title: value.title,
            prompt: value.prompt,
            trigger_kind: WatcherTriggerKind::parse(value.trigger_kind.as_str())?,
            process_id: value.process_id,
            target_thread_id: value.target_thread_id,
            agent_completion_condition: value
                .completion_condition
                .as_deref()
                .map(WatcherAgentCompletionCondition::parse)
                .transpose()?,
            timeout_at: value
                .timeout_at
                .map(epoch_seconds_to_datetime)
                .transpose()?,
            requires_response: value.requires_response != 0,
            status: WatcherStatus::parse(value.status.as_str())?,
            last_run_turn_id: value.last_run_turn_id,
            last_run_status: value
                .last_run_status
                .as_deref()
                .map(WatcherRunStatus::parse)
                .transpose()?,
            last_error: value.last_error,
            created_at: epoch_seconds_to_datetime(value.created_at)?,
            updated_at: epoch_seconds_to_datetime(value.updated_at)?,
        })
    }
}

#[derive(Debug, sqlx::FromRow)]
pub(crate) struct WatcherRunRow {
    pub(crate) id: String,
    pub(crate) watcher_id: String,
    pub(crate) thread_id: String,
    pub(crate) turn_id: Option<String>,
    pub(crate) trigger_fired_at: i64,
    pub(crate) status: String,
    pub(crate) summary: Option<String>,
    pub(crate) error: Option<String>,
    pub(crate) started_at: i64,
    pub(crate) finished_at: Option<i64>,
}

impl TryFrom<WatcherRunRow> for WatcherRun {
    type Error = anyhow::Error;

    fn try_from(value: WatcherRunRow) -> Result<Self, Self::Error> {
        Ok(Self {
            id: value.id,
            watcher_id: value.watcher_id,
            thread_id: value.thread_id,
            turn_id: value.turn_id,
            trigger_fired_at: epoch_seconds_to_datetime(value.trigger_fired_at)?,
            status: WatcherRunStatus::parse(value.status.as_str())?,
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
