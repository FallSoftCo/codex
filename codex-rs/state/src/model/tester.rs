use anyhow::Context;
use anyhow::Result;
use chrono::DateTime;
use chrono::Utc;
use std::path::PathBuf;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TesterStatus {
    Pending,
    Starting,
    Running,
    Waiting,
    Paused,
    Stopped,
    Failed,
}

impl TesterStatus {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Starting => "starting",
            Self::Running => "running",
            Self::Waiting => "waiting",
            Self::Paused => "paused",
            Self::Stopped => "stopped",
            Self::Failed => "failed",
        }
    }

    pub fn parse(value: &str) -> Result<Self> {
        match value {
            "pending" => Ok(Self::Pending),
            "starting" => Ok(Self::Starting),
            "running" => Ok(Self::Running),
            "waiting" => Ok(Self::Waiting),
            "paused" => Ok(Self::Paused),
            "stopped" => Ok(Self::Stopped),
            "failed" => Ok(Self::Failed),
            _ => Err(anyhow::anyhow!("invalid tester status: {value}")),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TesterReportKind {
    Created,
    Started,
    Progress,
    Waiting,
    Failed,
    Stopped,
}

impl TesterReportKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Created => "created",
            Self::Started => "started",
            Self::Progress => "progress",
            Self::Waiting => "waiting",
            Self::Failed => "failed",
            Self::Stopped => "stopped",
        }
    }

    pub fn parse(value: &str) -> Result<Self> {
        match value {
            "created" => Ok(Self::Created),
            "started" => Ok(Self::Started),
            "progress" => Ok(Self::Progress),
            "waiting" => Ok(Self::Waiting),
            "failed" => Ok(Self::Failed),
            "stopped" => Ok(Self::Stopped),
            _ => Err(anyhow::anyhow!("invalid tester report kind: {value}")),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Tester {
    pub id: String,
    pub name: String,
    pub objective: String,
    pub background: Option<String>,
    pub skill_level: Option<String>,
    pub temperament: Option<String>,
    pub starting_knowledge: Vec<String>,
    pub constraints: Vec<String>,
    pub allowed_interfaces: Vec<String>,
    pub controller_thread_id: Option<String>,
    pub tester_thread_id: Option<String>,
    pub cwd: Option<PathBuf>,
    pub status: TesterStatus,
    pub last_observed_thread_status: Option<String>,
    pub last_error: Option<String>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TesterReport {
    pub id: String,
    pub tester_id: String,
    pub report_kind: TesterReportKind,
    pub summary: String,
    pub details: Option<String>,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TesterCreateParams {
    pub id: String,
    pub name: String,
    pub objective: String,
    pub background: Option<String>,
    pub skill_level: Option<String>,
    pub temperament: Option<String>,
    pub starting_knowledge: Vec<String>,
    pub constraints: Vec<String>,
    pub allowed_interfaces: Vec<String>,
    pub controller_thread_id: Option<String>,
    pub cwd: Option<PathBuf>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ClaimedTester {
    pub id: String,
    pub name: String,
    pub objective: String,
    pub background: Option<String>,
    pub skill_level: Option<String>,
    pub temperament: Option<String>,
    pub starting_knowledge: Vec<String>,
    pub constraints: Vec<String>,
    pub allowed_interfaces: Vec<String>,
    pub controller_thread_id: Option<String>,
    pub cwd: Option<PathBuf>,
}

#[derive(Debug, sqlx::FromRow)]
pub(crate) struct TesterRow {
    pub(crate) id: String,
    pub(crate) name: String,
    pub(crate) objective: String,
    pub(crate) background: Option<String>,
    pub(crate) skill_level: Option<String>,
    pub(crate) temperament: Option<String>,
    pub(crate) starting_knowledge_json: String,
    pub(crate) constraints_json: String,
    pub(crate) allowed_interfaces_json: String,
    pub(crate) controller_thread_id: Option<String>,
    pub(crate) tester_thread_id: Option<String>,
    pub(crate) cwd: Option<String>,
    pub(crate) status: String,
    pub(crate) last_observed_thread_status: Option<String>,
    pub(crate) last_error: Option<String>,
    pub(crate) created_at: i64,
    pub(crate) updated_at: i64,
}

impl TryFrom<TesterRow> for Tester {
    type Error = anyhow::Error;

    fn try_from(value: TesterRow) -> Result<Self, Self::Error> {
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
            controller_thread_id: value.controller_thread_id,
            tester_thread_id: value.tester_thread_id,
            cwd: value.cwd.map(PathBuf::from),
            status: TesterStatus::parse(value.status.as_str())?,
            last_observed_thread_status: value.last_observed_thread_status,
            last_error: value.last_error,
            created_at: epoch_seconds_to_datetime(value.created_at)?,
            updated_at: epoch_seconds_to_datetime(value.updated_at)?,
        })
    }
}

#[derive(Debug, sqlx::FromRow)]
pub(crate) struct TesterReportRow {
    pub(crate) id: String,
    pub(crate) tester_id: String,
    pub(crate) report_kind: String,
    pub(crate) summary: String,
    pub(crate) details: Option<String>,
    pub(crate) created_at: i64,
}

impl TryFrom<TesterReportRow> for TesterReport {
    type Error = anyhow::Error;

    fn try_from(value: TesterReportRow) -> Result<Self, Self::Error> {
        Ok(Self {
            id: value.id,
            tester_id: value.tester_id,
            report_kind: TesterReportKind::parse(value.report_kind.as_str())?,
            summary: value.summary,
            details: value.details,
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
