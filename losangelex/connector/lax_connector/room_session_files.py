"""Protected, once-approved host account boundary for many logical sessions."""
import hashlib,json,os,stat
from pathlib import Path
from uuid import UUID
from .runtime_files import private_file,state_directory
from .rpc_shared import host_manifest


def digest_file(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def host_policy(config):
    if os.name=='nt':return windows_host_policy(config)
    if __import__('sys').platform=='darwin':return macos_host_policy(config)
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
    return {**policy,'initialPermissions':approved_initial_permissions(config,{},policy)},manifest


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
    # Linux consumes this common spec validator; Windows/macOS own full native
    # account/root/parent validation in their supplied platform adapters.
    policy,_=host_policy({**config,'agentId':spec['parentRuntime']['agentId'],
                          'roomOriginPolicy':spec['parentRuntime'].get('roomOriginPolicy',spec['parentRuntime'].get('policy'))})
    if policy['nativeIdentity']!=spec['nativeIdentity'] or policy['operatingInstructions']!=spec['operatingInstructions']:
        raise PermissionError('Original parent native/host operating policy differs')
    for key,child in [('state','state'),('workspace',policy.get('workspaceRelative','work'))]:
        p=Path(config[key]);expected=Path(policy['root'])/spec['agentId']/child
        if p!=expected or p.resolve()!=p:
            raise PermissionError('Original host-approved logical session path required')
    for guide in spec['operatingInstructions']:
        if digest_file(guide['path'])!=guide['sha256']:raise PermissionError('Host operating instructions changed')
    return spec


def windows_host_policy(config,*,resident=True,role_handover=False):
    """Normalize the OS owner's actual parent/ACL/native policy, not Linux UID."""
    from . import room_factory_windows_state as platform
    import sys
    selection=config.get('roomOriginPolicy')
    if not isinstance(selection,dict) or set(selection)!={'path','sha256'}:
        raise PermissionError('Protected Windows parent room-session policy is missing')
    raw=platform.read(selection['path'],selection['sha256'])
    if role_handover:
        if resident:raise ValueError('Role maintenance is an explicit stopped-parent operator path')
        from .room_role_maintenance_windows import inspect_stopped_parent
        proof=inspect_stopped_parent(Path(selection['path']),expected_policy_sha256=selection['sha256'])
    else:
        proof=platform.inspect_parent(Path(selection['path']),expected_policy_sha256=selection['sha256'])
        if resident:platform.require(proof['parentRuntime']['pid']==os.getpid(),'Factory must run inside accepted resident host runtime')
        acceptance=platform.read_parent_acceptance(raw,expected_policy_sha256=selection['sha256'])
        platform.require(acceptance.get('state')=='running' and acceptance.get('admissionAllowed') is True
            and acceptance['runtimeIdentity']==proof['parentRuntime'] and acceptance['nativeIdentity']==proof['sharedNative'],
            'Owner parent acceptance closed or changed during inspection')
        if resident:platform.require(platform.argv_digest(sys.orig_argv)==acceptance['parentArgvSha256'],'Accepted resident parent argv differs')
    platform.require(all(raw[k]==config[k] for k in ('authorityId','hostId')) and raw['parentAgentId']==config['agentId'],
                     'Original Windows parent authority/host/agent binding differs')
    platform.require(config['nativeServer']=={'manifest':raw['nativeHostManifest']},'Original Windows shared manifest required')
    guides=raw.get('operatingInstructions')
    platform.require(isinstance(guides,list) and 1<=len(guides)<=16,'Host-approved operatingInstructions missing from parent policy')
    for guide in guides:
        path=Path(guide['path']);info=path.lstat()
        platform.require(path.is_absolute() and path.resolve()==path and path.is_file()
            and not info.st_file_attributes & 0x400 and digest_file(path)==guide['sha256'],'Original host operating guide differs')
    parent_config=platform.read(raw['parentConfigPath'])
    defaults=approved_defaults(config,parent_config,raw)
    policy={**defaults,'initialPermissions':approved_initial_permissions(config,parent_config,raw),
            'schema':'lax-room-session-policy/v1','authorityId':raw['authorityId'],'hostId':raw['hostId'],
            'parentAgentId':raw['parentAgentId'],'root':raw['agentRoot'],'workspaceRelative':'home/work',
            'nativeIdentity':proof['sharedNative'],'operatingInstructions':guides,
            'appServerManifestSha256':raw['nativeHostManifestSha256']}
    return policy,host_manifest(config)


def macos_host_policy(config):
    """Host-only counterpart of the supplied MacAgentFiles child validator.

    No synthetic child/credential is manufactured just to inspect the parent.
    All process IDs are read from this parent and protected original metadata.
    """
    from . import room_factory_macos as platform
    selection=config.get('roomOriginPolicy')
    if not isinstance(selection,dict) or set(selection)!={'path','sha256'}:
        raise PermissionError('Protected macOS host account policy missing')
    raw=platform.load(selection['path'],private=True,sha=selection['sha256'])
    account=platform.pwd.getpwuid(os.geteuid())
    platform.require(raw.get('schema')=='lax-macos-room-account/v1'
        and (raw['uid'],raw['user'],raw['serviceHome'])==(os.geteuid(),account.pw_name,account.pw_dir),
        'Original macOS host NSS/account policy differs')
    platform.require(raw['initialPermissions']=={'sandbox':'danger-full-access','approvalPolicy':'never'},
                     'Host policy must authorize explicit initial room permissions')
    manifest=json.loads(platform.pin_file(raw['nativeManifest']))
    parent=json.loads(platform.pin_file(raw['parentConfig']))
    enrollment=json.loads(platform.pin_file(raw['ownerReceipt']))
    platform.require((raw['authorityId'],raw['hostId'],raw['ownerAgentId'])==
        (config['authorityId'],config['hostId'],config['agentId']) and
        (manifest['authorityId'],manifest['hostId'],manifest['ownerAgentId'],manifest['serviceUser'])==
        (raw['authorityId'],raw['hostId'],raw['ownerAgentId'],account.pw_name) and
        manifest['schema']=='lax-native-host/v1' and manifest['platform']=='darwin'
        and manifest['runtimeMode']=='room-conversation','Original macOS authority/host/parent differs')
    platform.require(all(parent[k]==config[k] for k in ('authorityId','hostId','agentId','nativeThreadId','nativeServer','codexHome','binary'))
        and config['nativeServer']=={'manifest':raw['nativeManifest']['path']}
        and (enrollment['agentId'],enrollment['nodeId'],enrollment['nativeThreadId'],enrollment['sharedNativeService'])==
        (config['agentId'],config['hostId'],config['nativeThreadId'],manifest['unit']),
        'Original macOS parent config/enrollment/thread differs')
    root=platform.trusted(raw['agentRoot'],private=True,directory=True)
    platform.require(platform.identity(root)==raw['agentRootIdentity'],'Original host agent root incarnation changed')
    for original in (manifest['codexHome'],manifest['state'],parent['state'],parent.get('workspace',manifest['workspace'])):
        platform.require(not platform.overlap(root,original),'Agent root overlaps original native/profile/parent state')
    parent_identity=platform.process_identity(os.getpid())
    platform.require(platform.program(raw['interpreter'])==str(Path(parent_identity['image']).resolve()),
                     'Current parent interpreter image differs')
    locator=raw.get('nativeRuntimeMetadata')
    if locator:
        platform.require(set(locator) in ({'path'},{'path','sha256'}),'Exact protected native runtime locator required')
        metadata=platform.load(locator['path'],private=True,sha=locator.get('sha256'))
        native_identity=platform.process_identity(metadata['pid'])
    elif raw.get('nativeProcess'):
        native_identity=platform.process_identity(raw['nativeProcess']['pid'])
        platform.require(native_identity==raw['nativeProcess'],'Original accepted native incarnation changed')
    else:raise PermissionError('Original protected native PID metadata locator is required; no process scan/daemon fallback')
    platform.require(parent_identity['uid']==native_identity['uid']==os.geteuid()
        and Path(native_identity['image']).resolve()==Path(manifest['binary']).resolve()
        and config['binary']==manifest['binary']==raw['binary']['path']
        and config['codexHome']==manifest['codexHome'],'Original shared native image/profile differs')
    platform.program(raw['binary']);platform.ipc(manifest,raw.get('nativeSocketPin'))
    platform.trusted(manifest['codexHome'],private=True,directory=True)
    platform.trusted(Path(manifest['codexHome'])/'auth.json',private=True) # metadata only
    guides=raw.get('operatingInstructions')
    platform.require(isinstance(guides,list) and 1<=len(guides)<=16,'Approved macOS host guide list missing')
    for guide in guides:platform.read(guide['path'],sha=guide['sha256'])
    defaults=approved_defaults(config,parent,raw)
    return {**defaults,'initialPermissions':approved_initial_permissions(config,parent,raw),
        'schema':'lax-room-session-policy/v1','authorityId':config['authorityId'],'hostId':config['hostId'],
        'parentAgentId':config['agentId'],'root':str(root),'workspaceRelative':'work',
        'nativeIdentity':native_identity,'parentRuntimeIdentity':parent_identity,
        'operatingInstructions':guides,'appServerManifestSha256':raw['nativeManifest']['sha256']},manifest


def approved_defaults(config,parent,policy):
    """No model sampling/default guess when a legacy parent config omits it."""
    result={}
    for key in ('model','effort'):
        value=config.get(key) or parent.get(key) or policy.get(key)
        if not isinstance(value,str) or not value.strip():
            raise PermissionError('Exact approved parent '+key+' default is missing from host policy')
        if policy.get(key) and policy[key]!=value:
            raise PermissionError('Approved parent '+key+' differs from current host configuration')
        result[key]=value
    return result


def approved_initial_permissions(config,parent,policy):
    """Fresh child defaults from reviewed policy/explicit parent, never warm inference."""
    keys=('sandbox','approvalPolicy')
    value=policy.get('initialPermissions')
    if value is None:value={key:config.get(key) or parent.get(key) for key in keys}
    if value!={'sandbox':'danger-full-access','approvalPolicy':'never'}:
        raise PermissionError('Exact reviewed initial room permissions unavailable')
    for source in (config,parent):
        if any(source.get(key) is not None and source[key]!=value[key] for key in keys):
            raise PermissionError('Current parent restriction differs from initial room policy; no widening')
    return dict(value)


def parent_admission_revision(config):
    """Protected owner-record change marker, not admission or a process proof.

    Only opt-in Windows v2 has a mutable acceptance locator. A missing/invalid
    record has no valid revision; the bounded catalog-edge fallback may inspect
    known never-attached registrations without any timer or native input replay.
    """
    if os.name!='nt':return None
    try:
        from . import room_factory_windows_state as platform
        selection=config['roomOriginPolicy']
        raw=platform.read(selection['path'],selection['sha256'])
        if raw.get('schema')!='lax-windows-room-parent-policy/v2':return None
        acceptance=platform.read_parent_acceptance(raw,expected_policy_sha256=selection['sha256'])
        return hashlib.sha256(json.dumps(acceptance,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    except Exception:return None


def inspection_policy(config):
    """Read-only release CLI validates the ACTUAL owner-accepted parent.

    The inspecting CLI is not the resident parent's PID/argv. Factory/session
    admission still calls host_policy with its strict in-parent fence; this
    helper admits no session and never changes parent acceptance.
    """
    if os.name=='nt':return windows_host_policy(config,resident=False)
    return host_policy(config)
