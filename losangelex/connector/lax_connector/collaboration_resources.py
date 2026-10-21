"""Read the registered checkout identity without running its Git configuration."""
import os
import re
import stat
from pathlib import Path


def open_root(root, *, search_only=False):
    """Resolve every absolute root component without following directory links."""
    path = Path(root)
    if not path.is_absolute() or str(path) != str(root):
        raise ValueError("Literal absolute physical root required")
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_DIRECTORY
    # Traversing a search-only parent must not require directory enumeration.
    # Mutation/fsync consumers retain a readable root by default; artifact
    # readers request search-only handles without directory enumeration.
    search_flags = (flags & ~os.O_RDONLY) | getattr(os, "O_PATH", os.O_RDONLY)
    root_flags = search_flags if search_only else flags
    fd = os.open("/", root_flags if len(path.parts) == 1 else search_flags)
    try:
        for index, part in enumerate(path.parts[1:], 1):
            if part in ("", ".", ".."):
                raise ValueError("Canonical root components required")
            child = os.open(part, root_flags if index == len(path.parts) - 1 else search_flags, dir_fd=fd)
            os.close(fd)
            fd = child
        result, fd = fd, None
        return result
    finally:
        if fd is not None:
            os.close(fd)


def revision(root):
    """Read standard Git HEAD/ref metadata, including a registered linked checkout.

    The linked metadata must use Git's conventional .git/worktrees layout and
    point back to this exact checkout. No hooks, configuration or helpers run.
    Every metadata directory/file is opened without following links.
    """
    def read(base, relative):
        flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
        fd = open_root(str(base))
        try:
            parts = relative.split("/")
            if any(part in ("", ".", "..") for part in parts):
                raise ValueError("Literal Git metadata path required")
            for part in parts[:-1]:
                child = os.open(part, flags | os.O_DIRECTORY, dir_fd=fd)
                os.close(fd)
                fd = child
            child = os.open(parts[-1], flags, dir_fd=fd)
            try:
                before = os.fstat(child)
                if not stat.S_ISREG(before.st_mode) or before.st_size > 65536:
                    raise ValueError("Bounded regular Git revision metadata required")
                data = os.read(child, 65537)
                after = os.fstat(child)
                identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
                if identity(before) != identity(after) or len(data) != before.st_size:
                    raise ValueError("Git revision metadata changed during observation")
                return data.decode("ascii").strip()
            finally:
                os.close(child)
        finally:
            os.close(fd)
    checkout = Path(root)
    fd = open_root(root)
    try:
        git_type = os.stat(".git", dir_fd=fd, follow_symlinks=False).st_mode
    finally:
        os.close(fd)
    pointer = None
    if stat.S_ISDIR(git_type):
        metadata = common = checkout / ".git"
    elif stat.S_ISREG(git_type):
        pointer = read(checkout, ".git")
        if not pointer.startswith("gitdir: "):
            raise ValueError("Literal Git checkout metadata pointer required")
        target = pointer[len("gitdir: "):]
        metadata = Path(target)
        if (not metadata.is_absolute() or str(metadata) != target
                or metadata.parent.name != "worktrees" or metadata.parent.parent.name != ".git"):
            raise ValueError("Registered conventional linked Git metadata required")
        common = metadata.parent.parent
        if read(metadata, "gitdir") != str(checkout / ".git") or read(metadata, "commondir") != "../..":
            raise ValueError("Git linked metadata does not register this exact checkout")
    else:
        raise ValueError("Nonsymlink Git checkout metadata required")
    head = read(metadata, "HEAD")
    if head.startswith("ref: "):
        ref = head[5:]
        if not re.fullmatch(r"refs/[A-Za-z0-9_./-]+", ref) or any(p in ("", ".", "..") for p in ref.split("/")):
            raise ValueError("Literal repository ref required")
        # Git's private worktree namespaces stay local; ordinary refs are shared.
        ref_root = metadata if ref.startswith(("refs/worktree/", "refs/bisect/", "refs/rewritten/")) else common
        try:
            result = read(ref_root, ref)
        except FileNotFoundError:
            matches = [line.split(" ", 1)[0] for line in read(common, "packed-refs").splitlines() if line.endswith(" " + ref)]
            if len(matches) != 1:
                raise ValueError("Original repository ref is unavailable")
            result = matches[0]
        if read(metadata, "HEAD") != head:
            raise ValueError("Repository HEAD changed during observation")
    else:
        result = head
    if pointer is not None and (read(checkout, ".git") != pointer
            or read(metadata, "gitdir") != str(checkout / ".git") or read(metadata, "commondir") != "../.."):
        raise ValueError("Git checkout registration changed during observation")
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", result):
        raise ValueError("Exact original repository revision required")
    return result


def verify_native_path(root, relative, pid):
    """Compare opened host and actual native root views component by component."""
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    host = os.open("/", flags | os.O_DIRECTORY)
    # This is a kernel process-root link for the already authenticated native PID.
    try:
        native = os.open("/proc/" + str(int(pid)) + "/root", os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY)
    except OSError:
        os.close(host)
        raise
    # An empty relative path is the controller's root-only namespace observation.
    parts = [*Path(root["root"]).parts[1:], *(relative.split("/") if relative else [])]
    root_length = len(Path(root["root"]).parts) - 1
    try:
        for index, part in enumerate(parts):
            if part in ("", ".", ".."):
                raise ValueError("Literal native target components required")
            opened = []
            try:
                for parent in (host, native):
                    try:
                        opened.append(os.open(part, flags | (os.O_DIRECTORY if index < len(parts)-1 else 0), dir_fd=parent))
                    except FileNotFoundError:
                        opened.append(None)
                if opened == [None, None]:
                    return
                if None in opened:
                    raise ValueError("Native and bridge target presence differs")
                left, right = [os.fstat(fd) for fd in opened]
                if (left.st_dev,left.st_ino,stat.S_IFMT(left.st_mode)) != (right.st_dev,right.st_ino,stat.S_IFMT(right.st_mode)):
                    raise ValueError("Native PathUri resolves to another physical target")
                if index == root_length-1 and (left.st_dev,left.st_ino) != (root["device"],root["inode"]):
                    raise ValueError("Native registered root incarnation differs")
                os.close(host)
                os.close(native)
                host,native = opened
                opened = []
            finally:
                for fd in opened:
                    if fd is not None:
                        os.close(fd)
    finally:
        os.close(host)
        os.close(native)
