use super::*;
use crate::model::PathClaimAcquireResult;
use crate::model::PathClaimConflict;
use crate::model::PathClaimKind;
use crate::model::PathClaimRow;
use crate::model::PathClaimSpec;
use codex_protocol::ThreadId;
use std::collections::BTreeSet;
use std::path::Path;
use std::time::Duration;
use uuid::Uuid;

impl StateRuntime {
    pub async fn claim_path_ownership(
        &self,
        owner_thread_id: ThreadId,
        claims: &[PathClaimSpec],
        lease_duration: Duration,
    ) -> anyhow::Result<PathClaimAcquireResult> {
        self.ensure_state_schema_current().await?;

        let owner_thread_id = owner_thread_id.to_string();
        let now = Utc::now().timestamp();
        let lease_seconds = i64::try_from(lease_duration.as_secs()).unwrap_or(i64::MAX);
        let lease_expires_at = now.saturating_add(lease_seconds.max(0));

        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        let result = try_claim_path_ownership_in_tx(
            &mut tx,
            owner_thread_id.as_str(),
            claims,
            now,
            lease_expires_at,
        )
        .await?;
        tx.commit().await?;
        Ok(result)
    }

    pub async fn release_path_claims(
        &self,
        owner_thread_id: ThreadId,
        claims: &[PathClaimSpec],
    ) -> anyhow::Result<u64> {
        self.ensure_state_schema_current().await?;

        let claims = dedupe_claim_specs(claims)?;
        if claims.is_empty() {
            return Ok(0);
        }

        let owner_thread_id = owner_thread_id.to_string();
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        delete_expired_path_claims(&mut tx, Utc::now().timestamp()).await?;

        let mut released = 0;
        for claim in claims {
            let result = sqlx::query(
                r#"
DELETE FROM path_claims
WHERE owner_thread_id = ?
  AND claim_kind = ?
  AND path = ?
                "#,
            )
            .bind(owner_thread_id.as_str())
            .bind(claim.kind.as_str())
            .bind(claim.path.to_string_lossy().as_ref())
            .execute(&mut *tx)
            .await?;
            released += result.rows_affected();
        }

        tx.commit().await?;
        Ok(released)
    }

    pub async fn list_path_claims(
        &self,
        owner_thread_id: Option<ThreadId>,
    ) -> anyhow::Result<Vec<crate::PathClaim>> {
        self.ensure_state_schema_current().await?;

        let now = Utc::now().timestamp();
        let mut tx = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        delete_expired_path_claims(&mut tx, now).await?;
        let claims = load_active_path_claims(
            &mut tx,
            owner_thread_id.as_ref().map(ThreadId::to_string),
            now,
        )
        .await?;
        tx.commit().await?;
        Ok(claims)
    }
}

pub(crate) async fn try_claim_path_ownership_in_tx(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    owner_thread_id: &str,
    claims: &[PathClaimSpec],
    now: i64,
    lease_expires_at: i64,
) -> anyhow::Result<PathClaimAcquireResult> {
    let claims = dedupe_claim_specs(claims)?;
    if claims.is_empty() {
        return Ok(PathClaimAcquireResult {
            acquired: true,
            claims: Vec::new(),
            conflicts: Vec::new(),
        });
    }

    delete_expired_path_claims(tx, now).await?;

    let existing_claims = load_active_path_claims(tx, /*owner_thread_id*/ None, now).await?;
    let conflicts = collect_path_claim_conflicts(&claims, owner_thread_id, &existing_claims);
    if !conflicts.is_empty() {
        return Ok(PathClaimAcquireResult {
            acquired: false,
            claims: Vec::new(),
            conflicts,
        });
    }

    let mut acquired_claims = Vec::with_capacity(claims.len());
    for claim in claims {
        let existing = existing_claims.iter().find(|existing| {
            existing.owner_thread_id == owner_thread_id
                && existing.kind == claim.kind
                && existing.path == claim.path
        });
        let id = existing
            .map(|existing| existing.id.clone())
            .unwrap_or_else(|| Uuid::new_v4().to_string());
        let claimed_at = existing
            .map(|existing| existing.claimed_at.timestamp())
            .unwrap_or(now);
        sqlx::query(
            r#"
INSERT INTO path_claims (
    id,
    owner_thread_id,
    claim_kind,
    path,
    claimed_at,
    updated_at,
    lease_expires_at
) VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(claim_kind, path) DO UPDATE SET
    updated_at = excluded.updated_at,
    lease_expires_at = excluded.lease_expires_at
WHERE path_claims.owner_thread_id = excluded.owner_thread_id
            "#,
        )
        .bind(id.as_str())
        .bind(owner_thread_id)
        .bind(claim.kind.as_str())
        .bind(claim.path.to_string_lossy().as_ref())
        .bind(claimed_at)
        .bind(now)
        .bind(lease_expires_at)
        .execute(&mut **tx)
        .await?;

        acquired_claims.push(crate::PathClaim {
            id,
            owner_thread_id: owner_thread_id.to_string(),
            kind: claim.kind,
            path: claim.path.clone(),
            claimed_at: DateTime::from_timestamp(claimed_at, 0)
                .ok_or_else(|| anyhow::anyhow!("invalid claimed_at timestamp"))?,
            updated_at: DateTime::from_timestamp(now, 0)
                .ok_or_else(|| anyhow::anyhow!("invalid updated_at timestamp"))?,
            lease_expires_at: DateTime::from_timestamp(lease_expires_at, 0)
                .ok_or_else(|| anyhow::anyhow!("invalid lease_expires_at timestamp"))?,
        });
    }

    Ok(PathClaimAcquireResult {
        acquired: true,
        claims: acquired_claims,
        conflicts: Vec::new(),
    })
}

fn dedupe_claim_specs(claims: &[PathClaimSpec]) -> anyhow::Result<Vec<PathClaimSpec>> {
    let mut seen = BTreeSet::new();
    let mut deduped = Vec::new();
    for claim in claims {
        if !claim.path.is_absolute() {
            return Err(anyhow::anyhow!(
                "path claims must be absolute: {}",
                claim.path.display()
            ));
        }
        if claim.path.as_os_str().is_empty() {
            return Err(anyhow::anyhow!("path claims must not be empty"));
        }
        let key = (claim.kind, claim.path.clone());
        if seen.insert(key) {
            deduped.push(claim.clone());
        }
    }
    Ok(deduped)
}

pub(crate) async fn delete_expired_path_claims(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    now: i64,
) -> anyhow::Result<()> {
    sqlx::query("DELETE FROM path_claims WHERE lease_expires_at <= ?")
        .bind(now)
        .execute(&mut **tx)
        .await?;
    Ok(())
}

pub(crate) async fn load_active_path_claims(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    owner_thread_id: Option<String>,
    now: i64,
) -> anyhow::Result<Vec<crate::PathClaim>> {
    let rows = if let Some(owner_thread_id) = owner_thread_id {
        sqlx::query_as::<_, PathClaimRow>(
            r#"
SELECT
    id,
    owner_thread_id,
    claim_kind,
    path,
    claimed_at,
    updated_at,
    lease_expires_at
FROM path_claims
WHERE lease_expires_at > ?
  AND owner_thread_id = ?
ORDER BY path ASC, claim_kind ASC, owner_thread_id ASC, id ASC
            "#,
        )
        .bind(now)
        .bind(owner_thread_id)
        .fetch_all(&mut **tx)
        .await?
    } else {
        sqlx::query_as::<_, PathClaimRow>(
            r#"
SELECT
    id,
    owner_thread_id,
    claim_kind,
    path,
    claimed_at,
    updated_at,
    lease_expires_at
FROM path_claims
WHERE lease_expires_at > ?
ORDER BY path ASC, claim_kind ASC, owner_thread_id ASC, id ASC
            "#,
        )
        .bind(now)
        .fetch_all(&mut **tx)
        .await?
    };
    rows.into_iter().map(TryInto::try_into).collect()
}

pub(crate) fn collect_path_claim_conflicts(
    requested: &[PathClaimSpec],
    owner_thread_id: &str,
    active_claims: &[crate::PathClaim],
) -> Vec<PathClaimConflict> {
    let mut conflicts = Vec::new();
    for requested_claim in requested {
        for active_claim in active_claims {
            if active_claim.owner_thread_id == owner_thread_id {
                continue;
            }
            if claims_overlap(requested_claim, active_claim) {
                conflicts.push(PathClaimConflict {
                    requested: requested_claim.clone(),
                    blocking_claim: active_claim.clone(),
                });
            }
        }
    }
    conflicts
}

fn claims_overlap(requested: &PathClaimSpec, active: &crate::PathClaim) -> bool {
    match (requested.kind, active.kind) {
        (PathClaimKind::File, PathClaimKind::File) => requested.path == active.path,
        (PathClaimKind::File, PathClaimKind::Directory) => {
            path_is_same_or_descendant(requested.path.as_path(), active.path.as_path())
        }
        (PathClaimKind::Directory, PathClaimKind::File) => {
            path_is_same_or_descendant(active.path.as_path(), requested.path.as_path())
        }
        (PathClaimKind::Directory, PathClaimKind::Directory) => {
            path_is_same_or_descendant(requested.path.as_path(), active.path.as_path())
                || path_is_same_or_descendant(active.path.as_path(), requested.path.as_path())
        }
    }
}

fn path_is_same_or_descendant(path: &Path, ancestor: &Path) -> bool {
    path == ancestor || path.starts_with(ancestor)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::StateRuntime;
    use pretty_assertions::assert_eq;
    use std::path::PathBuf;
    use std::sync::Arc;
    use tempfile::TempDir;

    async fn new_runtime() -> (TempDir, Arc<StateRuntime>) {
        let codex_home = TempDir::new().expect("temp dir");
        let runtime = StateRuntime::init(codex_home.path().to_path_buf(), "test".to_string())
            .await
            .expect("state runtime");
        (codex_home, runtime)
    }

    fn file_claim(path: &str) -> PathClaimSpec {
        PathClaimSpec {
            kind: PathClaimKind::File,
            path: PathBuf::from(path),
        }
    }

    fn directory_claim(path: &str) -> PathClaimSpec {
        PathClaimSpec {
            kind: PathClaimKind::Directory,
            path: PathBuf::from(path),
        }
    }

    #[tokio::test]
    async fn claim_path_ownership_allows_refresh_and_release_for_same_owner() {
        let (_codex_home, runtime) = new_runtime().await;
        let owner = ThreadId::new();
        let claims = vec![file_claim("/repo/src/app.ts")];

        let initial = runtime
            .claim_path_ownership(owner, &claims, Duration::from_secs(30))
            .await
            .expect("initial claim");
        assert!(initial.acquired);
        assert_eq!(initial.conflicts, Vec::<PathClaimConflict>::new());
        assert_eq!(initial.claims.len(), 1);

        let refreshed = runtime
            .claim_path_ownership(owner, &claims, Duration::from_secs(60))
            .await
            .expect("refresh claim");
        assert!(refreshed.acquired);
        assert_eq!(refreshed.claims.len(), 1);
        assert_eq!(refreshed.claims[0].id, initial.claims[0].id);
        assert!(refreshed.claims[0].lease_expires_at >= initial.claims[0].lease_expires_at);

        let listed = runtime
            .list_path_claims(Some(owner))
            .await
            .expect("list claims");
        assert_eq!(listed, refreshed.claims);

        let released = runtime
            .release_path_claims(owner, &claims)
            .await
            .expect("release claims");
        assert_eq!(released, 1);
        assert_eq!(
            runtime
                .list_path_claims(Some(owner))
                .await
                .expect("list claims after release"),
            Vec::<crate::PathClaim>::new()
        );
    }

    #[tokio::test]
    async fn claim_path_ownership_detects_overlapping_directory_and_file_conflicts() {
        let (_codex_home, runtime) = new_runtime().await;
        let owner_a = ThreadId::new();
        let owner_b = ThreadId::new();

        let claim = runtime
            .claim_path_ownership(
                owner_a,
                &[directory_claim("/repo/src/feature")],
                Duration::from_secs(30),
            )
            .await
            .expect("directory claim");
        assert!(claim.acquired);

        let conflict = runtime
            .claim_path_ownership(
                owner_b,
                &[file_claim("/repo/src/feature/mod.rs")],
                Duration::from_secs(30),
            )
            .await
            .expect("conflicting file claim");
        assert!(!conflict.acquired);
        assert_eq!(conflict.claims, Vec::new());
        assert_eq!(conflict.conflicts.len(), 1);
        assert_eq!(
            conflict.conflicts[0].blocking_claim.path,
            PathBuf::from("/repo/src/feature")
        );
        assert_eq!(
            conflict.conflicts[0].requested,
            file_claim("/repo/src/feature/mod.rs")
        );
    }

    #[tokio::test]
    async fn concurrent_claims_for_same_file_are_conflict_safe() {
        let codex_home = TempDir::new().expect("temp dir");
        let runtime_a = StateRuntime::init(codex_home.path().to_path_buf(), "test".to_string())
            .await
            .expect("runtime a");
        let runtime_b = StateRuntime::init(codex_home.path().to_path_buf(), "test".to_string())
            .await
            .expect("runtime b");

        let owner_a = ThreadId::new();
        let owner_b = ThreadId::new();
        let claims = vec![file_claim("/repo/src/lib.rs")];

        let (claim_a, claim_b) = tokio::join!(
            runtime_a.claim_path_ownership(owner_a, &claims, Duration::from_secs(30)),
            runtime_b.claim_path_ownership(owner_b, &claims, Duration::from_secs(30)),
        );
        let claim_a = claim_a.expect("claim a");
        let claim_b = claim_b.expect("claim b");
        let acquired = [claim_a.acquired, claim_b.acquired]
            .into_iter()
            .filter(|acquired| *acquired)
            .count();
        assert_eq!(acquired, 1);
        assert!(
            (!claim_a.acquired && !claim_a.conflicts.is_empty())
                || (!claim_b.acquired && !claim_b.conflicts.is_empty())
        );
    }
}
