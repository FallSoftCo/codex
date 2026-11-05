"""Pinned unchanged shared native dependency of a connector-only release.

No image alias/hardlink, daemon restart, profile migration or native write. The
existing native process/package stays in its accepted root while SDK code gets
an independent immutable closure. Revalidate the dependency at every approval
step. Cutover requires the captured process incarnation; an already accepted
software closure permits a normal restart of that same service and state.
"""
import pwd
from pathlib import Path
from . import service_observer as observer
from .native_image_upgrade import _identity
from .service_restart import file_hash, file_identity
from .rpc_shared import host_manifest


def capture(config):
    value = host_manifest(config)
    path = Path(config['nativeServer']['manifest'])
    expected = Path('/var/lib/harness') / config['authorityId'] / 'native-hosts' / config['hostId'] / 'manifest.json'
    if path != expected:
        raise ValueError('Unchanged native dependency requires the canonical host declaration')
    unit = 'lax-native-' + config['authorityId'].replace('-', '')[:8] + '-' + config['hostId'].replace('-', '')[:8] + '.service'
    if value['unit'] != unit:
        raise ValueError('Original native service differs')
    props = observer.properties(unit)
    guardian = observer.process(int(props['MainPID']))
    uid = pwd.getpwnam(value['serviceUser']).pw_uid
    image = Path(config['binary']).stat()
    if (props['ActiveState'] != 'active' or props['User'] != value['serviceUser']
            or props['KillMode'] != 'control-group' or not guardian
            or guardian['uid'] != uid or guardian['controlGroup'] != props['ControlGroup']
            or (guardian['executableDevice'], guardian['executableInode']) != (image.st_dev, image.st_ino)):
        raise ValueError('Original shared native process identity differs')
    from .host_native import native_command
    command = (Path('/proc') / str(guardian['pid']) / 'cmdline').read_bytes().rstrip(b'\0').decode().split('\0')
    if command != native_command(value):
        raise ValueError('Original shared native startup arguments differ')
    state = Path(value['state']); info = state.lstat()
    if not state.is_dir() or state.is_symlink() or info.st_uid != uid:
        raise ValueError('Original native state ownership differs')
    return {'schema': 'lax-retained-native/v1', 'manifest': str(path),
            'manifestSha256': file_hash(path, 0)[0], 'unit': unit,
            'definitionSha256': observer.unit_definition(props),
            'binary': config['binary'], 'imageIdentity': file_identity(Path(config['binary'])),
            'imageSha256': file_hash(Path(config['binary']), 0)[0],
            'guardian': {k: guardian[k] for k in ('pid', 'start', 'uid', 'controlGroup', 'executableDevice', 'executableInode')},
            'state': str(state), 'stateIdentity': [info.st_dev, info.st_ino, info.st_uid],
            'modelsStarted': 0, 'nativeRestartRequired': False}


def pin_package(record, package):
    root = Path(package['packageRoot'])
    pins = []
    for asset in [*package['assets'].values(), {'path': str(root / 'codex-package.json')}]:
        path = Path(asset['path']); resolved = path.resolve(strict=True)
        digest, identity = file_hash(resolved, 0)
        if asset.get('sha256', digest) != digest:
            raise ValueError('Retained native package changed after its actual service-UID probe')
        pins.append({'path': str(path), 'resolved': str(resolved), 'identity': identity,
                     'linkIdentity': list(_identity(path.lstat())), 'sha256': digest})
    return {**record, 'packageRoot': str(root), 'assets': pins}


def verify(record, config, *, require_original_incarnation=True):
    if record.get('schema') != 'lax-retained-native/v1' or config['binary'] != record['binary']:
        raise ValueError('Reviewed unchanged native dependency differs')
    value = host_manifest(config)
    if config['nativeServer']['manifest'] != record['manifest']:
        raise ValueError('Original native declaration path changed')
    if file_hash(Path(record['manifest']), 0)[0] != record['manifestSha256']:
        raise ValueError('Original native declaration changed')
    props = observer.properties(record['unit'])
    if (props['ActiveState'] != 'active' or props['User'] != value['serviceUser']
            or props['KillMode'] != 'control-group'
            or (require_original_incarnation and int(props['MainPID']) != record['guardian']['pid'])
            or observer.unit_definition(props) != record['definitionSha256']):
        raise ValueError('Original retained native service incarnation changed')
    guardian = observer.process(int(props['MainPID']))
    keys = (record['guardian'].keys() if require_original_incarnation
            else set(record['guardian']) - {'pid', 'start'})
    if not guardian or any(guardian[k] != record['guardian'][k] for k in keys):
        raise ValueError('Original retained native process changed')
    same = (guardian['pid'] == record['guardian']['pid']
            and guardian['start'] == record['guardian']['start'])
    if not same:
        previous = observer.process(record['guardian']['pid'])
        if previous and previous['start'] == record['guardian']['start']:
            raise ValueError('Original native incarnation is still running; no overlapping successor allowed')
    if file_identity(Path(record['binary'])) != record['imageIdentity']:
        raise ValueError('Original retained native image changed')
    state = Path(record['state']); info = state.lstat()
    if state.is_symlink() or [info.st_dev, info.st_ino, info.st_uid] != record['stateIdentity']:
        raise ValueError('Original retained native state changed')
    from .host_native import native_command
    command = (Path('/proc') / str(guardian['pid']) / 'cmdline').read_bytes().rstrip(b'\0').decode().split('\0')
    if command != native_command(value):
        raise ValueError('Original retained native arguments changed')
    for asset in record.get('assets', []):
        path = Path(asset['path'])
        if (str(path.resolve(strict=True)) != asset['resolved']
                or list(_identity(path.lstat())) != asset['linkIdentity']
                or file_identity(Path(asset['resolved'])) != asset['identity']):
            raise ValueError('Original retained native package asset changed')

    return {'sameIncarnation': same, 'originalGuardian': record['guardian'],
            'currentGuardian': {k: guardian[k] for k in record['guardian']},
            'unchangedServiceSoftwareProfileAndState': True}
