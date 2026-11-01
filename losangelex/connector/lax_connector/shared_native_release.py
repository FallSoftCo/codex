"""Pinned engine/client release preparation for an existing shared native host.

The operator drains and stops both declared services. Metadata publication starts
neither service and never replays native input. Existing context/profile/state
and the original service identities are retained.
"""
import base64
import hashlib
import json
import os
import pwd
from pathlib import Path
from . import service_observer as observer
from .rpc_shared import host_manifest,validate_host_manifest


def prepare(config,new_config,expected_manifest,expected_definition):
    value=host_manifest(config)
    path=Path(config['nativeServer']['manifest'])
    expected=Path('/var/lib/harness')/config['authorityId']/'native-hosts'/config['hostId']/'manifest.json'
    if path!=expected:
        raise ValueError('Shared engine upgrade requires its existing canonical host declaration')
    from .service_restart import file_hash
    before=path.read_bytes()
    if file_hash(path,0)[0]!=expected_manifest or hashlib.sha256(before).hexdigest()!=expected_manifest:
        raise ValueError('Original shared host declaration CAS changed')
    future={**value,'binary':new_config['binary']}
    validate_host_manifest(new_config,future)
    unit='lax-native-'+config['authorityId'].replace('-','')[:8]+'-'+config['hostId'].replace('-','')[:8]+'.service'
    if value['unit']!=unit or value['ownerAgentId']!=config['agentId']:
        raise ValueError('Shared host upgrade belongs to its original owner and unit')
    props=observer.properties(unit)
    if observer.unit_definition(props)!=expected_definition or props['ActiveState']!='active':
        raise ValueError('Original shared host unit changed or is not active')
    guardian=observer.process(int(props['MainPID']))
    uid=pwd.getpwnam(value['serviceUser']).pw_uid
    image=Path(value['binary']).stat()
    if (not guardian or guardian['uid']!=uid or guardian['controlGroup']!=props['ControlGroup']
            or (guardian['executableDevice'],guardian['executableInode'])!=(image.st_dev,image.st_ino)
            or props['User']!=value['serviceUser'] or props['KillMode']!='control-group'):
        raise ValueError('Original native daemon process identity differs')
    from .host_native import native_command
    command=(Path('/proc')/str(guardian['pid'])/'cmdline').read_bytes().rstrip(b'\0').decode().split('\0')
    if command!=native_command(value):
        raise ValueError('Original native daemon startup arguments differ')
    unit_path=Path(props['FragmentPath']);unit_before=unit_path.read_bytes()
    if unit_before.decode().count(value['binary'])!=1:
        raise ValueError('Native unit requires one exact binary occurrence')
    unit_after=unit_before.decode().replace(value['binary'],future['binary']).encode()
    state=Path(value['state']);info=state.stat()
    if state.is_symlink() or info.st_uid!=uid:
        raise ValueError('Original native state owner differs')
    targets=[]
    for target,old,new in ((path,before,(json.dumps(future,indent=2)+'\n').encode()),
                           (unit_path,unit_before,unit_after)):
        targets.append({'path':str(target),'uid':0,'mode':target.stat().st_mode&0o777,
                        'before':base64.b64encode(old).decode(),'after':base64.b64encode(new).decode()})
    return {'unit':unit,'guardian':guardian,'state':str(state),'stateIdentity':[info.st_dev,info.st_ino,info.st_uid],
            'oldManifestSha256':expected_manifest,'oldDefinitionSha256':expected_definition,
            'newManifestSha256':hashlib.sha256(base64.b64decode(targets[0]['after'])).hexdigest(),
            'modelsStarted':0},targets


def offline(plan):
    declaration=plan['sharedNativeUpgrade']
    props=observer.properties(declaration['unit'])
    if (props['ActiveState'] not in ('inactive','failed') or int(props['MainPID'])!=0
            or props['ControlGroup'] and observer.members(props['ControlGroup'])):
        raise ValueError('Shared engine transition requires its stopped empty native service')
    old=declaration['guardian'];current=observer.process(old['pid'])
    if current and current['start']==old['start']:
        raise ValueError('Original native daemon has not independently stopped')
    state=Path(declaration['state']);info=state.stat()
    if state.is_symlink() or [info.st_dev,info.st_ino,info.st_uid]!=declaration['stateIdentity']:
        raise ValueError('Original native context storage was replaced')
    # Full target bytes are checked by the existing prefix-CAS state validator.
    target=declaration['targets'][1]
    digest=observer.unit_definition(props)
    if digest not in {hashlib.sha256(base64.b64decode(target[k])).hexdigest() for k in ('before','after')}:
        raise ValueError('Native unit is outside its original paired release')
