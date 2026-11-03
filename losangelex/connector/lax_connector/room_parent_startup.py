"""Parent runtime startup evidence, NOT a fabricated OS-manager acceptance.

The owning host lifecycle approves/pins actual incarnation/admission once. A
logical room initializer cannot start, approve or re-enroll its parent service.
"""
import hashlib,os,sys
from pathlib import Path
from .journal import saved


def windows_startup(config):
    from . import room_factory_windows_state as platform
    selection=config['roomOriginPolicy'];policy=platform.read(selection['path'],selection['sha256'])
    platform.require(policy['schema']=='lax-windows-room-parent-policy/v1','Actual Windows host policy required')
    platform.require(all(policy[k]==config[k] for k in ('authorityId','hostId')) and policy['parentAgentId']==config['agentId'],
                     'Parent startup identity differs')
    parent=platform.read(policy['parentConfigPath'])
    platform.require(all(parent[k]==config[k] for k in ('authorityId','hostId','agentId','nativeThreadId','nativeServer')),
                     'Original accepted parent configuration differs')
    metadata=platform.read(policy['parentRuntimeMetadata'])
    platform.require(metadata.get('state')=='running' and metadata['pid']==os.getpid(),
                     'Original host runtime receipt must name this actual parent PID')
    manifest=platform.read(policy['nativeHostManifest'],policy['nativeHostManifestSha256'])
    platform.require(manifest['ownerAgentId']==config['agentId'] and manifest['hostId']==config['hostId']
        and manifest['authorityId']==config['authorityId'] and config['nativeServer']=={'manifest':policy['nativeHostManifest']},
        'Original shared native declaration differs')
    # No manager/Task Scheduler/WMI, subprocess, native thread or model call.
    runtime=platform.process(os.getpid());native=platform.native_peer(manifest)
    return {'schema':'lax-room-parent-startup/v1','platform':'windows',
        **{k:policy[k] for k in ('authorityId','hostId','parentAgentId','nativeHostManifestSha256','parentTaskName')},
        'runtimeIdentity':runtime,'nativeIdentity':native,
        'parentArgvSha256':platform.argv_digest(sys.orig_argv),
        'admissionAllowed':False,'meaning':'Actual startup evidence only; owning host lifecycle must accept/pin admission separately'}


def emit(config):
    if os.name!='nt' or not config.get('roomOriginPolicy'):return None
    path=Path(config['state'])/'room-parent-startup.private.json'
    try:value=windows_startup(config)
    except Exception as error:
        value={'schema':'lax-room-parent-startup/v1','platform':'windows','parentRuntimePid':os.getpid(),
               'admissionAllowed':False,'state':'blocked','errorType':type(error).__name__}
    # This is explicitly startup EVIDENCE, never the protected parent acceptance
    # consumed by platform.inspect_parent. No self-approved admission/Root receipt.
    saved(path,value);return value
