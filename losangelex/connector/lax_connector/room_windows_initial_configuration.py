"""Source-bound Windows pre-resident failure, not an uncertain dispatch retry.

Original _load calls _scope BEFORE resident seal/files/native intent/bootstrap.
Require its accepted original guard diagnostic, five accepted HTTP steps and
immutable omitted-permission spec; PURE _scope reproduces the exact failure.
Current V2 owner acceptance is independently revalidated, never manufactured.
"""
import copy,hashlib,json,sys
from pathlib import Path
from uuid import UUID,uuid5

GUARD='Explicit NEW full native policy required'
SOURCES={'room_factory_windows.py':'2bf93497b20ca6434367fcf1833e9824c8e2a3bb1819b2e857c83397b6bfe91d',
    'room_factory_windows_state.py':'b848cdded1ceae776170f8cf7495c7af14b0cf52855bef9278d414c210dea1f9'}


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def journal_path(state,operation):
    return Path(state)/('windows-configuration-recovery-'+str(UUID(operation.removeprefix('native-admin:')))+'.json')


def select(owner,path,record):
    from .room_administration import FACTORY_TOOL,digest
    if sys.platform!='win32' or record.get('tool')!=FACTORY_TOOL or record.get('state') not in ('intent','unconfirmed'):return path,record
    from . import room_factory_windows as adapter,room_factory_windows_state as platform
    if any(sha(Path(adapter.__file__).with_name(n))!=v for n,v in SOURCES.items()):return path,record
    config=owner.host_config;operation=record['operationId'];steps=owner.state/digest(operation)
    specfile=None
    try:
        prefix=[platform.read(steps/(str(i)+'.json')) for i in range(5)]
        if any(p.get('state')!='accepted' for p in prefix) or any((steps/(str(i)+'.json')).exists() for i in (5,6,7)):return path,record
        room=record['arguments']['roomId'];node=config.get('nodeId',config['hostId']);base='rooms/'+room+'/environment-agents'
        rows=[r for r in prefix[1]['result']['agents'] if r.get('node')==node]
        if len(rows)!=1 or rows[0].get('room')!=room or rows[0].get('coordinator')!=config['agentId']:return path,record
        agent=rows[0]['agent'];directory=Path(config['state'])/'room-origin-factory'/('room-origin-'+agent)
        specfile=directory/'spec.private.json';spec=platform.read(specfile);dispatchfile=directory/'dispatch.json';dispatch=platform.read(dispatchfile)
        credentialfile=directory.parent/('agent-credential-'+agent+'.json');credential=platform.read(credentialfile);old=spec['connectorConfig']
        fixed='room-origin:'+str(uuid5(UUID(agent),'host-initialization'))
        if (record.get('binding')!=owner.binding or spec.get('schema')!='lax-room-origin-local-spec/v1'
                or (spec['authorityId'],spec['hostId'],spec['nodeId'],spec['originRoomId'],spec['agentId'],spec['operationId'])!=
                   (config['authorityId'],config['hostId'],node,room,agent,fixed)
                or spec['parentRuntime']['agentId']!=config['agentId']
                or dispatch!={'state':'dispatching','operationId':fixed,'specSha256':sha(specfile)}
                or (credential['authorityId'],credential['agentId'])!=(config['authorityId'],agent) or old['token']!=credential['token']
                or any(old.get(k) is not None for k in ('sandbox','approvalPolicy'))):return path,record
        wires=[('POST',base,{'operationId':operation+':allocate'}),('GET',base,None),
            ('POST',base+'/'+node+'/enroll',{'operationId':fixed+':enroll','enrollmentCredential':credential['token']}),
            ('GET','agents/'+agent+'/role',None),('GET','principals/'+agent,None)]
        if any(p.get('wireDigest')!=digest({'method':m,'path':route,'body':body}) for p,(m,route,body) in zip(prefix,wires)):return path,record
        diagnostic=None
        for file in sorted(owner.state.parent.glob(owner.state.name+'-diagnostic-*-blocked.json')):
            value=platform.read(file);payload=value.get('payload',{});receipt=value.get('receipt',{})
            if (value.get('accepted') is True and payload.get('note')==GUARD and payload.get('state')=='blocked'
                    and payload.get('originalOperation')=='room-origin:'+owner.state.name
                    and receipt.get('coordinatorId')==config['agentId'] and receipt.get('status')==payload
                    and receipt.get('revision')==payload.get('revision')):diagnostic=file;break
        if diagnostic is None:return path,record
        files=[path,specfile,dispatchfile,credentialfile,diagnostic,*[steps/(str(i)+'.json') for i in range(5)]]
        pins={str(p):sha(p) for p in files};planfile=directory/'windows-initial-configuration-successor.json'
        if planfile.exists():
            plan=platform.read(planfile)
            platform.require(plan.get('originalFiles')==pins and plan.get('binding')==owner.binding
                and plan.get('operationId')==operation and plan.get('sourceHashes')==SOURCES
                and Path(plan['spec']['path']).parent==directory and sha(plan['spec']['path'])==plan['spec']['sha256'],
                'Original Windows pre-resident successor evidence changed')
        else:
            from .room_session_files import host_policy,approved_initial_permissions
            policy,_=host_policy(config);selection=config['roomOriginPolicy'];raw=platform.read(selection['path'],selection['sha256'])
            platform.require(raw['schema']=='lax-windows-room-parent-policy/v2','Independent real V2 parent acceptance required')
            evidence=platform.inspect_parent(Path(selection['path']),expected_policy_sha256=selection['sha256'])
            binding={k:spec[k] for k in ('authorityId','hostId','agentId','originRoomId','operationId')}
            try:platform._scope(binding,old,evidence)
            except platform.Held as error:
                if str(error)!=GUARD:raise
            else:return path,record
            artifacts=('windows-resident-original.json','connector-initial.private.json','windows-state-intent.json',
                'windows-state-prepared.json','native-initialization-intent.json','resident-initialization-accepted.json','session-config.private.json')
            platform.require(not any((directory/n).exists() for n in artifacts)
                and not (Path(policy['root'])/agent).exists()
                and not any(directory.glob('host-result-*.json')),'Original resident/native phase is not proven prelaunch')
            adapter._native_matches(evidence['sharedNative'],spec['nativeIdentity'])
            platform.require(policy['operatingInstructions']==spec['operatingInstructions']
                and policy['appServerManifestSha256']==spec['nativeHostManifestSha256']
                and all(old.get(k)==policy[k] for k in ('model','effort'))
                and old['state']==str(Path(policy['root'])/agent/'state')
                and old['workspace']==str(Path(policy['root'])/agent/'home/work'),'Original approved child contract differs')
            new=copy.deepcopy(spec);new['connectorConfig'].update(approved_initial_permissions(config,old,policy))
            new['parentRuntime']={**spec['parentRuntime'],'pid':evidence['parentRuntime']['pid'],
                'identity':evidence['parentRuntime'],'roomOriginPolicy':selection}
            fingerprint=platform.digest(platform.canonical(new));file=directory/('spec-windows-successor-'+fingerprint+'.private.json')
            if file.exists():platform.require(platform.read(file)==new,'Original candidate specification differs')
            else:platform.once(file,new)
            adapter._load(file,fingerprint) # Full maintained CURRENT-parent/V2/guide check, read-only.
            plan={'schema':'lax-room-initial-configuration-successor/v1','binding':owner.binding,'operationId':operation,
                'originalFiles':pins,'sourceHashes':SOURCES,'positiveGuard':{'reason':GUARD,'phase':'before-resident-seal','threadStartIssued':False},
                'spec':{'path':str(file),'sha256':fingerprint}}
            platform.once(planfile,plan)
        target=journal_path(owner.state,operation)
        value={**record,'state':'intent','configurationSuccessor':plan,'windowsConfigurationRecovery':True};value.pop('result',None)
        if target.exists():
            prior=platform.read(target)
            platform.require(all(prior.get(k)==value.get(k) for k in ('operationId','binding','tool','arguments','configurationSuccessor','windowsConfigurationRecovery')),
                'Original Windows configuration workflow successor differs');value=prior
        return target,value
    except (OSError,KeyError):
        if specfile is not None and specfile.exists():raise # A held spec is never silently replaced.
        return path,record
