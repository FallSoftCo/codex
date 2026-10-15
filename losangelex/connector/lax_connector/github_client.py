"""Run GitHub CLI as the agent, using the installation's authorized account.

The provider reads its credential through sudo into the CLI child environment.
It preserves the caller's UID and working directory, and stores no token copy.
"""
import json
import os
import pathlib
import pwd
import subprocess
import sys
from uuid import UUID


def main():
    account = pwd.getpwuid(os.geteuid())
    parts = pathlib.Path(account.pw_dir).parts
    worker = (
        account.pw_name.startswith('hworker-')
        and len(parts) == 8
        and parts[:4] == ('/', 'var', 'lib', 'harness')
        and parts[5] == 'workers'
        and parts[7] == 'home'
    )
    env = dict(os.environ)
    own_config = pathlib.Path(env.get('GH_CONFIG_DIR') or (pathlib.Path(env.get('XDG_CONFIG_HOME') or (pathlib.Path(account.pw_dir) / '.config')) / 'gh'))
    informational = sys.argv[1:2] in (['--version'], ['help'], ['--help'], ['completion'])
    if worker and not informational and not (env.get('GH_TOKEN') or env.get('GITHUB_TOKEN') or (own_config / 'hosts.yml').exists()):
        authority = str(UUID(parts[4]))
        path = pathlib.Path('/etc/harness') / authority / 'github-provider.json'
        info = path.stat()
        if info.st_uid != 0 or info.st_mode & 0o022 or path.is_symlink():
            raise PermissionError('GitHub provider configuration is not installation-owned')
        provider = json.loads(path.read_text())
        owner = 'hglobal-' + authority.replace('-', '')[:12]
        if provider['authorityId'] != authority or provider['linuxAccount'] != owner:
            raise PermissionError('GitHub provider belongs to another installation')
        result = subprocess.run(
            ['/usr/bin/sudo', '-n', '-H', '-u', owner, '/usr/bin/gh', 'auth', 'token', '--hostname', 'github.com'],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=10, cwd='/',
        )
        if result.returncode or not result.stdout.strip():
            raise PermissionError('Installation GitHub authorization is unavailable')
        env['GH_TOKEN'] = result.stdout.decode().strip()
    os.execve('/usr/bin/gh', ['/usr/bin/gh', *sys.argv[1:]], env)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('GitHub authorization is unavailable; inspect the installation provider receipt.', file=sys.stderr)
        raise SystemExit(1)
