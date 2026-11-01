"""Host-local provisioning from an authenticated native room administrator.

Hollywood authorizes identity/membership only. The existing local LAX installer
owns the OS service and native context. An uncertain installer dispatch is only
inspected; it is never launched again by a retry or a new native tool call.
"""
from .runtime_files import state_directory
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from uuid import UUID, uuid4
from aiohttp import ClientSession, ClientTimeout
from .journal import saved
from .roles import administrator_available


class HostProvisionUnconfirmed(RuntimeError):
    pass


async def provision(transport,arguments,operation):
    owner=transport.owner;config=owner.host_config
    required=('hostId','binary','codexHome','model','effort','hollywoodUrl')
    if not config or any(not config.get(k) for k in required):
        raise PermissionError('This native context has no configured local provisioning host')
    if config.get('agentId')!=owner.config['agentId'] or config.get('authorityId')!=owner.config['authorityId']:
        raise PermissionError('Provisioning host belongs to another native agent')
    if not await asyncio.to_thread(administrator_available):
        raise PermissionError('Verified local host administration required')
    agent=str(UUID(arguments['agentId']));room=str(UUID(arguments['roomId']))
    if agent==owner.config['agentId']:raise ValueError('Provisioning cannot replace its own running owner')
    principal=await transport.http('GET','principals/'+agent)
    role=await transport.http('GET','agents/'+agent+'/role')
    detail=await transport.http('GET','rooms/'+room)
    if (role.get('principal')!=agent or role.get('authority')!=owner.config['authorityId']
            or detail.get('authorityId')!=owner.config['authorityId'] or detail.get('room',{}).get('id')!=room):
        raise ValueError('Host provisioning metadata belongs to another agent or room')
    member=next((a for a in detail['actors'] if a['id']==agent),None)
    if (principal.get('kind')!='agent' or not principal.get('active')
            or principal.get('authority')!=owner.config['authorityId']
            or not member or member.get('can_read') is not True):
        raise PermissionError('The existing agent must have current read membership in the selected room')
    credential_file=owner.state/('agent-credential-'+agent+'.json')
    if not credential_file.exists():
        raise ValueError('Original protected enrollment credential unavailable; reconcile that identity instead of creating a replacement')
    credential=json.loads(credential_file.read_text())
    if credential.get('agentId')!=agent or credential.get('authorityId')!=owner.config['authorityId']:
        raise PermissionError('Original enrollment credential belongs to another identity')
    # Verify the retained credential privately as that same agent before any
    # local account/unit is created. Do not expose credentials in tool output.
    async with ClientSession(timeout=ClientTimeout(total=15)) as session:
        async with session.get(config['hollywoodUrl'].rstrip('/')+'/hollywood/v3/principals/'+agent,
                headers={'Authorization':'Bearer '+credential['token'],
                         'X-Hollywood-Authority':owner.config['authorityId'],'X-Hollywood-Agent':agent}) as response:
            if response.status!=200:raise PermissionError('Original enrollment credential is not currently accepted')
            authenticated=await response.json()
            if (authenticated.get('id')!=agent or authenticated.get('authority')!=owner.config['authorityId']
                    or authenticated.get('kind')!='agent' or not authenticated.get('active')):
                raise PermissionError('Original enrollment credential identity differs')
    directory=owner.state/('host-'+str(UUID(operation.removeprefix('native-admin:'))))
    state_directory(directory, exist_ok=True)
    file=directory/'spec.private.json';dispatch=directory/'dispatch.json'
    prior=(dispatch.exists() or (directory/'initial-result.json').exists()
           or (directory/'inspect-result.json').exists() or any(directory.glob('inspection-*.json')))
    if file.exists():
        # Names, roles, SDK paths and the host manifest may legitimately advance.
        # The protected installer receipt, not a newly generated spec, decides
        # whether this exact original installation can be inspected.
        spec=json.loads(file.read_text())
        original={'runtimeMode':'room-conversation','authorityId':owner.config['authorityId'],
                  'agentId':agent,'hostId':str(UUID(config['hostId'])),
                  'rooms':[{'roomId':room,'after':0}],
                  'machineIdentity':hashlib.sha256(Path('/etc/machine-id').read_bytes()).hexdigest()}
        if any(spec.get(k)!=v for k,v in original.items()):
            raise HostProvisionUnconfirmed('Original host provisioning scope changed: '+operation)
    else:
        if prior:
            raise HostProvisionUnconfirmed('Original dispatched specification unavailable: '+operation)
        spec={'runtimeMode':'room-conversation','authorityId':owner.config['authorityId'],'agentId':agent,
          'hostId':str(UUID(config['hostId'])),'credential':credential['token'],
          'hollywoodUrl':config['hollywoodUrl'],'nativeName':principal['name'],'purpose':role['purpose'],
          # Send-time recipient snapshots prevent old pre-membership messages
          # becoming fresh instructions. Starting at zero retains any input
          # accepted for this member while its service was being provisioned.
          'rooms':[{'roomId':room,'after':0}],
          'machineIdentity':hashlib.sha256(Path('/etc/machine-id').read_bytes()).hexdigest(),
          'approvedModelAuthFile':str(Path(config['codexHome'])/'auth.json'),
          'binary':config['binary'],'interpreter':config.get('provisionInterpreter',sys.executable),
          'model':config['model'],'effort':config['effort']}
        if config.get('nativeServer') is not None:
            from .shared_account import request
            spec.update(nativeHostServer=True,nativeHostAttachment=request(config),executionProfile='unrestricted')
        saved(file,spec)
    command=['sudo','-n',spec['interpreter'],'-I','-B','-m','lax_connector.linux_worker','--spec',str(file)]
    if dispatch.exists():
        previous=json.loads(dispatch.read_text())
        if (previous.get('agentId'),previous.get('operationId'))!=(agent,operation):
            raise HostProvisionUnconfirmed('Original installer dispatch scope differs: '+operation)
        if previous.get('state')=='accepted':
            accepted=previous.get('receipt',{})
            if (accepted.get('authorityId'),accepted.get('agentId'))!=(spec['authorityId'],agent):
                raise HostProvisionUnconfirmed('Original installer acceptance scope differs: '+operation)
            return outcome(spec,room,previous['receipt'])
    if not prior:saved(dispatch,{'state':'dispatching','agentId':agent,'operationId':operation})
    # A local installation may already have created its account/unit even if its
    # response was lost. The generic workflow must retain this as unresolved.
    transport.accepted_writes=True
    async def execute(inspect):
        actual=command;pin=None;output=directory/'initial-result.json'
        if inspect:
            output=directory/('inspection-'+str(uuid4())+'.json')
            saved(output,{'state':'dispatching','originalSpecSha256':hashlib.sha256(file.read_bytes()).hexdigest()})
            actual=[*command,'--inspect']
        if inspect and sys.executable!=spec['interpreter']:
            # The current connector is only a selection, not root authority.
            # The privileged inspector validates/pins its accepted release and
            # NEVER uses it to run the original installer again.
            pin={'schema':'lax-factory-inspection-runtime/v1','ownerAgentId':owner.config['agentId'],
                 'authorityId':spec['authorityId'],'hostId':spec['hostId'],
                 'interpreter':sys.executable,'originalSpecSha256':hashlib.sha256(file.read_bytes()).hexdigest()}
            selected=directory/('inspection-runtime-'+hashlib.sha256(json.dumps(pin,sort_keys=True).encode()).hexdigest()+'.json')
            if selected.exists() and json.loads(selected.read_text())!=pin:
                raise HostProvisionUnconfirmed('Original maintenance selection differs: '+operation)
            if not selected.exists():saved(selected,pin)
            saved(output,{'state':'dispatching','runtime':pin})
            actual=['sudo','-n',pin['interpreter'],'-I','-B','-m','lax_connector.linux_worker',
                    '--spec',str(file),'--inspect','--inspection-owner',pin['ownerAgentId'],
                    '--expected-spec-sha256',pin['originalSpecSha256']]
        process=await asyncio.create_subprocess_exec(*actual,
            stdin=asyncio.subprocess.DEVNULL,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        out,err=await process.communicate()
        saved(output,{'returncode':process.returncode,'stderr':err.decode(errors='replace')[-4000:],
                      **({'runtime':pin} if pin else {})})
        if process.returncode:raise HostProvisionUnconfirmed('Original local provisioning requires inspection: '+operation)
        try:result=json.loads(out)
        except (ValueError,TypeError) as error:raise HostProvisionUnconfirmed('Original local provisioning reply unavailable: '+operation) from error
        if result.get('authorityId')!=spec['authorityId'] or result.get('agentId')!=agent:
            raise HostProvisionUnconfirmed('Original local provisioning identity mismatch: '+operation)
        if pin:
            accepted=result.get('maintenanceRuntime',{})
            if (any(accepted.get(k)!=v for k,v in pin.items())
                    or not accepted.get('acceptedReleaseOperation') or not accepted.get('acceptedReleaseDigest')):
                raise HostProvisionUnconfirmed('Original maintenance acceptance differs: '+operation)
            saved(output,{'state':'accepted','runtime':pin,'receipt':result})
        return result
    try:result=await execute(prior)
    except HostProvisionUnconfirmed:
        if prior:raise
        result=await execute(True)
    saved(dispatch,{'state':'accepted','agentId':agent,'operationId':operation,'receipt':result})
    return outcome(spec,room,result)


def outcome(spec,room,result):
    readiness=result.get('executionRegistration') or result.get('inspection',{}).get('executionRegistration',{})
    return {'agentId':spec['agentId'],'roomId':room,'hostId':spec['hostId'],'executionProvisioned':True,
            'executionReady':readiness.get('ready') is True,
            'worker':result,'note':'Local native service provisioned; this is not completion of any room task.'}
