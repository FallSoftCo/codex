"""Real SQLite/tool-runtime/restart journey; no native/model/network claim."""
import asyncio,json,tempfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from lax_connector.project_runtime import ProjectRuntime

async def main():
 with tempfile.TemporaryDirectory() as tmp:
  room,lead,authority,human=[str(uuid4()) for _ in range(4)]
  owner=SimpleNamespace(state=Path(tmp),config={'agentId':lead,'authorityId':authority})
  policy={'version':1,'roomId':room,'leadAgentId':lead,'revision':1}
  runtime=ProjectRuntime(owner,policy);ledger=runtime.ledger
  event=dict(id=str(uuid4()),room=room,author=human,body='Synthetic local work; no external actions.',audience='room',data={'authorKind':'human','roomMode':'lead','leadAgentId':lead,'leadRevision':1})
  assert (await runtime.candidate(event))['admit'];work=ledger.db.execute('SELECT id FROM work').fetchone()[0]
  ledger.admitted(event,'first')
  first={'key':'built-r1','summary':'Built original synthetic result','evidence':['artifact:sha256:'+'1'*64]}
  result=await runtime.call('lead_work',{'workId':work,'checkpoint':first},'call-first','first');assert not result['alreadyRecorded']
  ledger.ended('first','completed');assert ledger.work(work)['state']=='ready' and ledger.work(work)['no_progress']==0
  ledger.close();runtime=ProjectRuntime(owner,policy);ledger=runtime.ledger
  assert (await runtime.call('lead_work',{'workId':work,'checkpoint':first},'retry','first'))['alreadyRecorded']
  def admit_next(turn):
   row=ledger.db.execute("SELECT payload FROM outbox WHERE id LIKE 'ready:%' ORDER BY rowid DESC LIMIT 1").fetchone();payload=json.loads(row['payload']);coord=payload['coordination']
   e=dict(id=str(uuid4()),room=room,author=lead,recipient=lead,body=payload['body'],audience='direct',data={'roomMode':'lead','leadAgentId':lead,'leadRevision':1,'coordination':coord})
   assert ledger.candidate(e)[0];ledger.admitted(e,turn)
  for n in (2,3):
   admit_next('local-'+str(n));checkpoint={'key':'built-r'+str(n),'summary':'Material synthetic revision '+str(n),'evidence':['artifact:sha256:'+str(n)*64]}
   await runtime.call('lead_work',{'workId':work,'checkpoint':checkpoint},'call-'+str(n),'local-'+str(n));ledger.ended('local-'+str(n),'completed')
   assert ledger.work(work)['state']=='ready' and ledger.work(work)['no_progress']==0
  revision=ledger.work(work)['progress_revision'];admit_next('unchanged')
  duplicate={'key':'another-key','summary':'Rephrasing the same artifact is not work','evidence':['artifact:sha256:'+'3'*64]}
  assert (await runtime.call('lead_work',{'workId':work,'checkpoint':duplicate},'repeat','unchanged'))['alreadyRecorded'];assert ledger.work(work)['progress_revision']==revision
  ledger.ended('unchanged','completed');assert ledger.work(work)['no_progress']==1
  admit_next('unchanged-again');ledger.ended('unchanged-again','completed');assert ledger.work(work)['state']=='fault'
  # A scoped retry of the original checkpoint is still the same receipt after
  # later work faulted; it cannot revive or mutate that later state.
  assert (await runtime.call('lead_work',{'workId':work,'checkpoint':first},'old-accepted','unknown'))['alreadyRecorded'];assert ledger.work(work)['state']=='fault'
  rejected=False
  try:await runtime.call('lead_work',{'workId':work,'checkpoint':{**first,'summary':'Changed original request'}},'changed','first')
  except ValueError:rejected=True
  assert rejected
  ledger.close()
 print(json.dumps({'passed':True,'actualSQLiteReopen':True,'usefulLocalEnds':3,'rewordedEvidenceAddsProgress':False,'originalReceiptPreservedAfterFault':True,'unchangedNoProgressBoundPreserved':True,'nativeTurnsStarted':0,'providerCalls':0,'productionChanged':False}))

if __name__=='__main__':asyncio.run(main())
