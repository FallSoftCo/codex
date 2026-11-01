"""Windows' native AF_UNIX through asyncio IOCP, without a TCP intermediary.

CPython on Windows omits Unix-address conversion. Winsock supplies that small
platform boundary; established sockets use normal Python/aiohttp transports.
Authenticate the kernel-reported peer before sending any HTTP/RPC bytes.
"""
import asyncio
import ctypes
import os
from pathlib import Path
import select
import socket
from ctypes import wintypes as W

from aiohttp import BaseConnector


def current_sid():
    import win32api
    import win32con
    import win32security
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        return win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    finally:
        token.Close()


def private_path(path, *, directory=False):
    """Accept existing current-user-only objects; never repair an unsafe DACL."""
    import win32security
    path = Path(path)
    info = path.lstat()
    if info.st_file_attributes & 0x400 or (path.is_dir() != directory):
        raise PermissionError('Private Windows path has another type or is a reparse point')
    descriptor = win32security.GetNamedSecurityInfo(
        str(path), win32security.SE_FILE_OBJECT,
        win32security.OWNER_SECURITY_INFORMATION | win32security.DACL_SECURITY_INFORMATION,
    )
    user = current_sid()
    if descriptor.GetSecurityDescriptorOwner() != user:
        raise PermissionError('Private Windows path belongs to another user')
    acl = descriptor.GetSecurityDescriptorDacl()
    if acl is None or acl.GetAceCount() == 0:
        raise PermissionError('Private Windows DACL is absent or unusable')
    if directory and not descriptor.GetSecurityDescriptorControl()[0] & 0x1000:
        raise PermissionError('Private Windows directory must reject inherited access')
    for i in range(acl.GetAceCount()):
        ace = acl.GetAce(i)
        if ace[0][0] == win32security.ACCESS_DENIED_ACE_TYPE:
            continue
        if ace[0][0] != win32security.ACCESS_ALLOWED_ACE_TYPE or ace[2] != user:
            raise PermissionError('Private Windows path grants another identity access')
    return info


def create_private_directory(path):
    import pywintypes
    import win32file
    import win32security
    path = Path(path)
    if path.exists():
        private_path(path, directory=True)
        return
    user = win32security.ConvertSidToStringSid(current_sid())
    attributes = pywintypes.SECURITY_ATTRIBUTES()
    attributes.SECURITY_DESCRIPTOR = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        f'O:{user}D:P(A;OICI;FA;;;{user})', win32security.SDDL_REVISION_1,
    )
    win32file.CreateDirectory(str(path), attributes)
    private_path(path, directory=True)


def _authenticated_socket(path, binary, *, expected_pid=None):
    import win32api
    import win32con
    import win32file
    import win32security
    # Windows AF_UNIX rendezvous files are native reparse objects, not ordinary
    # private files. Pin and validate their containing directory, as codex-uds
    # does, and accept only the kernel's AF_UNIX tag (never junctions/symlinks).
    guard = win32file.CreateFile(
        str(Path(path).parent), 0x20000 | 0x80 | 1,
        win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
        None, win32con.OPEN_EXISTING, 0x02000000 | 0x00200000, None,
    )
    try:
        private_path(Path(path).parent, directory=True)
        info = Path(path).lstat()
        if info.st_reparse_tag != 0x80000023:
            raise PermissionError('Native endpoint is not a Windows AF_UNIX rendezvous')
        ws = ctypes.WinDLL('Ws2_32', use_last_error=True)
        handle_type = ctypes.c_size_t
        ws.WSASocketW.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_void_p, W.DWORD, W.DWORD]
        ws.WSASocketW.restype = handle_type
        ws.connect.argtypes = [handle_type, ctypes.c_void_p, ctypes.c_int]
        ws.connect.restype = ctypes.c_int
        ws.WSAIoctl.argtypes = [handle_type, W.DWORD, ctypes.c_void_p, W.DWORD, ctypes.c_void_p, W.DWORD, ctypes.POINTER(W.DWORD), ctypes.c_void_p, ctypes.c_void_p]
        ws.WSAIoctl.restype = ctypes.c_int
        ws.closesocket.argtypes = [handle_type]
        ws.WSAGetLastError.restype = ctypes.c_int
        class Address(ctypes.Structure):
            _fields_ = [('family', ctypes.c_ushort), ('path', ctypes.c_char * 108)]
        encoded = os.fsencode(path)
        if not encoded or len(encoded) >= 108:
            raise ValueError('Native Windows Unix-socket path exceeds its address boundary')
        raw = ws.WSASocketW(1, socket.SOCK_STREAM, 0, None, 0, 1)
        if raw == handle_type(-1).value:
            raise OSError(ws.WSAGetLastError(), 'Native socket creation failed')
        sock = None
        try:
            sock = socket.socket(1, socket.SOCK_STREAM, 0, fileno=raw)
            sock.setblocking(False)
            address = Address(1, encoded)
            if ws.connect(raw, ctypes.byref(address), ctypes.sizeof(address)) != 0:
                error = ws.WSAGetLastError()
                if error != 10035:
                    raise OSError(error, 'Native socket connection failed')
                if not select.select([], [sock], [sock], 3)[1]:
                    raise TimeoutError('Native socket connection timed out before sending data')
                error = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                if error:
                    raise OSError(error, 'Native socket connection failed')
            pid, returned = W.DWORD(), W.DWORD()
            if ws.WSAIoctl(raw, 0x58000100, None, 0, ctypes.byref(pid), ctypes.sizeof(pid), ctypes.byref(returned), None, None) != 0:
                raise OSError(ws.WSAGetLastError(), 'Native socket peer PID unavailable')
            if not pid.value or expected_pid is not None and pid.value != expected_pid:
                raise PermissionError('Native socket belongs to another process')
            process = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
            try:
                token = win32security.OpenProcessToken(process, win32con.TOKEN_QUERY)
                try:
                    if win32security.GetTokenInformation(token, win32security.TokenUser)[0] != current_sid():
                        raise PermissionError('Native socket belongs to another account')
                finally:
                    token.Close()
                kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                kernel.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, ctypes.POINTER(W.DWORD)]
                kernel.QueryFullProcessImageNameW.restype = W.BOOL
                image, size = ctypes.create_unicode_buffer(32768), W.DWORD(32768)
                if not kernel.QueryFullProcessImageNameW(int(process), 0, image, ctypes.byref(size)):
                    raise ctypes.WinError(ctypes.get_last_error())
                if not os.path.samefile(image.value, binary):
                    raise PermissionError('Native socket process image differs from the enrolled binary')
            finally:
                process.Close()
            return sock
        except BaseException:
            if sock is not None:
                sock.close()
            else:
                ws.closesocket(raw)
            raise
    finally:
        guard.Close()


class WindowsUnixConnector(BaseConnector):
    """One authenticated native socket per normal aiohttp connection."""
    def __init__(self, path, binary, **kwargs):
        super().__init__(**kwargs)
        self.path, self.binary = str(path), str(binary)

    async def _create_connection(self, req, traces, timeout):
        # Keep cancellation ownership until the bounded platform connect settles;
        # an abandoned thread must not leak a connected socket.
        task = asyncio.create_task(asyncio.to_thread(_authenticated_socket, self.path, self.binary))
        try:
            sock = await asyncio.shield(task)
        except BaseException:
            try:
                (await task).close()
            except Exception:
                pass
            raise
        try:
            _, protocol = await self._loop.create_connection(self._factory, sock=sock)
            return protocol
        except BaseException:
            sock.close()
            raise
