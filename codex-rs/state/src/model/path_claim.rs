use anyhow::Result;
use chrono::DateTime;
use chrono::Utc;
use std::path::PathBuf;

pub const DEFAULT_PATH_CLAIM_LEASE_SECONDS: i64 = 300;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum PathClaimKind {
    File,
    Directory,
}

impl PathClaimKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::File => "file",
            Self::Directory => "directory",
        }
    }

    pub fn parse(value: &str) -> Result<Self> {
        match value {
            "file" => Ok(Self::File),
            "directory" => Ok(Self::Directory),
            _ => Err(anyhow::anyhow!("invalid path claim kind: {value}")),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct PathClaimSpec {
    pub kind: PathClaimKind,
    pub path: PathBuf,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PathClaim {
    pub id: String,
    pub owner_thread_id: String,
    pub kind: PathClaimKind,
    pub path: PathBuf,
    pub claimed_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
    pub lease_expires_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PathClaimConflict {
    pub requested: PathClaimSpec,
    pub blocking_claim: PathClaim,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PathClaimAcquireResult {
    pub acquired: bool,
    pub claims: Vec<PathClaim>,
    pub conflicts: Vec<PathClaimConflict>,
}

#[derive(Debug, sqlx::FromRow)]
pub(crate) struct PathClaimRow {
    pub(crate) id: String,
    pub(crate) owner_thread_id: String,
    pub(crate) claim_kind: String,
    pub(crate) path: String,
    pub(crate) claimed_at: i64,
    pub(crate) updated_at: i64,
    pub(crate) lease_expires_at: i64,
}

impl TryFrom<PathClaimRow> for PathClaim {
    type Error = anyhow::Error;

    fn try_from(value: PathClaimRow) -> Result<Self, Self::Error> {
        Ok(Self {
            id: value.id,
            owner_thread_id: value.owner_thread_id,
            kind: PathClaimKind::parse(value.claim_kind.as_str())?,
            path: PathBuf::from(value.path),
            claimed_at: epoch_seconds_to_datetime(value.claimed_at)?,
            updated_at: epoch_seconds_to_datetime(value.updated_at)?,
            lease_expires_at: epoch_seconds_to_datetime(value.lease_expires_at)?,
        })
    }
}

fn epoch_seconds_to_datetime(value: i64) -> Result<DateTime<Utc>> {
    DateTime::from_timestamp(value, 0)
        .ok_or_else(|| anyhow::anyhow!("invalid epoch seconds: {value}"))
}
