"""Protected, once-approved host account boundary for many logical sessions."""
import hashlib,json,os,stat
from pathlib import Path
from uuid import UUID
from .runtime_files import private_file,state_directory
from .rpc_shared import host_manifest


def digest_file(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def host_policy(config):
    selection=config.get('roomOriginPolicy')
    if not isinstance(selection,dict) or set(selection)!={'path','sha256'}:
        raise PermissionError('Parent host room-session policy is not installed; no per-agent service or private daemon fallback')
    file=Path(selection['path']);info=private_file(file,administrator_allowed=True)
    if os.name!='nt' and info.st_uid!=0:raise PermissionError('Host-owner approved room-session policy required')
    if digest_file(file)!=selection['sha256']:raise PermissionError('Approved parent host session policy changed')
    policy=json.loads(file.read_text());manifest=host_manifest(config)
    if (policy.get('schema')!='lax-room-session-policy/v1' or
        any(policy.get(k)!=config.get(k) for k in ('authorityId','hostId')) or
        policy.get('parentAgentId')!=config['agentId'] or
        policy.get('appServerManifestSha256')!=digest_file(config['nativeServer']['manifest'])):
        raise PermissionError('Original parent/native room-session policy binding differs')
    root=Path(policy['root']);meta=root.lstat()
    if not root.is_absolute() or root.is_symlink() or not stat.S_ISDIR(meta.st_mode):
        raise PermissionError('Protected approved host-owned session root required')
    if os.name!='nt' and (meta.st_uid!=os.geteuid() or meta.st_mode & 0o077):
        raise PermissionError('Session root must be private to the original parent account')
    if str(Path(manifest['codexHome']).resolve())!=str(Path(config['codexHome']).resolve()):
        raise PermissionError('Original shared profile required')
    guides=policy.get('operatingInstructions')
    if not guides:raise PermissionError('Approved host operating instructions are missing')
    for guide in guides:
        p=Path(guide['path'])
        if not p.is_absolute() or p.is_symlink() or not p.is_file() or digest_file(p)!=guide['sha256']:
            raise PermissionError('Approved host operating instruction pin changed')
    return policy,manifest


def validate_spec(spec_path,expected_spec_sha256):
    private_file(spec_path)
    if digest_file(spec_path)!=expected_spec_sha256:raise ValueError('Original room session specification changed')
    spec=json.loads(spec_path.read_text());config=spec['connectorConfig']
    if spec.get('schema')!='lax-room-origin-local-spec/v1':raise ValueError('Room-origin session spec required')
    for k in ('authorityId','agentId','hostId'):UUID(spec[k])
    if (config['agentId']!=spec['agentId'] or config['authorityId']!=spec['authorityId'] or
        config.get('originRoomId')!=spec['originRoomId'] or
        config['rooms']!=[{'roomId':spec['originRoomId'],'after':0}] or 'nativeThreadId' in config):
        raise ValueError('Distinct original room session config required')
    if digest_file(config['nativeServer']['manifest'])!=spec['nativeHostManifestSha256']:
        raise PermissionError('Original shared native manifest changed')
    policy,_=host_policy({**config,'agentId':spec['parentRuntime']['agentId'],
                          'roomOriginPolicy':spec['parentRuntime']['policy']})
    if policy['nativeIdentity']!=spec['nativeIdentity'] or policy['operatingInstructions']!=spec['operatingInstructions']:
        raise PermissionError('Original parent native/host operating policy differs')
    for key,child in [('state','state'),('workspace','work')]:
        p=Path(config[key]);expected=Path(policy['root'])/spec['agentId']/child
        if p!=expected or p.resolve()!=p:
            raise PermissionError('Original host-approved logical session path required')
    for guide in spec['operatingInstructions']:
        if digest_file(guide['path'])!=guide['sha256']:raise PermissionError('Host operating instructions changed')
    return spec
