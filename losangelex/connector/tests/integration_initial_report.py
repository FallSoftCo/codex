"""Actual API180 model + two PG/HOME stores + NATS + full Mac factory boundary.

CPU only: synthetic Darwin NSS/process/native RPC, ZERO real native/model calls.
Existing reviewed disposable HOME fixture provides stores/auth, not production.
"""
import ast,asyncio,hashlib,importlib.util,json,os,secrets,socket,subprocess,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID,uuid4
import nats,psycopg
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer
from hollywood_backbone import server
from hollywood_backbone.federation_identity import describe,install_reference
from hollywood_backbone.federation_agent_gateway import LocalAgentGateway
from hollywood_backbone.federation_node_router import NodeRouter
from hollywood_backbone.federation_domain import AgentDomain
from hollywood_backbone.federation_service import Service
from lax_connector import room_origin_factory as factory,room_session_files as sessions,room_initial_report as reports
from lax_connector.conversational_agent import ConversationalAgent
from lax_connector.room_administration import RoomAdministration,AdministrationSteps,AdministrationUnconfirmed,FACTORY_TOOL,digest
from lax_connector.room_initial_configuration import journal_path as configuration_journal
from lax_connector.room_host_provision import HostProvisionUnconfirmed
from lax_connector.journal import saved


async def main():
    root=Path(os.environ['ROOM_HOME_NATS_QA']);source=Path(os.environ['SDK250_HOME_FIXTURE'])
    tree=ast.parse(source.read_text());assert ast.unparse(tree.body[-1])=='asyncio.run(main())';tree.body.pop()
    helpers={'__file__':str(source)};exec(compile(tree,str(source),'exec'),helpers)
    assert hashlib.sha256(Path(server.__file__).read_bytes()).hexdigest()==reports.CONTRACT['serverSourceSha256']
    cfg=json.loads((root/'database.json').read_text())
    with psycopg.connect(**cfg,autocommit=True) as c:c.execute('CREATE DATABASE room_home')
    authority,cpu,home=[str(uuid4()) for _ in range(3)]
    cs,owner,parent,ct,cb=helpers['boot'](cfg,authority,cpu,'SDK251 isolated canonical')
    hs,ho,hp,ht,hb=helpers['boot']({**cfg,'dbname':'room_home'},authority,home,'SDK251 isolated HOME')
    helpers['enroll_host_reference'](cs,hs,home);helpers['enroll_host_reference'](hs,cs,cpu)
    install_reference(cs,owner,describe(hs,ho,hp),enroll_execution_reference=True)
    install_reference(hs,ho,describe(cs,owner,parent),enroll_execution_reference=True)
    for node,actor in ((cpu,parent),(home,hp)):cs.room_default_set(owner,node,{'agentId':actor,'enabled':True,'revision':0})
    passwords={n:secrets.token_urlsafe(40) for n in ('cpu','home')}
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    users=[{'user':name,'password':passwords[name],'permissions':{'publish':{'allow':[f'hollywood.v2.{authority}.node.*.service.{node}.>','_INBOX.>','$SRV.>']},'subscribe':{'allow':[f'hollywood.v2.{authority}.node.{node}.service.>','_INBOX.>','$SRV.>']}}} for name,node in (('cpu',cpu),('home',home))]
    saved(root/'nats.conf',{'host':'127.0.0.1','port':port,'authorization':{'users':users}})
    log=(root/'nats.log').open('w');broker=subprocess.Popen(['/opt/hollywood-node-cpu-20261029-r01/nats-server','-c',str(root/'nats.conf')],stdout=log,stderr=log)
    clients=[];services=[];apis=[];domain_reports=[];invokes=[];cases=[];results=[]
    fixture_source=Path(__file__).resolve().parents[1]/'platform_qualification/macos-resident-r03/test_room_factory_macos.py'
    module=importlib.util.spec_from_file_location('macfiles_report_fixture',fixture_source);fixture=importlib.util.module_from_spec(module);module.loader.exec_module(fixture)
    fixture.ROOT=Path(os.environ['SDK250_MAC_QA'])
    original_invoke=server.invoke
    async def invoke(req,method,*args):
        if method=='room_agent_report':invokes.append(args)
        return await original_invoke(req,method,*args)
    try:
        deadline=time.monotonic()+5
        while 'Server is ready' not in (root/'nats.log').read_text():
            if broker.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Owned fixture broker unavailable')
            await asyncio.sleep(.02)
        for name in ('cpu','home'):clients.append(await nats.connect(f'nats://127.0.0.1:{port}',user=name,password=passwords[name]))
        for connection,node,bindings,store in ((clients[0],cpu,cb,cs),(clients[1],home,hb,hs)):
            domain=AgentDomain(bindings)
            async def receive(req,domain=domain):
                if req.payload.get('action')=='room_agent_report':domain_reports.append(req.request_id)
                return await domain.invoke(req)
            service=Service(connection,authority_id=authority,host_id=node,node_id=node,legacy=False,
                handlers={'hollywood.agent.domain':receive,'hollywood.agent.authenticate':domain.authenticate})
            await service.start();services.append(service)
            gateway=LocalAgentGateway(connection,authority_id=authority,host_id=node,node_id=node)
            api=TestServer(server.application(store,node_router=NodeRouter(store,gateway),federated_agent_gateway=gateway));await api.start_server();apis.append(api)
        async with ClientSession() as session:
            for mode in ('lost-ack','unknown-before-wire'):
                room=str(uuid4());cs.create_room(owner,room,'SDK251 fixture '+room,'No business/model',parent)
                with cs.pool.connection() as c:c.execute('INSERT INTO hb_membership(authority,room,principal,can_read,can_post,can_request) VALUES(%s,%s,%s,true,true,true) ON CONFLICT DO NOTHING',(authority,room,hp))
                # Own authenticated HTTP first discovers the exact canonical child.
                transport=SimpleNamespace(config={'authorityId':authority,'agentId':hp,'hostId':home,'token':ht['Global'],
                    'hollywoodUrl':str(apis[1].make_url('/')).rstrip('/')},session=session)
                async def http(method,path,body=None):return await ConversationalAgent.http(transport,method,path,body)
                base='rooms/'+room+'/environment-agents';inventory=await http('GET',base)
                child=next(r['agent'] for r in inventory['agents'] if r['node']==home)
                case=fixture.ResidentFilesTests()
                with patch.object(fixture,'uuid4',side_effect=[UUID(authority),UUID(room),UUID(child),UUID(home),UUID(hp),uuid4()]):case.setUp()
                cases.append(case);case.public_spec()
                config=json.loads((case.b/'parent.private.json').read_text())
                config.update(runtimeMode='room-conversation',hollywoodUrl=transport.config['hollywoodUrl'],token=ht['Global'],model='declared-model',effort='xhigh')
                case.put(case.b/'parent.private.json',config);case.policy.update(parentConfig=case.pin(case.b/'parent.private.json'),operatingInstructions=[case.pin(case.b/'OPERATIONS.txt')])
                case.put(case.policyfile,case.policy);config['roomOriginPolicy']=case.pin(case.policyfile);transport.config=config
                posts=[];enabled=[False];receipt_down=[False];bad_status=[];bounded_wire=[]
                async def request(method,path,body=None):
                    if method=='GET' and path.startswith('administration/commands/') and receipt_down[0]:
                        # Actual canonical command GET is denied/unavailable, NOT
                        # permission to resend a bounded unknown metadata request.
                        from lax_connector.errors import HttpFailure
                        raise HttpFailure(403,'SYNTHETIC receipt visibility unavailable')
                    bounded=method=='POST' and path.endswith('/report') and body['operationId'].startswith('room-report:v1:')
                    if method!='GET':posts.append((path,body))
                    if bounded:
                        bounded_wire.append(dict(body))
                        if mode=='unknown-before-wire' and enabled[0]:
                            receipt_down[0]=True;raise ConnectionError('SYNTHETIC ambiguous transport before wire')
                    try:value=await http(method,path,body)
                    except Exception as error:
                        if method=='POST' and path.endswith('/report') and len(body['operationId'])>128:bad_status.append(getattr(error,'status',None))
                        raise
                    if bounded and enabled[0]:receipt_down[0]=True;raise ConnectionError('SYNTHETIC ACK lost AFTER actual PG commit')
                    return value
                attached=[];supervisor=SimpleNamespace(config=config,attach=lambda r:attached.append(r))
                state=case.b/'administration';thread=case.parentthread;call_id='room-origin:'+hashlib.sha256(room.encode()).hexdigest()
                def admin():return RoomAdministration(authority=authority,agent=hp,thread=thread,request=request,state=state,host_config=config,session_supervisor=supervisor)
                real=factory.origin_configuration
                def legacy(*a,**kw):v=real(*a,**kw);v.pop('sandbox');v.pop('approvalPolicy');return v
                with patch.object(server,'invoke',invoke),patch.object(factory,'sys',SimpleNamespace(platform='darwin')),patch.object(sessions,'host_policy',sessions.macos_host_policy):
                    with patch.object(factory,'origin_configuration',legacy):first=await admin().call(FACTORY_TOOL,{'roomId':room},call_id)
                    operation=first['operationId'];assert len(operation)==49
                    before=(len(invokes),len(domain_reports))
                    # Reproduce exact SDK250 production-shaped bad136 request.
                    with patch.object(reports,'report_id',side_effect=lambda value:value):
                        try:await admin().call('hollywood_admin_reconcile',{'operationId':operation},'original')
                        except AdministrationUnconfirmed:pass
                        else:raise AssertionError('Actual API180 must reject original136')
                    assert bad_status==[400] and before==(len(invokes),len(domain_reports))
                    assert case.rpc_calls.count('thread/start')==1 and len(attached)==1
                    oldpath=configuration_journal(state,operation);old=json.loads(oldpath.read_text())
                    old_step=state/digest(operation)/('initial-configuration-'+old['configurationSuccessor']['spec']['sha256'])/'6.json'
                    bad_id=json.loads(old_step.read_text())['operationId']
                    try:await http('GET','administration/commands/'+bad_id)
                    except Exception as error:
                        assert error.status==403
                        AdministrationSteps(admin(),operation,workflow=old).inspection(old_step,error)
                    else:raise AssertionError('Invalid original report unexpectedly has a receipt')
                    selected_path,selected=reports.select(admin(),oldpath,old);proof=selected['reportSuccessor'];pins={**old['configurationSuccessor']['originalFiles'],**proof['originalFiles']}
                    assert len(proof['originalOperationId'])==136 and len(proof['reportOperationId'])==79
                    # Ambiguous native receipt and wire drift must fail BEFORE any HTTP/native retry.
                    context=Path(next(p for p in pins if p.endswith('/native-context.json')));raw=context.read_bytes();v=json.loads(raw);v.update(state='creating',threadStartAttempted=True);saved(context,v)
                    try:reports.select(admin(),oldpath,old)
                    except HostProvisionUnconfirmed:pass
                    else:raise AssertionError('Unknown native evidence was accepted')
                    context.write_bytes(raw)
                    legacy_step=old_step.read_bytes();changed=json.loads(legacy_step);changed['wireDigest']='0'*64;saved(old_step,changed)
                    try:reports.select(admin(),oldpath,old)
                    except HostProvisionUnconfirmed:pass
                    else:raise AssertionError('Changed original report wire was accepted')
                    old_step.write_bytes(legacy_step)
                    native_before=list(case.rpc_calls);enabled[0]=True
                    with patch.object(factory,'provision',side_effect=AssertionError('NO factory/native replay')):
                        try:await admin().call('hollywood_admin_reconcile',{'operationId':operation},'original')
                        except AdministrationUnconfirmed:pass
                        else:raise AssertionError('Receipt outage must retain bounded original unknown')
                        if mode=='unknown-before-wire':
                            try:await admin().call('hollywood_admin_reconcile',{'operationId':operation},'original')
                            except AdministrationUnconfirmed:pass
                            else:raise AssertionError('403/absent receipt cannot permit resend')
                            assert len(bounded_wire)==1
                            # Explicit fixture operator supplies the SAME exact
                            # metadata wire once; SDK never resent it itself.
                            await http('POST',base+'/'+home+'/report',bounded_wire[0])
                        final=await admin().call('hollywood_admin_reconcile',{'operationId':operation},'original')
                        again=await admin().call('hollywood_admin_reconcile',{'operationId':operation},'original')
                    assert final==again and final['reportDisposition']=='matching-canonical-receipt-read'
                    assert len(bounded_wire)==1 and case.rpc_calls==native_before
                    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in pins.items())
                    current=await http('GET',base);own=reports.slot(current,room,home,child,hp);assert own['receipt']==proof['receipt']
                    # The actual HTTP model accepts128, rejects129 before domain.
                    valid={'operationId':'B'*92+room,'revision':own['revision'],'state':'provisioning','note':reports.NOTE,'receipt':proof['receipt']}
                    before=(len(invokes),len(domain_reports))
                    try:await http('POST',base+'/'+home+'/report',{**valid,'operationId':valid['operationId']+'X'})
                    except Exception as error:assert error.status==400
                    else:raise AssertionError('129 characters were accepted')
                    assert before==(len(invokes),len(domain_reports))
                    await http('POST',base+'/'+home+'/report',valid)
                    assert len(invokes)>before[0] and len(domain_reports)>before[1] # Real NATS path exercised.
                    with cs.pool.connection() as c:
                        rejected=c.execute('SELECT count(*) AS n FROM hb_administrative_command WHERE operation=%s',(proof['originalOperationId'],)).fetchone()['n']
                        accepted=c.execute('SELECT count(*) AS n FROM hb_administrative_command WHERE operation=%s',(proof['reportOperationId'],)).fetchone()['n']
                    assert rejected==0 and accepted==1
                    results.append({'mode':mode,'passed':True,'legacyLength':136,'boundedLength':79,'legacyHttpStatus':400,
                        'invalidBeforeInvokeAndNats':True,'actual128Accepted129Rejected':True,'rejectedCommandRows':rejected,
                        'boundedCommandRows':accepted,'sdkBoundedPostAttempts':1,'originalProofFilesUnchanged':len(pins),
                        'actualOldReceipt403RetainedNotUsedAsProof':True,'wireAndNativeUnknownRejected':True,
                        'syntheticThreadStartAttempts':1,'threadStartsDuringReportRecovery':0,'canonicalReceiptReadCompletes':True})
                case.doCleanups();case.tearDown();cases.remove(case)
        result={'passed':True,'api180ServerSourceSha256':reports.CONTRACT['serverSourceSha256'],'realPgStores':2,
            'realAuthenticatedNatsNodes':2,'scenarios':results,'realNativeCalls':0,'modelCalls':0,
            'limits':'Synthetic Darwin processes/NSS/native RPC only; actual HTTP validator/NATS/PG and Mac adapter/files. Not fleet Ready.'}
        saved(root/'result.json',result);print(json.dumps(result))
    finally:
        for case in cases:case.doCleanups();case.tearDown()
        for api in apis:await api.close()
        for service in services:await service.stop()
        for client in clients:await client.close()
        broker.terminate();broker.wait(timeout=5);log.close();cs.close();hs.close()
        saved(root/'closure.json',{'brokerExit':broker.returncode,'servicesClientsClosed':True})


asyncio.run(main())
