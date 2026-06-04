use async_trait::async_trait;
use codex_exec_server::CopyOptions;
use codex_exec_server::CreateDirectoryOptions;
use codex_exec_server::ExecutorFileSystem;
use codex_exec_server::FileMetadata;
use codex_exec_server::FileSystemResult;
use codex_exec_server::FileSystemSandboxContext;
use codex_exec_server::ReadDirectoryEntry;
use codex_exec_server::RemoveOptions;
use codex_utils_absolute_path::AbsolutePathBuf;
use std::collections::HashMap;
use std::path::Path;
use std::path::PathBuf;
use tokio::io;

pub(crate) struct ApplyPatchTurnFileSystem<'a> {
    inner: &'a dyn ExecutorFileSystem,
    resurrected_deleted_files: HashMap<PathBuf, Vec<u8>>,
}

impl<'a> ApplyPatchTurnFileSystem<'a> {
    pub(crate) fn new(
        inner: &'a dyn ExecutorFileSystem,
        resurrected_deleted_files: HashMap<PathBuf, Vec<u8>>,
    ) -> Self {
        Self {
            inner,
            resurrected_deleted_files,
        }
    }
}

#[async_trait]
impl ExecutorFileSystem for ApplyPatchTurnFileSystem<'_> {
    async fn canonicalize(
        &self,
        path: &AbsolutePathBuf,
        sandbox: Option<&FileSystemSandboxContext>,
    ) -> FileSystemResult<AbsolutePathBuf> {
        self.inner.canonicalize(path, sandbox).await
    }

    async fn join(
        &self,
        base_path: &AbsolutePathBuf,
        path: &Path,
    ) -> FileSystemResult<AbsolutePathBuf> {
        self.inner.join(base_path, path).await
    }

    async fn parent(&self, path: &AbsolutePathBuf) -> FileSystemResult<Option<AbsolutePathBuf>> {
        self.inner.parent(path).await
    }

    async fn read_file(
        &self,
        path: &AbsolutePathBuf,
        sandbox: Option<&FileSystemSandboxContext>,
    ) -> FileSystemResult<Vec<u8>> {
        match self.inner.read_file(path, sandbox).await {
            Ok(bytes) => Ok(bytes),
            Err(err) if err.kind() == io::ErrorKind::NotFound => self
                .resurrected_deleted_files
                .get(path.as_path())
                .cloned()
                .ok_or(err),
            Err(err) => Err(err),
        }
    }

    async fn write_file(
        &self,
        path: &AbsolutePathBuf,
        contents: Vec<u8>,
        sandbox: Option<&FileSystemSandboxContext>,
    ) -> FileSystemResult<()> {
        self.inner.write_file(path, contents, sandbox).await
    }

    async fn create_directory(
        &self,
        path: &AbsolutePathBuf,
        create_directory_options: CreateDirectoryOptions,
        sandbox: Option<&FileSystemSandboxContext>,
    ) -> FileSystemResult<()> {
        self.inner
            .create_directory(path, create_directory_options, sandbox)
            .await
    }

    async fn get_metadata(
        &self,
        path: &AbsolutePathBuf,
        sandbox: Option<&FileSystemSandboxContext>,
    ) -> FileSystemResult<FileMetadata> {
        self.inner.get_metadata(path, sandbox).await
    }

    async fn read_directory(
        &self,
        path: &AbsolutePathBuf,
        sandbox: Option<&FileSystemSandboxContext>,
    ) -> FileSystemResult<Vec<ReadDirectoryEntry>> {
        self.inner.read_directory(path, sandbox).await
    }

    async fn remove(
        &self,
        path: &AbsolutePathBuf,
        remove_options: RemoveOptions,
        sandbox: Option<&FileSystemSandboxContext>,
    ) -> FileSystemResult<()> {
        self.inner.remove(path, remove_options, sandbox).await
    }

    async fn copy(
        &self,
        source_path: &AbsolutePathBuf,
        destination_path: &AbsolutePathBuf,
        copy_options: CopyOptions,
        sandbox: Option<&FileSystemSandboxContext>,
    ) -> FileSystemResult<()> {
        self.inner
            .copy(source_path, destination_path, copy_options, sandbox)
            .await
    }
}
