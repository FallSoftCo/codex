//! SQLite-backed state for rollout metadata.
//!
//! This crate is intentionally small and focused: it extracts rollout metadata
//! from JSONL rollouts and mirrors it into a local SQLite database. Backfill
//! orchestration and rollout scanning live in `codex-core`.

mod extract;
pub mod log_db;
mod migrations;
mod model;
mod paths;
mod runtime;

pub use model::ClaimedScheduledTask;
pub use model::ClaimedTaskWatch;
pub use model::CoordinationAct;
pub use model::CoordinationActKind;
pub use model::CoordinationTask;
pub use model::CoordinationTaskAcceptParams;
pub use model::CoordinationTaskCreateParams;
pub use model::CoordinationTaskDoneParams;
pub use model::CoordinationTaskHandoffParams;
pub use model::CoordinationTaskKind;
pub use model::CoordinationTaskListFilter;
pub use model::CoordinationTaskStatus;
pub use model::CoordinationTaskTransitionOutcome;
pub use model::CoordinationTaskYieldParams;
pub use model::DEFAULT_COORDINATION_LEASE_SECONDS;
pub use model::LogEntry;
pub use model::LogQuery;
pub use model::LogRow;
pub use model::PathClaim;
pub use model::PathClaimAcquireResult;
pub use model::PathClaimConflict;
pub use model::PathClaimKind;
pub use model::PathClaimSpec;
pub use model::Phase2InputSelection;
pub use model::Phase2JobClaimOutcome;
pub use model::RunningScheduledTaskRun;
pub use model::RunningTaskWatchRun;
/// Preferred entrypoint: owns configuration and metrics.
pub use runtime::StateRuntime;

/// Low-level storage engine: useful for focused tests.
///
/// Most consumers should prefer [`StateRuntime`].
pub use extract::apply_rollout_item;
pub use extract::rollout_item_affects_thread_metadata;
pub use model::AgentJob;
pub use model::AgentJobCreateParams;
pub use model::AgentJobItem;
pub use model::AgentJobItemCreateParams;
pub use model::AgentJobItemStatus;
pub use model::AgentJobProgress;
pub use model::AgentJobStatus;
pub use model::Anchor;
pub use model::BackfillState;
pub use model::BackfillStats;
pub use model::BackfillStatus;
pub use model::ClaimedTesterRun;
pub use model::ClaimedWatcher;
pub use model::DEFAULT_PATH_CLAIM_LEASE_SECONDS;
pub use model::DirectionalThreadSpawnEdgeStatus;
pub use model::ExtractionOutcome;
pub use model::RunningWatcherRun;
pub use model::ScheduledTask;
pub use model::ScheduledTaskCreateParams;
pub use model::ScheduledTaskKind;
pub use model::ScheduledTaskRun;
pub use model::ScheduledTaskRunStatus;
pub use model::SortDirection;
pub use model::SortKey;
pub use model::Stage1JobClaim;
pub use model::Stage1JobClaimOutcome;
pub use model::Stage1Output;
pub use model::Stage1OutputRef;
pub use model::Stage1StartupClaimParams;
pub use model::TaskWatch;
pub use model::TaskWatchCreateParams;
pub use model::TaskWatchRun;
pub use model::TaskWatchRunStatus;
pub use model::TaskWatchStatus;
pub use model::TaskWatchUpdateParams;
pub use model::TesterExecutionClass;
pub use model::TesterRun;
pub use model::TesterRunArtifact;
pub use model::TesterRunArtifactKind;
pub use model::TesterRunCreateParams;
pub use model::TesterRunReport;
pub use model::TesterRunReportKind;
pub use model::TesterRunStatus;
pub use model::ThreadMetadata;
pub use model::ThreadMetadataBuilder;
pub use model::ThreadsPage;
pub use model::Watcher;
pub use model::WatcherAgentCompletionCondition;
pub use model::WatcherCreateParams;
pub use model::WatcherRun;
pub use model::WatcherRunStatus;
pub use model::WatcherStatus;
pub use model::WatcherTriggerKind;
pub use runtime::RemoteControlEnrollmentRecord;
pub use runtime::DeviceKeyBindingRecord;
pub use runtime::ThreadFilterOptions;
pub use runtime::logs_db_filename;
pub use runtime::logs_db_path;
pub use runtime::state_db_filename;
pub use runtime::state_db_path;

/// Environment variable for overriding the SQLite state database home directory.
pub const SQLITE_HOME_ENV: &str = "CODEX_SQLITE_HOME";

pub const LOGS_DB_FILENAME: &str = "logs";
pub const LOGS_DB_VERSION: u32 = 2;
pub const STATE_DB_FILENAME: &str = "state";
pub const STATE_DB_VERSION: u32 = 7;

/// Errors encountered during DB operations. Tags: [stage]
pub const DB_ERROR_METRIC: &str = "codex.db.error";
/// Metrics on backfill process. Tags: [status]
pub const DB_METRIC_BACKFILL: &str = "codex.db.backfill";
/// Metrics on backfill duration. Tags: [status]
pub const DB_METRIC_BACKFILL_DURATION_MS: &str = "codex.db.backfill.duration_ms";
