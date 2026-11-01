"""Read original native context through the shared transport; never start/resume a turn."""
import asyncio,json,sys
from pathlib import Path
from .rpc_shared import SharedAppServer
async def inspect(config_path,manifest_path):
 c=json.loads(Path(config_path).read_text());m=json.loads(Path(manifest_path).read_text())
 if c.get('runtimeMode')!='room-conversation' or c.get('nativeServer') not in (None,{'manifest':manifest_path}):
  raise ValueError('Only an existing conversational private transport can be adopted')
 c={**c,'nativeServer':{'manifest':manifest_path},'binary':m['binary']}
 async def observe(*args):pass
 rpc=SharedAppServer(c,observe,observe)
 try:
  await rpc.start();loaded=await rpc.call('thread/loaded/list',{})
  if set(loaded['data'])-{c['nativeThreadId']}:raise ValueError('Other host contexts require coordinated owner drainage')
  v=(await rpc.call('thread/read',{'threadId':c['nativeThreadId'],'includeTurns':False}))['thread']
  if v['id']!=m.get('adoptedNativeThreadId',c['nativeThreadId']) or v['status']['type'] not in ('idle','notLoaded'):
   raise ValueError('Original native context must be present and idle before transport migration')
  return {'nativeThreadId':v['id'],'status':v['status']['type'],'nativeState':m['state'],'modelCalls':0}
 finally:await rpc.close()
if __name__=='__main__':print(json.dumps(asyncio.run(inspect(*sys.argv[1:]))))
