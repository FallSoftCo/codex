use std::io;

use codex_file_system::ExecutorFileSystem;
use codex_utils_absolute_path::AbsolutePathBuf;
use toml::Value as TomlValue;

const DEFAULT_PROJECT_ROOT_MARKERS: &[&str] = &[".git"];

/// Reads `project_root_markers` from a merged `config.toml` [toml::Value].
///
/// Invariants:
/// - If `project_root_markers` is not specified, returns `Ok(None)`.
/// - If `project_root_markers` is specified, returns `Ok(Some(markers))` where
///   `markers` is a `Vec<String>` (including `Ok(Some(Vec::new()))` for an
///   empty array, which indicates that root detection should be disabled).
/// - Returns an error if `project_root_markers` is specified but is not an
///   array of strings.
pub fn project_root_markers_from_config(config: &TomlValue) -> io::Result<Option<Vec<String>>> {
    let Some(table) = config.as_table() else {
        return Ok(None);
    };
    let Some(markers_value) = table.get("project_root_markers") else {
        return Ok(None);
    };
    let TomlValue::Array(entries) = markers_value else {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "project_root_markers must be an array of strings",
        ));
    };
    if entries.is_empty() {
        return Ok(Some(Vec::new()));
    }
    let mut markers = Vec::new();
    for entry in entries {
        let Some(marker) = entry.as_str() else {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "project_root_markers must be an array of strings",
            ));
        };
        markers.push(marker.to_string());
    }
    Ok(Some(markers))
}

pub fn default_project_root_markers() -> Vec<String> {
    DEFAULT_PROJECT_ROOT_MARKERS
        .iter()
        .map(ToString::to_string)
        .collect()
}

pub async fn project_root_marker_exists(
    fs: &dyn ExecutorFileSystem,
    marker_path: &AbsolutePathBuf,
    marker: &str,
) -> io::Result<bool> {
    let metadata = fs.get_metadata(marker_path, /*sandbox*/ None).await?;
    if marker != ".git" {
        return Ok(true);
    }

    if metadata.is_directory {
        let head_path = marker_path.join("HEAD");
        return match fs.get_metadata(&head_path, /*sandbox*/ None).await {
            Ok(head_metadata) => Ok(head_metadata.is_file),
            Err(err) if err.kind() == io::ErrorKind::NotFound => Ok(false),
            Err(err) => Err(err),
        };
    }

    if metadata.is_file {
        let contents = fs.read_file_text(marker_path, /*sandbox*/ None).await?;
        return Ok(contents.trim_start().starts_with("gitdir:"));
    }

    Ok(false)
}
