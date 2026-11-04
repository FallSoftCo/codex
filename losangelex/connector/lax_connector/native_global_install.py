"""First single-context Global for a new Linux node, using existing installers.

This never invokes the legacy three-purpose installer. Native process ownership
stays in host_native; logical room contexts stay in the resident parent.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
from uuid import UUID
from urllib.parse import urlsplit
from .journal import saved

SCHEMA = 'lax-native-global-install/v1'


def policy_path(authority, agent):
    return Path('/var/lib/harness')/str(UUID(authority))/'workers'/str(UUID(agent))/'room-session-policy.json'


def configuration_policy(spec, authority, agent, home):
    if not spec.get('roomCoordinator'):
        return None
    path = policy_path(authority, agent)
    if not path.exists():
        return None  # Only before the original fresh host infrastructure exists.
    from .linux_worker import protected
    policy = protected(path)
    if (policy.get('parentAgentId') != agent or policy.get('authorityId') != authority
            or policy.get('hostId') != spec['hostId']):
        raise ValueError('Original Global room policy belongs to another host/agent')
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def install_policy(spec, config, account, home, host_runtime):
    """Called inside fresh Linux provisioning, BEFORE Global's first resume."""
    options=spec.get('roomCoordinator')
    if not options:
        return
    if (spec.get('runtimeMode')!='room-conversation' or spec.get('nativeHostServer') is not True
            or spec.get('executionProfile','unrestricted')!='unrestricted'
            or not isinstance(options,dict) or set(options)!={'operatingInstructions'}):
        raise ValueError('Explicit unrestricted single-context Global policy required')
    guides=options['operatingInstructions']
    if not isinstance(guides,list) or not 1<=len(guides)<=16:
        raise ValueError('Approved host operating instructions required')
    from .linux_worker import protected
    for guide in guides:
        if set(guide)!={'path','sha256'}:
            raise ValueError('Exact host guide path/hash required')
        path=Path(guide['path']);info=path.lstat()
        if (not path.is_absolute() or path.is_symlink() or not path.is_file()
                or info.st_uid!=0 or info.st_mode&0o022
                or hashlib.sha256(path.read_bytes()).hexdigest()!=guide['sha256']):
            raise PermissionError('Approved host guide differs')
    manifest=host_runtime['manifest']
    pid=int(subprocess.check_output(['systemctl','show',manifest['unit'],'-p','MainPID','--value'],text=True,timeout=10))
    proc=Path('/proc')/str(pid)
    identity={'pid':pid,'startTicks':int((proc/'stat').read_text().rsplit(')',1)[1].split()[19]),
              'image':str((proc/'exe').resolve()),'uid':proc.stat().st_uid}
    if identity['uid']!=account.pw_uid or Path(identity['image'])!=Path(spec['binary']).resolve():
        raise PermissionError('Actual native host process differs from the approved profile')
    root=home/'room-agents';root.mkdir(mode=0o700,exist_ok=True)
    if root.is_symlink():raise PermissionError('Logical room root cannot be a symlink')
    os.chown(root,account.pw_uid,account.pw_gid);root.chmod(0o700)
    path=policy_path(spec['authorityId'],spec['agentId'])
    value={'schema':'lax-room-session-policy/v1','authorityId':spec['authorityId'],'hostId':spec['hostId'],
           'parentAgentId':spec['agentId'],'root':str(root),'nativeIdentity':identity,
           'operatingInstructions':guides,'initialPermissions':{'approvalPolicy':'never','sandbox':'danger-full-access'},
           'appServerManifestSha256':hashlib.sha256(Path(config['nativeServer']['manifest']).read_bytes()).hexdigest()}
    if path.exists():
        if protected(path)!=value:
            raise ValueError('Original host Global policy changed; inspect the same installation')
    else:
        saved(path,value);path.chmod(0o644)
    config['roomOriginPolicy']=configuration_policy(spec,spec['authorityId'],spec['agentId'],home)


def provision(profile, *, activate=False, startup_enabled=None, startup_dependencies=None):
    if os.geteuid()!=0 or profile.get('schema')!=SCHEMA or profile.get('runtimeMode')!='room-conversation':
        raise PermissionError('Explicit administrator-owned native Global profile required')
    if startup_dependencies:
        raise ValueError('API/client lifecycle is separate from the native Global installation')
    if startup_enabled is False:
        raise ValueError('Use prepare without activation for a stopped new installation')
    from .linux_worker import protected
    authority,agent,host=[str(UUID(profile[k])) for k in ('authorityId','agentId','hostId')]
    # Establish traversable protected runtime ancestors before private intent
    # directories. mkdir(parents=True) would inherit root's private umask and
    # leave the native service UID unable to reach its own work directory.
    for path in (Path('/var/lib/harness'),Path('/var/lib/harness')/authority):
        if not path.exists():
            path.mkdir(mode=0o711);path.chmod(0o711)
        info=path.lstat()
        if (path.is_symlink() or not path.is_dir() or info.st_uid!=0
                or info.st_mode&0o022 or not info.st_mode&0o001):
            raise PermissionError('Runtime ancestor requires original-owner directory reconciliation')
    root=Path('/var/lib/harness')/authority/'native-global-install'/host
    root.mkdir(mode=0o700,parents=True,exist_ok=True)
    if root.is_symlink() or root.stat().st_uid!=0 or root.stat().st_mode&0o077:
        raise PermissionError('Native Global operation directory must be private to root')
    intent=root/'profile.private.json'
    if intent.exists():
        if protected(intent)!=profile:raise ValueError('Original Global initialization profile changed')
    else:saved(intent,profile)
    spec={k:profile[k] for k in ('authorityId','agentId','hostId','credential','hollywoodUrl',
          'nativeName','purpose','rooms','machineIdentity','approvedModelAuthFile','binary','interpreter','model','effort')}
    spec.update(runtimeMode='room-conversation',nativeHostServer=True,executionProfile='unrestricted',
                roomCoordinator={'operatingInstructions':profile['operatingInstructions']})
    for key in ('serviceMemoryMaxBytes','nativeHostMemoryMaxBytes'):
        if key in profile:spec[key]=profile[key]
    spec_file=root/'worker-spec.private.json'
    if spec_file.exists():
        if protected(spec_file)!=spec:raise ValueError('Original native Global specification changed')
    else:saved(spec_file,spec)
    if not activate:
        return {'state':'prepared','specification':str(spec_file),'nativeOrModelStarted':False}
    route=urlsplit(profile['hollywoodUrl'])
    if (route.scheme!='http' or route.hostname not in ('127.0.0.1','localhost','::1')
            or route.username or route.password or route.path not in ('','/') or route.query or route.fragment):
        raise ValueError('Native Global initialization requires its actual local Hollywood API')
    if len(profile['rooms'])!=1:
        raise ValueError('A new Global begins only in its canonical Global room')
    from .host import request
    read=lambda path:request(profile['hollywoodUrl'],profile['credential'],'GET',path)
    principal=read('principals/'+agent)
    role=read('agents/'+agent+'/role')
    origin=read('agents/'+agent+'/origin-adoption')
    room=profile['rooms'][0]['roomId']
    if ((principal['id'],principal['authority'],principal['kind'],principal['administrator'],
         principal['home_node'],principal['identity_reference'])!=(agent,authority,'agent',True,host,False)
            or role['primary_role'].casefold()!='global' or role['home_room']!=room
            or (origin['agent'],origin['node'],origin['room'])!=(agent,host,room)):
        raise PermissionError('Authoritative original Global/host/room initialization differs')
    # Service enrollment lives under the protected host registry even though
    # conversational agents do not use the legacy task/controller scheduler.
    registry=Path('/var/lib/harness')/authority/'hosts'/host
    registry.mkdir(mode=0o700,parents=True,exist_ok=True)
    if registry.is_symlink() or registry.stat().st_uid!=0 or registry.stat().st_mode&0o077:
        raise PermissionError('Protected native host registry required')
    from .linux_worker import provision as install
    receipt=install(spec)
    from .host_native import location
    from .shared_account import authorize
    path=location(authority,host)/'manifest.json'
    sharing=authorize(authority,host,hashlib.sha256(path.read_bytes()).hexdigest())
    result={'schema':SCHEMA,'state':'installed','agentId':agent,'hostId':host,
            'worker':receipt,'sharedAccount':sharing,'modelsStartedByInstallation':0,
            'networkAndProviderQualification':'separate; service health is not inference proof'}
    saved(root/'result.private.json',result)
    return result
