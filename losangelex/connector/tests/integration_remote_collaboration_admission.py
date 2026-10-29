"""Real HTTP/PG split admission; rollback-only metadata, no services/models."""
import asyncio,contextlib,json,secrets,shutil,sys
from pathlib import Path
from uuid import uuid4,uuid5,UUID
import psycopg
from psycopg.rows import dict_row
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer
from hollywood_backbone.store import Store,digest
from hollywood_backbone.server import application
from lax_connector.collaboration_admission import admit,accepted_resources
from lax_connector.collaboration_install import prepare
from lax_connector.host import request
from lax_connector.service_observer import protected

root=Path(sys.argv[1]);i=json.loads((root/'enterprise/installation-intent.json').read_text())
assert i['name']=='Single-context native federation qualification'
fixture=root/('remote-admission-'+str(uuid4()));fixture.mkdir(mode=0o700)
def save(p,v):p.write_text(json.dumps(v,indent=2)+'\n');p.chmod(0o600)
host,agent,controller,workspace=[str(uuid4()) for _ in range(4)];key=secrets.token_urlsafe(40)
with psycopg.connect(**json.loads((root/'database.json').read_text()),row_factory=dict_row) as c:
 c.execute('BEGIN')
 class Borrow:
  @contextlib.contextmanager
  def connection(self):
   with c.transaction():yield c
 store=Store.__new__(Store);store.pool=Borrow()
 async def run():
  async with TestServer(application(store),host='127.0.0.1') as server:
   url=str(server.make_url('/')).rstrip('/')
   async with ClientSession() as client:
    async def api(method,path,payload=None):
     async with client.request(method,server.make_url('/hollywood/v3/'+path),json=payload,headers={'Authorization':'Bearer '+i['credentials']['Owner']['token']}) as r:
      v=await r.json();assert r.status==200,(r.status,v);return v
    for identity,kind,token in [(controller,'service',key),(agent,'agent',secrets.token_urlsafe(40))]:
     await api('POST','principals',{'id':identity,'name':'Rollback remote admission '+identity,'kind':kind,'enrollmentCredentialDigest':digest(token)})
    await api('POST','placements',{'hostId':host,'agentId':agent,'name':'Rollback remote host '+host,'identityFingerprint':'b'*64,'capabilities':{'metadataOnly':True}})
    await api('PUT','hosts/'+host+'/admission',{'operationId':'remote-admit-'+host,'revision':0,'controllerId':controller,'machineIdentity':'b'*64,'maxConcurrent':1,'reservedInteractive':0,'controlAgentIds':[],'memoryPerTurnBytes':2**30,'reserveMemoryBytes':2**30,'sampleMaxAgeSeconds':15,'connectorMaxAgeSeconds':30})
    # This foreign root deliberately does not exist on the admitting CPU host.
    environment=digest({'hostId':host,'environmentId':'local'})
    workspace=str(uuid5(UUID(host),'physical-root:'+digest([environment,123,456])))
    resource={'hostId':host,'environmentId':'local','root':'/var/lib/remote-host-only-'+host,'device':123,'inode':456,'workspaceId':workspace}
    automatic={'schema':'lax-automatic-native-capture/v3','resources':[resource]}
    seeds={agent:{'workspaceIds':[workspace],'defaultWorkspaceId':workspace}}
    proposal={'schema':'lax-collaboration-admission-proposal/v1','authorityId':i['authorityId'],'hostId':host,'machineIdentity':'b'*64,'hollywoodUrl':'https://untrusted-proposal.invalid','adapterSha256':'c'*64,'enrollmentSha256':digest(automatic),'resources':[resource],'agents':seeds}
    save(fixture/'admission.prepared.json',proposal)
    save(fixture/'administrator.json',{'authorityId':i['authorityId'],'hollywoodUrl':url,'token':i['credentials']['Owner']['token']})
    accepted=await asyncio.to_thread(admit,fixture/'admission.prepared.json',fixture/'administrator.json',fixture/'owner-state')
    save(fixture/'admission.accepted.json',accepted)
    manifest={k:proposal[k] for k in ['authorityId','hostId','adapterSha256','enrollmentSha256']};manifest['admissionProposalSha256']=digest(proposal)
    relay=lambda method,path,payload=None:request(url,key,method,path,payload)
    policy=(await asyncio.to_thread(relay,'GET','hosts/'+host+'/admission'))['policy']
    rows,defaults=await asyncio.to_thread(accepted_resources,fixture,manifest,{'automaticCapture':automatic},seeds,relay,policy)
    assert rows[0]['registryRevision']==1 and len(defaults)==1
    again=await asyncio.to_thread(admit,fixture/'admission.prepared.json',fixture/'administrator.json',fixture/'owner-state');assert again==accepted
    assert c.execute('SELECT revision FROM hb_physical_agent_grant WHERE workspace=%s AND principal=%s',(workspace,agent)).fetchone()['revision']==1
    changed={**accepted,'proposalSha256':'f'*64};save(fixture/'admission.accepted.json',changed)
    try:await asyncio.to_thread(accepted_resources,fixture,manifest,{},seeds,relay,policy)
    except Exception:pass
    else:raise AssertionError('Changed admission receipt accepted')
    save(fixture/'admission.accepted.json',accepted)
    c.execute("UPDATE hb_collaboration_bridge SET state='revoked' WHERE host=%s",(host,))
    try:await asyncio.to_thread(accepted_resources,fixture,manifest,{},seeds,relay,policy)
    except Exception:pass
    else:raise AssertionError('Revoked bridge accepted')
    # Also exercise actual preparation against an existing qualified local owner.
    enrolled=json.loads((root/'host-enrollment.json').read_text())
    existing=protected(Path(enrolled['configPath']))
    spec={'schema':'lax-collaboration-install/v1','controllerConfig':enrolled['configPath'],'bootstrapMode':'preauthorized','captureProtocol':'lax-automatic-native-capture/v3','resources':[{'name':'qa','root':'/var/lib/harness/'+i['authorityId']+'/global/work'}],'agents':{i['credentials']['Global']['principalId']:{'resources':['qa'],'defaultResource':'qa'}},'interpreter':'/var/lib/lax-releases/nextcomp-single-context-20261029-r03/venv/bin/python'}
    prepare(spec,fixture/'local-prepared')
    bridge=protected(fixture/'local-prepared/bridge.prepared.json')
    assert 'administratorConfig' not in bridge['automaticCapture']
    pub=protected(fixture/'local-prepared/admission.prepared.json')
    assert existing['token'] not in json.dumps(pub) and 'token' not in pub
    return {'passed':True,'realPostgreSQLAndHTTP':True,'ownerCredentialNeverSentToProposalURL':True,'remoteRootNotOpenedByOwner':True,'canonicalGrantAndDefaultAdmittedOnce':True,'originalAcceptanceReconciles':True,'changedReceiptRejected':True,'revokedBridgeRejected':True,'actualLocalPreparationOmitsAdministratorConfiguration':True,'publicProposalContainsNoHostCredential':True,'modelsOrServicesStarted':0,'databaseFixturesRolledBack':True}
 try:result=asyncio.run(run())
 finally:c.rollback();shutil.rmtree(fixture)
(root/'remote-collaboration-admission-qualification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
