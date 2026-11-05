"""Read original native context through the shared transport; never start/resume a turn."""
import argparse,asyncio,json
from pathlib import Path
from .rpc_shared import SharedAppServer
async def inspect(config_path,manifest_path,*,existing_client=False,allow_terminal_failure=False):
 if allow_terminal_failure and not existing_client:
  raise ValueError('Terminal failure inspection is limited to an unchanged existing shared client')
 c=json.loads(Path(config_path).read_text());m=json.loads(Path(manifest_path).read_text())
 if c.get('runtimeMode')!='room-conversation' or c.get('nativeServer') not in (None,{'manifest':manifest_path}):
  raise ValueError('Only an existing conversational private transport can be adopted')
 if existing_client and (c.get('nativeServer')!={'manifest':manifest_path} or not c.get('agentId')):
  raise ValueError('Existing shared client declaration required')
 c={**c,'nativeServer':{'manifest':manifest_path},'binary':m['binary']}
 async def observe(*args):pass
 rpc=SharedAppServer(c,observe,observe)
 try:
  await rpc.start();loaded=await rpc.call('thread/loaded/list',{})
  others=set(loaded['data'])-{c['nativeThreadId']}
  if others and not existing_client:raise ValueError('Other host contexts require coordinated owner drainage')
  v=(await rpc.call('thread/read',{'threadId':c['nativeThreadId'],'includeTurns':False}))['thread']
  expected=c['nativeThreadId'] if existing_client and m.get('ownerAgentId')!=c['agentId'] else m.get('adoptedNativeThreadId',c['nativeThreadId'])
  status=v['status']['type'];terminal_failure=None
  if v['id']!=expected:
   raise ValueError('Original native context identity changed')
  if status=='systemError' and allow_terminal_failure:
   # A failed turn is inactive, not healthy. Preserve its identity without a
   # thread/resume or turn/start just to upgrade an unchanged client runtime.
   turns=await rpc.call('thread/turns/list',{'threadId':v['id'],'limit':1})
   commands=await rpc.call('thread/backgroundTerminals/list',{'threadId':v['id'],'limit':100})
   if (len(turns.get('data',[]))!=1 or turns['data'][0].get('status')!='failed'
       or commands.get('data')!=[] or commands.get('nextCursor') is not None):
    raise ValueError('Failed original context lacks terminal/no-command evidence')
   terminal_failure={'id':turns['data'][0]['id'],'status':'failed'}
  elif status not in ('idle','notLoaded'):
   raise ValueError('Original native context must be present and idle before transport migration')
  from .room_session_inspect import inspect_sessions
  logical=await inspect_sessions(c)
  if terminal_failure and not logical.get('quiet'):
   raise ValueError('Failed parent has unsettled logical contexts')
  return {'logicalSessions':logical,'nativeThreadId':v['id'],'status':status,'nativeState':m['state'],'modelCalls':0,
          **({'terminalFailedTurn':terminal_failure,'healthy':False} if terminal_failure else {}),
          **({'otherLoadedThreadsPreserved':len(others)} if existing_client else {})}
 finally:await rpc.close()
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('config');parser.add_argument('manifest');parser.add_argument('--existing-client',action='store_true');parser.add_argument('--allow-terminal-failure',action='store_true');args=parser.parse_args()
 print(json.dumps(asyncio.run(inspect(args.config,args.manifest,existing_client=args.existing_client,allow_terminal_failure=args.allow_terminal_failure))))
