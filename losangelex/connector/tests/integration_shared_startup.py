"""Cold native IPC readiness: client starts before the one real daemon exists."""
import asyncio,json,os,signal,time
from pathlib import Path
from uuid import uuid4
from lax_connector.rpc_shared import SharedAppServer
async def main():
 os.umask(0o077);root=Path(os.environ['STARTUP_EVIDENCE']);root.mkdir();home=root/'profile';home.mkdir();socket=root/'native.sock';binary=os.environ['SHARED_NATIVE_BINARY'];authority,host=str(uuid4()),str(uuid4())
 value={'schema':'lax-native-host/v1','runtimeMode':'room-conversation','authorityId':authority,'hostId':host,'binary':binary,'codexHome':str(home),'state':str(root/'native'),'socket':str(socket)};(root/'host.json').write_text(json.dumps(value))
 async def observe(*args):pass
 client=SharedAppServer({'authorityId':authority,'hostId':host,'binary':binary,'codexHome':str(home),'state':str(root),'nativeServer':{'manifest':str(root/'host.json')}},observe,observe)
 process=None
 async def launch():
  nonlocal process
  await asyncio.sleep(.65)
  env=dict(os.environ,CODEX_HOME=str(home),LAX_NATIVE_ENTERPRISE='1',LAX_NATIVE_RUNTIME_MODE='room-conversation');env.pop('LAX_CANONICAL_NATIVE_CHANNEL',None)
  with (root/'native.log').open('xb') as log:process=await asyncio.create_subprocess_exec(binary,'--listen','unix://'+str(socket),env=env,stdout=log,stderr=log,start_new_session=True)
 task=asyncio.create_task(launch());start=time.monotonic()
 try:
  await client.start();elapsed=time.monotonic()-start;await task
  assert elapsed>=.65 and process.returncode is None
  loaded=await client.call('thread/loaded/list',{});assert loaded['data']==[]
  threads=await client.call('thread/list',{'limit':1});assert threads['data']==[]
  result={'state':'passed','connectedAfterDelayedNativeStartup':True,'elapsedSeconds':round(elapsed,3),'nativeProcessesStarted':1,'threadsCreated':0,'modelCalls':0,'productionChanged':False};(root/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
 finally:
  await task;await client.close()
  if process and process.returncode is None:
   os.killpg(process.pid,signal.SIGTERM)
   try:await asyncio.wait_for(process.wait(),10)
   except asyncio.TimeoutError:os.killpg(process.pid,signal.SIGKILL);await process.wait()
asyncio.run(main())
