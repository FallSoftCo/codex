"""Existing two-PG-store/authenticated-NATS fixture + real SDK/HTTP journals.

Only disposable database.json under ROOM_HOME_NATS_QA is used. Native adapter,
host policy and ready facts are synthetic; no native/model/live host effects.
SDK250_HOME_FIXTURE names the reviewed existing API fixture (never modified).
"""
import ast,asyncio,copy,hashlib,json,os,secrets,socket,subprocess,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
import nats,psycopg
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer
from hollywood_backbone.server import application
from hollywood_backbone.store import digest
from hollywood_backbone.federation_identity import describe,install_reference
from hollywood_backbone.federation_agent_gateway import LocalAgentGateway
from hollywood_backbone.federation_node_router import NodeRouter
from hollywood_backbone.federation_domain import AgentDomain
from hollywood_backbone.federation_service import Service
from hollywood_backbone.backplane import BackplaneError
from hollywood_backbone import room_agent_home_http as home_http
from lax_connector.conversational_agent import ConversationalAgent
from lax_connector.errors import HttpFailure
from lax_connector.journal import saved
from lax_connector.room_administration import RoomAdministration,AdministrationUnconfirmed,FACTORY_TOOL
from lax_connector.room_origin_control import RoomOriginControl


async def main():
    root=Path(os.environ['ROOM_HOME_NATS_QA']);source=Path(os.environ['SDK250_HOME_FIXTURE'])
    raw=source.read_bytes();tree=ast.parse(raw,str(source))
    assert ast.unparse(tree.body[-1])=='asyncio.run(main())';tree.body.pop()
    helpers={'__file__':str(source)};exec(compile(tree,str(source),'exec'),helpers)
    cfg=json.loads((root/'database.json').read_text())
    with psycopg.connect(**cfg,autocommit=True) as c:c.execute('CREATE DATABASE room_home')
    authority,cpu,home=[str(uuid4()) for _ in range(3)]
    cs,owner,parent,ct,cb=helpers['boot'](cfg,authority,cpu,'SDK250 isolated canonical')
    hs,ho,hp,ht,hb=helpers['boot']({**cfg,'dbname':'room_home'},authority,home,'SDK250 isolated HOME')
    helpers['enroll_host_reference'](cs,hs,home);helpers['enroll_host_reference'](hs,cs,cpu)
    install_reference(cs,owner,describe(hs,ho,hp),enroll_execution_reference=True)
    install_reference(hs,ho,describe(cs,owner,parent),enroll_execution_reference=True)
    for node,actor in ((cpu,parent),(home,hp)):cs.room_default_set(owner,node,{'agentId':actor,'enabled':True,'revision':0})
    def room():
        identity=str(uuid4());cs.create_room(owner,identity,'SDK250 fixture '+identity,'No business input/model',parent)
        # Explicit synthetic reader grant makes the existing canonical room
        # projection available; this is not any production permission repair.
        with cs.pool.connection() as c:
            c.execute('INSERT INTO hb_membership(authority,room,principal,can_read,can_post,can_request) VALUES(%s,%s,%s,true,true,true) ON CONFLICT DO NOTHING',(authority,identity,hp))
        return identity
    first=room();passwords={k:secrets.token_urlsafe(40) for k in ('cpu','home')}
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    users=[{'user':name,'password':passwords[name],'permissions':{'publish':{'allow':[f'hollywood.v2.{authority}.node.*.service.{node}.>','_INBOX.>','$SRV.>']},'subscribe':{'allow':[f'hollywood.v2.{authority}.node.{node}.service.>','_INBOX.>','$SRV.>']}}} for name,node in (('cpu',cpu),('home',home))]
    saved(root/'nats.conf',{'host':'127.0.0.1','port':port,'authorization':{'users':users}})
    log=(root/'nats.log').open('w');broker=subprocess.Popen(['/opt/hollywood-node-cpu-20261029-r01/nats-server','-c',str(root/'nats.conf')],stdout=log,stderr=log)
    clients=[];services=[];apis=[];attach=[];lost=[False];interrupt=[True];hold_read=[True];posts=[];native=[]
    original_prepare=home_http.prepare
    async def prepare(*a):
        if interrupt[0]:interrupt[0]=False;raise BackplaneError('SYNTHETIC_INTERRUPTED_LOCAL_PREPARE')
        return await original_prepare(*a)
    try:
        deadline=time.monotonic()+5
        while 'Server is ready' not in (root/'nats.log').read_text():
            if broker.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Owned fixture broker failed')
            await asyncio.sleep(.02)
        for name in ('cpu','home'):clients.append(await nats.connect(f'nats://127.0.0.1:{port}',user=name,password=passwords[name]))
        for connection,node,bindings,store in ((clients[0],cpu,cb,cs),(clients[1],home,hb,hs)):
            domain=AgentDomain(bindings)
            async def receive(req,domain=domain,node=node):
                mutation=req.payload.get('action')=='room_agent_home_attach'
                if mutation:attach.append(req.request_id)
                value=await domain.invoke(req)
                if mutation and not lost[0]:lost[0]=True;raise BackplaneError('REPLY_UNKNOWN')
                return value
            service=Service(connection,authority_id=authority,host_id=node,node_id=node,legacy=False,handlers={'hollywood.agent.domain':receive,'hollywood.agent.authenticate':domain.authenticate})
            await service.start();services.append(service)
            gateway=LocalAgentGateway(connection,authority_id=authority,host_id=node,node_id=node)
            api=TestServer(application(store,node_router=NodeRouter(store,gateway),federated_agent_gateway=gateway));await api.start_server();apis.append(api)
        async with ClientSession() as session:
            manifest=root/'manifest';saved(manifest,{'fixture':True,'socket':str(root/'NO-NATIVE-SOCKET')});guide=root/'AGENTS.md';guide.write_text('SYNTHETIC no native/model')
            config={'runtimeMode':'room-conversation','authorityId':authority,'agentId':hp,'hostId':home,
                'state':str(root/'parent'),'token':ht['Global'],'hollywoodUrl':str(apis[1].make_url('/')).rstrip('/'),
                'nativeServer':{'manifest':str(manifest)},'model':'SYNTHETIC-NO-PROVIDER','effort':'low','binary':'/SYNTHETIC/NO-NATIVE','codexHome':str(root/'unused-profile'),
                'roomOriginPolicy':{'path':'/SYNTHETIC/POLICY','sha256':'1'*64}}
            transport=SimpleNamespace(config=config,session=session)
            async def request(method,path,body=None):
                if method!='GET':posts.append((path,body))
                if hold_read[0] and path.startswith('administration/commands/'):
                    hold_read[0]=False;raise ConnectionError('SYNTHETIC original inspection interrupted')
                return await ConversationalAgent.http(transport,method,path,body)
            supervisor=SimpleNamespace(config=config,attach=lambda r:None,reconcile_admission=lambda:None,checkpoint=lambda:None)
            policy={'root':str(root/'agents'),'nativeIdentity':{'fixture':True},'initialPermissions':{'sandbox':'danger-full-access','approvalPolicy':'never'},'operatingInstructions':[{'path':str(guide),'sha256':hashlib.sha256(guide.read_bytes()).hexdigest()}]}
            async def adapter(file,directory,**kw):
                spec=json.loads(file.read_text());native.append(spec['operationId'])
                assert all(spec['connectorConfig'][k]==policy['initialPermissions'][k] for k in ('sandbox','approvalPolicy'))
                return {**{k:spec[k] for k in ('operationId','authorityId','originRoomId','agentId','hostId')},'state':'ready','nativeThreadId':'SYNTHETIC-'+spec['agentId'],'sharedAppServer':True,'appServerManifestSha256':hashlib.sha256(manifest.read_bytes()).hexdigest()}
            import importlib
            original_import=importlib.import_module
            def modules(name,*a,**kw):return SimpleNamespace(provision_local=adapter) if name=='.room_factory_linux' else original_import(name,*a,**kw)
            control=RoomOriginControl(config=config,request=request,thread='SYNTHETIC-ORIGINAL-GLOBAL',state=root/'control',session_supervisor=supervisor)
            catalog=await request('GET','rooms');slot=next(s for s in catalog['roomAgentInitializations'] if s['room']==first)
            key=hashlib.sha256((first+'\0'+home+'\0'+slot['agent']).encode()).hexdigest()
            def admin():return RoomAdministration(authority=authority,agent=hp,thread=control.thread,request=request,state=control.state/key,host_config=config,session_supervisor=supervisor)
            with patch.object(home_http,'prepare',prepare),patch('lax_connector.room_session_files.host_policy',return_value=(policy,{})),patch('lax_connector.room_origin_factory.importlib.import_module',modules):
                with_raise=False
                try:await admin().call(FACTORY_TOOL,{'roomId':first},'room-origin:'+key)
                except AdministrationUnconfirmed:with_raise=True
                assert with_raise and not attach and not native
                credential=Path(config['state'])/'room-origin-factory'/('agent-credential-'+slot['agent']+'.json');original_credential=credential.read_bytes()
                base='rooms/'+first+'/environment-agents'
                for i in range(2):
                    inventory=await request('GET',base);own=next(r for r in inventory['agents'] if r['node']==home)
                    await request('POST',base+'/'+home+'/report',{'operationId':'fixture-prior-blocked-'+str(i),'revision':own['revision'],'state':'blocked','note':'SYNTHETIC legacy diagnostic; no native','receipt':None})
                prior=await request('GET',base);catalog=await request('GET','rooms');slot=next(s for s in catalog['roomAgentInitializations'] if s['room']==first)
                saved(control.state/(key+'.json'),{'state':'reported','slot':slot,'attempts':8,'result':prior})
                try:await admin().call(FACTORY_TOOL,{'roomId':first},'room-origin:'+key)
                except AdministrationUnconfirmed:pass
                else:raise AssertionError('Lost canonical attach ACK was not held')
                assert len(attach)==1 and not native
                from uuid import UUID,uuid5
                enroll='room-origin:'+str(uuid5(UUID(slot['agent']),'host-initialization'))+':enroll'
                receipt=await request('GET','administration/commands/'+enroll);assert receipt['operationId']==enroll
                fresh=await request('GET','rooms');current=next(s for s in fresh['roomAgentInitializations'] if s['room']==first)
                assert current['state']=='blocked' and current['revision']==slot['revision'] # Identity projection is the real edge.
                control.observe(fresh);await asyncio.gather(*list(control.active.values()))
                assert len(native)==1 and credential.read_bytes()==original_credential
                assert sum(path.endswith('/enroll') for path,_ in posts)==2 and len(attach)==1
                assert (control.state/(key+'-attempt-8.json')).exists()
                assert json.loads((control.state/(key+'.json')).read_text())['result']['operationId']==json.loads(next((control.state/key).glob('workflow-*.json')).read_text())['operationId']
                second=room();fresh=await request('GET','rooms')
                place=hs.placement_read(ho,hp);hs.placement_state(ho,hp,{'operationId':'fixture-pause','revision':place['placement']['revision'],'hostId':home,'enabled':False})
                before=len(posts);control.observe(fresh);await asyncio.gather(*list(control.active.values()));assert len(posts)==before
                place=hs.placement_read(ho,hp);hs.placement_state(ho,hp,{'operationId':'fixture-enable','revision':place['placement']['revision'],'hostId':home,'enabled':True})
                control.observe(await request('GET','rooms'));await asyncio.gather(*list(control.active.values()))
                assert len(native)==2 and len(attach)==2
                await control.close()
            with hs.pool.connection() as c:
                births=c.execute('SELECT count(*) AS n FROM hb_room_agent_home_birth').fetchone()['n']
                phases=c.execute('SELECT phase FROM hb_room_agent_home_outbound').fetchall()
            assert births==2 and all(r['phase']=='answered' for r in phases)
            result={'passed':True,'realPgStores':2,'realAuthenticatedNatsNodes':2,'realHttpAndHomeDispatchCAS':True,
                'canonicalAttachMutations':len(attach),'sameOriginalWorkflowCredentialAfterReportedCanonicalChange':True,
                'knownNotDispatchedContinuationAndLostAckReadback':True,'actualParentPauseEnableDeferral':True,
                'syntheticNativeAdapterCalls':len(native),'realNativeCalls':0,'modelCalls':0,
                'fixtureSourceSha256':hashlib.sha256(raw).hexdigest(),'limits':['Disposable CPU logical HOME nodes, not fleet readiness.','Native/host-policy facts are synthetic; no Ready claim.','Private loopback broker, not production TLS qualification.']}
            saved(root/'result.json',result);print(json.dumps(result))
    finally:
        for api in apis:await api.close()
        for service in services:await service.stop()
        for client in clients:await client.close()
        broker.terminate();broker.wait(timeout=5);log.close();cs.close();hs.close()
        saved(root/'closure.json',{'ownedBrokerPid':broker.pid,'brokerExit':broker.returncode,'servicesAndClientsClosed':True})


asyncio.run(main())
