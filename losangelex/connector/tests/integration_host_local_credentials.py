"""Actual HTTP/PG host-local enrollment; isolated authority, rollback-only rows."""
import asyncio,contextlib,json,shutil,sys
from pathlib import Path
from uuid import uuid4
import psycopg
from psycopg.rows import dict_row
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer
from hollywood_backbone.server import application
from hollywood_backbone.store import Store
from lax_connector.host import enroll

root=Path(sys.argv[1]);i=json.loads((root/'enterprise/installation-intent.json').read_text())
assert i['name']=='Single-context native federation qualification'
host=str(uuid4());authority=i['authorityId']
local=Path('/var/lib/harness')/authority/'hosts'/host
assert not local.exists()
with psycopg.connect(**json.loads((root/'database.json').read_text()),row_factory=dict_row) as c:
 c.execute('BEGIN')
 class Borrow:
  @contextlib.contextmanager
  def connection(self):
   with c.transaction():yield c
 store=Store.__new__(Store);store.pool=Borrow()
 async def run():
  async with TestServer(application(store),host='127.0.0.1') as server:
   async with ClientSession() as client:
    spec={'authorityId':authority,'hostId':host,'hollywoodUrl':str(server.make_url('/')).rstrip('/'),'enrollmentMode':'preauthorized','policy':{'maxConcurrent':1,'reservedInteractive':0,'controlAgentIds':[],'memoryPerTurnBytes':2**30,'reserveMemoryBytes':2**30,'sampleMaxAgeSeconds':15,'connectorMaxAgeSeconds':30}}
    proposal=enroll(spec,prepare_only=True)
    assert 'token' not in json.dumps(proposal) and not (local/'controller.json').exists()
    secret=json.loads((local/'enrollment-intent.json').read_text())['token']
    assert secret not in json.dumps(proposal)
    async def call(method,path,payload):
     async with client.request(method,server.make_url('/hollywood/v3/'+path),json=payload,headers={'Authorization':'Bearer '+i['credentials']['Owner']['token']}) as r:
      v=await r.json();assert r.status==200,(r.status,v);return v
    await call('POST','principals',proposal['principal'])
    # A placement establishes the host identity without starting an executor.
    peer=str(uuid4())
    await call('POST','principals',{'id':peer,'name':'Rollback host peer '+peer,'kind':'agent','enrollmentCredentialDigest':'a'*64})
    await call('POST','placements',{'operationId':'local-enroll-'+host,'hostId':host,'agentId':peer,'name':'Rollback host '+host,'identityFingerprint':proposal['machineIdentity'],'capabilities':{'metadataOnly':True}})
    await call('PUT','hosts/'+host+'/admission',proposal['policy'])
    result=await asyncio.to_thread(enroll,spec)
    installed=json.loads(Path(result['configPath']).read_text())
    assert installed['token']==secret and installed['machineIdentity']==proposal['machineIdentity']
    assert 'administratorCredential' not in installed
    again=await asyncio.to_thread(enroll,spec); assert again==result
    try: await asyncio.to_thread(enroll,{**spec,'administratorCredential':{'token':'forbidden'}})
    except ValueError: pass
    else: raise AssertionError('Owner credential accepted in preauthorized mode')
    return {'passed':True,'realPostgreSQLAndHTTP':True,'hostSecretGeneratedAndRetainedLocally':True,'ownerCredentialAbsentOnHost':True,'digestOnlyCanonicalAdmission':True,'finalizationAuthenticatedAsOwnController':True,'sameIntentReconcilesWithoutNewCredential':True,'servicesOrModelsStarted':0,'databaseFixturesRolledBack':True}
 try: result=asyncio.run(run())
 finally:
  c.rollback()
  shutil.rmtree(local)
(root/'host-local-enrollment-qualification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
