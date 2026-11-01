"""Small platform boundary for existing conversational receipts and ownership."""
import os
from pathlib import Path


def machine_identity():
    import hashlib
    if os.name == 'nt':
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Cryptography') as key:
            value, _ = winreg.QueryValueEx(key, 'MachineGuid')
        if not isinstance(value, str) or not value.strip():
            raise PermissionError('Original Windows machine identity unavailable')
        raw = value.strip().lower().encode()
    else:
        raw = Path('/etc/machine-id').read_bytes().strip()
    return hashlib.sha256(raw).hexdigest()


def exclusive_lock(stream):
    """Hold one process owner until the existing stream is closed."""
    if os.name == 'nt':
        import msvcrt
        stream.seek(0, os.SEEK_END)
        if not stream.tell():
            stream.write('\0')
            stream.flush()
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def durable_replace(source, destination):
    """Replace a flushed same-directory receipt, with platform durability."""
    source, destination = Path(source), Path(destination)
    if source.parent.resolve(strict=True) != destination.parent.resolve(strict=True):
        raise ValueError('Receipt replacement must stay in its original directory')
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        import win32security
        from .windows_ipc import current_sid, private_path
        # Elevated Windows tokens default new files to Administrators ownership.
        # The exclusively created, flushed temporary must instead retain the
        # current account's explicit ownership before it becomes a receipt.
        win32security.SetNamedSecurityInfo(
            str(source), win32security.SE_FILE_OBJECT,
            win32security.OWNER_SECURITY_INFORMATION, current_sid(), None, None, None,
        )
        private_path(source)
        move = ctypes.WinDLL('kernel32', use_last_error=True).MoveFileExW
        move.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
        move.restype = wintypes.BOOL
        # No cross-volume copy or delayed/reboot operation is permitted.
        if not move(str(source), str(destination), 0x1 | 0x8):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        source.replace(destination)
        descriptor = os.open(destination.parent, os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def private_file(path, *, administrator_allowed=False):
    if os.name == 'nt':
        from .windows_ipc import private_path
        return private_path(path)
    import stat
    info = Path(path).lstat()
    owners = (0, os.geteuid()) if administrator_allowed else (os.geteuid(),)
    forbidden = 0o022 if administrator_allowed else 0o077
    if not stat.S_ISREG(info.st_mode) or info.st_uid not in owners or info.st_mode & forbidden:
        raise PermissionError('Original private runtime file belongs to another owner or is writable')
    return info


def state_directory(path, *, parents=False, exist_ok=False):
    """Create conversational state with native current-user-only permissions.

    Windows Python's mkdir(mode=0700) adds SYSTEM/Administrators/OWNER RIGHTS
    ACEs rather than the enrolled SID-only ACL required for private receipts.
    Existing unsafe paths are rejected, never silently changed.
    """
    path = Path(path)
    if os.name != 'nt':
        path.mkdir(mode=0o700, parents=parents, exist_ok=exist_ok)
        return path
    from .windows_ipc import create_private_directory, private_path
    if path.exists():
        if not exist_ok:
            raise FileExistsError(str(path))
        private_path(path, directory=True)
        return path
    if parents and not path.parent.exists():
        state_directory(path.parent, parents=True, exist_ok=True)
    private_path(path.parent, directory=True)
    try:
        create_private_directory(path)
    except FileExistsError:
        if not exist_ok:
            raise
        private_path(path, directory=True)
    return path
