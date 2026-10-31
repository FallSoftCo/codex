"""Initialize one named native agent context before starting its resident service.

Identity, native database and original initialization receipt remain bound. This
is provisioning, not per-message execution: no user input, model turn, room post,
Hollywood executor or replacement context is created on an ordinary restart.
"""
import argparse
import asyncio
import fcntl
import hashlib
import json
from pathlib import Path
from uuid import UUID
from .journal import saved
from .rpc import AppServer
from .room_tools import TOOLS


async def initialize(config):
    if config.get('runtimeMode')!='room-conversation':raise ValueError('Explicit conversational provisioning required')
    authority=str(UUID(config['authorityId']));agent=str(UUID(config['agentId']))
    state=Path(config['state']);home=Path(config['codexHome']);workspace=Path(config['workspace'])
    if not all(p.is_absolute() for p in (state,home,workspace)) or not workspace.is_dir():
        raise ValueError('Original absolute agent paths and existing workspace required')
    if any(k in config for k in ('homes','tokens','installedPurposeRuntime')):
        raise ValueError('No implicit purpose-context adoption')
    name=config['nativeName'].strip()
    if not name:raise ValueError('Meaningful native agent name required')
    binding={'authorityId':authority,'agentId':agent,'codexHome':str(home),'nativeState':str(state/'native')}
    request={'cwd':str(workspace),'model':config['model'],'sandbox':config['sandbox'],
             'approvalPolicy':config.get('approvalPolicy','never'),'dynamicTools':TOOLS,
             'baseInstructions':config['instructions'],
             'config':{'model_reasoning_effort':config['effort'],'features.default_mode_request_user_input':True}}
    fingerprint=hashlib.sha256(json.dumps({'binding':binding,'name':name,'request':request},sort_keys=True,separators=(',',':')).encode()).hexdigest()
    state.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (state/'connector.lock').open('a') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        file=state/'native-context.json'
        prior=json.loads(file.read_text()) if file.exists() else None
        if prior:
            if prior.get('binding')!=binding or prior.get('requestDigest')!=fingerprint:
                raise ValueError('Original native initialization differs; explicit upgrade required')
            if prior.get('state')!='ready':
                raise RuntimeError('Original native initialization requires reconciliation; no replacement context created')
            return prior
        record={'schema':'lax-room-native-context/v1','state':'creating','binding':binding,'requestDigest':fingerprint}
        saved(file,record)
        turns=[]
        async def event(method,params):
            if method=='turn/started':turns.append(params)
        async def unsupported(*args):raise RuntimeError('No native execution expected during provisioning')
        rpc=AppServer(config['binary'],home,state/'native',event,unsupported,enterprise=True)
        try:
            await rpc.start()
            created=await rpc.call('thread/start',request)
            thread=created['thread']['id']
            record.update(state='naming',nativeThreadId=thread);saved(file,record)
            # This is the real display name, not a dummy history item or a
            # settings toggle. Native naming persists an empty paginated context.
            await rpc.call('thread/name/set',{'threadId':thread,'name':name})
            if turns:raise RuntimeError('Unexpected native turn during initialization')
            record.update(state='ready',nativeName=name,modelTurnsRequested=0);saved(file,record)
            return record
        finally:await rpc.close()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,required=True)
    args=parser.parse_args();result=asyncio.run(initialize(json.loads(args.config.read_text())))
    print(json.dumps(result))

if __name__=='__main__':main()
