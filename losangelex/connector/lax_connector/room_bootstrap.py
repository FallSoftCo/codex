"""Initialize one named native agent context before starting its resident service.

Identity, native database and original initialization receipt remain bound. This
is provisioning, not per-message execution: no user input, model turn, room post,
Hollywood executor or replacement context is created on an ordinary restart.
"""
from .runtime_files import state_directory
import argparse
import asyncio
from .runtime_files import exclusive_lock
import hashlib
import json
from pathlib import Path
from uuid import UUID
from .journal import saved
from .rpc_shared import native_client, host_manifest
from .room_tools import TOOLS
from .room_permissions import persist_new_thread, requested


async def initialize(config, *, recovery=None):
    if config.get('runtimeMode')!='room-conversation':raise ValueError('Explicit conversational provisioning required')
    authority=str(UUID(config['authorityId']));agent=str(UUID(config['agentId']))
    state=Path(config['state']);home=Path(config['codexHome']);workspace=Path(config['workspace'])
    if not all(p.is_absolute() for p in (state,home,workspace)) or not workspace.is_dir():
        raise ValueError('Original absolute agent paths and existing workspace required')
    if any(k in config for k in ('homes','tokens','installedPurposeRuntime')):
        raise ValueError('No implicit purpose-context adoption')
    name=config['nativeName'].strip()
    if not name:raise ValueError('Meaningful native agent name required')
    native_state=Path(host_manifest(config)['state']) if config.get('nativeServer') is not None else state/'native'
    binding={'authorityId':authority,'agentId':agent,'codexHome':str(home),'nativeState':str(native_state)}
    request={'cwd':str(workspace),'model':config['model'],**requested(config),'dynamicTools':TOOLS,
             'baseInstructions':config['instructions'],
             'config':{'model_reasoning_effort':config['effort'],'features.default_mode_request_user_input':True}}
    fingerprint=hashlib.sha256(json.dumps({'binding':binding,'name':name,'request':request},sort_keys=True,separators=(',',':')).encode()).hexdigest()
    state_directory(state, parents=True,exist_ok=True)
    with (state/'connector.lock').open('a') as lock:
        exclusive_lock(lock)
        file=state/'native-context.json'
        prior=json.loads(file.read_text()) if file.exists() else None
        recover_original=False
        if prior:
            if prior.get('binding')!=binding or prior.get('requestDigest')!=fingerprint:
                raise ValueError('Original native initialization differs; explicit upgrade required')
            if prior.get('state')=='ready':return prior
            safe_transport_phase=(prior.get('state') in ('connecting','transport-unavailable')
                                  and prior.get('threadStartAttempted') is False)
            if not safe_transport_phase:
                if recovery is None:
                    raise RuntimeError('Original native initialization requires reconciliation; no replacement context created')
                from .room_bootstrap_recovery import verify
                verify(recovery,file,prior,binding,fingerprint)
                recover_original=True
        record={'schema':'lax-room-native-context/v1','state':'connecting',
                'threadStartAttempted':False,'binding':binding,'requestDigest':fingerprint}
        if not recover_original:saved(file,record)
        turns=[]
        async def event(method,params):
            if method=='turn/started':turns.append(params)
        async def unsupported(*args):raise RuntimeError('No native execution expected during provisioning')
        rpc=native_client(config,event,unsupported)
        try:
            try:
                await rpc.start()
            except Exception as error:
                if not recover_original:
                    record.update(state='transport-unavailable',errorType=type(error).__name__)
                    saved(file,record)
                raise
            if recover_original:
                from .room_bootstrap_recovery import reconcile_empty
                await reconcile_empty(rpc,recovery,file,prior,record)
            record.update(state='creating',threadStartAttempted=True);saved(file,record)
            created=await rpc.call('thread/start',request)
            thread=created['thread']['id']
            record.update(state='created',nativeThreadId=thread);saved(file,record)
            effective=await persist_new_thread(rpc,thread,created,config)
            record.update(state='naming',nativeThreadId=thread);saved(file,record)
            # This is the real display name, not a dummy history item or a
            # settings toggle. Native naming persists an empty paginated context.
            await rpc.call('thread/name/set',{'threadId':thread,'name':name})
            if turns:raise RuntimeError('Unexpected native turn during initialization')
            record.update(state='ready',nativeName=name,modelTurnsRequested=0,nativePermissionsPersisted=True,effectivePermissions=effective);saved(file,record)
            return record
        finally:await rpc.close()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--recover-unstarted',type=Path)
    args=parser.parse_args();result=asyncio.run(initialize(json.loads(args.config.read_text()),recovery=args.recover_unstarted))
    print(json.dumps(result))

if __name__=='__main__':main()
