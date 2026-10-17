//! Local same-account path serialization. Cross-account/host collaboration uses
//! Hollywood's canonical physical namespace permits, not shared writable temp files.
//!
//! Version 2 isolates private Unix lock roots by effective UID. Switching from
//! the old shared root requires draining old native writers; no lock is migrated
//! or deleted automatically.
use std::collections::BTreeSet;
use std::fs::File;
use std::fs::OpenOptions;
#[cfg(unix)]
use std::os::unix::fs::DirBuilderExt;
#[cfg(unix)]
use std::os::unix::fs::MetadataExt;
#[cfg(unix)]
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;

use crate::Hunk;
use anyhow::Context;
use codex_utils_path_uri::PathUri;

pub(crate) struct PatchPathLockGuards {
    _lock_files: Vec<File>,
}

fn collect_hunk_lock_paths(hunks: &[Hunk], cwd: &PathUri) -> anyhow::Result<Vec<String>> {
    let mut paths = BTreeSet::new();
    for hunk in hunks {
        let path_uri = hunk.resolve_path(cwd)?;
        paths.insert(path_uri.to_string());
        if let Hunk::UpdateFile {
            move_path: Some(dest),
            ..
        } = hunk
        {
            paths.insert(cwd.join(&dest.to_string_lossy())?.to_string());
        }
    }
    Ok(paths.into_iter().collect())
}

pub(crate) async fn lock_hunk_paths(
    hunks: &[Hunk],
    cwd: &PathUri,
) -> anyhow::Result<PatchPathLockGuards> {
    let paths = collect_hunk_lock_paths(hunks, cwd)?;
    tokio::task::spawn_blocking(move || lock_hunk_paths_blocking(paths))
        .await
        .context("failed to join apply_patch path lock task")?
}

fn lock_hunk_paths_blocking(paths: Vec<String>) -> anyhow::Result<PatchPathLockGuards> {
    let lock_root = apply_patch_lock_root();
    prepare_lock_root(&lock_root)?;

    let mut lock_files = Vec::with_capacity(paths.len());
    for path in paths {
        let lock_path = lock_root.join(format!("{}.lock", apply_patch_lock_key(&path)));
        let mut options = OpenOptions::new();
        options.read(true).write(true).create(true).truncate(false);
        #[cfg(unix)]
        options
            .mode(0o600)
            .custom_flags(rustix::fs::OFlags::NOFOLLOW.bits() as i32);
        let file = options.open(&lock_path).with_context(|| {
            format!(
                "failed to open apply_patch lock file {}",
                lock_path.display()
            )
        })?;
        #[cfg(unix)]
        {
            let info = file.metadata()?;
            anyhow::ensure!(
                info.is_file()
                    && info.uid() == rustix::process::geteuid().as_raw()
                    && info.nlink() == 1
                    && info.mode() & 0o077 == 0,
                "private owned apply_patch lock file required"
            );
        }
        file.lock()
            .with_context(|| format!("failed to lock apply_patch path {path}"))?;
        lock_files.push(file);
    }
    Ok(PatchPathLockGuards {
        _lock_files: lock_files,
    })
}

fn apply_patch_lock_root() -> PathBuf {
    #[cfg(unix)]
    let name = format!(
        "codex-apply-patch-locks-v2-{}",
        rustix::process::geteuid().as_raw()
    );
    #[cfg(not(unix))]
    let name = "codex-apply-patch-locks-v2";
    std::env::temp_dir().join(name)
}

fn apply_patch_lock_key(path: &str) -> String {
    const FNV_OFFSET: u64 = 0xcbf29ce484222325;
    const FNV_PRIME: u64 = 0x100000001b3;

    let mut hash = FNV_OFFSET;
    for byte in path.as_bytes() {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(FNV_PRIME);
    }
    format!("{hash:016x}-{}", path.len())
}

fn prepare_lock_root(root: &Path) -> anyhow::Result<()> {
    #[cfg(unix)]
    {
        let mut builder = std::fs::DirBuilder::new();
        builder.mode(0o700);
        match builder.create(root) {
            Ok(()) => {}
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {}
            Err(error) => {
                return Err(error).context("failed to create private apply_patch lock root");
            }
        }
        let info = root.symlink_metadata()?;
        anyhow::ensure!(
            info.is_dir()
                && info.uid() == rustix::process::geteuid().as_raw()
                && info.mode() & 0o077 == 0,
            "private owned nonsymlink apply_patch lock root required"
        );
    }
    #[cfg(not(unix))]
    std::fs::create_dir_all(root)?;
    Ok(())
}

#[cfg(test)]
#[path = "path_locks_tests.rs"]
mod tests;
