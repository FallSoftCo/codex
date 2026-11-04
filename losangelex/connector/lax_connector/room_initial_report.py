"""Bounded initialization report keys; source-proven SDK250 input successor.

API180 RoomAgentReport validates <=128 characters BEFORE invoke/domain/NATS.
Only its exact oversized configuration-stage report can be superseded here.
Receipt absence/403 and generic HTTP failures are never non-admission proof.
No platform adapter, native RPC, session attach or execution replay in this module.
"""
import hashlib,json
from pathlib import Path
from uuid import UUID
from .room_initial_configuration import load,sha
from .room_host_provision import HostProvisionUnconfirmed

CONTRACT={'schema':'hollywood180-room-agent-report-input/v1','maxOperationCharacters':128,
    'serverSourceSha256':'6611061d05c484e42ec823003c59cb336982aa4d8efccf5bd8287a79926f0788',
    'validationBeforeInvoke':True}
NOTE='Host accepted; awaiting fresh original native runtime observation'


def report_id(original):
    if not isinstance(original,str) or not original:raise ValueError('Original report identity required')
    return original if len(original)<=128 else 'room-report:v1:'+hashlib.sha256(original.encode()).hexdigest()


def journal_path(state,operation):
    return Path(state)/('report-recovery-'+str(UUID(operation.removeprefix('native-admin:')))+'.json')


def slot(inventory,room,node,agent,actor):
    rows=[r for r in inventory.get('agents',[]) if r.get('node')==node]
    if (inventory.get('roomId')!=room or len(rows)!=1 or rows[0].get('room')!=room
            or rows[0].get('agent')!=agent or rows[0].get('coordinator')!=actor
            or type(rows[0].get('revision')) is not int or rows[0]['revision']<1):
        raise HostProvisionUnconfirmed('Original report canonical room/home/actor differs')
    return rows[0]


def select(owner,path,record):
    from .room_administration import FACTORY_TOOL,digest
    if (record.get('tool')!=FACTORY_TOOL or not record.get('configurationSuccessor')
            or record['state'] not in ('intent','unconfirmed')):return path,record
    plan=record['configurationSuccessor'];operation=record['operationId']
    if operation!='native-admin:'+str(UUID(operation.removeprefix('native-admin:'))):return path,record
    directory=owner.state/digest(operation)/('initial-configuration-'+plan['spec']['sha256']);file=directory/'6.json'
    if not file.exists():return path,record
    old=load(file);legacy=operation+':initial-config:'+plan['spec']['sha256']+':report'
    if old.get('operationId')!=legacy or len(legacy)!=136:return path,record
    if old.get('state')!='sending':raise HostProvisionUnconfirmed('Oversized report has contradictory acceptance; inspect original')
    if record.get('binding')!=owner.binding or plan.get('binding')!=owner.binding or plan.get('operationId')!=operation:
        raise HostProvisionUnconfirmed('Original report workflow binding differs')
    specfile=Path(plan['spec']['path']);spec=load(specfile);factory=specfile.parent
    if sha(specfile)!=plan['spec']['sha256']:raise HostProvisionUnconfirmed('Original report spec changed')
    suffix='-initial-successor-'+plan['spec']['sha256']
    resultfile=factory/('host-result-'+hashlib.sha256(operation.encode()).hexdigest()+suffix+'.json')
    dispatchfile=factory/('dispatch'+suffix+'.json');result=load(resultfile);dispatch=load(dispatchfile)
    acceptedfile=factory/'native-initialization-accepted.json';accepted=load(acceptedfile)
    intentfile=factory/'native-initialization-intent.json';intent=load(intentfile)
    config=spec['connectorConfig'];contextfile=Path(config['state'])/'native-context.json';context=load(contextfile)
    sessionfile=Path(result['sessionConfigPath']);session=load(sessionfile)
    thread=result.get('nativeThreadId')
    if not isinstance(thread,str) or str(UUID(thread))!=thread:
        raise HostProvisionUnconfirmed('Original accepted native thread identity is missing')
    scope={k:spec[k] for k in ('operationId','authorityId','originRoomId','agentId','hostId')}
    if (any(result.get(k)!=v for k,v in scope.items()) or result.get('state')!='ready' or result.get('sharedAppServer') is not True
            or result.get('modelTurnsRequested')!=0 or accepted.get('state')!='ready' or context!=accepted
            or accepted.get('nativePermissionsPersisted') is not True
            or accepted.get('nativeThreadId')!=result.get('nativeThreadId') or accepted.get('modelTurnsRequested')!=0
            or session!={**config,'nativeThreadId':result['nativeThreadId']} or sha(sessionfile)!=result['sessionConfigSha256']
            or dispatch!={'state':'ready','operationId':spec['operationId'],'specSha256':sha(specfile)}
            or any(intent.get('binding',{}).get(k)!=v for k,v in {**scope,'nodeId':spec['nodeId'],'specSha256':sha(specfile)}.items())
            or intent.get('nativeIdentity')!=spec['nativeIdentity']
            or accepted.get('binding',{}).get('authorityId')!=spec['authorityId']
            or accepted.get('binding',{}).get('agentId')!=spec['agentId']):
        raise HostProvisionUnconfirmed('Original native initialization is not conclusively accepted; no report correction')
    manifest=load(config['nativeServer']['manifest'])
    if (sha(config['nativeServer']['manifest'])!=spec['nativeHostManifestSha256']
            or result['appServerManifestSha256']!=spec['nativeHostManifestSha256']
            or accepted['binding'].get('codexHome')!=config['codexHome'] or accepted['binding'].get('nativeState')!=manifest['state']):
        raise HostProvisionUnconfirmed('Original native report binding differs')
    prefix=load(directory/'5.json');room=spec['originRoomId'];node=spec['nodeId'];agent=spec['agentId'];base='rooms/'+room+'/environment-agents'
    if (prefix.get('state')!='accepted' or prefix.get('wireDigest')!=digest({'method':'GET','path':base,'body':None})
            or (spec['authorityId'],spec['hostId'],spec['parentRuntime']['agentId'])!=
               (owner.host_config['authorityId'],owner.host_config['hostId'],owner.host_config['agentId'])):
        raise HostProvisionUnconfirmed('Original report prefix/home differs')
    prior=slot(prefix['result'],room,node,agent,owner.host_config['agentId'])
    receipt={'nativeThreadId':result['nativeThreadId'],'nativeHostId':node,
             'appServerManifestSha256':result['appServerManifestSha256'],'sharedAppServer':True}
    payload={'operationId':legacy,'revision':prior['revision'],'state':'provisioning','note':NOTE,'receipt':receipt}
    if (old.get('wireDigest')!=digest({'method':'POST','path':base+'/'+node+'/report','body':payload})
            or old.get('method')!='POST' or old.get('path')!=base+'/'+node+'/report'):
        raise HostProvisionUnconfirmed('Original oversized report wire differs')
    files=[path,file,directory/'5.json',specfile,resultfile,dispatchfile,acceptedfile,intentfile,contextfile,sessionfile]
    proof={'schema':'lax-room-report-input-successor/v1','binding':owner.binding,'operationId':operation,
        'validationContract':CONTRACT,'originalOperationId':legacy,'originalWireDigest':old['wireDigest'],
        'originalFiles':{str(p):sha(p) for p in files},'reportOperationId':report_id(legacy),
        'roomId':room,'nodeId':node,'agentId':agent,'receipt':receipt,'nativeIdentity':spec['nativeIdentity']}
    target=journal_path(owner.state,operation);value={**record,'state':'intent','reportSuccessor':proof};value.pop('result',None)
    if target.exists():
        previous=load(target)
        if any(previous.get(k)!=value.get(k) for k in ('binding','operationId','tool','arguments','configurationSuccessor','reportSuccessor')):
            raise HostProvisionUnconfirmed('Original report successor evidence changed')
        value=previous
    return target,value


async def finish(transport):
    """Only canonical GET/report/receipt reads; no enrollment/native/attach calls."""
    proof=transport.workflow['reportSuccessor'];config=transport.owner.host_config
    from .room_session_files import host_policy
    policy,_=host_policy(config)
    if (policy['appServerManifestSha256']!=proof['receipt']['appServerManifestSha256']
            or policy['nativeIdentity']!=proof['nativeIdentity']):
        raise HostProvisionUnconfirmed('Current protected parent/native policy differs')
    base='rooms/'+proof['roomId']+'/environment-agents'
    # Fresh read, not a cached pre-POST snapshot: a lost ACK/denied command read
    # can settle ONLY by positively matching canonical original native evidence.
    current=await transport.owner.request('GET',base)
    own=slot(current,proof['roomId'],proof['nodeId'],proof['agentId'],config['agentId'])
    if own.get('receipt') is not None:
        if own['receipt']!=proof['receipt']:raise HostProvisionUnconfirmed('Canonical native receipt differs; never overwrite')
        return {**current,'reportDisposition':'matching-canonical-receipt-read'}
    current=await transport.http('GET',base)
    own=slot(current,proof['roomId'],proof['nodeId'],proof['agentId'],config['agentId'])
    if own.get('receipt') is not None:
        if own['receipt']!=proof['receipt']:raise HostProvisionUnconfirmed('Canonical native receipt changed during inspection')
        return {**current,'reportDisposition':'matching-canonical-receipt-read'}
    await transport.http('POST',base+'/'+proof['nodeId']+'/report',{'operationId':proof['reportOperationId'],
        'revision':own['revision'],'state':'provisioning','note':NOTE,'receipt':proof['receipt']})
    return await transport.http('GET',base)
