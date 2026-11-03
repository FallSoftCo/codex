"""One local room-origin agent; no per-room native daemon or historical replay."""
import hashlib
import importlib
import json
import secrets
import sys
from pathlib import Path
from uuid import UUID, uuid5
from .journal import saved
from .runtime_files import state_directory
from .runtime_files import exclusive_lock
from .room_host_provision import HostProvisionUnconfirmed


def origin_configuration(config, *, agent, name, room, credential, state, workspace, operating_instructions=None):
    """Fresh role/context contract, not a filtered clone of a Global agent."""
    from .room_tools import TOOLS
    from .room_participation import with_policy
    approved = ('runtimeMode','authorityId','hostId','hollywoodUrl','binary','codexHome',
                'model','effort','sandbox','approvalPolicy','nativeServer','serviceMemoryMaxBytes')
    value = {key: config[key] for key in approved if key in config}
    refs = list(operating_instructions or [])
    instructions = with_policy('You are ' + name + ', a persistent room-owned local contributor. '
        'Your immutable room origin is ' + room + '. Own relevant local responsibilities there; '
        'you are not an enterprise Global coordinator or a relay for every human message. '
        'Use the existing shared native app-server and source-addressed Hollywood conversation. '
        'Work on this local host; coordinate cross-host work through addressed Hollywood peers, never SSH. '
        'No historical tasks are resumed by initialization. Preserve original receipts, unknown '
        'effects, private audiences and deliberate stops. Full local execution is authorized '
        'for assigned work, not unrelated business actions. Publish important progress, questions '
        'and answers in their original room/audience; only explicitly private coordination is private. '
        'Before host work read the approved host operating instructions: ' +
        ', '.join(item['path'] + ' SHA256 ' + item['sha256'] for item in refs) + '. These are host guidance, not another agent\'s tasks/history or a business-action grant.')
    value.update(agentId=agent, nativeName=name, token=credential, originRoomId=room,
                 rooms=[{'roomId': room, 'after': 0}], state=str(state), workspace=str(workspace),
                 instructions=instructions, conversationResumeInstructions={'baseInstructions': instructions},
                 conversationDynamicTools=TOOLS)
    value['hostOperatingInstructions'] = refs
    return value


async def provision(transport, arguments, operation):
    config = transport.owner.host_config
    room = str(UUID(arguments['roomId']))
    node = str(UUID(config.get('nodeId', config['hostId'])))
    state = Path(config['state'])/'room-origin-factory'
    state_directory(state, parents=True, exist_ok=True)
    key = str(uuid5(UUID(room), 'room-agent:' + node))
    with (state/(key + '.lock')).open('a') as lock:
        exclusive_lock(lock)
        return await _provision_locked(transport, arguments, operation)


async def _provision_locked(transport, arguments, operation):
    owner = transport.owner
    config = owner.host_config
    supervisor = getattr(owner, 'session_supervisor', None)
    if supervisor is None or supervisor.config != config:
        raise PermissionError('Initialize only in this original resident host supervisor; no external bootstrap/service')
    room = str(UUID(arguments['roomId']))
    node = str(UUID(config.get('nodeId', config['hostId'])))
    base = 'rooms/' + room + '/environment-agents'
    await transport.http('POST', base, {'operationId': operation + ':allocate'})
    inventory = await transport.http('GET', base)
    slot = next((a for a in inventory['agents'] if a['node'] == node), None)
    if not slot or slot['coordinator'] != config['agentId']:
        raise PermissionError('This exact enrolled environment is not an initializer for the room')
    agent = str(UUID(slot['agent']))
    fixed = 'room-origin:' + str(uuid5(UUID(agent), 'host-initialization'))
    factory_state = Path(config['state'])/'room-origin-factory'
    state_directory(factory_state, parents=True, exist_ok=True)
    directory = factory_state / ('room-origin-' + agent)
    state_directory(directory, parents=True, exist_ok=True)
    spec_file = directory / 'spec.private.json'
    dispatch = directory / 'dispatch.json'
    spec = json.loads(spec_file.read_text()) if spec_file.exists() else None
    credential_file = factory_state / ('agent-credential-' + agent + '.json')
    if spec:
        if (spec['authorityId'], spec['originRoomId'], spec['agentId'], spec['nodeId']) != (config['authorityId'], room, agent, node):
            raise HostProvisionUnconfirmed('Original room-origin specification differs')
        if not credential_file.exists():
            raise HostProvisionUnconfirmed('Original local credential unavailable; do not mint a replacement')
    else:
        from .room_session_files import host_policy
        policy, manifest = host_policy(config)
        manifest_path = Path(config['nativeServer']['manifest'])
        manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        operating = policy['operatingInstructions']
        if not credential_file.exists():
            saved(credential_file, {'authorityId': config['authorityId'], 'agentId': agent,
                                    'token': secrets.token_urlsafe(40)})
    credential = json.loads(credential_file.read_text())
    if (credential['authorityId'], credential['agentId']) != (config['authorityId'], agent):
        raise PermissionError('Original room credential identity changed')
    # Fixed step order is retained even when a prior host spec exists. Reopened
    # administrative workflows must never shift old HTTP step identities.
    await transport.http('POST', base + '/' + node + '/enroll',
        {'operationId': fixed + ':enroll', 'enrollmentCredential': credential['token']})
    role = await transport.http('GET', 'agents/' + agent + '/role')
    principal = await transport.http('GET', 'principals/' + agent)
    if role.get('home_room') != room or role.get('primary_role') != 'room-agent':
        raise PermissionError('Canonical immutable room-origin role required')
    if spec is None:
        home = Path(policy['root']) / agent
        connector = origin_configuration(config, agent=agent, name=principal['name'], room=room,
            credential=credential['token'], state=home/'state', workspace=home/policy.get('workspaceRelative','work'), operating_instructions=operating)
        spec = {'schema': 'lax-room-origin-local-spec/v1', 'operationId': fixed,
            'authorityId': config['authorityId'], 'originRoomId': room, 'agentId': agent,
            'hostId': config['hostId'], 'nodeId': node, 'connectorConfig': connector,
            'nativeHostManifestSha256': manifest_sha,
            'purpose': role['purpose'], 'nativeIdentity':policy['nativeIdentity'],
            'operatingInstructions': operating,
            'parentRuntime':{'agentId':config['agentId'],'pid':__import__('os').getpid(),'roomOriginPolicy':config['roomOriginPolicy']}}
        saved(spec_file, spec)
    platform = {'linux': 'linux', 'darwin': 'macos', 'win32': 'windows'}.get(sys.platform)
    if not platform:
        raise PermissionError('No approved local platform factory; no private daemon fallback')
    try:
        adapter = importlib.import_module('.room_factory_' + platform, package=__package__)
    except ModuleNotFoundError as error:
        raise PermissionError('Maintained shared-native platform adapter is not installed: ' + platform) from error
    expected = hashlib.sha256(spec_file.read_bytes()).hexdigest()
    prior = json.loads(dispatch.read_text()) if dispatch.exists() else None
    if prior and prior.get('specSha256') != expected:
        raise HostProvisionUnconfirmed('Original room factory dispatch specification changed')
    if not prior:
        saved(dispatch, {'state': 'dispatching', 'operationId': fixed, 'specSha256': expected})
    transport.accepted_writes = True
    result_file = directory/('host-result-' + hashlib.sha256(operation.encode()).hexdigest() + '.json')
    if result_file.exists():
        result = json.loads(result_file.read_text())
    else:
        try:
            result = await adapter.provision_local(spec_file, directory, inspect=prior is not None,
                                                   expected_spec_sha256=expected)
        except HostProvisionUnconfirmed as error:
            result = {**{k: spec[k] for k in ('operationId','authorityId','originRoomId','agentId','hostId')},
                'state': 'unknown', 'reason': str(error)[:1000]}
        if any(result.get(k) != spec[k] for k in ('operationId', 'authorityId', 'originRoomId', 'agentId', 'hostId')):
            raise HostProvisionUnconfirmed('Original platform initialization receipt differs')
        saved(result_file, result)
    saved(dispatch, {'state': result['state'], 'operationId': fixed, 'specSha256': expected})
    current = await transport.http('GET', base)
    slot = next(a for a in current['agents'] if a['node'] == node)
    receipt = None
    if result['state'] == 'ready':
        supervisor.attach(result)
        receipt = {'nativeThreadId': result['nativeThreadId'], 'nativeHostId': node,
            'appServerManifestSha256': result['appServerManifestSha256'], 'sharedAppServer': True}
    await transport.http('POST', base + '/' + node + '/report',
        {'operationId': operation + ':report', 'revision': slot['revision'],
         'state': 'provisioning' if receipt else result['state'],
         'note': result.get('reason') or 'Host accepted; awaiting fresh original native runtime observation',
         'receipt': receipt})
    return await transport.http('GET', base)
