//! Non-destructive selection of an existing native state lineage.
use std::path::Path;
use std::path::PathBuf;

pub(crate) const LEGACY_LAX_STATE_DB_FILENAME: &str = "state_7.sqlite";

pub(crate) fn state_database_path(home: &Path) -> anyhow::Result<PathBuf> {
    let current = home.join(crate::STATE_DB_FILENAME);
    let legacy = home.join(LEGACY_LAX_STATE_DB_FILENAME);
    let current_exists = current.try_exists()?;
    let legacy_exists = legacy.try_exists()?;
    anyhow::ensure!(
        !(current_exists && legacy_exists),
        "Both current state_5.sqlite and legacy LAX state_7.sqlite exist; explicit state-lineage reconciliation is required before opening either database"
    );
    Ok(if legacy_exists { legacy } else { current })
}
