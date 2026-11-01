"""Own one Windows service child for its lifetime, without a polling supervisor.

Task Scheduler owns restart policy. The child is assigned to a kill-on-close Job
before its initial thread runs, so stopping the task cannot orphan a native
daemon or database. This launcher never retries a command or starts a model.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def serve(specification):
    import pywintypes
    import win32api
    import win32con
    import win32event
    import win32file
    import win32job
    import win32process
    import win32security
    from .journal import saved
    from .runtime_files import exclusive_lock, private_file
    from .windows_ipc import private_path

    private_file(specification)
    spec = json.loads(Path(specification).read_text())
    if (spec.get('schema') != 'lax-windows-process/v1'
            or spec.get('role') not in {'postgres', 'native'}):
        raise ValueError('Explicit enrolled Windows process role required')
    command = spec['command']
    if (not isinstance(command, list) or not command
            or not all(isinstance(v, str) and '\0' not in v for v in command)
            or not Path(command[0]).is_absolute() or not Path(command[0]).is_file()):
        raise ValueError('Pinned absolute executable and literal argv required')
    expected_name = {'postgres': 'postgres.exe', 'native': 'codex-app-server.exe'}[spec['role']]
    if Path(command[0]).name.lower() != expected_name:
        raise ValueError('Executable does not match the enrolled service role')
    memory = spec['memoryBytes']
    if type(memory) is not int or not 128 * 1024**2 <= memory <= 8 * 1024**3:
        raise ValueError('Bounded measured Windows Job memory required')
    state = Path(spec['state'])
    private_path(state, directory=True)
    cwd = Path(spec['cwd'])
    private_path(cwd, directory=True)
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        if win32security.GetTokenInformation(token, win32security.TokenElevation):
            raise PermissionError('Windows services require the limited desktop token')
        if win32security.GetTokenInformation(token, win32security.TokenSessionId) != 1:
            raise PermissionError('Windows services require the existing interactive Session 1')
    finally:
        token.Close()
    environment = dict(os.environ)
    for key in ('LAX_CANONICAL_NATIVE_CHANNEL', 'CODEX_CLI_PATH', 'CODEX_EXECUTABLE', 'CODEX_EXEC_SERVER_URL', 'OPENAI_API_KEY', 'CODEX_API_KEY'):
        environment.pop(key, None)
    environment.update(spec.get('environment', {}))
    import ctypes
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    with (state / 'process.lock').open('a') as lock:
        exclusive_lock(lock)
        job = win32job.CreateJobObject(None, '')
        limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        limits['BasicLimitInformation']['LimitFlags'] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | win32job.JOB_OBJECT_LIMIT_JOB_MEMORY
        limits['JobMemoryLimit'] = memory
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
        attributes = pywintypes.SECURITY_ATTRIBUTES()
        attributes.bInheritHandle = True
        output = win32file.CreateFile(str(state / 'process.log'), win32con.GENERIC_WRITE,
                                     win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
                                     attributes, win32con.OPEN_ALWAYS, 0, None)
        win32file.SetFilePointer(output, 0, win32con.FILE_END)
        null = win32file.CreateFile('NUL', win32con.GENERIC_READ,
                                   win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
                                   attributes, win32con.OPEN_EXISTING, 0, None)
        process = thread = None
        try:
            startup = win32process.STARTUPINFO()
            startup.dwFlags = win32process.STARTF_USESTDHANDLES
            startup.hStdInput, startup.hStdOutput, startup.hStdError = null, output, output
            process, thread, pid, _ = win32process.CreateProcess(
                command[0], subprocess.list2cmdline(command), None, None, True,
                win32process.CREATE_SUSPENDED | win32process.CREATE_NO_WINDOW | win32process.CREATE_UNICODE_ENVIRONMENT,
                environment, str(cwd), startup,
            )
            try:
                win32job.AssignProcessToJobObject(job, process)
                saved(state / 'process.json', {'role': spec['role'], 'pid': pid, 'state': 'starting', 'time': time.time()})
                win32process.ResumeThread(thread)
            except BaseException:
                win32process.TerminateProcess(process, 1)
                win32event.WaitForSingleObject(process, 10000)
                raise
            thread.Close(); thread = None
            win32event.WaitForSingleObject(process, win32event.INFINITE)
            status = win32process.GetExitCodeProcess(process)
            saved(state / 'process.json', {'role': spec['role'], 'pid': pid, 'state': 'stopped', 'exitCode': status, 'time': time.time()})
            return status
        finally:
            # Closing the job also stops descendants. Never close another task's job.
            job.Close()
            if thread is not None:
                thread.Close()
            if process is not None:
                process.Close()
            null.Close(); output.Close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', required=True, type=Path)
    args = parser.parse_args()
    sys.exit(serve(args.spec))


if __name__ == '__main__':
    main()
