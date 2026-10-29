"""Accepted real canonical recovery -> local journal settlement; no native start."""
import asyncio,contextlib,copy,json,shutil,sys
from pathlib import Path
from uuid import uuid4
import psycopg
from psycopg.rows import dict_row
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer
from hollywood_backbone.server import application
from hollywood_backbone.store import Store
from lax_connector.journal import ExecutionJournals
from lax_connector.pre_native_recovery import settle
r=Path(sys.argv[1]);i=json.loads((r/'enterprise/installation-intent.json').read_text());delivery='1103975b-9ff6-4636-ac12-b373c9656b21'
assert i['name']=='Single-context native federation qualification'
original=Path('/var/lib/harness')/i['authorityId']/'global/state/executions'/delivery/'1/execution.json';record=json.loads(original.read_text());agent=record['delivery']['agent'];host=record['delivery']['host'];fixture=r/('local-recovery-test-'+str(uuid4()));fixture.mkdir(mode=0o700)
with psycopg.connect(**json.loads((r/'database.json').read_text()),row_factory=dict_row) as c:
 c.execute('BEGIN')
 class Borrow:
  @contextlib.contextmanager
  def connection(self):
   with c.transaction():yield c
 store=Store.__new__(Store);store.pool=Borrow()
 async def run():
  async with TestServer(application(store),host='127.0.0.1') as server:
   async with ClientSession() as client:
    async with client.get(server.make_url('/hollywood/v3/deliveries/'+delivery),headers={'Authorization':'Bearer '+i['credentials']['Owner']['token']}) as response:
     captured=await response.json();assert response.status==200
  assert captured['preNativeRecovery']['previousGeneration']==1 and captured['preNativeRecovery']['outcome']=='native_launch_not_dispatched'
  journals=ExecutionJournals(fixture,agent=agent,host=host);journal=journals.begin(record);config={'agentId':agent,'hostId':host}
  assert settle(journal,record,{k:v for k,v in captured.items() if k!='preNativeRecovery'},config) is None
  wrong=copy.deepcopy(captured);wrong['preNativeRecovery']['previousClaimId']=str(uuid4())
  try:settle(journal,record,wrong,config)
  except RuntimeError:pass
  else:raise AssertionError('Different original claim accepted')
  birth=journal.directory/'native-process.json';birth.write_text('{}')
  try:settle(journal,record,captured,config)
  except RuntimeError:pass
  else:raise AssertionError('Local native process evidence ignored')
  birth.unlink()
  value=settle(journal,record,captured,config);assert value['modelsStarted']==0 and value['originalRequestState']=='pending'
  assert json.loads((journal.directory/'execution.before-pre-native-recovery.json').read_text())==record
  assert json.loads(journal.read_text())['state']=='failed' and not list(journals.open_index.iterdir())
  assert json.loads(original.read_text())==record
  return {'passed':True,'realCanonicalHTTPRead':True,'acceptedOriginalRecoveryRequired':True,'wrongClaimAndLocalBirthEvidenceRejected':True,'originalObservationPreserved':True,'oldAttemptIndexClosedWithoutChangingCanonicalRequest':True,'actualWorkerJournalUnmodifiedByTest':True,'modelsOrProcessesStarted':0}
 try:result=asyncio.run(run())
 finally:c.rollback();shutil.rmtree(fixture)
(r/'pre-native-local-settlement-qualification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
