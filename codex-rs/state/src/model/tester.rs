use anyhow::Context;
use anyhow::Result;
use chrono::DateTime;
use chrono::Utc;
use std::path::PathBuf;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TesterExecutionClass {
    TerminalFullAccess,
    TerminalSandboxed,
}

impl TesterExecutionClass {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::TerminalFullAccess => "terminal_full_access",
            Self::TerminalSandboxed => "terminal_sandboxed",
        }
    }

    pub fn parse(value: &str) -> Result<Self> {
        match value {
            "terminal_full_access" => Ok(Self::TerminalFullAccess),
            "terminal_sandboxed" => Ok(Self::TerminalSandboxed),
            _ => Err(anyhow::anyhow!("invalid tester execution class: {value}")),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TesterRunStatus {
    Queued,
    Starting,
    Running,
    BlockedEnvironment,
    BlockedProduct,
    CompletedSuccess,
    CompletedFailure,
    Stopped,
    Crashed,
}

impl TesterRunStatus {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Queued => "queued",
            Self::Starting => "starting",
            Self::Running => "running",
            Self::BlockedEnvironment => "blocked_environment",
            Self::BlockedProduct => "blocked_product",
            Self::CompletedSuccess => "completed_success",
            Self::CompletedFailure => "completed_failure",
            Self::Stopped => "stopped",
            Self::Crashed => "crashed",
        }
    }

    pub fn parse(value: &str) -> Result<Self> {
        match value {
            "queued" => Ok(Self::Queued),
            "starting" => Ok(Self::Starting),
            "running" => Ok(Self::Running),
            "blocked_environment" => Ok(Self::BlockedEnvironment),
            "blocked_product" => Ok(Self::BlockedProduct),
            "completed_success" => Ok(Self::CompletedSuccess),
            "completed_failure" => Ok(Self::CompletedFailure),
            "stopped" => Ok(Self::Stopped),
            "crashed" => Ok(Self::Crashed),
            _ => Err(anyhow::anyhow!("invalid tester run status: {value}")),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TesterRunReportKind {
    Created,
    Started,
    Progress,
    Observation,
    BlockedEnvironment,
    BlockedProduct,
    CompletedSuccess,
    CompletedFailure,
    Stopped,
    Crashed,
}

impl TesterRunReportKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Created => "created",
            Self::Started => "started",
            Self::Progress => "progress",
            Self::Observation => "observation",
            Self::BlockedEnvironment => "blocked_environment",
            Self::BlockedProduct => "blocked_product",
            Self::CompletedSuccess => "completed_success",
            Self::CompletedFailure => "completed_failure",
            Self::Stopped => "stopped",
            Self::Crashed => "crashed",
        }
    }

    pub fn parse(value: &str) -> Result<Self> {
        match value {
            "created" => Ok(Self::Created),
            "started" => Ok(Self::Started),
            "progress" => Ok(Self::Progress),
            "observation" => Ok(Self::Observation),
            "blocked_environment" => Ok(Self::BlockedEnvironment),
            "blocked_product" => Ok(Self::BlockedProduct),
            "completed_success" => Ok(Self::CompletedSuccess),
            "completed_failure" => Ok(Self::CompletedFailure),
            "stopped" => Ok(Self::Stopped),
            "crashed" => Ok(Self::Crashed),
            _ => Err(anyhow::anyhow!("invalid tester run report kind: {value}")),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TesterRunArtifactKind {
    Rollout,
}

impl TesterRunArtifactKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Rollout => "rollout",
        }
    }

    pub fn parse(value: &str) -> Result<Self> {
        match value {
            "rollout" => Ok(Self::Rollout),
            _ => Err(anyhow::anyhow!("invalid tester run artifact kind: {value}")),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TesterRun {
    pub id: String,
    pub name: String,
    pub objective: String,
    pub background: Option<String>,
    pub skill_level: Option<String>,
    pub temperament: Option<String>,
    pub starting_knowledge: Vec<String>,
    pub constraints: Vec<String>,
    pub allowed_interfaces: Vec<String>,
    pub execution_class: TesterExecutionClass,
    pub controller_thread_id: Option<String>,
    pub runtime_thread_id: Option<String>,
    pub rollout_path: Option<PathBuf>,
    pub cwd: Option<PathBuf>,
    pub status: TesterRunStatus,
    pub last_observed_thread_status: Option<String>,
    pub last_error: Option<String>,
    pub last_parsed_rollout_index: i64,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TesterRunReport {
    pub id: String,
    pub tester_run_id: String,
    pub report_kind: TesterRunReportKind,
    pub summary: String,
    pub details: Option<String>,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TesterRunArtifact {
    pub id: String,
    pub tester_run_id: String,
    pub artifact_kind: TesterRunArtifactKind,
    pub label: String,
    pub path: PathBuf,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TesterRunCreateParams {
    pub id: String,
    pub name: String,
    pub objective: String,
    pub background: Option<String>,
    pub skill_level: Option<String>,
    pub temperament: Option<String>,
    pub starting_knowledge: Vec<String>,
    pub constraints: Vec<String>,
    pub allowed_interfaces: Vec<String>,
    pub execution_class: TesterExecutionClass,
    pub controller_thread_id: Option<String>,
    pub cwd: Option<PathBuf>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ClaimedTesterRun {
    pub id: String,
    pub name: String,
    pub objective: String,
    pub background: Option<String>,
    pub skill_level: Option<String>,
    pub temperament: Option<String>,
    pub starting_knowledge: Vec<String>,
    pub constraints: Vec<String>,
    pub allowed_interfaces: Vec<String>,
    pub execution_class: TesterExecutionClass,
    pub controller_thread_id: Option<String>,
    pub cwd: Option<PathBuf>,
}

#[derive(Debug, sqlx::FromRow)]
pub(crate) struct TesterRunRow {
    pub(crate) id: String,
    pub(crate) name: String,
    pub(crate) objective: String,
    pub(crate) background: Option<String>,
    pub(crate) skill_level: Option<String>,
    pub(crate) temperament: Option<String>,
    pub(crate) starting_knowledge_json: String,
    pub(crate) constraints_json: String,
    pub(crate) allowed_interfaces_json: String,
    pub(crate) execution_class: String,
    pub(crate) controller_thread_id: Option<String>,
    pub(crate) runtime_thread_id: Option<String>,
    pub(crate) rollout_path: Option<String>,
    pub(crate) cwd: Option<String>,
    pub(crate) status: String,
    pub(crate) last_observed_thread_status: Option<String>,
    pub(crate) last_error: Option<String>,
    pub(crate) last_parsed_rollout_index: i64,
    pub(crate) created_at: i64,
    pub(crate) updated_at: i64,
}

impl TryFrom<TesterRunRow> for TesterRun {
    type Error = anyhow::Error;

    fn try_from(value: TesterRunRow) -> Result<Self, Self::Error> {
        Ok(Self {
            id: value.id,
            name: value.name,
            objective: value.objective,
            background: value.background,
            skill_level: value.skill_level,
            temperament: value.temperament,
            starting_knowledge: parse_string_vec(value.starting_knowledge_json)?,
            constraints: parse_string_vec(value.constraints_json)?,
            allowed_interfaces: parse_string_vec(value.allowed_interfaces_json)?,
            execution_class: TesterExecutionClass::parse(value.execution_class.as_str())?,
            controller_thread_id: value.controller_thread_id,
            runtime_thread_id: value.runtime_thread_id,
            rollout_path: value.rollout_path.map(PathBuf::from),
            cwd: value.cwd.map(PathBuf::from),
            status: TesterRunStatus::parse(value.status.as_str())?,
            last_observed_thread_status: value.last_observed_thread_status,
            last_error: value.last_error,
            last_parsed_rollout_index: value.last_parsed_rollout_index,
            created_at: epoch_seconds_to_datetime(value.created_at)?,
            updated_at: epoch_seconds_to_datetime(value.updated_at)?,
        })
    }
}

#[derive(Debug, sqlx::FromRow)]
pub(crate) struct TesterRunReportRow {
    pub(crate) id: String,
    pub(crate) tester_run_id: String,
    pub(crate) report_kind: String,
    pub(crate) summary: String,
    pub(crate) details: Option<String>,
    pub(crate) created_at: i64,
}

impl TryFrom<TesterRunReportRow> for TesterRunReport {
    type Error = anyhow::Error;

    fn try_from(value: TesterRunReportRow) -> Result<Self, Self::Error> {
        Ok(Self {
            id: value.id,
            tester_run_id: value.tester_run_id,
            report_kind: TesterRunReportKind::parse(value.report_kind.as_str())?,
            summary: value.summary,
            details: value.details,
            created_at: epoch_seconds_to_datetime(value.created_at)?,
        })
    }
}

#[derive(Debug, sqlx::FromRow)]
pub(crate) struct TesterRunArtifactRow {
    pub(crate) id: String,
    pub(crate) tester_run_id: String,
    pub(crate) artifact_kind: String,
    pub(crate) label: String,
    pub(crate) path: String,
    pub(crate) created_at: i64,
}

impl TryFrom<TesterRunArtifactRow> for TesterRunArtifact {
    type Error = anyhow::Error;

    fn try_from(value: TesterRunArtifactRow) -> Result<Self, Self::Error> {
        Ok(Self {
            id: value.id,
            tester_run_id: value.tester_run_id,
            artifact_kind: TesterRunArtifactKind::parse(value.artifact_kind.as_str())?,
            label: value.label,
            path: PathBuf::from(value.path),
            created_at: epoch_seconds_to_datetime(value.created_at)?,
        })
    }
}

fn parse_string_vec(value: String) -> Result<Vec<String>> {
    serde_json::from_str(&value).with_context(|| format!("invalid JSON string vector: {value}"))
}

fn epoch_seconds_to_datetime(value: i64) -> Result<DateTime<Utc>> {
    DateTime::from_timestamp(value, 0)
        .ok_or_else(|| anyhow::anyhow!("invalid epoch seconds: {value}"))
}
