"""Prepare one logical Linux session in its EXISTING host process/account.

No sudo, OS account, systemd unit, subprocess or new native daemon is created.
The parent supervisor attaches ConversationalAgent after this once-only bootstrap.
"""
import json,os
from pathlib import Path
from .journal import saved
from .runtime_files import state_directory
from .room_session_files import validate_spec,digest_file
from .room_host_provision import HostProvisionUnconfirmed
from .room_bootstrap import initialize


def linux_process(identity):
    pid=identity['pid'];root=Path('/proc')/str(pid)
    # PID alone is not an incarnation. Pin the accepted start tick and image.
    data=(root/'stat').read_text().rsplit(')',1)[1].split()
    if int(data[19])!=identity['startTicks'] or (root/'exe').resolve()!=Path(identity['image']).resolve():
        raise PermissionError('Original shared native process incarnation changed')
    if root.stat().st_uid != identity['uid'] or identity['uid']!=os.geteuid():
        raise PermissionError('Original same-account native process owner differs')
    return dict(identity)


async def provision_local(spec_path,operation_dir,*,inspect,expected_spec_sha256):
    spec=validate_spec(spec_path,expected_spec_sha256);config=spec['connectorConfig']
    native=linux_process(spec['nativeIdentity'])
    for key in ('state','workspace'):state_directory(config[key],parents=True,exist_ok=True)
    intent=Path(config['state'])/'native-context.json'
    if inspect and not intent.exists():
        # An outer dispatch intent can precede actual native bootstrap. This is
        # a proven unstarted phase, not an unknown thread/start permission.
        pass
    elif intent.exists():
        original=json.loads(intent.read_text())
        if original.get('state')!='ready' and not (original.get('threadStartAttempted') is False and
                original.get('state') in ('connecting','transport-unavailable')):
            raise HostProvisionUnconfirmed('Original native context delivery requires reconciliation; no replacement thread')
    try:result=await initialize(config)
    except Exception as error:
        original=json.loads(intent.read_text()) if intent.exists() else {}
        if original.get('threadStartAttempted') is True:
            raise HostProvisionUnconfirmed('Original thread creation requires reconciliation') from error
        raise
    linux_process(native)
    if digest_file(config['nativeServer']['manifest'])!=spec['nativeHostManifestSha256']:
        raise HostProvisionUnconfirmed('Original native manifest changed during bootstrap')
    resident={**config,'nativeThreadId':result['nativeThreadId']}
    file=operation_dir/'session-config.private.json'
    if file.exists():
        if json.loads(file.read_text())!=resident:raise HostProvisionUnconfirmed('Original resident session config differs')
    else:saved(file,resident)
    return {'schema':'lax-room-origin-host-result/v1',
        **{k:spec[k] for k in ('operationId','authorityId','originRoomId','agentId','hostId')},
        'state':'ready','reason':None,'nativeThreadId':result['nativeThreadId'],
        'sharedAppServer':True,'appServerManifestSha256':spec['nativeHostManifestSha256'],
        'parentRuntimePid':os.getpid(),'nativeIdentity':native,
        'sessionConfigPath':str(file),'sessionConfigSha256':digest_file(file),'modelTurnsRequested':0}
