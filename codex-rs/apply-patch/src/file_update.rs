use crate::collaborative_replacements::augment_pattern_with_target_insertions;
use codex_exec_server::ExecutorFileSystem;
use codex_exec_server::FileSystemSandboxContext;
use codex_exec_server::ReadFileOptions;
use codex_utils_path_uri::PathUri;
use similar::TextDiff;

use crate::ApplyPatchError;
use crate::IoError;
use crate::UpdateFileChunk;
use crate::seek_sequence;
use crate::text_file::Replacement;
use crate::text_file::SourceFile;

#[cfg(test)]
#[path = "file_update_tests.rs"]
mod tests;

pub(crate) struct AppliedPatch {
    pub(crate) original_contents: String,
    pub(crate) new_contents: String,
}

/// Return *only* the new file contents (joined into a single `String`) after
/// applying the chunks to the file at `path`.
pub(crate) async fn derive_new_contents_from_chunks(
    path: &PathUri,
    chunks: &[UpdateFileChunk],
    fs: &dyn ExecutorFileSystem,
    follow_symlinks: bool,
    sandbox: Option<&FileSystemSandboxContext>,
) -> std::result::Result<AppliedPatch, ApplyPatchError> {
    let original_contents = fs
        .read_file_text(path, ReadFileOptions { follow_symlinks }, sandbox)
        .await
        .map_err(|err| {
            ApplyPatchError::IoError(IoError {
                context: format!(
                    "Failed to read file to update {}",
                    path.inferred_native_path_string()
                ),
                source: err,
            })
        })?;

    let path_text = path.inferred_native_path_string();
    let mut source_file = SourceFile::parse(&original_contents);
    let original_lines = source_file.line_texts();
    let replacements = compute_replacements(&original_lines, &path_text, chunks)?;
    source_file.apply_replacements(&replacements);
    let new_contents = source_file.into_contents();
    Ok(AppliedPatch {
        original_contents,
        new_contents,
    })
}

/// Compute a list of replacements needed to transform `original_lines` into the
/// new lines, given the patch `chunks`. Each replacement is returned as
/// `(start_index, old_len, new_lines)`.
fn compute_replacements(
    original_lines: &[String],
    path: &str,
    chunks: &[UpdateFileChunk],
) -> std::result::Result<Vec<Replacement>, ApplyPatchError> {
    let mut replacements: Vec<Replacement> = Vec::new();
    let mut line_index: usize = 0;

    for chunk in chunks {
        // If a chunk has a `change_context`, we use seek_sequence to find it, then
        // adjust our `line_index` to continue from there.
        if let Some(ctx_line) = &chunk.change_context {
            if let Some(idx) = seek_sequence::seek_sequence(
                original_lines,
                std::slice::from_ref(ctx_line),
                line_index,
                /*eof*/ false,
            ) {
                line_index = idx + 1;
            } else {
                return Err(ApplyPatchError::ComputeReplacements(format!(
                    "Failed to find context '{ctx_line}' in {path}"
                )));
            }
        }

        if chunk.old_lines.is_empty() {
            replacements.push((original_lines.len(), 0, chunk.new_lines.clone()));
            continue;
        }

        // Otherwise, try to match the existing lines in the file with the old lines
        // from the chunk. If found, schedule that region for replacement.
        // Attempt to locate the `old_lines` verbatim within the file.  In many
        // real‑world diffs the last element of `old_lines` is an *empty* string
        // representing the terminating newline of the region being replaced.
        // This sentinel is not present in `original_lines` because `SourceFile`
        // stores the terminator on the preceding line rather than as an extra
        // trailing element. If a direct search fails and the pattern ends with
        // an empty string, retry without that final element so modifications
        // touching the end‑of‑file can be located reliably.

        let mut pattern: &[String] = &chunk.old_lines;
        let mut found =
            seek_sequence::seek_sequence(original_lines, pattern, line_index, chunk.is_end_of_file);

        let mut new_slice: &[String] = &chunk.new_lines;

        if found.is_none() && pattern.last().is_some_and(String::is_empty) {
            // Retry without the trailing empty line which represents the final
            // newline in the file.
            pattern = &pattern[..pattern.len() - 1];
            if new_slice.last().is_some_and(String::is_empty) {
                new_slice = &new_slice[..new_slice.len() - 1];
            }

            found = seek_sequence::seek_sequence(
                original_lines,
                pattern,
                line_index,
                chunk.is_end_of_file,
            );
        }

        if let Some(start_idx) = found {
            append_context_replacements(
                &mut replacements,
                start_idx,
                pattern.len(),
                new_slice,
                &chunk.context_line_indices,
            );
            line_index = start_idx + pattern.len();
        } else if let Some(augmented) =
            augment_pattern_with_target_insertions(original_lines, pattern, new_slice, line_index)
        {
            let start_idx = seek_sequence::seek_sequence(
                original_lines,
                &augmented.lines,
                line_index,
                chunk.is_end_of_file,
            )
            .ok_or_else(|| {
                ApplyPatchError::ComputeReplacements(format!(
                    "Failed to align cooperative patch in {path}"
                ))
            })?;
            let mut preserved_context = chunk
                .context_line_indices
                .iter()
                .filter_map(|&(old, new)| {
                    augmented
                        .original_indices
                        .get(old)
                        .map(|&index| (index, new))
                })
                .chain(augmented.preserved_insertions.iter().copied())
                .collect::<Vec<_>>();
            // Preserve only parser context and positively identified existing
            // peer insertions. An explicit -same/+same remains a replacement.
            preserved_context.sort_unstable();
            if preserved_context
                .windows(2)
                .any(|pair| pair[0].0 >= pair[1].0 || pair[0].1 >= pair[1].1)
            {
                return Err(ApplyPatchError::ComputeReplacements(format!(
                    "Ambiguous cooperative patch context in {path}; reread and rebase"
                )));
            }
            append_context_replacements(
                &mut replacements,
                start_idx,
                augmented.lines.len(),
                new_slice,
                &preserved_context,
            );
            line_index = start_idx + augmented.lines.len();
        } else {
            return Err(ApplyPatchError::ComputeReplacements(format!(
                "Failed to find expected lines in {}:\n{}",
                path,
                chunk.old_lines.join("\n"),
            )));
        }
    }

    replacements.sort_by_key(|(index, _, _)| *index);

    Ok(replacements)
}

// Keep unchanged context lines and their original line terminators. This is
// also required when the fork fallback matches a partially applied insertion.
fn append_context_replacements(
    replacements: &mut Vec<Replacement>,
    start_idx: usize,
    matched_old_len: usize,
    new_slice: &[String],
    context_indices: &[(usize, usize)],
) {
    let mut old_start = 0;
    let mut new_start = 0;
    for &(old_context, new_context) in context_indices {
        if old_context >= matched_old_len || new_context >= new_slice.len() {
            break;
        }
        if old_start != old_context || new_start != new_context {
            replacements.push((
                start_idx + old_start,
                old_context - old_start,
                new_slice[new_start..new_context].to_vec(),
            ));
        }
        old_start = old_context + 1;
        new_start = new_context + 1;
    }
    if old_start != matched_old_len || new_start != new_slice.len() {
        replacements.push((
            start_idx + old_start,
            matched_old_len - old_start,
            new_slice[new_start..].to_vec(),
        ));
    }
}

/// Intended result of a file update for apply_patch.
#[derive(Debug, Eq, PartialEq)]
pub struct ApplyPatchFileUpdate {
    pub(crate) unified_diff: String,
    pub(crate) original_content: String,
    pub(crate) content: String,
}

pub async fn unified_diff_from_chunks(
    path: &PathUri,
    chunks: &[UpdateFileChunk],
    fs: &dyn ExecutorFileSystem,
    sandbox: Option<&FileSystemSandboxContext>,
) -> std::result::Result<ApplyPatchFileUpdate, ApplyPatchError> {
    unified_diff_from_chunks_with_context(path, chunks, /*context*/ 1, fs, sandbox).await
}

pub async fn unified_diff_from_chunks_with_context(
    path: &PathUri,
    chunks: &[UpdateFileChunk],
    context: usize,
    fs: &dyn ExecutorFileSystem,
    sandbox: Option<&FileSystemSandboxContext>,
) -> std::result::Result<ApplyPatchFileUpdate, ApplyPatchError> {
    let AppliedPatch {
        original_contents,
        new_contents,
    } = derive_new_contents_from_chunks(path, chunks, fs, /*follow_symlinks*/ true, sandbox)
        .await?;
    let text_diff = TextDiff::from_lines(&original_contents, &new_contents);
    let unified_diff = text_diff.unified_diff().context_radius(context).to_string();
    Ok(ApplyPatchFileUpdate {
        unified_diff,
        original_content: original_contents,
        content: new_contents,
    })
}
