"""Resident Windows room adapter, lax-room-origin-platform-adapter/v2.

Runs IN the existing parent runtime. Only common room_bootstrap performs the
once-only native initialization; the parent's supervisor attaches the logical
ConversationalAgent later. This module never creates/controls an OS service or
process. Returned sessionConfigPath is PRIVATE to the in-process supervisor.
"""
import hashlib,os,sys,time
from pathlib import Path
from uuid import UUID
from . import room_bootstrap
from . import room_factory_windows_state as platform
from .room_tools import TOOLS

SDK_BASE='acc4e932c0fb988e47acfa566981a40da2a56247'
CONTRACT_SHA='dc525199f336aaabd604026251fec65caf9bfdbf984c1eaca8e9ce1b27db7a2e'
def _runtime_pid():return os.getpid()
def _own_argv_digest():return platform.argv_digest(sys.orig_argv)
def _hash(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def _native_matches(actual,expected):
    platform.require(isinstance(expected,dict) and all(k in expected for k in ('pid','created','image')),
        'Windows nativeIdentity requires PID, platform creation/birth and image')
    platform.require(actual['pid']==expected['pid'] and actual['created']==expected['created']
        and os.path.samefile(actual['image'],expected['image']),'Original native incarnation differs')
    for key in ('ownerSidSha256','sessionId'):
        if key in expected:platform.require(actual[key]==expected[key],'Original native identity pin differs')
def _guides(spec,cfg):
    guides=spec['operatingInstructions']
    platform.require(isinstance(guides,list) and 1<=len(guides)<=16,'Approved host guide list required')
    resume=cfg.get('conversationResumeInstructions',{})
    platform.require(isinstance(resume,dict) and resume,'Fresh explicit room resume instructions required')
    initial=cfg['instructions'];resumed='\n'.join(resume.values())
    for guide in guides:
        platform.require(set(guide)=={'path','sha256'},'Guide path and exact raw SHA required')
        path=Path(guide['path']);info=path.lstat()
        platform.require(path.is_absolute() and path.resolve()==path and path.is_file()
            and not info.st_file_attributes&0x400 and info.st_size<=256*1024,'Approved host guide unavailable/aliased/oversize')
        platform.require(_hash(path)==guide['sha256'],'Approved host guide bytes changed')
        platform.require(all(value in instructions for instructions in (initial,resumed) for value in (str(path),guide['sha256'])),
            'Initial and resume room instructions must include approved host guide path and SHA')
def _result(spec,state,reason,proof=None,thread=None,path=None):
    # LOCAL return only. Common MUST NOT publish sessionConfigPath or private
    # spec/config content in its canonical cross-host receipt.
    return {'schema':'lax-room-origin-host-result/v1','operationId':spec['operationId'],
        **{k:spec[k] for k in ('authorityId','originRoomId','agentId','hostId')},
        'state':state,'reason':reason,'nativeThreadId':thread,'sharedAppServer':True,
        'appServerManifestSha256':spec['nativeHostManifestSha256'],'modelTurnsRequested':0,
        'parentRuntimePid':proof['parentRuntime']['pid'] if proof else None,
        'nativeIdentity':proof['sharedNative'] if proof else None,
        'sessionConfigPath':str(path) if path else None,'sessionConfigSha256':_hash(path) if path else None,
        'logicalSessionAttached':False,'canonicalObservationRequired':True}
def _load(spec_path,expected):
    spec=platform.read(spec_path,expected)
    platform.require(spec['schema']=='lax-room-origin-local-spec/v1','Original resident local spec required')
    for key in ('authorityId','hostId','nodeId','originRoomId','agentId'):
        platform.require(str(UUID(spec[key]))==spec[key],'Canonical original room/host/agent identity required')
    platform.require(spec['nodeId']==spec['hostId'],'Windows enrolled local host/node differs')
    parent=spec['parentRuntime']
    platform.require(isinstance(parent,dict) and isinstance(parent.get('roomOriginPolicy'),dict),
        'Windows parentRuntime requires agentId,pid,roomOriginPolicy path/hash')
    policy_ref=parent['roomOriginPolicy']
    platform.require(set(policy_ref)=={'path','sha256'},'Exact protected roomOriginPolicy reference required')
    policy=platform.read(Path(policy_ref['path']),policy_ref['sha256'])
    proof=platform.inspect_parent(Path(policy_ref['path']),expected_policy_sha256=policy_ref['sha256'])
    platform.require(parent['agentId']==proof['parentAgentId'] and parent['pid']==proof['parentRuntime']['pid'],
        'Original parent agent/runtime identity differs')
    platform.require(_runtime_pid()==proof['parentRuntime']['pid'],'Factory/bootstrap must run IN existing parent runtime, never a child process')
    acceptance=platform.read_parent_acceptance(policy,expected_policy_sha256=policy_ref['sha256'])
    platform.require(_own_argv_digest()==acceptance['parentArgvSha256'],'Original in-process runtime command differs')
    platform.require(policy['nativeHostManifestSha256']==spec['nativeHostManifestSha256'],'Original descriptor SHA differs')
    _native_matches(proof['sharedNative'],spec['nativeIdentity'])
    cfg=dict(spec['connectorConfig'])
    platform.require(cfg.get('conversationDynamicTools',TOOLS)==TOOLS,'Fresh room tool declarations must match SDK246')
    cfg['conversationDynamicTools']=TOOLS
    binding={k:spec[k] for k in ('authorityId','hostId','originRoomId','agentId','operationId')}
    platform._scope(binding,cfg,proof)
    parent_cfg=platform.read(Path(policy['parentConfigPath']))
    platform.require(parent_cfg['agentId']==proof['parentAgentId'] and parent_cfg['hostId']==spec['hostId']
        and parent_cfg['authorityId']==spec['authorityId'],'Original parent config binding differs')
    platform.require(cfg['model']==parent_cfg.get('model',policy.get('model'))
        and cfg['effort']==parent_cfg.get('effort',policy.get('effort')),'Original owner model/effort defaults differ')
    platform.require(parent_cfg.get('nativeThreadId'),'Original parent native thread identity required')
    _guides(spec,cfg)
    return spec,cfg,binding,policy_ref,proof,parent_cfg['nativeThreadId']

async def provision_local(spec_path: Path, operation_dir: Path, *, inspect: bool, expected_spec_sha256: str) -> dict:
    spec,cfg,binding,policy_ref,proof,parent_thread=_load(Path(spec_path),expected_spec_sha256)
    op=Path(operation_dir);platform.require(op.is_absolute() and op.resolve()==op,'Fixed exact operation directory required')
    platform.private_path(op,directory=True)
    seal={'specSha256':expected_spec_sha256,'binding':binding,'contractSha256':CONTRACT_SHA}
    original=op/'windows-resident-original.json'
    if original.exists():platform.require(platform.read(original)==seal,'Original resident spec/operation cannot change')
    elif inspect:return _result(spec,'blocked','Original resident dispatch absent; inspect created nothing',proof)
    else:platform.once(original,seal)
    initial=op/'connector-initial.private.json'
    if initial.exists():platform.require(platform.read(initial)==cfg,'Original initial role/config cannot change')
    elif inspect:return _result(spec,'unknown','Original initial configuration missing; not recreated',proof)
    else:platform.once(initial,cfg)
    prepared=platform.prepare_agent(Path(policy_ref['path']),initial,op,
        expected_policy_sha256=policy_ref['sha256'],expected_config_sha256=_hash(initial),binding=binding,inspect=inspect)
    if prepared['state']!='prepared':return _result(spec,'blocked',prepared['reason'],proof)
    state=Path(cfg['state']);slot=state.parent
    with platform._lock(slot,create=False):
        current=platform.inspect_parent(Path(policy_ref['path']),expected_policy_sha256=policy_ref['sha256'])
        platform.require(current==proof,'Original parent/native incarnation changed before bootstrap')
        context_file=state/'native-context.json';prior=platform.read(context_file) if context_file.exists() else None
        intent=op/'native-initialization-intent.json'
        ready=prior and prior.get('state')=='ready'
        safe_unstarted=(prior and prior.get('state') in ('connecting','transport-unavailable')
            and prior.get('threadStartAttempted') is False)
        if prior and not ready and not safe_unstarted:
            return _result(spec,'unknown','Original thread/start, created or naming result is uncertain; never create a replacement',proof,prior.get('nativeThreadId'))
        if inspect and not prior:
            return _result(spec,'unknown','Original native context receipt missing; no thread/start replayed',proof)
        if not inspect and intent.exists() and not ready:
            return _result(spec,'unknown','Original dispatch exists; inspect the same operation without replaying first initialization',proof)
        if intent.exists():platform.require(platform.read(intent)['specSha256']==expected_spec_sha256,'Original initialization intent differs')
        elif inspect:return _result(spec,'unknown','Original initialization intent missing; context is not adopted',proof)
        else:platform.once(intent,{'specSha256':expected_spec_sha256,'parentRuntimePid':proof['parentRuntime']['pid'],
            'nativeIdentity':proof['sharedNative'],'at':time.time(),'modelTurnsRequested':0})
        try:context=await room_bootstrap.initialize(cfg)
        except Exception as error:
            context=platform.read(context_file) if context_file.exists() else {}
            evidence=op/'bootstrap-error.json'
            if not evidence.exists():platform.once(evidence,{'errorType':type(error).__name__,'phase':context.get('state'),
                'threadStartAttempted':context.get('threadStartAttempted'),'at':time.time()})
            safe=context.get('state') in ('connecting','transport-unavailable') and context.get('threadStartAttempted') is False
            return _result(spec,'blocked' if safe else 'unknown',
                'Original transport is proven unstarted; inspect SAME operation after repair' if safe else
                'Original native bootstrap outcome uncertain; hold its receipt and never repeat thread/start',proof,context.get('nativeThreadId'))
        platform.require(context['state']=='ready' and context.get('nativePermissionsPersisted') is True
            and context.get('modelTurnsRequested')==0,'Original native initialization acceptance incomplete')
        thread=context['nativeThreadId'];platform.require(thread!=parent_thread,'New room agent cannot adopt original Global thread')
        manifest=platform.read(cfg['nativeServer']['manifest'],spec['nativeHostManifestSha256'])
        platform.require(context['binding']=={'authorityId':spec['authorityId'],'agentId':spec['agentId'],
            'codexHome':cfg['codexHome'],'nativeState':manifest['state']},'Original new-thread binding differs')
        runtime={**cfg,'nativeThreadId':thread};target=op/'session-config.private.json'
        if target.exists():platform.require(platform.read(target)==runtime,'Original resident session config changed')
        else:platform.once(target,runtime)
        after=platform.inspect_parent(Path(policy_ref['path']),expected_policy_sha256=policy_ref['sha256'])
        platform.require(after==proof,'Original parent/native incarnation changed during initialization')
        _native_matches(after['sharedNative'],spec['nativeIdentity'])
        acceptance=op/'resident-initialization-accepted.json'
        value={'operationId':spec['operationId'],'specSha256':expected_spec_sha256,'nativeThreadId':thread,
            'sessionConfigSha256':_hash(target),'parentRuntimePid':proof['parentRuntime']['pid'],'nativeIdentity':after['sharedNative'],
            'logicalSessionAttached':False,'modelTurnsRequested':0}
        if acceptance.exists():platform.require(platform.read(acceptance)==value,'Original resident initialization receipt differs')
        else:platform.once(acceptance,value)
        return _result(spec,'ready','Native bootstrap and exact resident config accepted; common supervisor attach and fresh observation STILL required',after,thread,target)
