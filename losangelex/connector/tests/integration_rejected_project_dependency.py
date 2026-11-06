"""Real SQLite + project runtime + publication ledger; synthetic HTTP only."""
import asyncio,json,tempfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from lax_connector.project_runtime import ProjectRuntime
from lax_connector.room_tools import RoomTools
from lax_connector.errors import HttpFailure

async def main():
 with tempfile.TemporaryDirectory()as tmp:
  root=Path(tmp);room,lead,authority,human,peer=[str(uuid4())for _ in range(5)]
  policy=dict(version=1,roomId=room,leadAgentId=lead,revision=1)
  mode='reject';calls=[];saved_payload=None
  async def http(method,path,payload=None):
   nonlocal saved_payload
   calls.append((method,path))
   if method=='POST':saved_payload=payload
   if mode=='reject':raise HttpFailure(403,'Peer not authorized',may_apply=False)
   if mode=='unknown':raise HttpFailure(503 if method=='POST'else 403,'Unavailable original command',may_apply=True)
   assert mode=='accepted' and method=='GET'
   return dict(accepted=True,deliveries=[],event=dict(id=str(uuid4()),authority=authority,room=room,author=lead,recipient=peer,kind='message',body=saved_payload['body'],audience='direct',source=None,data=dict(coordination=saved_payload['coordination'],responsePhase='message')))
  def runtime_at(path):
   owner=SimpleNamespace(state=path,config=dict(agentId=lead,authorityId=authority))
   owner.tools=RoomTools(authority_id=authority,agent_id=lead,thread_id='native-fixture',request=http,state=path/'publications')
   runtime=ProjectRuntime(owner,policy);owner.tools.project=runtime;return runtime
  def admit(runtime,turn):
   event=dict(id=str(uuid4()),room=room,author=human,body='Synthetic original work',audience='room',data=dict(authorKind='human',roomMode='lead',leadAgentId=lead,leadRevision=1))
   assert runtime.ledger.candidate(event)[0];runtime.ledger.admitted(event,turn)
   return runtime.ledger.db.execute('SELECT id FROM work').fetchone()[0]
  r=runtime_at(root/'rejected');work=admit(r,'turn-rejected');args=dict(taskId=work,workId=work,recipientId=peer,questionKey='original-question',question='A bounded actual dependency?')
  try:await r.call('team_question',args,'tool-1','turn-rejected');assert False
  except HttpFailure:pass
  assert r.ledger.db.execute('SELECT state FROM outbox').fetchone()[0]=='blocked'
  assert not any(r.ledger.dependencies(work).values())
  r.ledger.ended('turn-rejected','completed');assert r.ledger.work(work)['state']=='ready'
  try:r.ledger.disposition(work,'waiting','Waiting for a peer that never received a question');assert False
  except ValueError:pass
  # Actual SDK259 persisted shape. Repair once; do not rewrite/replay the rejected send.
  with r.ledger.db:r.ledger.db.execute("UPDATE work SET state='waiting',reason='Waiting for addressed worker results' WHERE id=?",(work,))
  old_revision=r.ledger.work(work)['revision'];r.ledger.close();r=runtime_at(root/'rejected');r.ledger.reconcile_waiting()
  assert r.ledger.work(work)['state']=='ready' and r.ledger.work(work)['revision']==old_revision+1
  count=r.ledger.db.execute("SELECT count(*) FROM outbox WHERE id LIKE 'ready:%'").fetchone()[0]
  r.ledger.close();r=runtime_at(root/'rejected');r.ledger.reconcile_waiting()
  assert r.ledger.db.execute("SELECT count(*) FROM outbox WHERE id LIKE 'ready:%'").fetchone()[0]==count
  assert r.ledger.snapshot(work_id=work)['communicationBlocked'][0]['reason'].endswith('Peer not authorized')
  r.ledger.disposition(work,'paused','Explicit stop');r.ledger.reconcile_waiting();assert r.ledger.work(work)['state']=='paused';r.ledger.close()
  assert sum(method=='POST' for method,path in calls)==1
  # A denied GET after uncertain POST is not rejected delivery and never authorizes resend.
  mode='unknown';calls.clear();r=runtime_at(root/'unknown');work=admit(r,'turn-unknown');args.update(taskId=work,workId=work)
  try:await r.call('team_question',args,'tool-2','turn-unknown');assert False
  except HttpFailure:pass
  row=r.ledger.db.execute('SELECT * FROM outbox').fetchone();key=row['id'];assert row['state']=='ready'
  r.ledger.ended('turn-unknown','completed');assert r.ledger.work(work)['state']=='waiting'
  r.ledger.close();r=runtime_at(root/'unknown');r.ledger.reconcile_waiting();assert r.ledger.work(work)['state']=='waiting'
  try:await r.send(key);assert False
  except HttpFailure:pass
  assert sum(method=='POST'for method,path in calls)==1
  mode='accepted';receipt=await r.send(key);assert r.ledger.dependencies(work)['questions']==1
  answer=dict(id=str(uuid4()),room=room,author=peer,recipient=lead,body='Actual bounded result',audience='direct',source=receipt['event']['id'],data=dict(roomMode='lead',leadAgentId=lead,leadRevision=1,coordination=dict(type='answer',taskId=work,revision=1)))
  assert r.ledger.candidate(answer)[0] and r.ledger.work(work)['state']=='ready'
  # A delivered real human question remains a legitimate wait.
  source=r.ledger.work(work)['source'];payload=dict(body='Which device should be used?',audience='room',sourceEventId=source,responsePhase='blocked')
  with r.ledger.db:r.ledger.queue('human-question',payload)
  r.ledger.accepted('human-question',dict(event=dict(id=str(uuid4()),data=dict(responsePhase='blocked'))))
  r.ledger.disposition(work,'waiting','Human response needs_input');r.ledger.reconcile_waiting();assert r.ledger.work(work)['state']=='waiting';r.ledger.close()
  # The same rejection must not trap a worker in waiting or suppress its answer.
  worker_calls=[];worker_reject=True
  async def worker_http(method,path,payload=None):
   worker_calls.append(method)
   if worker_reject:raise HttpFailure(403,'Selected peer is outside this project',may_apply=False)
   return dict(accepted=True,deliveries=[],event=dict(id=str(uuid4()),authority=authority,room=room,author=peer,recipient=payload.get('recipientId'),kind='message',body=payload['body'],audience=payload['audience'],source=payload.get('sourceEventId'),data=dict(coordination=payload['coordination'],responsePhase=payload['responsePhase'])))
  owner=SimpleNamespace(state=root/'worker',config=dict(agentId=peer,authorityId=authority))
  owner.tools=RoomTools(authority_id=authority,agent_id=peer,thread_id='worker-fixture',request=worker_http,state=owner.state/'publications')
  worker=ProjectRuntime(owner,policy);owner.tools.project=worker;task=str(uuid4())
  event=dict(id=str(uuid4()),room=room,author=lead,recipient=peer,body='Synthetic selected task',audience='room',data=dict(roomMode='lead',leadAgentId=lead,leadRevision=1,coordination=dict(type='task',taskId=task,revision=1)))
  assert worker.ledger.candidate(event)[0];worker.ledger.admitted(event,'worker-turn')
  try:await worker.call('team_question',dict(taskId=task,recipientId=str(uuid4()),questionKey='technical-question',question='Synthetic bounded dependency?'),'worker-call','worker-turn');assert False
  except HttpFailure:pass
  assert worker.ledger.db.execute('SELECT state FROM assignment WHERE id=?',(task,)).fetchone()[0]=='progress'
  worker_reject=False;await worker.worker_missing_result('worker-turn','original-output')
  assert worker.ledger.db.execute('SELECT state FROM assignment WHERE id=?',(task,)).fetchone()[0]=='failed'
  question=dict(id=str(uuid4()),room=room,author=lead,recipient=peer,body='Explain the actual rejection?',audience='direct',data=dict(roomMode='lead',leadAgentId=lead,leadRevision=1,coordination=dict(type='question',taskId=task,revision=1)))
  assert worker.ledger.candidate(question)[0];worker.ledger.admitted(question,'question-turn')
  await worker.peer_final(dict(turn='question-turn',body='The peer rejected admission; no task was dispatched.'))
  assert worker.ledger.db.execute('SELECT state FROM team_question WHERE event=?',(question['id'],)).fetchone()[0]=='answered'
  assert worker_calls==['POST','POST','POST'];worker.ledger.close()
 print(json.dumps(dict(passed=True,actualSQLiteRestart=True,actualPublicationLedger=True,rejectedQuestionWaits=False,legacyRepairOnce=True,uncertainPostReplayed=False,originalAnswerResumes=True,genuineHumanQuestionAndStopPreserved=True,workerRejectionReturnsToLead=True,workerAnswerNotSuppressed=True,nativeTurns=0,providerCalls=0)))

if __name__=='__main__':asyncio.run(main())
