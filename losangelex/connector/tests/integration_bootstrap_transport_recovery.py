"""Cold native IPC readiness: client starts before the one real daemon exists."""
import asyncio,json,os,signal,time,hashlib
from pathlib import Path
from uuid import uuid4
from lax_connector.rpc_shared import SharedAppServer
from lax_connector.room_bootstrap import initialize
from lax_connector.room_bootstrap_recovery import SOURCE_KINDS,reconcile_empty
async def main():
 os.umask(0o077);root=Path(os.environ['STARTUP_EVIDENCE']);root.mkdir();home=root/'profile';home.mkdir();socket=root/'native.sock';binary=os.environ['SHARED_NATIVE_BINARY'];authority,host=str(uuid4()),str(uuid4());agent=str(uuid4())
 value={'schema':'lax-native-host/v1','runtimeMode':'room-conversation','authorityId':authority,'hostId':host,'ownerAgentId':agent,'binary':binary,'codexHome':str(home),'state':str(root/'native'),'socket':str(socket)};(root/'host.json').write_text(json.dumps(value))
 async def observe(*args):pass
 client=SharedAppServer({'authorityId':authority,'hostId':host,'binary':binary,'codexHome':str(home),'state':str(root),'nativeServer':{'manifest':str(root/'host.json')}},observe,observe)
 (root/'work').mkdir()
 (home/'config.toml').write_text('model_provider="fixture"\n[model_providers.fixture]\nname="Owned no-model fixture"\nbase_url="http://127.0.0.1:9/v1"\nwire_api="responses"\nrequires_openai_auth=false\n')
 config={'runtimeMode':'room-conversation','authorityId':authority,'agentId':agent,'hostId':host,'binary':binary,'codexHome':str(home),'workspace':str(root/'work'),'state':str(root/'state'),'nativeName':'Original bootstrap context','instructions':'Owned no-model initialization','model':'gpt-6.1-sol','effort':'xhigh','sandbox':'danger-full-access','approvalPolicy':'never','nativeServer':{'manifest':str(root/'host.json')}}
 (root/'config.json').write_text(json.dumps(config))
 legacy=await asyncio.create_subprocess_exec(os.environ['LEGACY_BOOTSTRAP_PYTHON'],'-I','-m','lax_connector.room_bootstrap','--config',str(root/'config.json'),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
 stdout,stderr=await legacy.communicate();failed_at=time.time();(root/'legacy-error.log').write_bytes(stderr)
 assert legacy.returncode!=0 and not socket.exists()
 original=root/'state/native-context.json';prior=json.loads(original.read_text());assert prior['state']=='creating' and 'nativeThreadId' not in prior
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
  receipt={'schema':'lax-native-bootstrap-not-sent/v1','binding':prior['binding'],'requestDigest':prior['requestDigest'],'originalContextSha256':hashlib.sha256(original.read_bytes()).hexdigest(),'noNativeThreadStartIssued':True,'failedAttemptExitUnixSeconds':failed_at,'socketReadyUnixSeconds':socket.stat().st_mtime}
  proof=root/'operator-proof.json';proof.write_text(json.dumps(receipt))
  recovered=await initialize(config,recovery=proof);assert recovered['state']=='ready'
  again=await initialize(config);assert again['nativeThreadId']==recovered['nativeThreadId']
  listed=await client.call('thread/list',{'limit':10,'sourceKinds':SOURCE_KINDS,'modelProviders':[]})
  loaded=await client.call('thread/loaded/list',{})
  (root/'inventory-after-recovery.json').write_text(json.dumps({'listed':listed,'loaded':loaded,'recovered':recovered},indent=2))
  client.bind_thread(recovered['nativeThreadId'])
  exact=await client.call('thread/read',{'threadId':recovered['nativeThreadId'],'includeTurns':False})
  assert exact['thread']['id']==recovered['nativeThreadId']
  assert len(loaded['data'])==1 and loaded['data'][0]==recovered['nativeThreadId']
  blocked=root/'blocked-original-context.json';blocked.write_text(json.dumps(prior))
  guarded=dict(receipt,originalContextSha256=hashlib.sha256(blocked.read_bytes()).hexdigest())
  guarded_path=root/'operator-proof-existing-context.json';guarded_path.write_text(json.dumps(guarded))
  try:await reconcile_empty(client,guarded_path,blocked,prior,{'binding':prior['binding'],'requestDigest':prior['requestDigest']})
  except RuntimeError:pass
  else:raise AssertionError('Existing native context was not protected')
  assert json.loads(blocked.read_text())==prior
  result={'state':'passed','realLegacyPreSocketFailureReconciled':True,'firstOriginalContextCreatedExactlyOnce':True,'readyReentryPreservesOriginalId':True,'existingContextBlocksReplacement':True,'nativeProcessesStarted':1,'modelCalls':0,'productionChanged':False};(root/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))

 finally:
  await task;await client.close()
  if process and process.returncode is None:
   os.killpg(process.pid,signal.SIGTERM)
   try:await asyncio.wait_for(process.wait(),10)
   except asyncio.TimeoutError:os.killpg(process.pid,signal.SIGKILL);await process.wait()
asyncio.run(main())
