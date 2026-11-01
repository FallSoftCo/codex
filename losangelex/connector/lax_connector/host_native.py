"""Install one native daemon per enrolled host/profile, using upstream transport.

No model polling, message relay, per-room process or automatic profile migration.
The native daemon itself is the service; there is no additional resident broker.
"""
import hashlib
import json
import os
import subprocess
from pathlib import Path
from uuid import UUID
from .journal import saved
from .native_package import runtime_command


def run(*args):
    # Bound installation/control-plane waits. A timeout retains the original
    # intent for reconciliation; it never creates a new daemon or retries start.
    return subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, check=True,
                          timeout=120 if args[:2] == ('systemctl', 'enable') else 30)


def location(authority, host):
    return Path('/var/lib/harness') / str(UUID(authority)) / 'native-hosts' / str(UUID(host))


def selection(spec, home):
    if spec.get('nativeHostServer') is not True:
        return None
    if spec.get('runtimeMode') != 'room-conversation':
        raise ValueError('Shared native host is only an explicit conversational installation')
    directory = location(spec['authorityId'], spec['hostId'])
    return {'manifest': str(directory / 'manifest.json')}


def profile_state(spec, home):
    adoption=adopted_state(spec,home)
    return Path(adoption['state']) if adoption else (location(spec['authorityId'], spec['hostId']) / 'state' if selection(spec, home) else home / 'state/native')


def unit_name(authority, host):
    return 'lax-native-' + UUID(authority).hex[:8] + '-' + UUID(host).hex[:8] + '.service'


def adopted_state(spec, home):
    adoption=spec.get('nativeStateAdoption')
    if adoption is None:return None
    if (not isinstance(adoption,dict) or set(adoption)!={'state','nativeThreadId','configurationSha256'}
            or adoption['state']!=str(home/'state/native')
            or not isinstance(adoption['nativeThreadId'],str) or not adoption['nativeThreadId']
            or not isinstance(adoption['configurationSha256'],str)
            or len(adoption['configurationSha256'])!=64
            or any(c not in '0123456789abcdef' for c in adoption['configurationSha256'])):
        raise ValueError('Exact original native state, thread and configuration proof required')
    return adoption


def manifest(spec, home, user):
    directory = location(spec['authorityId'], spec['hostId'])
    adoption=adopted_state(spec,home)
    return {'schema': 'lax-native-host/v1', 'runtimeMode': 'room-conversation',
            'authorityId': str(UUID(spec['authorityId'])), 'hostId': str(UUID(spec['hostId'])),
            'ownerAgentId': str(UUID(spec['agentId'])), 'serviceUser': user,
            'binary': spec['binary'], 'codexHome': str(home/'codex-home'), 'workspace': str(home/'work'),
            'state': adoption['state'] if adoption else str(directory/'state'),
            **({'adoptedNativeThreadId':adoption['nativeThreadId'], 'adoptedConfigurationSha256':adoption['configurationSha256']} if adoption else {}),
            'socket': str(Path('/var/lib/lax-native-sockets') / hashlib.sha256((str(UUID(spec['authorityId']))+'/'+str(UUID(spec['hostId']))).encode()).hexdigest()[:24] / 'native.sock'),
            'unit': unit_name(spec['authorityId'],spec['hostId'])}


def native_command(value):
    return runtime_command(value['binary']) + ['--listen','unix://'+value['socket'],
        '-c','sqlite_home='+json.dumps(value['state']+'/sqlite'),
        '-c','log_dir='+json.dumps(value['state']+'/logs'),'-c','check_for_update_on_startup=false']


def unit(value, memory_max=8*1024**3):
    if type(memory_max) is not int or memory_max < 256*1024**2:
        raise ValueError('Measured native host service memory bound required')
    workspace = str(value['workspace'])
    if not Path(workspace).is_absolute() or any(ch.isspace() for ch in workspace):
        raise ValueError('Installed native workspace requires an absolute UUID path without whitespace')
    # Installed UUID paths have no control characters. Quote complete systemd argv
    # words rather than interpreting a shell command or an inherited launcher.
    quote=lambda v:json.dumps(str(v))
    command=native_command(value)
    return '\n'.join(['[Unit]','Description=LAX shared native host '+value['hostId'],
        'After=network-online.target','StartLimitIntervalSec=120','StartLimitBurst=3',
        '[Service]','Type=simple','User='+value['serviceUser'],'WorkingDirectory='+workspace.replace('%','%%'),
        'Environment='+quote('CODEX_HOME='+value['codexHome']),
        'Environment=LAX_NATIVE_ENTERPRISE=1','Environment=LAX_NATIVE_RUNTIME_MODE=room-conversation',
        'UnsetEnvironment=LAX_CANONICAL_NATIVE_CHANNEL CODEX_CLI_PATH CODEX_EXECUTABLE CODEX_EXEC_SERVER_URL',
        'ExecStart='+' '.join(map(quote,command)),'Restart=on-failure','RestartSec=10',
        'UMask=0077','MemoryMax='+str(memory_max),'CPUWeight=100','KillMode=control-group',
        'TimeoutStopSec=60','[Install]','WantedBy=multi-user.target',''])


def ensure(spec, account, home):
    if os.geteuid()!=0 or selection(spec,home) is None:
        raise PermissionError('Explicit administrator host installation required')
    value=manifest(spec,home,account.pw_name);directory=location(spec['authorityId'],spec['hostId'])
    for path in (directory.parent,directory):
        if not path.exists():
            path.mkdir(mode=0o711);path.chmod(0o711)
    for path in (directory.parent,directory):
        if path.is_symlink() or path.stat().st_uid!=0 or path.stat().st_mode&0o022:
            raise PermissionError('Host registry must retain administrator ownership')
    file=directory/'manifest.json';receipt=directory/'installation.json'
    if file.exists():
        previous_manifest=json.loads(file.read_text())
        if os.path.samefile(previous_manifest['binary'],value['binary']):
            value['binary']=previous_manifest['binary']  # Same immutable image through an accepted hardlink alias.
        if file.is_symlink() or previous_manifest!=value:
            raise ValueError('Existing host/profile ownership differs; explicit migration required')
        if not receipt.exists():
            raise RuntimeError('Original native host installation requires reconciliation')
        previous=json.loads(receipt.read_text())
        # Never resurrect a deliberately stopped host daemon by running install.
        status=run('systemctl','show',value['unit'],'-p','ActiveState','--value').stdout.strip()
        return {**previous,'reconciled':True,'serviceActiveState':status,'serviceStarted':False}
    adoption=adopted_state(spec,home)
    if adoption:
        config_path=home/'connector.json'
        before=config_path.read_bytes();config=json.loads(before)
        state=Path(adoption['state'])
        if (hashlib.sha256(before).hexdigest()!=adoption['configurationSha256']
                or config.get('nativeThreadId')!=adoption['nativeThreadId']
                or config.get('nativeServer') is not None
                or config.get('codexHome')!=value['codexHome']
                or config.get('state')!=str(home/'state')
                or state.is_symlink() or not state.is_dir()
                or state.stat().st_uid!=account.pw_uid
                or not (state/'sqlite').is_dir()):
            raise ValueError('Original private native ownership changed; adoption refused')
    # Refuse an overlapping owner of the same native profile. No signal/restart.
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():continue
        try:
            entries=process.joinpath('environ').read_bytes().split(b'\0')
            if ('CODEX_HOME='+value['codexHome']).encode() in entries:
                command=process.joinpath('cmdline').read_bytes()
                if b'app-server' in command:
                    raise RuntimeError('Original profile is still in use; drain its owner before shared adoption')
        except (FileNotFoundError,PermissionError,ProcessLookupError):pass
    socket_parent=Path(value['socket']).parent
    if not socket_parent.parent.exists():
        socket_parent.parent.mkdir(mode=0o711);socket_parent.parent.chmod(0o711)
    for path in (Path(value['state']),socket_parent):
        if not path.exists():path.mkdir(mode=0o700)
        os.chown(path,account.pw_uid,account.pw_gid)
    saved(file,value);file.chmod(0o644)
    content=unit(value,spec.get('nativeHostMemoryMaxBytes',8*1024**3))
    target=Path('/etc/systemd/system')/value['unit']
    if target.exists():raise ValueError('Existing native unit requires original-owner inspection')
    target.write_text(content);target.chmod(0o644)
    saved(directory/'installation-intent.json',{'manifest':value,'unitSha256':hashlib.sha256(content.encode()).hexdigest(),'state':'prepared'})
    # enable reloads newly written units itself. Do not run a second host-wide
    # reload and repeat filesystem-generator work.
    run('systemctl','enable','--now',value['unit'])
    ready=run('systemctl','show',value['unit'],'-p','ActiveState','--value').stdout.strip()
    result={'schema':'lax-native-host-installation/v1','manifest':value,'unitSha256':hashlib.sha256(content.encode()).hexdigest(),'serviceActiveState':ready,'serviceStarted':True,'modelTurnsRequested':0}
    saved(receipt,result)
    if ready!='active':raise RuntimeError('Original native host did not become active; inspect it without replacing identity')
    return result
