use pretty_assertions::assert_eq;
use sqlx::Row;
use sqlx::migrate::Migration;
use sqlx::migrate::Migrator;
use sqlx_sqlite::SqlitePool;

use super::reconcile_legacy_state_migration_versions;
use crate::migrations::LAX_MIGRATOR;
use crate::migrations::STATE_MIGRATOR;
use crate::migrations::runtime_lax_migrator;
use crate::migrations::runtime_state_migrator;

// Reconstruct the two released parents' actual SQL and numbering. This is an
// upgrade fixture, rather than a second implementation of migration recovery.
fn released_fork_migrator() -> Migrator {
    let mut migrations: Vec<Migration> = STATE_MIGRATOR
        .migrations
        .iter()
        .filter_map(|migration| {
            let version = match migration.version {
                1..=34 | 39..=40 => migration.version,
                35..=38 | 41..=43 => migration.version + 11,
                _ => return None,
            };
            Some(Migration::new(
                version,
                migration.description.clone(),
                migration.migration_type,
                migration.sql.clone(),
                migration.no_tx,
            ))
        })
        .chain(LAX_MIGRATOR.migrations.iter().cloned())
        .collect();
    migrations.sort_by_key(|migration| migration.version);
    Migrator::with_migrations(migrations)
}

async fn applied(pool: &SqlitePool) -> Vec<(String, i64, Vec<u8>)> {
    sqlx::query(
        "SELECT 'upstream' AS namespace, version, checksum FROM _sqlx_migrations
         UNION ALL SELECT 'lax', version, checksum FROM _lax_migrations
         ORDER BY namespace, version",
    )
    .fetch_all(pool)
    .await
    .expect("read both migration namespaces")
    .iter()
    .map(|row| {
        (
            row.get("namespace"),
            row.get("version"),
            row.get("checksum"),
        )
    })
    .collect()
}

async fn file_pool(path: &std::path::Path) -> SqlitePool {
    use sqlx::sqlite::SqliteConnectOptions;
    sqlx::sqlite::SqlitePoolOptions::new()
        .max_connections(1)
        .connect_with(
            SqliteConnectOptions::new()
                .filename(path)
                .create_if_missing(true),
        )
        .await
        .expect("open disposable file-backed state")
}

#[tokio::test]
async fn fresh_and_both_released_lineages_upgrade_without_replaying_sql_or_losing_state() {
    for parent in ["fresh", "upstream", "lax"] {
        let home = tempfile::tempdir().expect("isolated state home");
        let original = home.path().join(if parent == "lax" {
            "state_7.sqlite"
        } else {
            "state_5.sqlite"
        });
        let pool = file_pool(&original).await;
        match parent {
            "upstream" => STATE_MIGRATOR.run(&pool).await.expect("released upstream"),
            "lax" => released_fork_migrator()
                .run(&pool)
                .await
                .expect("released fork"),
            _ => {}
        }
        if parent != "fresh" {
            sqlx::query(
                "INSERT INTO threads (
                     id, rollout_path, created_at, updated_at, source, model_provider,
                     cwd, title, sandbox_policy, approval_mode
                 ) VALUES ('canary', '/workspace/rollout.jsonl', 1700000000, 1700000001,
                           'cli', 'openai', '/workspace', 'preserve me', 'read-only', 'on-request')",
            )
            .execute(&pool).await.expect("existing thread");
        }
        if parent == "lax" {
            sqlx::query(
                "INSERT INTO path_claims VALUES (
                     'claim-canary', 'canary', 'file', '/workspace/shared.rs', 1, 2, 3)",
            )
            .execute(&pool)
            .await
            .expect("existing private path claim");
        }
        assert_eq!(
            crate::state_layout::state_database_path(home.path()).expect("unique existing layout"),
            original
        );
        reconcile_legacy_state_migration_versions(&pool)
            .await
            .expect("atomic reconciliation");
        runtime_state_migrator()
            .run(&pool)
            .await
            .expect("upstream upgrade");
        runtime_lax_migrator()
            .run(&pool)
            .await
            .expect("LAX extensions upgrade");
        let snapshot = applied(&pool).await;
        let mut expected = STATE_MIGRATOR
            .migrations
            .iter()
            .map(|migration| {
                (
                    "upstream".to_string(),
                    migration.version,
                    migration.checksum.to_vec(),
                )
            })
            .chain(LAX_MIGRATOR.migrations.iter().map(|migration| {
                (
                    "lax".to_string(),
                    migration.version,
                    migration.checksum.to_vec(),
                )
            }))
            .collect::<Vec<_>>();
        expected.sort();
        assert_eq!(snapshot, expected, "parent {parent}");
        pool.close().await;

        // Cold reopen uses the same file, with no rename or empty parallel store.
        let selected = crate::state_layout::state_database_path(home.path())
            .expect("same lineage on cold reopen");
        assert_eq!(selected, original);
        let pool = file_pool(&selected).await;
        reconcile_legacy_state_migration_versions(&pool)
            .await
            .expect("reopen reconciliation");
        runtime_state_migrator()
            .run(&pool)
            .await
            .expect("reopen upstream");
        runtime_lax_migrator().run(&pool).await.expect("reopen LAX");
        assert_eq!(applied(&pool).await, snapshot, "parent {parent}");
        if parent != "fresh" {
            let title: String = sqlx::query_scalar("SELECT title FROM threads WHERE id = 'canary'")
                .fetch_one(&pool)
                .await
                .expect("preserved thread");
            assert_eq!(title, "preserve me");
        }
        if parent == "lax" {
            let claim: (String, String, i64) = sqlx::query_as(
                "SELECT owner_thread_id, path, lease_expires_at FROM path_claims WHERE id = 'claim-canary'",
            ).fetch_one(&pool).await.expect("preserved claim");
            assert_eq!(
                claim,
                ("canary".to_string(), "/workspace/shared.rs".to_string(), 3)
            );
            assert!(!home.path().join("state_5.sqlite").exists());
        }
        pool.close().await;
    }
    let home = tempfile::tempdir().expect("ambiguous historical home");
    std::fs::write(home.path().join("state_5.sqlite"), b"current-canary").expect("current store");
    std::fs::write(home.path().join("state_7.sqlite"), b"legacy-canary").expect("legacy store");
    assert!(crate::state_layout::state_database_path(home.path()).is_err());
    assert_eq!(
        std::fs::read(home.path().join("state_5.sqlite")).expect("current retained"),
        b"current-canary"
    );
    assert_eq!(
        std::fs::read(home.path().join("state_7.sqlite")).expect("legacy retained"),
        b"legacy-canary"
    );
}

#[tokio::test]
async fn changed_known_migration_is_rejected_without_checksum_repair() {
    let pool = SqlitePool::connect("sqlite::memory:")
        .await
        .expect("open SQLite");
    STATE_MIGRATOR.run(&pool).await.expect("released upstream");
    sqlx::query("UPDATE _sqlx_migrations SET checksum = X'FF' WHERE version = 35")
        .execute(&pool)
        .await
        .expect("simulate incompatible SQL history");
    reconcile_legacy_state_migration_versions(&pool)
        .await
        .expect("do not guess unknown SQL");
    assert!(runtime_state_migrator().run(&pool).await.is_err());
    let checksum: Vec<u8> =
        sqlx::query_scalar("SELECT checksum FROM _sqlx_migrations WHERE version = 35")
            .fetch_one(&pool)
            .await
            .expect("preserved incompatible receipt");
    assert_eq!(checksum, vec![255]);
    pool.close().await;
}
