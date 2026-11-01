"""Read original native context through the shared transport; never start/resume a turn."""
import argparse,asyncio,json
from pathlib import Path
from .rpc_shared import SharedAppServer
async def inspect(config_path,manifest_path,*,existing_client=False):
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
  if v['id']!=expected or v['status']['type'] not in ('idle','notLoaded'):
   raise ValueError('Original native context must be present and idle before transport migration')
  return {'nativeThreadId':v['id'],'status':v['status']['type'],'nativeState':m['state'],'modelCalls':0,
          **({'otherLoadedThreadsPreserved':len(others)} if existing_client else {})}
 finally:await rpc.close()
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('config');parser.add_argument('manifest');parser.add_argument('--existing-client',action='store_true');args=parser.parse_args()
 print(json.dumps(asyncio.run(inspect(args.config,args.manifest,existing_client=args.existing_client))))
