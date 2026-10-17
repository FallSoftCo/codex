use super::*;
use crate::Hunk;
use crate::apply_patch;
use crate::parse_patch;
use codex_exec_server::LOCAL_FS;
use codex_utils_path_uri::PathUri;
use pretty_assertions::assert_eq;
use std::fs;
use tempfile::tempdir;

fn wrap_patch(body: &str) -> String {
    format!("*** Begin Patch\n{body}\n*** End Patch")
}

#[tokio::test]
async fn test_unified_diff() {
    // Start with a file containing four lines.
    let dir = tempdir().unwrap();
    let path = dir.path().join("multi.txt");
    fs::write(&path, "foo\nbar\nbaz\nqux\n").unwrap();
    let patch = wrap_patch(&format!(
        r#"*** Update File: {}
@@
 foo
-bar
+BAR
@@
 baz
-qux
+QUX"#,
        path.display()
    ));
    let patch = parse_patch(&patch).unwrap();

    let update_file_chunks = match patch.hunks.as_slice() {
        [Hunk::UpdateFile { chunks, .. }] => chunks,
        _ => panic!("Expected a single UpdateFile hunk"),
    };
    let path_uri = PathUri::from_host_native_path(&path).expect("absolute test path");
    let diff = unified_diff_from_chunks(
        &path_uri,
        update_file_chunks,
        LOCAL_FS.as_ref(),
        /*sandbox*/ None,
    )
    .await
    .unwrap();
    let expected_diff = r#"@@ -1,4 +1,4 @@
 foo
-bar
+BAR
 baz
-qux
+QUX
"#;
    let expected = ApplyPatchFileUpdate {
        unified_diff: expected_diff.to_string(),
        original_content: "foo\nbar\nbaz\nqux\n".to_string(),
        content: "foo\nBAR\nbaz\nQUX\n".to_string(),
    };
    assert_eq!(expected, diff);
}

#[tokio::test]
async fn test_unified_diff_first_line_replacement() {
    // Replace the very first line of the file.
    let dir = tempdir().unwrap();
    let path = dir.path().join("first.txt");
    fs::write(&path, "foo\nbar\nbaz\n").unwrap();

    let patch = wrap_patch(&format!(
        r#"*** Update File: {}
@@
-foo
+FOO
 bar
"#,
        path.display()
    ));

    let patch = parse_patch(&patch).unwrap();
    let chunks = match patch.hunks.as_slice() {
        [Hunk::UpdateFile { chunks, .. }] => chunks,
        _ => panic!("Expected a single UpdateFile hunk"),
    };

    let resolved_path = PathUri::from_host_native_path(&path).expect("absolute test path");
    let diff = unified_diff_from_chunks(
        &resolved_path,
        chunks,
        LOCAL_FS.as_ref(),
        /*sandbox*/ None,
    )
    .await
    .unwrap();
    let expected_diff = r#"@@ -1,2 +1,2 @@
-foo
+FOO
 bar
"#;
    let expected = ApplyPatchFileUpdate {
        unified_diff: expected_diff.to_string(),
        original_content: "foo\nbar\nbaz\n".to_string(),
        content: "FOO\nbar\nbaz\n".to_string(),
    };
    assert_eq!(expected, diff);
}

#[tokio::test]
async fn test_unified_diff_last_line_replacement() {
    // Replace the very last line of the file.
    let dir = tempdir().unwrap();
    let path = dir.path().join("last.txt");
    fs::write(&path, "foo\nbar\nbaz\n").unwrap();

    let patch = wrap_patch(&format!(
        r#"*** Update File: {}
@@
 foo
 bar
-baz
+BAZ
"#,
        path.display()
    ));

    let patch = parse_patch(&patch).unwrap();
    let chunks = match patch.hunks.as_slice() {
        [Hunk::UpdateFile { chunks, .. }] => chunks,
        _ => panic!("Expected a single UpdateFile hunk"),
    };

    let resolved_path = PathUri::from_host_native_path(&path).expect("absolute test path");
    let diff = unified_diff_from_chunks(
        &resolved_path,
        chunks,
        LOCAL_FS.as_ref(),
        /*sandbox*/ None,
    )
    .await
    .unwrap();
    let expected_diff = r#"@@ -2,2 +2,2 @@
 bar
-baz
+BAZ
"#;
    let expected = ApplyPatchFileUpdate {
        unified_diff: expected_diff.to_string(),
        original_content: "foo\nbar\nbaz\n".to_string(),
        content: "foo\nbar\nBAZ\n".to_string(),
    };
    assert_eq!(expected, diff);
}

#[tokio::test]
async fn test_unified_diff_insert_at_eof() {
    // Insert a new line at end-of-file.
    let dir = tempdir().unwrap();
    let path = dir.path().join("insert.txt");
    fs::write(&path, "foo\nbar\nbaz\n").unwrap();

    let patch = wrap_patch(&format!(
        r#"*** Update File: {}
@@
+quux
*** End of File
"#,
        path.display()
    ));

    let patch = parse_patch(&patch).unwrap();
    let chunks = match patch.hunks.as_slice() {
        [Hunk::UpdateFile { chunks, .. }] => chunks,
        _ => panic!("Expected a single UpdateFile hunk"),
    };

    let path_uri = PathUri::from_host_native_path(&path).expect("absolute test path");
    let diff =
        unified_diff_from_chunks(&path_uri, chunks, LOCAL_FS.as_ref(), /*sandbox*/ None)
            .await
            .unwrap();
    let expected_diff = r#"@@ -3 +3,2 @@
 baz
+quux
"#;
    let expected = ApplyPatchFileUpdate {
        unified_diff: expected_diff.to_string(),
        original_content: "foo\nbar\nbaz\n".to_string(),
        content: "foo\nbar\nbaz\nquux\n".to_string(),
    };
    assert_eq!(expected, diff);
}

#[tokio::test]
async fn test_unified_diff_interleaved_changes() {
    // Original file with six lines.
    let dir = tempdir().unwrap();
    let path = dir.path().join("interleaved.txt");
    fs::write(&path, "a\nb\nc\nd\ne\nf\n").unwrap();

    // Patch replaces two separate lines and appends a new one at EOF using
    // three distinct chunks.
    let patch_body = format!(
        r#"*** Update File: {}
@@
 a
-b
+B
@@
 d
-e
+E
@@
 f
+g
*** End of File"#,
        path.display()
    );
    let patch = wrap_patch(&patch_body);

    // Extract chunks then build the unified diff.
    let parsed = parse_patch(&patch).unwrap();
    let chunks = match parsed.hunks.as_slice() {
        [Hunk::UpdateFile { chunks, .. }] => chunks,
        _ => panic!("Expected a single UpdateFile hunk"),
    };

    let path_uri = PathUri::from_host_native_path(&path).expect("absolute test path");
    let diff =
        unified_diff_from_chunks(&path_uri, chunks, LOCAL_FS.as_ref(), /*sandbox*/ None)
            .await
            .unwrap();

    let expected_diff = r#"@@ -1,6 +1,7 @@
 a
-b
+B
 c
 d
-e
+E
 f
+g
"#;

    let expected = ApplyPatchFileUpdate {
        unified_diff: expected_diff.to_string(),
        original_content: "a\nb\nc\nd\ne\nf\n".to_string(),
        content: "a\nB\nc\nd\nE\nf\ng\n".to_string(),
    };

    assert_eq!(expected, diff);

    let mut stdout = Vec::new();
    let mut stderr = Vec::new();
    apply_patch(
        &patch,
        &PathUri::from_host_native_path(dir.path()).expect("absolute test path"),
        &mut stdout,
        &mut stderr,
        LOCAL_FS.as_ref(),
        /*sandbox*/ None,
    )
    .await
    .unwrap();
    let contents = fs::read_to_string(path).unwrap();
    assert_eq!(
        contents,
        r#"a
B
c
d
E
f
g
"#
    );
}

#[tokio::test]
async fn cooperative_partial_insertion_preserves_existing_mixed_terminators_and_bom() {
    let home = tempdir().expect("isolated shared-source fixture");
    let path = home.path().join("shared.txt");
    fs::write(&path, "\u{feff}alpha\r\nalready\nomega\r\n").expect("existing peer bytes");
    let patch =
        wrap_patch("*** Update File: shared.txt\n@@\n \u{feff}alpha\n+already\n+fresh\n omega\n");
    let cwd = PathUri::from_host_native_path(home.path()).expect("native workspace");
    let mut stdout = Vec::new();
    let mut stderr = Vec::new();
    apply_patch(
        &patch,
        &cwd,
        &mut stdout,
        &mut stderr,
        LOCAL_FS.as_ref(),
        None,
    )
    .await
    .expect("apply remaining cooperative insertion");
    assert_eq!(
        fs::read(&path).expect("resulting source"),
        "\u{feff}alpha\r\nalready\nfresh\r\nomega\r\n".as_bytes()
    );
    assert_eq!(stderr, Vec::<u8>::new());
}

#[tokio::test]
async fn cooperative_fuzzy_peer_insertion_preserves_actual_bytes() {
    let home = tempdir().expect("isolated shared-source fixture");
    let path = home.path().join("shared.txt");
    fs::write(&path, "\u{feff}alpha\r\nalready  \nomega\r\n").expect("existing peer bytes");
    let patch =
        wrap_patch("*** Update File: shared.txt\n@@\n \u{feff}alpha\n+already\n+fresh\n omega\n");
    let cwd = PathUri::from_host_native_path(home.path()).expect("native workspace");
    apply_patch(
        &patch,
        &cwd,
        &mut Vec::new(),
        &mut Vec::new(),
        LOCAL_FS.as_ref(),
        None,
    )
    .await
    .expect("apply remaining cooperative insertion");
    assert_eq!(
        fs::read(&path).expect("resulting source"),
        "\u{feff}alpha\r\nalready  \nfresh\r\nomega\r\n".as_bytes()
    );
}

#[tokio::test]
async fn cooperative_explicit_replacement_is_not_preserved_as_context() {
    let home = tempdir().expect("isolated shared-source fixture");
    let path = home.path().join("shared.txt");
    fs::write(&path, "alpha\r\npeer\nsame\nomega\r\n").expect("existing peer bytes");
    let patch =
        wrap_patch("*** Update File: shared.txt\n@@\n alpha\n+peer\n-same\n+same\n omega\n");
    let cwd = PathUri::from_host_native_path(home.path()).expect("native workspace");
    apply_patch(
        &patch,
        &cwd,
        &mut Vec::new(),
        &mut Vec::new(),
        LOCAL_FS.as_ref(),
        None,
    )
    .await
    .expect("apply explicit replacement beside peer insertion");
    assert_eq!(
        fs::read(&path).expect("resulting source"),
        "alpha\r\npeer\nsame\r\nomega\r\n".as_bytes()
    );
}

#[tokio::test]
async fn cooperative_ambiguous_context_refuses_without_rewriting_peer_bytes() {
    let home = tempdir().expect("isolated shared-source fixture");
    let path = home.path().join("shared.txt");
    let before = "same\r\nnew\nsame\r\n";
    fs::write(&path, before).expect("existing peer bytes");
    let patch = wrap_patch("*** Update File: shared.txt\n@@\n-same\n same\n+new\n+same\n");
    let cwd = PathUri::from_host_native_path(home.path()).expect("native workspace");
    let result = apply_patch(
        &patch,
        &cwd,
        &mut Vec::new(),
        &mut Vec::new(),
        LOCAL_FS.as_ref(),
        None,
    )
    .await;
    assert!(
        result.is_err(),
        "incompatible peer/context origins must refuse"
    );
    assert_eq!(fs::read(&path).expect("original source"), before.as_bytes());
}

#[tokio::test]
async fn cooperative_fuzzy_peer_insertions_preserve_original_bytes() {
    for (existing, requested) in [("already  ", "already"), ("already—", "already-")] {
        let home = tempdir().expect("isolated cooperative fixture");
        let path = home.path().join("shared.txt");
        fs::write(&path, format!("\u{feff}alpha\r\n{existing}\nomega\r\n"))
            .expect("existing peer bytes");
        let patch = wrap_patch(&format!(
            "*** Update File: shared.txt\n@@\n \u{feff}alpha\n+{requested}\n+fresh\n omega\n"
        ));
        apply_patch(
            &patch,
            &PathUri::from_host_native_path(home.path()).expect("native workspace"),
            &mut Vec::new(),
            &mut Vec::new(),
            LOCAL_FS.as_ref(),
            /*sandbox*/ None,
        )
        .await
        .expect("cooperative update");
        assert_eq!(
            fs::read(&path).expect("result"),
            format!("\u{feff}alpha\r\n{existing}\nfresh\r\nomega\r\n").as_bytes()
        );
    }
}

#[tokio::test]
async fn cooperative_explicit_same_text_replacement_keeps_changed_line_semantics() {
    let home = tempdir().expect("isolated cooperative fixture");
    let path = home.path().join("shared.txt");
    fs::write(&path, "\u{feff}alpha\r\npeer\nsame\nomega\r\n").expect("existing peer bytes");
    let patch = wrap_patch(
        "*** Update File: shared.txt\n@@\n \u{feff}alpha\n+peer\n-same\n+same\n omega\n",
    );
    apply_patch(
        &patch,
        &PathUri::from_host_native_path(home.path()).expect("native workspace"),
        &mut Vec::new(),
        &mut Vec::new(),
        LOCAL_FS.as_ref(),
        /*sandbox*/ None,
    )
    .await
    .expect("cooperative update");
    assert_eq!(
        fs::read(&path).expect("result"),
        "\u{feff}alpha\r\npeer\nsame\r\nomega\r\n".as_bytes()
    );
}
