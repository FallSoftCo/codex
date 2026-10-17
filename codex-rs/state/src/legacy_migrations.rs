//! Preserve released LAX state while keeping upstream migration numbers unchanged.
use sqlx::Row;
use sqlx_sqlite::SqlitePool;

use crate::migrations::LAX_MIGRATOR;
use crate::migrations::STATE_MIGRATOR;

#[derive(Clone, Copy)]
enum Namespace {
    Upstream,
    Lax,
}

struct MigrationMove {
    original_version: i64,
    target_version: i64,
    checksum: Vec<u8>,
    namespace: Namespace,
}

/// Relocate only byte-identical known migrations, atomically and with an audit.
/// SQLx remains responsible for rejecting unknown or changed known-version SQL.
pub(crate) async fn reconcile_legacy_state_migration_versions(
    pool: &SqlitePool,
) -> anyhow::Result<()> {
    let mut tx = pool.begin_with("BEGIN IMMEDIATE").await?;
    sqlx::query(
        "CREATE TABLE IF NOT EXISTS _lax_migrations (
            version BIGINT PRIMARY KEY,
            description TEXT NOT NULL,
            installed_on TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            success BOOLEAN NOT NULL,
            checksum BLOB NOT NULL,
            execution_time BIGINT NOT NULL
        )",
    )
    .execute(&mut *tx)
    .await?;
    let exists = sqlx::query_scalar::<_, i64>(
        "SELECT COUNT(*) FROM sqlite_master
         WHERE type = 'table' AND name = '_sqlx_migrations'",
    )
    .fetch_one(&mut *tx)
    .await?;
    if exists == 0 {
        tx.commit().await?;
        return Ok(());
    }
    let rows = sqlx::query(
        "SELECT version, description, checksum, success FROM _sqlx_migrations ORDER BY version",
    )
    .fetch_all(&mut *tx)
    .await?;
    let mut moves = Vec::new();
    for row in rows {
        let version: i64 = row.try_get("version")?;
        anyhow::ensure!(
            row.try_get::<bool, _>("success")?,
            "dirty migration {version}"
        );
        let description: String = row.try_get("description")?;
        let checksum: Vec<u8> = row.try_get("checksum")?;
        let known = LAX_MIGRATOR
            .migrations
            .iter()
            .map(|migration| (Namespace::Lax, migration))
            .chain(
                STATE_MIGRATOR
                    .migrations
                    .iter()
                    .map(|migration| (Namespace::Upstream, migration)),
            )
            .find(|(_, migration)| {
                migration.checksum.as_ref() == checksum.as_slice()
                    && migration.description.as_ref() == description
            });
        if let Some((namespace, migration)) = known
            && (matches!(namespace, Namespace::Lax) || migration.version != version)
        {
            moves.push(MigrationMove {
                original_version: version,
                target_version: migration.version,
                checksum,
                namespace,
            });
        }
    }
    if !moves.is_empty() {
        sqlx::query(
            "CREATE TABLE IF NOT EXISTS _lax_legacy_migration_map (
                original_version BIGINT NOT NULL,
                description TEXT NOT NULL,
                installed_on TIMESTAMP NOT NULL,
                success BOOLEAN NOT NULL,
                checksum BLOB NOT NULL,
                execution_time BIGINT NOT NULL,
                target_namespace TEXT NOT NULL,
                target_version BIGINT NOT NULL,
                PRIMARY KEY (original_version, checksum)
            )",
        )
        .execute(&mut *tx)
        .await?;
    }
    // Snapshot all moves before freeing colliding version numbers.
    for movement in &moves {
        let namespace = match movement.namespace {
            Namespace::Upstream => "upstream",
            Namespace::Lax => "lax",
        };
        sqlx::query(
            "INSERT INTO _lax_legacy_migration_map
             SELECT version, description, installed_on, success, checksum, execution_time, ?, ?
             FROM _sqlx_migrations WHERE version = ? AND checksum = ?",
        )
        .bind(namespace)
        .bind(movement.target_version)
        .bind(movement.original_version)
        .bind(&movement.checksum)
        .execute(&mut *tx)
        .await?;
    }
    for movement in &moves {
        sqlx::query("DELETE FROM _sqlx_migrations WHERE version = ? AND checksum = ?")
            .bind(movement.original_version)
            .bind(&movement.checksum)
            .execute(&mut *tx)
            .await?;
    }
    for movement in &moves {
        let sql = match movement.namespace {
            Namespace::Upstream => {
                "INSERT INTO _sqlx_migrations
                 SELECT target_version, description, installed_on, success, checksum, execution_time
                 FROM _lax_legacy_migration_map WHERE original_version = ? AND checksum = ?"
            }
            Namespace::Lax => {
                "INSERT INTO _lax_migrations
                 SELECT target_version, description, installed_on, success, checksum, execution_time
                 FROM _lax_legacy_migration_map WHERE original_version = ? AND checksum = ?"
            }
        };
        // A conflicting destination aborts the whole transaction. Never rewrite
        // checksums or partially repair an unrecognized/ambiguous state lineage.
        sqlx::query(sql)
            .bind(movement.original_version)
            .bind(&movement.checksum)
            .execute(&mut *tx)
            .await?;
    }
    tx.commit().await?;
    Ok(())
}

#[cfg(test)]
#[path = "legacy_migrations_tests.rs"]
mod tests;
