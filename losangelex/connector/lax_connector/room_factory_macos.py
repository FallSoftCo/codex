"""macOS account/agent-file boundary for ONE existing resident host runtime.

No OS service, native initialization, RPC, model input, process start/stop or
supervisor is implemented here. The common room factory owns initialization and
its existing host runtime owns logical session attachment/readiness. The public r03 wrapper delegates the existing initializer only inside the
original resident process; that supervisor owns session attachment/readiness.
"""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import stat
import ctypes
import sys
from uuid import UUID
MAX = 4 * 1024 * 1024

class Hold(RuntimeError):
    """A public, credential-free admission/inspection reason."""


def require(value, reason):
    if not value:
        raise Hold(reason)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def trusted(path, *, private=False, directory=False):
    p = Path(path)
    require(p.is_absolute() and p.resolve(strict=True) == p, 'Aliased local path is not admitted')
    for parent in (p, *p.parents):
        st = parent.lstat()
        require(not stat.S_ISLNK(st.st_mode) and st.st_uid in (0, os.geteuid())
                and not st.st_mode & 0o022, 'Untrusted local path writer')
    st = p.lstat()
    require(stat.S_ISDIR(st.st_mode) if directory else stat.S_ISREG(st.st_mode), 'Local path type differs')
    if private:
        require(st.st_uid == os.geteuid() and not st.st_mode & 0o077, 'Owner-private local path required')
    return p


def read(path, *, private=False, sha=None):
    p = trusted(path, private=private)
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        require(before.st_size <= MAX, 'Local metadata size exceeds bound')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(MAX + 1)
        after = os.fstat(fd)
        require(len(raw) <= MAX and (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), 'Local metadata changed during read')
        require(sha is None or digest(raw) == sha, 'Original local metadata pin differs')
        return raw
    finally:
        os.close(fd)


def load(path, **kwargs):
    return json.loads(read(path, **kwargs))


def program(pin):
    # Venv executables are intentional aliases of the accepted SAME Python.
    p = Path(pin['path']).resolve(strict=True)
    trusted(p)
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        st = os.fstat(fd)
        require(st.st_size <= 1024 ** 3, 'Program size exceeds bound')
        h = hashlib.sha256()
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            for part in iter(lambda: stream.read(1024 * 1024), b''):
                h.update(part)
        after = os.fstat(fd)
        require((st.st_dev, st.st_ino, st.st_mtime_ns, st.st_size)
                == (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_size)
                and h.hexdigest() == pin['sha256'], 'Accepted program pin differs')
    finally:
        os.close(fd)
    return str(p)


def sync(directory):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def save_once(path, value):
    return save_raw_once(path, wire(value) + b'\n')


def save_raw_once(path, raw):
    p = Path(path)
    if p.exists() or p.is_symlink():
        require(read(p, private=True) == raw, 'Original local receipt differs; reconcile it')
        return
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb', closefd=False) as f:
            f.write(raw)
            f.flush()
            os.fsync(fd)
    finally:
        os.close(fd)
    sync(p.parent)


def mkdir(path):
    p = Path(path)
    trusted(p.parent, directory=True)
    if not p.exists():
        p.mkdir(mode=0o700)
        sync(p.parent)
    return trusted(p, private=True, directory=True)


def ipc(manifest, pin):
    p = Path(manifest['socket'])
    uid = os.geteuid()
    def ident(path):
        st = Path(path).lstat()
        return {'device': st.st_dev, 'inode': st.st_ino, 'uid': st.st_uid,
                'mode': stat.S_IMODE(st.st_mode), 'type': stat.S_IFMT(st.st_mode)}
    if p.is_symlink():
        trusted(p.parent, private=True, directory=True)
        require(isinstance(pin, dict) and pin.get('schema') == 'lax-native-ipc-alias/v1',
                'Original native IPC alias pin required')
        target = Path(pin['targetPath'])
        require(ident(p) == pin['alias'] and os.readlink(p) == pin['linkText']
                and p.resolve(strict=True) == target and target.resolve(strict=True) == target,
                'Original native IPC alias changed')
        require(target.parent.parent == Path('/private/tmp'), 'Unsupported original native IPC target')
        for parent in (target.parent, *target.parent.parents):
            st = parent.lstat()
            require(stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode), 'Native IPC parent type differs')
            if parent == Path('/private/tmp'):
                require(st.st_uid == 0 and stat.S_IMODE(st.st_mode) == 0o1777, 'Native system temp is not root sticky')
            else:
                require(st.st_uid in (0, uid) and not st.st_mode & 0o022, 'Native IPC parent writer differs')
        require(ident(target) == pin['target'] and ident(target.parent) == pin['targetParent'],
                'Original native IPC target changed')
        p = target
    else:
        trusted(p.parent, private=True, directory=True)
    st = p.lstat()
    require(stat.S_ISSOCK(st.st_mode) and st.st_uid == uid and not st.st_mode & 0o077,
            'Original private native socket is unavailable')
    parent = p.parent.stat()
    require(parent.st_uid == uid and not parent.st_mode & 0o077, 'Original native socket parent is not private')
    return ident(p)


def process_identity(pid):
    """Read Darwin libproc in-process; no ps child, manager call or signal.

    proc_bsdinfo layout/PROC_PIDTBSDINFO=3 are from the installed Apple SDK
    sys/proc_info.h; MAXCOMLEN=16, SSTOP=4/SZOMB=5 from sys/param.h/proc.h.
    birth is kernel seconds.microseconds, not PID alone or a sampled wall clock.
    """
    require(sys.platform == 'darwin' and type(pid) is int and pid > 0,
            'Original Darwin process pin is invalid')
    class BSDInfo(ctypes.Structure):
        _fields_ = [('prefix', ctypes.c_uint32 * 12), ('comm', ctypes.c_char * 16),
                    ('name', ctypes.c_char * 32), ('suffix', ctypes.c_uint32 * 6),
                    ('startSec', ctypes.c_uint64), ('startUsec', ctypes.c_uint64)]
    require(ctypes.sizeof(BSDInfo) == 136, 'Darwin process ABI size differs')
    lib = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
    lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    lib.proc_pidinfo.restype = ctypes.c_int
    lib.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    lib.proc_pidpath.restype = ctypes.c_int
    before, after = BSDInfo(), BSDInfo()
    require(lib.proc_pidinfo(pid, 3, 0, ctypes.byref(before), 136) == 136
            and before.prefix[3] == pid and before.prefix[1] not in (0, 4, 5),
            'Original parent/native process is unavailable or stopped')
    path = ctypes.create_string_buffer(4096)
    count = lib.proc_pidpath(pid, path, 4096)
    require(0 < count < 4096 and path.value, 'Original process image is unavailable')
    require(lib.proc_pidinfo(pid, 3, 0, ctypes.byref(after), 136) == 136
            and (before.prefix[3], before.prefix[5], before.startSec, before.startUsec)
            == (after.prefix[3], after.prefix[5], after.startSec, after.startUsec)
            and after.prefix[1] not in (0, 4, 5), 'Process incarnation changed during read')
    return {'pid': pid, 'uid': int(before.prefix[5]),
            'birth': str(before.startSec) + '.' + str(before.startUsec).zfill(6),
            'image': path.value.decode('utf-8')}


def pin_file(selection, *, private=True):
    return read(selection['path'], private=private, sha=selection['sha256'])


def identity(path):
    st = Path(path).lstat()
    return {'device': st.st_dev, 'inode': st.st_ino, 'uid': st.st_uid,
            'mode': stat.S_IMODE(st.st_mode), 'type': stat.S_IFMT(st.st_mode)}


def overlap(a, b):
    a, b = Path(a), Path(b)
    return a == b or a in b.parents or b in a.parents


class MacAgentFiles:
    """Protected per-agent files under one separately approved host agentRoot.

    account_policy is a protected, hash-pinned owner deployment receipt, never
    synthesized from an agent config flag. This helper cannot create that policy
    or agentRoot. Common public spec/session schema is owned by the common layer.
    """
    def __init__(self, account_policy, expected_policy_sha256, *, process_reader=None,
                 native_identity=None, parent_identity=None):
        self.policy_path = Path(account_policy)
        self.policy_sha = expected_policy_sha256
        self.process_reader = process_reader or process_identity
        self.policy = json.loads(read(self.policy_path, private=True, sha=self.policy_sha))
        self.native_socket = None
        self.native_pin = native_identity or self.policy.get('nativeProcess')
        self.parent_pin = parent_identity or self.policy.get('parentProcess')

    def validate_parent(self, config):
        p = self.policy
        account = pwd.getpwuid(os.geteuid())
        require(p.get('schema') == 'lax-macos-room-account/v1'
                and p.get('uid') == os.geteuid() and p.get('user') == account.pw_name
                and p.get('serviceHome') == account.pw_dir,
                'Original host-owned account policy differs')
        require(p.get('initialPermissions') == {'sandbox': 'danger-full-access', 'approvalPolicy': 'never'},
                'Original host policy does not permit the declared initial room access')
        manifest = json.loads(pin_file(p['nativeManifest']))
        require(manifest.get('schema') == 'lax-native-host/v1'
                and manifest.get('runtimeMode') == 'room-conversation'
                and manifest.get('platform') == 'darwin'
                and (manifest.get('authorityId'), manifest.get('hostId'), manifest.get('ownerAgentId'), manifest.get('serviceUser'))
                == (p['authorityId'], p['hostId'], p['ownerAgentId'], account.pw_name),
                'Original shared native descriptor scope differs')
        parent = json.loads(pin_file(p['parentConfig']))
        enrollment = json.loads(pin_file(p['ownerReceipt']))
        require((parent.get('authorityId'), parent.get('hostId'), parent.get('agentId'))
                == (p['authorityId'], p['hostId'], p['ownerAgentId'])
                and (enrollment.get('agentId'), enrollment.get('nodeId'), enrollment.get('sharedNativeService'))
                == (p['ownerAgentId'], p['hostId'], manifest['unit']),
                'Original resident parent enrollment/config differs')
        require(parent.get('nativeThreadId') == enrollment.get('nativeThreadId')
                and isinstance(parent.get('nativeThreadId'), str) and parent['nativeThreadId'],
                'Original parent thread binding differs')
        require(parent.get('codexHome') == manifest['codexHome']
                and parent.get('nativeServer') == {'manifest': p['nativeManifest']['path']},
                'Original parent native profile/selection differs')
        root = trusted(p['agentRoot'], private=True, directory=True)
        require(identity(root) == p['agentRootIdentity'], 'Original approved agent root incarnation differs')
        for original in (manifest['codexHome'], manifest['state'], parent['state'], parent.get('workspace', manifest['workspace'])):
            require(not overlap(root, original), 'Agent root overlaps original profile/state/workspace')
        require(config.get('nativeServer') == parent['nativeServer']
                and (config.get('authorityId'), config.get('hostId')) == (p['authorityId'], p['hostId'])
                and config.get('agentId') != p['ownerAgentId']
                and config.get('codexHome') == manifest['codexHome']
                and config.get('binary') == manifest['binary'] == parent['binary'],
                'New logical agent cannot replace the parent profile or daemon')
        require(config.get('runtimeMode') == 'room-conversation'
                and config.get('sandbox') == 'danger-full-access' and config.get('approvalPolicy') == 'never'
                and not any(k in config for k in ('nativeThreadId', 'nativeStateAdoption', 'homes', 'tokens', 'installedPurposeRuntime')),
                'Fresh declared initial room configuration required')
        require(all(isinstance(config.get(k), str) and config[k].strip() for k in
                ('nativeName', 'instructions', 'model', 'effort', 'token', 'hollywoodUrl')),
                'Explicit initial room role/model/credential is incomplete')
        from .room_tools import TOOLS
        require(config.get('conversationDynamicTools') == TOOLS, 'Reviewed room tool declarations differ')
        trusted(manifest['codexHome'], private=True, directory=True)
        trusted(Path(manifest['codexHome']) / 'auth.json', private=True)  # metadata only; never copied/read
        for expected in (self.native_pin, self.parent_pin):
            require(isinstance(expected, dict) and set(expected) == {'pid', 'uid', 'birth', 'image'} and expected['uid'] == os.geteuid()
                    and self.process_reader(expected['pid']) == expected,
                    'Original shared native/parent incarnation changed or is stopped')
        require(Path(self.native_pin['image']).resolve(strict=True) == Path(manifest['binary']).resolve(strict=True),
                'Original native image differs')
        require(program(p['interpreter']) == str(Path(self.parent_pin['image']).resolve(strict=True)),
                'Original parent interpreter image differs')
        require(p['binary']['path'] == manifest['binary'], 'Accepted shared native binary path differs')
        program(p['binary'])
        socket = ipc(manifest, p.get('nativeSocketPin'))
        if self.native_socket is not None:
            require(socket == self.native_socket, 'Original native socket incarnation changed')
        self.native_socket = socket
        require(read(self.policy_path, private=True, sha=self.policy_sha), 'Original account policy unavailable')
        return {'authorityId': p['authorityId'], 'hostId': p['hostId'], 'uid': p['uid'],
                'ownerAgentId': p['ownerAgentId'], 'parentNativeThreadId': parent['nativeThreadId'],
                'nativeManifestSha256': p['nativeManifest']['sha256'], 'accountPolicySha256': self.policy_sha,
                'parentProcess': self.parent_pin, 'nativeProcess': self.native_pin,
                'sharedAppServer': True, 'parentAccountValidated': True,
                'logicalSessionReadiness': 'not_observed_by_platform_file_helper'}

    def manifest_state(self, config):
        self.validate_parent(config)
        return json.loads(pin_file(self.policy['nativeManifest']))['state']

    @contextlib.contextmanager
    def lock(self, scope, operation_dir, expected_spec_sha256, *, inspect):
        root = trusted(self.policy['agentRoot'], private=True, directory=True)
        operation = trusted(operation_dir, private=True, directory=True)
        for key in ('authorityId', 'originRoomId', 'agentId', 'hostId', 'nodeId'):
            require(str(UUID(scope[key])) == scope[key], 'Canonical original room identity required')
        require(scope['authorityId'] == self.policy['authorityId']
                and scope['hostId'] == scope['nodeId'] == self.policy['hostId']
                and scope['agentId'] != self.policy['ownerAgentId']
                and isinstance(scope['operationId'], str) and 0 < len(scope['operationId']) <= 200,
                'Original logical room/account scope differs')
        binding = {key: scope[key] for key in ('operationId', 'authorityId', 'originRoomId', 'agentId', 'hostId', 'nodeId')}
        binding.update(specSha256=expected_spec_sha256, operationDirectory=str(operation),
                       accountPolicySha256=self.policy_sha)
        lock_path = root / (scope['agentId'] + '.lock')
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                    and not info.st_mode & 0o077, 'Component lock is not owner-private')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            claim = root / (scope['agentId'] + '.claim.json')
            home = root / scope['agentId']
            if inspect:
                require(load(claim, private=True) == binding, 'Original logical room claim differs')
            else:
                require(claim.exists() or not home.exists(), 'Existing logical home has no original enrollment')
                save_once(claim, binding)
            yield root, home, operation, binding
        finally:
            os.close(fd)

    def verify_input(self, config, scope, *, raw_spec, expected_spec_sha256):
        require(digest(raw_spec) == expected_spec_sha256, 'Original raw spec SHA differs')
        original = json.loads(raw_spec)
        require(all(original.get(k) == scope[k] for k in
                ('operationId', 'authorityId', 'originRoomId', 'agentId', 'hostId', 'nodeId'))
                and original.get('connectorConfig') == config,
                'Original raw spec scope/config differs')
        require(config.get('rooms') == [{'roomId': scope['originRoomId'], 'after': 0}],
                'Immutable origin room configuration differs')
        return self.validate_parent(config)

    def materialize_locked(self, config, home, operation, binding, parent, *, inspect):
        """Caller holds original component lock; no init or session attach here."""
        self.validate_parent(config)
        require(config.get('state') == str(home / 'state') and config.get('workspace') == str(home / 'work'),
                'Distinct logical state/workspace must remain in the approved agent root')
        name = home / 'initial-config.private.json'
        receipt = operation / 'platform-files.json'
        expected = {'schema': 'lax-macos-room-files/v1', 'binding': binding,
                    'initialConfigPath': str(name), 'initialConfigSha256': digest(wire(config) + b'\n'),
                    'state': config['state'], 'workspace': config['workspace'],
                    'parentEvidence': parent, 'osServicesCreated': 0, 'nativeThreadsCreated': 0,
                    'modelTurnsRequested': 0, 'sessionAttachmentRequired': True}
        if inspect:
            for directory in (home, home / 'state', home / 'work'):
                trusted(directory, private=True, directory=True)
            require(read(name, private=True) == wire(config) + b'\n' and load(receipt, private=True) == expected,
                    'Original logical room files/receipt differ')
        else:
            mkdir(home)
            mkdir(home / 'state')
            mkdir(home / 'work')
            save_once(name, config)
            self.validate_parent(config)
            save_once(receipt, expected)
        self.validate_parent(config)
        return expected

    def prepare_files(self, config, scope, operation_dir, *, raw_spec, expected_spec_sha256, inspect=False):
        """Internal file-only prepare/inspect; no native/session operations."""
        parent = self.verify_input(config, scope, raw_spec=raw_spec, expected_spec_sha256=expected_spec_sha256)
        with self.lock(scope, operation_dir, expected_spec_sha256, inspect=inspect) as (_, home, operation, binding):
            return self.materialize_locked(config, home, operation, binding, parent, inspect=inspect)


def guides(config, approved):
    require(isinstance(approved, list) and 0 < len(approved) <= 32, 'Approved operating guide pins required')
    from .room_participation import resume_overrides
    overrides, _ = resume_overrides(config)
    require(bool(overrides), 'Fresh explicit resume role instructions required')
    initial, resume = config['instructions'], '\n'.join(overrides.values())
    for pin in approved:
        require(set(pin) == {'path', 'sha256'}, 'Exact operating guide pin required')
        read(pin['path'], sha=pin['sha256'])
        require(all(pin[k] in initial and pin[k] in resume for k in ('path', 'sha256')),
                'Approved host guide must be bound to initial and resume role instructions')


def output(spec, state, *, reason=None, thread=None, config=None, parent=None):
    result = {'schema': 'lax-room-origin-host-result/v1',
              **{k: spec[k] for k in ('operationId', 'authorityId', 'originRoomId', 'agentId', 'hostId')},
              'state': state, 'sharedAppServer': True,
              'appServerManifestSha256': spec['nativeHostManifestSha256'], 'modelTurnsRequested': 0}
    if reason:
        result['reason'] = reason
    if parent:
        result.update(parentRuntimePid=parent['parentProcess']['pid'], nativeIdentity=parent['nativeProcess'])
    if thread:
        result['nativeThreadId'] = thread
    if config:
        result.update(sessionConfigPath=str(config), sessionConfigSha256=digest(read(config, private=True)),
                      sessionAttachmentRequired=True, canonicalObservationRequired=True)
    return result


async def provision_local(spec_path: Path, operation_dir: Path, *, inspect: bool,
                          expected_spec_sha256: str) -> dict:
    """Pinned resident contract r03: bootstrap on original daemon, no OS manager.

    ready means bootstrap/local session config accepted, NOT supervisor attached
    or canonical room ready. The common owner must attach in its existing process
    and wait for a fresh matching native observation. Paths in this LOCAL result
    MUST be stripped from canonical/public receipts by that common owner.
    """
    spec, helper, parent, operation = None, None, None, None
    try:
        raw = read(spec_path, private=True, sha=expected_spec_sha256)
        candidate = json.loads(raw)
        require(candidate.get('schema') == 'lax-room-origin-local-spec/v1', 'Original local room spec schema differs')
        for k in ('authorityId', 'originRoomId', 'agentId', 'hostId', 'nodeId'):
            require(str(UUID(candidate[k])) == candidate[k], 'Canonical original room identity required')
        require(isinstance(candidate.get('operationId'), str) and 0 < len(candidate['operationId']) <= 200,
                'Stable original operation required')
        spec = candidate
        operation = trusted(operation_dir, private=True, directory=True)
        selected = spec['parentRuntime']['roomOriginPolicy']
        require(set(selected) == {'path', 'sha256'}, 'Exact original host account policy selection required')
        helper = MacAgentFiles(selected['path'], selected['sha256'],
                               native_identity=spec['nativeIdentity'],
                               parent_identity=spec['parentRuntime'].get('identity'))
        require(spec['parentRuntime']['agentId'] == helper.policy['ownerAgentId']
                and spec['nativeHostManifestSha256'] == helper.policy['nativeManifest']['sha256']
                and spec['nativeIdentity'] == helper.native_pin,
                'Original parent/native selection differs')
        require(helper.parent_pin and helper.parent_pin['pid'] == os.getpid(),
                'Logical room bootstrap must run inside the original resident parent process')
        config = spec['connectorConfig']
        parent = helper.verify_input(config, spec, raw_spec=raw, expected_spec_sha256=expected_spec_sha256)
        guides(config, spec['operatingInstructions'])
        with helper.lock(spec, operation, expected_spec_sha256, inspect=inspect) as (_, home, operation, binding):
            require(read(spec_path, private=True) == raw, 'Original private spec changed')
            prepared = helper.materialize_locked(config, home, operation, binding, parent, inspect=inspect)
            intent = operation / 'native-initialization-intent.json'
            context = home / 'state/native-context.json'
            prior = load(context, private=True) if context.exists() else None
            if prior:
                safe = prior.get('state') in ('connecting', 'transport-unavailable') and prior.get('threadStartAttempted') is False
                require(prior.get('state') == 'ready' or safe,
                        'Original native initialization is uncertain; no replacement or replay')
                # Keep exact original phase bytes before a proven not-sent retry.
                if safe:
                    save_raw_once(operation / ('unstarted-before-' + digest(read(context, private=True)) + '.json'), read(context, private=True))
            elif inspect or intent.exists():
                raise Hold('Original initialization dispatch has no positive unstarted proof; inspect original receipts')
            save_once(intent, {'schema': 'lax-room-origin-native-intent/v1', 'binding': binding,
                              'initialConfigSha256': prepared['initialConfigSha256'],
                              'nativeIdentity': spec['nativeIdentity'], 'parentRuntimePid': parent['parentProcess']['pid']})
            from .room_bootstrap import initialize
            initialized = await initialize(config)
            require(initialized.get('state') == 'ready' and initialized.get('nativePermissionsPersisted') is True
                    and initialized.get('modelTurnsRequested') == 0,
                    'Original native bootstrap is not ready')
            expected_binding = {'authorityId': spec['authorityId'], 'agentId': spec['agentId'],
                                'codexHome': config['codexHome'], 'nativeState': helper.manifest_state(config)}
            require(initialized.get('binding') == expected_binding, 'Original bootstrap binding differs')
            thread = initialized.get('nativeThreadId', '')
            require(str(UUID(thread)) == thread and thread != parent['parentNativeThreadId'],
                    'Original new room thread must differ from parent thread')
            from .room_permissions import verified, requested
            verified(initialized['effectivePermissions'], requested(config))
            require(load(context, private=True) == initialized, 'Original native bootstrap receipt differs')
            helper.validate_parent(config)
            guides(config, spec['operatingInstructions'])
            require(read(spec_path, private=True) == raw, 'Original private spec changed')
            save_once(operation / 'native-initialization-accepted.json', initialized)
            session = home / 'session-config.private.json'
            save_once(session, {**config, 'nativeThreadId': thread})
            helper.validate_parent(config)
            return output(spec, 'ready', thread=thread, config=session, parent=parent)
    except Exception as error:
        if spec is None:
            raise Hold('Original protected macOS room specification could not be verified') from None
        reason = str(error) if isinstance(error, Hold) else 'Original resident bootstrap/file evidence could not be confirmed'
        uncertain = bool(operation and (operation / 'native-initialization-intent.json').exists())
        return output(spec, 'unknown' if uncertain else 'blocked', reason=reason, parent=parent)
