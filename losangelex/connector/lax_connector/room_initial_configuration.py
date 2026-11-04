"""One explicit successor for a source-proven failed Mac PRELAUNCH guard.

Not generic completed-workflow retry. Keep the original completed workflow,
spec, blocked dispatch/result and accepted report wire immutable. Only this exact
maintained validator's positive failure, before its lock/files/native boundary,
can certify the original never-started operation. Missing files alone never can.
"""
import copy,hashlib,json,os
from pathlib import Path
from .runtime_files import private_file

GUARD='Fresh declared initial room configuration required'
VALIDATOR_SHA256='aeef4b5170312bf1e1f95a623664249c89f43261080db9f229c30565ce9c9f8b'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    private_file(path)
    return json.loads(Path(path).read_text())


def journal_path(state,operation):
    from uuid import UUID
    identity=str(UUID(operation.removeprefix('native-admin:')))
    return Path(state)/('configuration-recovery-'+identity+'.json')


def original(owner,path,record):
    from .room_administration import FACTORY_TOOL,digest
    from . import room_factory_macos as mac
    if (record.get('state')!='completed' or record.get('tool')!=FACTORY_TOOL
            or record.get('binding')!=owner.binding or sha(mac.__file__)!=VALIDATOR_SHA256):return None
    # This is deliberately Mac-specific legacy evidence, not a Linux/Windows
    # absence classifier. Their independent original admission fences stay intact.
    config=owner.host_config;room=record['arguments']['roomId'];operation=record['operationId']
    steps=owner.state/digest(operation)
    prefix=[load(steps/(str(i)+'.json')) for i in range(8)]
    if any(p.get('state')!='accepted' for p in prefix):return None
    node=config.get('nodeId',config['hostId']);base='rooms/'+room+'/environment-agents'
    rows=[r for r in prefix[1]['result']['agents'] if r.get('node')==node]
    if len(rows)!=1 or rows[0].get('room')!=room or rows[0].get('coordinator')!=config['agentId']:return None
    agent=rows[0]['agent'];directory=Path(config['state'])/'room-origin-factory'/('room-origin-'+agent)
    specfile=directory/'spec.private.json';spec=load(specfile)
    resultfile=directory/('host-result-'+hashlib.sha256(operation.encode()).hexdigest()+'.json')
    result=load(resultfile);dispatch=load(directory/'dispatch.json')
    child=spec['connectorConfig'];credential=directory.parent/('agent-credential-'+agent+'.json');secret=load(credential)
    from uuid import UUID,uuid5
    scope={k:spec[k] for k in ('operationId','authorityId','originRoomId','agentId','hostId')}
    if (spec.get('schema')!='lax-room-origin-local-spec/v1' or spec['authorityId']!=config['authorityId']
            or spec['originRoomId']!=room or spec['agentId']!=agent or spec['hostId']!=node or spec['nodeId']!=node
            or spec['operationId']!='room-origin:'+str(uuid5(UUID(agent),'host-initialization'))
            or any(child.get(k)!=spec[k] for k in ('authorityId','hostId','agentId','originRoomId'))
            or spec['parentRuntime']['agentId']!=config['agentId'] or result.get('schema')!='lax-room-origin-host-result/v1'
            or any(result.get(k)!=v for k,v in scope.items()) or result.get('state')!='blocked' or result.get('reason')!=GUARD
            or result.get('modelTurnsRequested')!=0 or result.get('nativeThreadId')
            or dispatch!={'state':'blocked','operationId':spec['operationId'],'specSha256':sha(specfile)}
            or secret.get('authorityId')!=config['authorityId'] or secret.get('agentId')!=agent
            or child.get('token')!=secret.get('token') or not secret.get('token')
            or any(child.get(k) is not None for k in ('sandbox','approvalPolicy'))):return None
    prior=[r for r in prefix[5]['result']['agents'] if r.get('node')==node and r.get('agent')==agent]
    if len(prior)!=1:return None
    wires=[('POST',base,{'operationId':operation+':allocate'}),('GET',base,None),
        ('POST',base+'/'+node+'/enroll',{'operationId':spec['operationId']+':enroll','enrollmentCredential':secret['token']}),
        ('GET','agents/'+agent+'/role',None),('GET','principals/'+agent,None),('GET',base,None),
        ('POST',base+'/'+node+'/report',{'operationId':operation+':report','revision':prior[0]['revision'],
            'state':'blocked','note':GUARD,'receipt':None}),('GET',base,None)]
    if any(p.get('wireDigest')!=digest({'method':m,'path':p0,'body':b}) for p,(m,p0,b) in zip(prefix,wires)):return None
    files=[path,specfile,resultfile,directory/'dispatch.json',credential,*[steps/(str(i)+'.json') for i in range(8)]]
    return directory,spec,{str(p):sha(p) for p in files}


def candidate(owner,path,record):
    try:facts=original(owner,path,record)
    except (OSError,KeyError,ValueError,TypeError):return None
    if facts is None:return None
    directory,spec,pins=facts;planfile=directory/'initial-configuration-successor.json'
    if planfile.exists():
        plan=load(planfile)
        if (plan.get('schema')!='lax-room-initial-configuration-successor/v1' or plan.get('originalFiles')!=pins
                or plan.get('binding')!=owner.binding or plan.get('operationId')!=record['operationId']
                or plan.get('positiveGuard')!={'reason':GUARD,'sourceSha256':VALIDATOR_SHA256,'threadStartIssued':False}
                or Path(plan['spec']['path']).parent!=directory or sha(plan['spec']['path'])!=plan['spec']['sha256']):
            raise ValueError('Original prelaunch successor evidence changed')
        return plan
    from .room_session_files import host_policy,approved_initial_permissions
    from . import room_factory_macos as mac
    # Original accepted BLOCKED guard is positive evidence; absence below is only
    # corroboration. Refuse any later claim/files/native state, even known unstarted.
    old=spec['connectorConfig'];selected=spec['parentRuntime']['roomOriginPolicy']
    helper=mac.MacAgentFiles(selected['path'],selected['sha256'],native_identity=spec['nativeIdentity'],
                            parent_identity=spec['parentRuntime'].get('identity'))
    try:helper.validate_parent(old)
    except mac.Hold as error:
        if str(error)!=GUARD:return None
    else:return None
    root=Path(helper.policy['agentRoot'])
    if any(p.exists() or p.is_symlink() for p in (root/spec['agentId'],root/(spec['agentId']+'.claim.json'),
            directory/'native-initialization-intent.json',directory/'native-initialization-accepted.json',directory/'platform-files.json')):
        return None
    policy,_=host_policy(owner.host_config)
    if (policy['nativeIdentity']!=spec['nativeIdentity'] or policy['operatingInstructions']!=spec['operatingInstructions']
            or policy['appServerManifestSha256']!=spec['nativeHostManifestSha256']
            or any(old.get(k)!=policy[k] for k in ('model','effort'))
            or old.get('state')!=str(Path(policy['root'])/spec['agentId']/'state')
            or old.get('workspace')!=str(Path(policy['root'])/spec['agentId']/'work')):return None
    successor=copy.deepcopy(spec)
    successor['connectorConfig'].update(approved_initial_permissions(owner.host_config,old,policy))
    successor['parentRuntime']={**spec['parentRuntime'],'pid':os.getpid(),
        'identity':policy['parentRuntimeIdentity'],'roomOriginPolicy':owner.host_config['roomOriginPolicy']}
    selection=successor['parentRuntime']['roomOriginPolicy']
    current=mac.MacAgentFiles(selection['path'],selection['sha256'],native_identity=spec['nativeIdentity'],
                             parent_identity=policy['parentRuntimeIdentity'])
    raw=json.dumps(successor,indent=2).encode()
    current.verify_input(successor['connectorConfig'],successor,raw_spec=raw,expected_spec_sha256=hashlib.sha256(raw).hexdigest())
    mac.guides(successor['connectorConfig'],successor['operatingInstructions'])
    fingerprint=hashlib.sha256(raw).hexdigest();file=directory/('spec-initial-successor-'+fingerprint+'.private.json')
    return {'schema':'lax-room-initial-configuration-successor/v1','binding':owner.binding,
        'operationId':record['operationId'],'originalFiles':pins,
        'positiveGuard':{'reason':GUARD,'sourceSha256':VALIDATOR_SHA256,'threadStartIssued':False},
        'spec':{'path':str(file),'sha256':fingerprint},'_newSpec':raw}


def available(config,state,thread,operation):
    from types import SimpleNamespace
    from uuid import UUID
    try:
        state=Path(state);path=state/('workflow-'+str(UUID(operation.removeprefix('native-admin:')))+'.json')
        record=load(path);owner=SimpleNamespace(host_config=config,state=state,
            binding={'authority':config['authorityId'],'agent':config['agentId'],'thread':thread})
        recovery=journal_path(state,operation)
        if recovery.exists() and load(recovery).get('state') in ('completed','rejected'):return False
        return candidate(owner,path,record) is not None
    except Exception:return False # Read-only eligibility never dispatches on unreadable evidence.


def select(owner,path,record):
    """Called only for the SAME completed FACTORY after current admin validation."""
    plan=candidate(owner,path,record)
    if plan is None:return path,record
    from . import room_factory_macos as mac
    raw=plan.pop('_newSpec',None);planfile=Path(plan['spec']['path']).parent/'initial-configuration-successor.json'
    if raw is not None:mac.save_raw_once(Path(plan['spec']['path']),raw);mac.save_once(planfile,plan)
    recovery=journal_path(owner.state,record['operationId'])
    value={**record,'state':'intent','configurationSuccessor':plan,'originalWorkflowSha256':sha(path)}
    value.pop('result',None) # In-memory successor, never overwrite original workflow.
    if recovery.exists():
        old=load(recovery)
        if any(old.get(k)!=value.get(k) for k in ('operationId','binding','tool','arguments','configurationSuccessor','originalWorkflowSha256')):
            raise ValueError('Original configuration recovery journal differs')
        value=old
    return recovery,value
