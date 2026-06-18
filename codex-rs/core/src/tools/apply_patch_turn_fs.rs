use codex_exec_server::CopyOptions;
use codex_exec_server::CreateDirectoryOptions;
use codex_exec_server::ExecutorFileSystem;
use codex_exec_server::ExecutorFileSystemFuture;
use codex_exec_server::FileMetadata;
use codex_exec_server::FileSystemReadStream;
use codex_exec_server::FileSystemSandboxContext;
use codex_exec_server::ReadDirectoryEntry;
use codex_exec_server::RemoveOptions;
use codex_utils_path_uri::PathUri;
use std::collections::HashMap;
use std::path::PathBuf;
use tokio::io;
use tokio_util::bytes::Bytes;

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

impl ExecutorFileSystem for ApplyPatchTurnFileSystem<'_> {
    fn canonicalize<'a>(
        &'a self,
        path: &'a PathUri,
        sandbox: Option<&'a FileSystemSandboxContext>,
    ) -> ExecutorFileSystemFuture<'a, PathUri> {
        self.inner.canonicalize(path, sandbox)
    }

    fn read_file<'a>(
        &'a self,
        path: &'a PathUri,
        sandbox: Option<&'a FileSystemSandboxContext>,
    ) -> ExecutorFileSystemFuture<'a, Vec<u8>> {
        Box::pin(async move {
            match self.inner.read_file(path, sandbox).await {
                Ok(bytes) => Ok(bytes),
                Err(err) if err.kind() == io::ErrorKind::NotFound => {
                    let resurrected = path.to_abs_path().ok().and_then(|path| {
                        self.resurrected_deleted_files.get(path.as_path()).cloned()
                    });
                    resurrected.ok_or(err)
                }
                Err(err) => Err(err),
            }
        })
    }

    fn read_file_stream<'a>(
        &'a self,
        path: &'a PathUri,
        sandbox: Option<&'a FileSystemSandboxContext>,
    ) -> ExecutorFileSystemFuture<'a, FileSystemReadStream> {
        Box::pin(async move {
            match self.inner.read_file_stream(path, sandbox).await {
                Ok(stream) => Ok(stream),
                Err(err) if err.kind() == io::ErrorKind::NotFound => {
                    let resurrected = path.to_abs_path().ok().and_then(|path| {
                        self.resurrected_deleted_files.get(path.as_path()).cloned()
                    });
                    resurrected
                        .map(|bytes| {
                            let stream = futures::stream::iter([Ok(Bytes::from(bytes))]);
                            FileSystemReadStream::new(stream)
                        })
                        .ok_or(err)
                }
                Err(err) => Err(err),
            }
        })
    }

    fn write_file<'a>(
        &'a self,
        path: &'a PathUri,
        contents: Vec<u8>,
        sandbox: Option<&'a FileSystemSandboxContext>,
    ) -> ExecutorFileSystemFuture<'a, ()> {
        self.inner.write_file(path, contents, sandbox)
    }

    fn create_directory<'a>(
        &'a self,
        path: &'a PathUri,
        create_directory_options: CreateDirectoryOptions,
        sandbox: Option<&'a FileSystemSandboxContext>,
    ) -> ExecutorFileSystemFuture<'a, ()> {
        self.inner
            .create_directory(path, create_directory_options, sandbox)
    }

    fn get_metadata<'a>(
        &'a self,
        path: &'a PathUri,
        sandbox: Option<&'a FileSystemSandboxContext>,
    ) -> ExecutorFileSystemFuture<'a, FileMetadata> {
        self.inner.get_metadata(path, sandbox)
    }

    fn read_directory<'a>(
        &'a self,
        path: &'a PathUri,
        sandbox: Option<&'a FileSystemSandboxContext>,
    ) -> ExecutorFileSystemFuture<'a, Vec<ReadDirectoryEntry>> {
        self.inner.read_directory(path, sandbox)
    }

    fn remove<'a>(
        &'a self,
        path: &'a PathUri,
        remove_options: RemoveOptions,
        sandbox: Option<&'a FileSystemSandboxContext>,
    ) -> ExecutorFileSystemFuture<'a, ()> {
        self.inner.remove(path, remove_options, sandbox)
    }

    fn copy<'a>(
        &'a self,
        source_path: &'a PathUri,
        destination_path: &'a PathUri,
        copy_options: CopyOptions,
        sandbox: Option<&'a FileSystemSandboxContext>,
    ) -> ExecutorFileSystemFuture<'a, ()> {
        self.inner
            .copy(source_path, destination_path, copy_options, sandbox)
    }
}
