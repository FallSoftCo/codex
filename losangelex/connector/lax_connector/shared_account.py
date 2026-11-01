"""Explicit attachment to one existing unrestricted native account boundary.

Logical agents are not mutually isolated OS principals in this mode. Protected
enrollment evidence binds their separate homes to the original service account;
the original daemon, profile, credentials and native peer checks do not change.
"""
import hashlib
import json
import os
import pwd
import stat
from pathlib import Path
from uuid import UUID

HARNESS = Path('/var/lib/harness')
TRUST = 'same-account-unrestricted/v1'


def worker_home(spec):
    return HARNESS / str(UUID(spec['authorityId'])) / 'workers' / str(UUID(spec['agentId'])) / 'home'


def declaration(path):
    from .service_restart import file_hash
    digest, _ = file_hash(path, 0)
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('Shared account declaration changed during read')
    return json.loads(raw), digest


def request(config):
    """Unchanged room-tool arguments use a separately approved factory policy."""
    from .rpc_shared import host_manifest
    if config.get('sandbox') != 'danger-full-access':
        raise PermissionError('Restricted or unrelated profiles cannot share a native account')
    value = host_manifest(config)
    path = Path(config['nativeServer']['manifest'])
    from .host_native import location
    if path != location(config['authorityId'], config['hostId']) / 'manifest.json':
        raise ValueError('Canonical existing host manifest required')
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise PermissionError('Original host declaration is not protected')
    policy=path.with_name('shared-account-policy.json')
    try:metadata=policy.lstat()
    except FileNotFoundError:
        raise PermissionError('Explicit root-approved same-account factory policy required; no private-profile fallback') from None
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid!=0 or metadata.st_mode&0o022:
        raise PermissionError('Shared account factory policy is not protected')
    for parent in policy.parents:
        info=parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:
            raise PermissionError('Shared account policy ancestry is not protected')
    approved=json.loads(policy.read_text())
    if (approved.get('schema')!='lax-native-account-sharing/v1' or approved.get('trustBoundary')!=TRUST
            or approved.get('identity')!=factory_identity(value)):
        raise PermissionError('Original same-account factory policy differs')
    return {'ownerAgentId': value['ownerAgentId'], 'trustBoundary': TRUST,
            'manifestSha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def factory_identity(value):
    return {k:value[k] for k in ('authorityId','hostId','ownerAgentId','serviceUser','codexHome','workspace','state','socket','unit')}


def authorize(authority, host, expected_manifest):
    """Explicit root-only metadata approval; starts and changes no service/profile."""
    if os.geteuid()!=0:raise PermissionError('Verified account-boundary administrator required')
    from .host_native import location
    path=location(authority,host)/'manifest.json';value,digest=declaration(path)
    if digest!=expected_manifest or value.get('schema')!='lax-native-host/v1' or value.get('runtimeMode')!='room-conversation':
        raise ValueError('Original conversational host manifest CAS differs')
    if (value['authorityId'],value['hostId'])!=(str(UUID(authority)),str(UUID(host))):
        raise ValueError('Original native host scope differs')
    account=pwd.getpwnam(value['serviceUser']);owner_scope(authority,value['ownerAgentId'],account)
    if value['codexHome']!=str(Path(account.pw_dir)/'codex-home'):
        raise PermissionError('Original native account profile differs')
    approval={'schema':'lax-native-account-sharing/v1','trustBoundary':TRUST,
              'identity':factory_identity(value),'approvalManifestSha256':digest}
    target=path.with_name('shared-account-policy.json')
    if target.exists():
        if declaration(target)[0]!=approval:raise ValueError('Original factory approval requires reconciliation, never replacement')
    else:
        with target.open('x') as f:json.dump(approval,f,sort_keys=True);f.write('\n');f.flush();os.fsync(f.fileno())
        target.chmod(0o644)
        fd=os.open(target.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)
    return {'policy':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'servicesStarted':0}


def owner_scope(authority, owner, account):
    """The caller's opt-in cannot promote an originally restricted host owner."""
    from .service_memory import approved_spec
    _, receipt, global_owner = approved_spec(authority, owner)
    if ((receipt.get('uid'), receipt.get('linuxUser')) != (account.pw_uid, account.pw_name)
            or receipt.get('agentId') != owner or receipt.get('authorityId') != authority):
        raise PermissionError('Protected native owner account evidence differs')
    if global_owner:
        allowed = type(receipt.get('sudoVerifiedUid')) is int and receipt['sudoVerifiedUid'] == 0 and receipt.get('home') == account.pw_dir
    else:
        policy_path = HARNESS / authority / 'workers' / owner / 'execution-policy-upgrade-receipt.json'
        policy = declaration(policy_path)[0] if policy_path.exists() else receipt
        if policy is not receipt and policy.get('originalSpecDigest') != receipt.get('specDigest'):
            raise ValueError('Original native owner policy receipt differs')
        allowed = (policy.get('executionProfile') == 'unrestricted'
                   and (policy is not receipt or receipt.get('administrator') is True)
                   and receipt.get('workspace') == str(Path(account.pw_dir) / 'work'))
    if not allowed:
        raise PermissionError('Original native profile is not an approved unrestricted account')


def attachment(spec, home, *, require_receipt=False):
    """Resolve only a pinned, explicitly trusted attachment; never create users."""
    from .host_native import location
    selected = spec.get('nativeHostAttachment')
    if selected is None and spec.get('nativeHostServer') is not True:
        return None
    path = location(spec['authorityId'], spec['hostId']) / 'manifest.json'
    if selected is None:
        if spec.get('nativeHostServer') is True and path.exists():
            value, _ = declaration(path)
            if value.get('ownerAgentId') != str(UUID(spec['agentId'])):
                raise PermissionError('Explicit same-account attachment required; no per-agent daemon fallback')
        return None
    if (spec.get('runtimeMode') != 'room-conversation' or spec.get('nativeHostServer') is not True
            or spec.get('executionProfile', 'unrestricted') != 'unrestricted'
            or spec.get('nativeStateAdoption') is not None
            or not isinstance(selected, dict)
            or set(selected) != {'ownerAgentId', 'manifestSha256', 'trustBoundary'}
            or selected['trustBoundary'] != TRUST
            or not isinstance(selected['manifestSha256'], str)
            or len(selected['manifestSha256']) != 64
            or any(c not in '0123456789abcdef' for c in selected['manifestSha256'])):
        raise PermissionError('Explicit same-account unrestricted native boundary required')
    home = Path(home)
    if home != worker_home(spec):
        raise ValueError('Distinct canonical agent home required')
    policy_path=home.parent/'execution-policy-upgrade-receipt.json'
    if policy_path.exists():
        policy=declaration(policy_path)[0]
        previous=declaration(home.parent/'provision-receipt.json')[0]
        if (policy.get('executionProfile')!='unrestricted'
                or policy.get('originalSpecDigest')!=previous.get('specDigest')):
            raise PermissionError('Shared account policy cannot claim restricted isolation; explicit profile migration required')
    value, digest = declaration(path)
    authority, host, agent, owner = [str(UUID(v)) for v in
        (spec['authorityId'], spec['hostId'], spec['agentId'], selected['ownerAgentId'])]
    if (value.get('schema') != 'lax-native-host/v1' or value.get('runtimeMode') != 'room-conversation'
            or (value.get('authorityId'), value.get('hostId'), value.get('ownerAgentId')) != (authority, host, owner)
            or owner == agent):
        raise ValueError('Shared account host/owner differs')
    account = pwd.getpwnam(value['serviceUser'])
    owner_scope(authority,owner,account)
    service_home = Path(account.pw_dir)
    if (value['codexHome'] != str(service_home / 'codex-home')
            or value['workspace'] != str(service_home / 'work')):
        raise PermissionError('Original native NSS profile differs')
    from .native_image_upgrade import _open_directory
    for p in (service_home, Path(value['codexHome']), Path(value['state'])):
        fd = _open_directory(p, account.pw_uid)
        os.close(fd)
    auth = Path(value['codexHome']) / 'auth.json'
    source = Path(spec['approvedModelAuthFile'])
    metadata = auth.lstat()
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != account.pw_uid
            or metadata.st_mode & 0o077 or not os.path.samefile(source, auth)):
        raise PermissionError('Attachment must use the original private native account, not equivalent credentials')
    identity = factory_identity(value)
    identity.update(uid=account.pw_uid, serviceHome=str(service_home))
    expected = {'schema': 'lax-shared-native-account/v1', 'authorityId': authority,
                'hostId': host, 'agentId': agent, 'request': selected, 'identity': identity}
    receipt = home.parent / 'shared-native-account.json'
    if receipt.exists():
        stored, _ = declaration(receipt)
        if stored != expected:
            raise ValueError('Original shared account enrollment differs')
    else:
        if require_receipt:
            raise ValueError('Original shared account enrollment receipt unavailable')
        from .service_observer import directory
        from .native_image_upgrade import require_settled_transition
        registry=directory(authority,host,owner)
        if registry.exists():
            fd=_open_directory(registry)
            try:require_settled_transition(fd)
            finally:os.close(fd)
        if digest != selected['manifestSha256'] or not os.path.samefile(value['binary'], spec['binary']):
            raise ValueError('Original shared host manifest/image CAS changed')
    return {'account': account, 'manifest': value, 'identity': identity, 'receipt': expected}


def attached_agents(authority, host):
    """Owner-only engine releases cannot silently strand enrolled clients."""
    root = HARNESS / str(UUID(authority)) / 'workers'
    if not root.exists():return []
    result=[]
    for count, child in enumerate(root.iterdir()):
        if count>=4096:raise ValueError('Shared account inventory bound exhausted')
        file=child/'shared-native-account.json'
        if not file.exists():continue
        value,_=declaration(file)
        if value['authorityId']==authority and value['hostId']==host:
            result.append(value['agentId'])
    return sorted(result)


def package_context(spec, uid, home):
    """Keep logical service paths separate from the protected NSS/profile owner.

    preflight_as_owner still enforces NSS equality. Only an existing protected
    attachment receipt may select a different HOME, never an arbitrary caller.
    """
    home = Path(home)
    bound = attachment(spec, home, require_receipt=True)
    if bound is None:
        return home, {}
    if bound['account'].pw_uid != uid:
        raise PermissionError('Original shared package execution UID differs')
    return Path(bound['account'].pw_dir), {'workspace': home / 'work'}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Approve one existing unrestricted account boundary; no service activation.')
    parser.add_argument('--authority',required=True);parser.add_argument('--host',required=True);parser.add_argument('--expected-manifest-sha256',required=True)
    args=parser.parse_args();print(json.dumps(authorize(args.authority,args.host,args.expected_manifest_sha256)))
