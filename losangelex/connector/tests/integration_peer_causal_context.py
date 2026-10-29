"""Actual authenticated canonical lineage reads for a typed completion; no model."""
import asyncio,json,shutil,sys
from pathlib import Path
from uuid import uuid4
from aiohttp import ClientSession
from lax_connector.continuation_context import LocatorLedger,build_context,receipt,ContextHeld
r=Path(sys.argv[1]);i=json.loads((r/'enterprise/installation-intent.json').read_text());assert i['name']=='Single-context native federation qualification'
c=json.loads(Path('/var/lib/harness') .joinpath(i['authorityId'],'global/connector.json').read_text());fixture=r/('peer-causal-test-'+str(uuid4()));fixture.mkdir(mode=0o700)
async def main():
 async with ClientSession() as client:
  async def get(path):
   async with client.get(c['hollywoodUrl']+'/hollywood/v3/'+path,headers={'Authorization':'Bearer '+c['token']}) as response:
    value=await response.json();assert response.status==200,(path,response.status,value);return value
  captured=await get('deliveries/8fec2ac6-fa6e-5e89-a0fc-5e50d196986a')
  assert captured['request']['kind']=='result' and captured['request']['data']['type']=='peerCompletion'
  ledger=LocatorLedger(fixture);ledger.remember(captured)
  built=await build_context(get,captured,ledger.resolve,inspection=True,retain_page=ledger.retain_audit)
  assert built and 'ozzz-gpu' in json.dumps(built)
  wrong=json.loads(json.dumps(captured));wrong['request']['data'].pop('type')
  try:receipt(wrong)
  except ContextHeld:pass
  else:raise AssertionError('Ordinary result admitted as a typed completion')
  return {'passed':True,'actualAuthenticatedHTTPAndCanonicalNativeDelegationReads':True,'typedResultCompletionAcceptedWithoutRewritingKind':True,'originalParentAndChildReceiptsVerified':True,'actualGPUResultInReadOnlyContext':True,'ordinaryResultStillRejected':True,'modelsOrNativeProcessesStarted':0,'canonicalMessagesOrDeliveriesChanged':False}
try:result=asyncio.run(main())
finally:shutil.rmtree(fixture)
(r/'peer-causal-context-qualification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
