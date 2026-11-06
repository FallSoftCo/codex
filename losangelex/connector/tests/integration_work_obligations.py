"""Durable lifecycle across admission, waits, late ACK, restart and recovery."""
import asyncio,json,tempfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from lax_connector.project_runtime import ProjectRuntime
from lax_connector.conversation_io import ConversationIO

async def main():
 with tempfile.TemporaryDirectory() as tmp:
  state=Path(tmp);room,lead,authority,human,peer=[str(uuid4())for _ in range(5)]
  config=dict(agentId=lead,authorityId=authority,nativeThreadId='native-original',state=tmp,rooms=[])
  owner=SimpleNamespace(state=state,config=config,thread='native-original',attention=SimpleNamespace(pending={}),native_active_turn=None)
  owner.conversation_io=ConversationIO(state/'conversation-io.sqlite',authority=authority,agent=lead,thread=owner.thread)
  policy=dict(version=1,roomId=room,leadAgentId=lead,revision=1);r=ProjectRuntime(owner,policy);l=r.ledger
  e=dict(id=str(uuid4()),room=room,author=human,body='Finish original product',audience='room',data=dict(authorKind='human',roomMode='lead',leadAgentId=lead,leadRevision=1))
  assert l.candidate(e)[0];l.admitted(e,'original-turn');work=l.db.execute('SELECT id FROM work').fetchone()[0]
  # Real historical need-input receipt survives independent work. It is not a
  # forever counter of all questions this project has ever asked.
  with l.db:
   l.queue('old-human',dict(body='Old host access problem',sourceEventId=e['id'],responsePhase='blocked'))
   l.obligations.human_intent('old-human',work,'original-turn')
  receipt=dict(event=dict(id=str(uuid4()),data={}))
  l.accepted('old-human',receipt);assert l.dependencies(work)['human']==1
  l.disposition(work,'ready','Independent work remains useful');assert l.dependencies(work)['human']==0
  l.ended('original-turn','completed');assert l.work(work)['state']=='ready'
  # Migrate the exact old bug: completed native turn, old human receipt, all
  # worker assignments terminal, yet the runtime persisted an automatic wait.
  with l.db:
   l.db.execute("UPDATE work SET state='waiting',reason='Waiting for addressed worker results' WHERE id=?",(work,))
   l.db.execute('DELETE FROM work_wait WHERE work=?',(work,))
  l.close();r=ProjectRuntime(owner,policy);l=r.ledger;l.obligations.reconcile()
  assert l.work(work)['state']=='recovering';due=l.recovery.next_due();assert due
  calls=[]
  class RPC:
   async def call(self,method,args):
    calls.append(method)
    if method=='thread/read':return dict(thread=dict(id=owner.thread,status=dict(type='idle')))
    if method=='thread/backgroundTerminals/list':return dict(data=[],nextCursor=None)
    if method=='thread/turns/list':return dict(data=[dict(id='original-turn',status='completed')])
    raise AssertionError('No execution RPC authorized')
  owner.rpc=RPC()
  # Unknown publication blocks continuation; restart does not erase that gate.
  with owner.conversation_io.db:owner.conversation_io.db.execute("INSERT INTO publication VALUES('original-turn',NULL,'unknown','room','attempting')")
  await l.recovery.inspect_due(owner,now=due+1);assert l.work(work)['state']=='recovering'
  with owner.conversation_io.db:owner.conversation_io.db.execute("UPDATE publication SET state='accepted'")
  await l.recovery.inspect_due(owner,now=l.recovery.next_due()+1);assert l.work(work)['state']=='ready'
  revision=l.work(work)['revision'];l.obligations.reconcile();l.close();r=ProjectRuntime(owner,policy);l=r.ledger;l.obligations.reconcile();assert l.work(work)['revision']==revision
  assert l.db.execute("SELECT count(*) FROM outbox WHERE id=?",('ready:'+work+':'+str(revision),)).fetchone()[0]==1
  # A genuine CURRENT human question stays waiting across restart/audits.
  with l.db:
   l.queue('current-human',dict(body='Actual missing decision',sourceEventId=e['id'],responsePhase='blocked'))
   l.obligations.human_intent('current-human',work,'current-turn')
  l.accepted('current-human',receipt);l.close();r=ProjectRuntime(owner,policy);l=r.ledger;l.obligations.reconcile()
  assert l.work(work)['state']=='waiting' and l.dependencies(work)['human']==1
  l.disposition(work,'ready','Explicit independent continuation')
  # A late accepted old human-question send must not overwrite newer work.
  with l.db:
   l.queue('late-human',dict(body='Older decision',sourceEventId=e['id'],responsePhase='blocked'))
   l.obligations.human_intent('late-human',work,'old-turn')
  l.disposition(work,'ready','Newer retained decision');l.accepted('late-human',receipt)
  assert l.work(work)['state']=='ready' and l.dependencies(work)['human']==0
  # Explicit pauses remain paused. Old accepted receipts are never rewritten.
  l.disposition(work,'paused','Deliberate stop');l.obligations.reconcile();assert l.work(work)['state']=='paused'
  assert l.db.execute("SELECT state FROM outbox WHERE id='old-human'").fetchone()[0]=='accepted'
  # Reconcile a genuinely missed native end from native metadata, not from a
  # textual final/elapsed time; repeated audit retains a single original notice.
  owner.native_active_turn='original-turn';handled=[]
  async def terminal_event(method,params):
   assert method=='turn/completed' and params['reconciledFromNativeRead']
   handled.append(params['turn']['id']);owner.native_active_turn=None
   owner.conversation_io.ended(params['turn']['id'],params['turn']['status'])
   r.ended(params['turn']['id'],params['turn']['status'])
  owner.event=terminal_event
  await r.audit_native_ends();await r.audit_native_ends()
  assert handled==['original-turn'] and owner.native_active_turn is None
  assert l.db.execute("SELECT count(*) FROM native_end_notice WHERE turn='original-turn'").fetchone()[0]==1
  assert all(x in ('thread/read','thread/backgroundTerminals/list','thread/turns/list')for x in calls)
  l.close();owner.conversation_io.close()
 print(json.dumps(dict(passed=True,currentWaitOwnership=True,staleWaitRecoveredOnce=True,unknownDeliveryPreserved=True,currentHumanWaitPreserved=True,lateAcknowledgementCannotOverrideNewerWork=True,stopPreserved=True,missedNativeEndReconciledOnce=True,modelCalls=0)))
if __name__=='__main__':asyncio.run(main())
