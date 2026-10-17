use super::*;
use pretty_assertions::assert_eq;
use std::sync::mpsc;
use std::time::Duration;

#[test]
fn concurrent_writers_wait_for_the_original_path_guard() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let path = root
        .path()
        .join("shared.txt")
        .to_string_lossy()
        .into_owned();
    let original = lock_hunk_paths_blocking(vec![path.clone()])?;
    let (tx, rx) = mpsc::channel();
    let next = std::thread::spawn(move || {
        let guard = lock_hunk_paths_blocking(vec![path]);
        tx.send(guard.is_ok()).unwrap();
    });
    assert_eq!(
        rx.recv_timeout(Duration::from_millis(100)),
        Err(mpsc::RecvTimeoutError::Timeout)
    );
    drop(original);
    assert_eq!(rx.recv_timeout(Duration::from_secs(5))?, true);
    next.join().unwrap();
    Ok(())
}

#[cfg(unix)]
#[test]
fn private_root_rejects_directory_links_and_shared_permissions() -> anyhow::Result<()> {
    use std::os::unix::fs::PermissionsExt;
    use std::os::unix::fs::symlink;
    let temp = tempfile::tempdir()?;
    let actual = temp.path().join("actual");
    prepare_lock_root(&actual)?;
    prepare_lock_root(&actual)?;
    let linked = temp.path().join("linked");
    symlink(&actual, &linked)?;
    assert!(prepare_lock_root(&linked).is_err());
    std::fs::set_permissions(&actual, std::fs::Permissions::from_mode(0o777))?;
    assert!(prepare_lock_root(&actual).is_err());
    assert_eq!(std::fs::read_dir(&actual)?.count(), 0);
    Ok(())
}
