"""Real shared-native role pointer + retained work + one resumed QA reply.

The root harness provides an isolated canonical authority and a host-owner QA
policy. No production connector, enrollment, room or original input is changed.
"""
import asyncio,json,hashlib,sys,time
from pathlib import Path
from types import SimpleNamespace
from lax_connector.journal import saved
from lax_connector.rpc_shared import native_client
from lax_connector.room_tools import TOOLS
from lax_connector.project_adoption import adopt,digest
from lax_connector.room_session_supervisor import RoomSessionSupervisor

async def main(file):
 plan=json.loads(Path(file).read_text());root=Path(file).parent
 old=plan['child'];parent=plan['parent'];rpc=None;supervisor=None;thread=None;events=[];failure=None
 async def event(method,params):
  if method in ('turn/started','turn/completed','error'):events.append({'method':method,'params':params});saved(root/'native-events.private.json',events)
 async def no_tools(*args):raise AssertionError('Mechanical role adoption must not execute model tools')
 try:
  Path(old['state']).mkdir(mode=0o700,parents=True,exist_ok=False);Path(old['workspace']).mkdir(mode=0o700,parents=True,exist_ok=True)
  rpc=native_client(old,event,no_tools);await rpc.start()
  native=await rpc.call('thread/start',{'cwd':old['workspace'],'model':old['model'],'sandbox':old['sandbox'],'approvalPolicy':old['approvalPolicy'],
      'baseInstructions':old['conversationResumeInstructions']['baseInstructions'],'dynamicTools':TOOLS,'config':{'model_reasoning_effort':old['effort']}})
  thread=native['thread']['id'];old['nativeThreadId']=thread
  await rpc.call('thread/name/set',{'threadId':thread,'name':'NextComp retained-work role-adoption QA'})
  await rpc.call('thread/inject_items',{'threadId':thread,'items':[{'type':'function_call_output','name':'old_fixture','output':'OLD_BROADCAST_CONTEXT_CANARY'}]})
  cfg=root/'original-config.private.json';saved(cfg,old);before=cfg.read_bytes()
  parentfile=root/'parent-config.private.json';saved(parentfile,parent)
  registry=Path(parent['state'])/'room-sessions'/('session-'+old['agentId']+'.json');registry.parent.mkdir(mode=0o700,parents=True)
  record=dict(agentId=old['agentId'],originRoomId=old['originRoomId'],nativeThreadId=thread,sessionConfigPath=str(cfg),sessionConfigSha256=hashlib.sha256(before).hexdigest());saved(registry,record)
  saved(registry.parent/'status.private.json',{'runtimeCapabilities':['project-role-handover/v1'],'qualificationBoundary':'real owner-approved QA policy; no OS service or model worker enrolled'})
  await rpc.call('thread/unsubscribe',{'threadId':thread});await rpc.close();rpc=None
  kwargs=dict(expected_config_sha=record['sessionConfigSha256'],expected_record_sha=hashlib.sha256(registry.read_bytes()).hexdigest(),policy=plan['policy'],seed=plan['seed'],operation='owned-retained-work-handover-r01',work=plan['work'])
  receipt=await adopt(parentfile,old['agentId'],**kwargs)
  assert cfg.read_bytes()==before and receipt['modelsStarted']==0 and receipt['originalInputReplayed'] is False
  again=await adopt(parentfile,old['agentId'],**kwargs);assert again==receipt
  saved(root/'handover-receipt.private.json',receipt)
  assert not [v for v in events if v['method']=='turn/started']
  supervisor=RoomSessionSupervisor(SimpleNamespace(config=parent,thread=parent['nativeThreadId']))
  supervisor.load();assert old['agentId']in supervisor.tasks,supervisor.records
  session=supervisor.sessions[old['agentId']];callback=session.rpc.on_event
  async def observed(method,params):await event(method,params);await callback(method,params)
  session.rpc.on_event=observed
  # Reconciliation of the original immutable bootstrap must attach no duplicate.
  supervisor.attach({**record,'state':'ready','sharedAppServer':True})
  assert len(supervisor.sessions)==1
  deadline=time.monotonic()+150
  while True:
   task=supervisor.tasks[old['agentId']]
   if task.done():task.result();raise RuntimeError('Adopted logical client stopped')
   ledger=session.project.ledger if session.project else None
   work=ledger.db.execute('SELECT * FROM work').fetchall()if ledger else []
   if work and all(v['state']=='complete'for v in work)and not session.native_active_turn and not session.conversation_io.pending():break
   if any(v['state']=='fault'for v in work):raise RuntimeError('Adopted lead reached a fault; inspect original work')
   if time.monotonic()>deadline:raise TimeoutError('Original retained QA work did not complete')
   await asyncio.sleep(.2)
  inputs=ledger.db.execute('SELECT canonical,reason,admit,turn FROM input').fetchall()
  original=[v for v in inputs if json.loads(v['canonical'])['id']==plan['work'][0]['eventId']]
  assert len(original)==1 and original[0]['admit']==0 and original[0]['turn']is None
  turns={v['params']['turn']['id']for v in events if v['method']=='turn/started'}
  assert len(turns)==1,events
  saved(root/'qualification.json',dict(passed=True,actualCanonicalHTTP=True,actualSharedNative=True,actualModelTools=True,
      sameOriginalNativeThread=thread,originalHumanReplayed=False,originalInputNativeAdmissions=0,sourceBoundWakeNativeTurns=len(turns),newAppServers=0,
      originalConfigurationRetained=cfg.read_bytes()==before,logicalClients=len(supervisor.sessions),handoverRepeatSameReceipt=True,
      boundary='QA approved root policy; production protected enrollment rollout not performed'))
 except BaseException as error:
  failure=error;saved(root/'failure.json',{'type':type(error).__name__,'message':str(error),'thread':thread})
 finally:
  active=supervisor.sessions[old['agentId']].native_active_turn if supervisor and old['agentId']in supervisor.sessions else None
  if active:
   intent=root/'interrupt-owned-qa.json';saved(intent,{'thread':thread,'turn':active,'state':'dispatching'})
   try:
    r=await supervisor.sessions[old['agentId']].rpc.call('turn/interrupt',{'threadId':thread,'turnId':active});saved(intent,{'thread':thread,'turn':active,'state':'acknowledged','receipt':r})
   except Exception as e:saved(intent,{'state':'unknown','error':str(e)})
  if supervisor:await supervisor.close()
  if rpc:await rpc.close()
  if thread:
   config={**old,'nativeThreadId':thread};rpc=native_client(config,event,no_tools)
   try:
    await rpc.start();meta=await rpc.call('thread/read',{'threadId':thread,'includeTurns':False})
    if meta['thread']['status']['type']in('idle','notLoaded'):
     await rpc.call('thread/archive',{'threadId':thread});saved(root/'cleanup.json',{'archivedOwnedQaThread':thread,'productionChanged':False})
    else:saved(root/'cleanup.json',{'unsettledOwnedQaThread':thread,'productionChanged':False})
   finally:await rpc.close()
 if failure:raise failure
if __name__=='__main__':asyncio.run(main(sys.argv[1]))
