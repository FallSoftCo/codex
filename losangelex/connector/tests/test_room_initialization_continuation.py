"""Real loopback HTTP and original journals; HOME/native authority is synthetic.

No model, real native bootstrap, production authority/credential or placement
write is used. This does not claim PostgreSQL/server-CAS qualification.
"""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4, uuid5

from aiohttp import ClientSession, web
from lax_connector.conversational_agent import ConversationalAgent
from lax_connector.errors import HttpFailure
from lax_connector.journal import saved
from lax_connector.room_administration import RoomAdministration, AdministrationSteps, AdministrationUnconfirmed, FACTORY_TOOL, digest
from lax_connector.room_origin_control import RoomOriginControl,enrollment_projection


class ContinuationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.authority,self.actor,self.node,self.room,self.child=[str(uuid4()) for _ in range(5)]
        self.binding={'authority':self.authority,'agent':self.actor,'thread':'ORIGINAL-THREAD'}
        self.operation='native-admin:'+str(uuid4())
        self.base='rooms/'+self.room+'/environment-agents'
        self.path=self.base+'/'+self.node+'/enroll'
        self.payload={'operationId':'room-origin:'+str(uuid5(UUID(self.child),'host-initialization'))+':enroll',
                      'enrollmentCredential':'SYNTHETIC-NOT-A-CREDENTIAL'}
        self.phase='preparing';self.posts=[];self.reads=[];self.lose_reply=False
        self.interrupt_prepare=False;self.allocations=[]
        self.attachments=0;self.receipt_override={}
        self.error={'error':'ORIGINAL_HOME_ATTACHMENT_NOT_DISPATCHED','mayApply':False};self.status=503
        self.enabled=False;self.placement_revision=1;self.placement_host=self.node
        self.pause_on_room_read=False
        self.slot={'room':self.room,'node':self.node,'agent':self.child,'coordinator':self.actor,'revision':1,
                   'state':'pending','receipt':None}
        async def handle(request):
            self.assertEqual(request.headers['Authorization'],'Bearer SYNTHETIC-ACTOR')
            self.assertEqual(request.headers['X-Hollywood-Authority'],self.authority)
            self.assertEqual(request.headers['X-Hollywood-Agent'],self.actor)
            path=request.path.removeprefix('/hollywood/v3/')
            if path=='placements/'+self.actor:
                self.reads.append(path)
                row={'authority':self.authority,'agent':self.actor,'host':self.placement_host,
                     'enabled':self.enabled,'generation':1,'revision':self.placement_revision}
                return web.json_response({'schema':'hollywood-placement/v1','authorityId':self.authority,
                    'agentId':self.actor,'hostId':self.placement_host,'placement':row,
                    'state':'enabled' if self.enabled else 'paused','mayApply':False,
                    'newExecutionAdmitted':False,'drainVerified':False})
            if request.method=='GET' and path=='administration/commands/'+self.payload['operationId']:
                self.reads.append(path)
                if self.phase!='accepted':return web.json_response(self.error,status=self.status)
                receipt={'schema':'hollywood-administrative-command/v1',
                    'authorityId':self.authority,'actorId':self.actor,'operationId':self.payload['operationId'],
                    'method':'POST','path':self.path,'wireDigest':digest({'method':'POST','path':self.path,'body':self.payload}),
                    'acceptedResult':{'agentId':self.child,'sameOperation':self.payload['operationId']}}
                receipt.update(self.receipt_override);return web.json_response(receipt)
            if request.method=='POST' and path==self.path:
                body=await request.json();self.posts.append(body);self.assertEqual(body,self.payload)
                if self.interrupt_prepare:
                    self.interrupt_prepare=False
                    self.phase='preparing';self.error={'error':'SYNTHETIC_INSPECTION_UNAVAILABLE','mayApply':True}
                    return web.json_response({'error':'ORIGINAL_HOME_ATTACHMENT_NOT_DISPATCHED','mayApply':False},status=503)
                if self.phase!='accepted':self.attachments+=1
                self.phase='accepted'
                if self.lose_reply:
                    self.lose_reply=False
                    return web.json_response({'error':'SYNTHETIC_REPLY_LOST_AFTER_ACCEPTANCE'},status=503)
                return web.json_response({'agentId':self.child,'sameOperation':body['operationId']})
            if path=='principals/'+self.actor:
                return web.json_response({'id':self.actor,'authority':self.authority,'active':True,
                                          'kind':'agent','administrator':True})
            if path=='principals/'+self.child:return web.json_response({'name':'SYNTHETIC contributor'})
            if path=='agents/'+self.child+'/role':
                return web.json_response({'home_room':self.room,'primary_role':'room-agent','purpose':'Synthetic fixture'})
            if request.method=='POST' and path==self.base:
                self.allocations.append(await request.json())
                return web.json_response({'agents':[self.slot],'complete':False})
            if request.method=='POST' and path==self.base+'/'+self.node+'/report':
                return web.json_response({'agents':[self.slot],'complete':False})
            if request.method=='GET' and path.startswith('rooms/'):
                if self.pause_on_room_read:self.enabled=False;self.placement_revision+=1
                return web.json_response({'capabilities':{},'agents':[self.slot],'complete':False})
            self.fail('Unexpected HTTP '+request.method+' '+path)
        app=web.Application();app.router.add_route('*','/hollywood/v3/{tail:.*}',handle)
        runner=web.AppRunner(app,access_log=None);await runner.setup();self.addAsyncCleanup(runner.cleanup)
        site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        self.session=ClientSession();self.addAsyncCleanup(self.session.close)
        self.config={'authorityId':self.authority,'agentId':self.actor,'hostId':self.node,
            'token':'SYNTHETIC-ACTOR','hollywoodUrl':'http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1]),
            'state':str(self.root/'parent')}
        self.http=SimpleNamespace(config=self.config,session=self.session)
        self.request=lambda *args:ConversationalAgent.http(self.http,*args)

    def steps(self,label='original'):
        state=self.root/label;state.mkdir()
        owner=SimpleNamespace(config={'authorityId':self.authority,'agentId':self.actor},
            host_config=self.config,binding=self.binding,state=state,request=self.request)
        record={'tool':FACTORY_TOOL,'operationId':self.operation,'arguments':{'roomId':self.room},
                'binding':dict(self.binding),'state':'unconfirmed'}
        directory=state/digest(self.operation);directory.mkdir()
        saved(directory/'0.json',{'state':'accepted','wireDigest':digest({'method':'POST','path':self.base,
              'body':{'operationId':self.operation+':allocate'}}),'result':{'allocated':True}})
        slot={'room':self.room,'node':self.node,'agent':self.child,'coordinator':self.actor,'revision':1}
        saved(directory/'1.json',{'state':'accepted','wireDigest':digest({'method':'GET','path':self.base,'body':None}),
                                 'result':{'agents':[slot]}})
        # Exact SDK249 shape: no invented method/path/accepted receipt on upgrade.
        saved(directory/'2.json',{'state':'sending','wireDigest':digest({'method':'POST','path':self.path,'body':self.payload}),
                                 'operationId':self.payload['operationId']})
        steps=AdministrationSteps(owner,self.operation,workflow=record);steps.position=2
        return steps,directory

    async def test_real_http_retains_structured_not_dispatched_proof(self):
        with self.assertRaises(HttpFailure) as caught:
            await self.request('GET','administration/commands/'+self.payload['operationId'])
        self.assertEqual((caught.exception.status,caught.exception.code,caught.exception.may_apply),
                         (503,'ORIGINAL_HOME_ATTACHMENT_NOT_DISPATCHED',False))
        self.assertIs(caught.exception.public_details()['mayApply'],False)

    async def test_reported_only_reopens_original_sending_enrollment_on_canonical_edge(self):
        key='f'*64
        control=RoomOriginControl(config=self.config,request=self.request,thread='ORIGINAL-THREAD',state=self.root/'control')
        self.addAsyncCleanup(control.close)
        identity=str(uuid5(UUID(self.actor),digest(['ORIGINAL-THREAD','room-origin:'+key])))
        operation='native-admin:'+identity
        state=control.state/key;state.mkdir();directory=state/digest(operation);directory.mkdir()
        workflow={'state':'unconfirmed','tool':FACTORY_TOOL,'arguments':{'roomId':self.room},
            'binding':self.binding,'operationId':operation}
        file=state/('workflow-'+identity+'.json');saved(file,workflow)
        saved(state/'pending.json',{'operationId':operation,'binding':self.binding})
        for i in (0,1):saved(directory/(str(i)+'.json'),{'state':'accepted'})
        saved(directory/'2.json',{'state':'sending','operationId':self.payload['operationId']})
        before={'identity_active':False,'origin_room':None,'origin_node':None,'member':False,
            'coordinator_enabled':True,'current_coordinator':self.actor}
        after={**before,'identity_active':True,'origin_room':self.room,'origin_node':self.node,'member':True}
        old={'state':'reported','canonicalEnrollment':before,'attempts':8}
        self.assertTrue(control.changed_reported_enrollment(key,self.slot,old,after))
        self.assertFalse(control.changed_reported_enrollment(key,self.slot,old,before))
        for field in ('origin_room','origin_node','current_coordinator','member','identity_active'):
            changed={**after,field:False}
            self.assertFalse(control.changed_reported_enrollment(key,self.slot,old,changed))
        for status in ('completed','rejected'):
            saved(file,{**workflow,'state':status})
            self.assertFalse(control.changed_reported_enrollment(key,self.slot,old,after))
        saved(file,workflow)
        factory=Path(self.config['state'])/'room-origin-factory'/('room-origin-'+self.child)
        factory.mkdir(parents=True);saved(factory/'spec.private.json',{'never':'absence-based native recovery'})
        self.assertFalse(control.changed_reported_enrollment(key,self.slot,old,after))
        # Diagnostic timestamps/freshness do not themselves create a wake edge.
        setup={'roomId':self.room,'agents':[{**self.slot,**after,'updated_at':'ignored','control_revision':50}]}
        self.assertEqual(enrollment_projection(self.config,self.slot,setup),after)
        self.assertEqual(self.posts,[])

    async def test_same_original_preparing_step_continues_and_retains_facts(self):
        steps,directory=self.steps();prefix=[(directory/(str(i)+'.json')).read_bytes() for i in (0,1)]
        result=await steps.http('POST',self.path,self.payload)
        self.assertEqual(result,{'agentId':self.child,'sameOperation':self.payload['operationId']})
        self.assertEqual(self.posts,[self.payload])
        self.assertEqual(prefix,[(directory/(str(i)+'.json')).read_bytes() for i in (0,1)])
        step=json.loads((directory/'2.json').read_text())
        self.assertEqual(step['operationId'],self.payload['operationId']);self.assertEqual(step['state'],'accepted')
        self.assertEqual(step['lastInspection']['code'],'ORIGINAL_HOME_ATTACHMENT_NOT_DISPATCHED')
        self.assertTrue(step['lastInspection']['continuation']);self.assertEqual(len(list((directory/'observations').iterdir())),2)
        steps.position=2;again=await steps.http('POST',self.path,self.payload)
        self.assertEqual(again,result);self.assertEqual(self.posts,[self.payload])

    async def test_lost_continuation_reply_requires_readback_never_another_post(self):
        steps,directory=self.steps();self.lose_reply=True
        with self.assertRaises(AdministrationUnconfirmed):await steps.http('POST',self.path,self.payload)
        self.assertEqual(json.loads((directory/'2.json').read_text())['state'],'sending')
        steps=AdministrationSteps(steps.owner,self.operation,workflow=steps.workflow);steps.position=2
        result=await steps.http('POST',self.path,self.payload)
        self.assertEqual(result['sameOperation'],self.payload['operationId']);self.assertEqual(self.posts,[self.payload])
        self.assertEqual(len(list((directory/'observations').iterdir())),3)

    async def test_interrupted_full_factory_reopens_same_workflow_and_credential(self):
        import importlib
        import hashlib
        manifest=self.root/'manifest';saved(manifest,{'fixture':True})
        guide=self.root/'AGENTS.md';guide.write_text('SYNTHETIC no native/model fixture')
        self.config.update(nativeServer={'manifest':str(manifest)},model='SYNTHETIC-NO-MODEL',effort='low',
            binary='/SYNTHETIC/NO-NATIVE',codexHome=str(self.root/'unused-profile'),
            roomOriginPolicy={'path':'/SYNTHETIC/POLICY','sha256':'1'*64})
        self.operation='native-admin:'+str(uuid5(UUID(self.actor),digest(['ORIGINAL-THREAD','ORIGINAL-CALL'])))
        self.interrupt_prepare=True
        # The factory's one newly-created fixture credential is captured only
        # inside this loopback handler, never printed or imported from a host.
        original_request=self.request
        async def request(method,path,payload=None):
            if method=='POST' and path==self.path and not self.posts:self.payload=dict(payload)
            return await original_request(method,path,payload)
        attached=[];native=[]
        supervisor=SimpleNamespace(config=self.config,attach=lambda r:attached.append(r))
        policy={'root':str(self.root/'agents'),'nativeIdentity':{'fixture':True},
            'initialPermissions':{'sandbox':'danger-full-access','approvalPolicy':'never'},
            'operatingInstructions':[{'path':str(guide),'sha256':hashlib.sha256(guide.read_bytes()).hexdigest()}]}
        async def adapter(file,directory,**kwargs):
            spec=json.loads(file.read_text());native.append(spec['operationId'])
            self.assertEqual({k:spec['connectorConfig'][k] for k in ('sandbox','approvalPolicy')},
                             policy['initialPermissions'])
            return {**{k:spec[k] for k in ('operationId','authorityId','originRoomId','agentId','hostId')},
                'state':'ready','nativeThreadId':'SYNTHETIC-NO-REAL-THREAD','sharedAppServer':True,
                'appServerManifestSha256':hashlib.sha256(manifest.read_bytes()).hexdigest()}
        real_import=importlib.import_module
        def modules(name,*a,**kw):
            return SimpleNamespace(provision_local=adapter) if name=='.room_factory_linux' else real_import(name,*a,**kw)
        def admin():return RoomAdministration(authority=self.authority,agent=self.actor,thread='ORIGINAL-THREAD',
            request=request,state=self.root/'factory-admin',host_config=self.config,session_supervisor=supervisor)
        with patch('lax_connector.room_session_files.host_policy',return_value=(policy,{})),\
             patch('lax_connector.room_origin_factory.importlib.import_module',modules),\
             patch('asyncio.create_subprocess_exec',side_effect=AssertionError('NO native/process')):
            with self.assertRaises(AdministrationUnconfirmed):await admin().call(FACTORY_TOOL,{'roomId':self.room},'ORIGINAL-CALL')
            credential=self.root/'parent/room-origin-factory'/('agent-credential-'+self.child+'.json')
            original_credential=credential.read_bytes()
            self.assertEqual(native,[]);self.assertFalse(list((self.root/'parent').glob('**/spec.private.json')))
            self.error={'error':'ORIGINAL_HOME_ATTACHMENT_NOT_DISPATCHED','mayApply':False}
            result=await admin().call(FACTORY_TOOL,{'roomId':self.room},'ORIGINAL-CALL')
            again=await admin().call(FACTORY_TOOL,{'roomId':self.room},'ORIGINAL-CALL')
        self.assertEqual(result,again);self.assertEqual(result['operationId'],self.operation)
        self.assertEqual(credential.read_bytes(),original_credential)
        self.assertEqual(self.posts,[self.payload,self.payload]) # Prepare, then SAME-key known continuation.
        self.assertEqual(self.attachments,1) # Synthetic HOME, not a PG/CAS claim.
        self.assertEqual(self.allocations,[{'operationId':self.operation+':allocate'}])
        self.assertEqual(len(native),1);self.assertEqual(len(attached),1)
        self.assertEqual(len(list((self.root/'factory-admin').glob('workflow-*.json'))),1)
        self.assertFalse(result['complete']) # Synthetic ready is NOT canonical readiness.
        self.assertNotIn('sandbox',self.config);self.assertNotIn('approvalPolicy',self.config)

    async def test_unknown_dispatch_absence_or_untyped_marker_never_reposts(self):
        cases=[(503,{'error':'ORIGINAL_HOME_ATTACHMENT_NOT_DISPATCHED','mayApply':True}),
               (503,{'error':'ORIGINAL_HOME_ATTACHMENT_NOT_DISPATCHED'}),
               (503,{'error':'ORIGINAL_HOME_ATTACHMENT_NOT_DISPATCHED','mayApply':'false'}),
               (503,{'error':'ORIGINAL_HOME_ATTACHMENT_NOT_DISPATCHED','mayApply':0}),
               (404,{'error':'ORIGINAL_HOME_ATTACHMENT_NOT_DISPATCHED','mayApply':False}),
               (503,{'error':'DISPATCHING_OR_REPLY_UNKNOWN','mayApply':False})]
        for i,(self.status,self.error) in enumerate(cases):
            with self.subTest(i=i):
                steps,_=self.steps(str(i))
                with self.assertRaises(AdministrationUnconfirmed):await steps.http('POST',self.path,self.payload)
        self.assertEqual(self.posts,[])

    async def test_other_tool_host_actor_thread_or_prefix_never_continues(self):
        for i,mutation in enumerate(('tool','host','actor','thread','slot','prefix')):
            with self.subTest(mutation=mutation):
                steps,directory=self.steps(str(i));steps.owner.host_config=dict(self.config)
                if mutation=='tool':steps.workflow['tool']='hollywood_create_agent'
                if mutation=='host':steps.owner.host_config['hostId']=str(uuid4())
                if mutation=='actor':steps.owner.host_config['agentId']=str(uuid4())
                if mutation=='thread':steps.workflow['binding']['thread']='OTHER-THREAD'
                if mutation=='slot':
                    value=json.loads((directory/'1.json').read_text());value['result']['agents'][0]['agent']=str(uuid4());saved(directory/'1.json',value)
                if mutation=='prefix':
                    value=json.loads((directory/'0.json').read_text());value['state']='sending';saved(directory/'0.json',value)
                with self.assertRaises(AdministrationUnconfirmed):await steps.http('POST',self.path,self.payload)
        self.assertEqual(self.posts,[])

    async def test_changed_wire_rejected_before_any_inspection_or_post(self):
        steps,_=self.steps()
        with self.assertRaisesRegex(ValueError,'step changed'):
            await steps.http('POST',self.path,{**self.payload,'enrollmentCredential':'DIFFERENT'})
        self.assertEqual((self.posts,self.reads),([],[]))

    async def test_wrong_accepted_home_receipt_scope_or_wire_never_reposts(self):
        self.phase='accepted'
        for i,field in enumerate(('actorId','authorityId','wireDigest','path','operationId')):
            with self.subTest(field=field):
                self.receipt_override={field:'DIFFERENT'};steps,_=self.steps(str(i))
                with self.assertRaisesRegex(AdministrationUnconfirmed,'receipt mismatch'):
                    await steps.http('POST',self.path,self.payload)
        self.assertEqual(self.posts,[])

    async def test_parent_pause_defers_all_rooms_and_rechecks_queued_sibling(self):
        slots=[{'room':str(uuid4()),'node':self.node,'agent':str(uuid4()),'state':'pending','revision':1,'receipt':None} for _ in range(6)]
        catalog={'authorityId':self.authority,'roomAgentInitializations':slots};calls=[]
        supervisor=SimpleNamespace(reconcile_admission=lambda:None,checkpoint=lambda:None)
        control=RoomOriginControl(config=self.config,request=self.request,thread='ORIGINAL-THREAD',
            state=self.root/'control',session_supervisor=supervisor)
        self.addAsyncCleanup(control.close)
        async def call(owner,name,args,call_id):
            calls.append((args['roomId'],call_id))
            if len(calls)==1:self.enabled=False;self.placement_revision+=1
            return {'fixture':'no native/model/HTTP mutation'}
        async def edge():
            control.observe(catalog);await asyncio.gather(*list(control.active.values()))
        with patch('lax_connector.room_origin_control.RoomAdministration.call',call):
            await edge();self.assertEqual(calls,[]);self.assertEqual(len(self.reads),1)
            self.assertFalse(list((self.root/'control').glob('*-attempt-*')))
            self.assertFalse((self.root/'parent/room-origin-factory').exists())
            self.enabled=True;self.placement_revision+=1
            await edge();self.assertEqual(len(calls),1,
                {p.name:json.loads(p.read_text()) for p in (self.root/'control').glob('*.json')})
            before=len(self.reads);await edge();self.assertEqual(len(self.reads)-before,1)
            self.assertEqual(len(calls),1)
            self.enabled=True;self.placement_revision+=1
            await edge();self.assertEqual(len(calls),6)
            self.assertEqual(len({key for _,key in calls}),6)
            before=len(self.reads);await edge();self.assertEqual(len(self.reads),before)
        self.assertEqual(self.posts,[])

    async def test_wrong_parent_host_fails_closed_without_control_or_factory(self):
        self.enabled=True;self.placement_host=str(uuid4())
        control=RoomOriginControl(config=self.config,request=self.request,thread='ORIGINAL-THREAD',state=self.root/'control',
            session_supervisor=SimpleNamespace(reconcile_admission=lambda:None,checkpoint=lambda:None))
        self.addAsyncCleanup(control.close)
        slot={'room':self.room,'node':self.node,'agent':self.child,'state':'pending','revision':1,'receipt':None}
        with patch('lax_connector.room_origin_control.RoomAdministration.call',side_effect=AssertionError('NO factory')):
            control.observe({'authorityId':self.authority,'roomAgentInitializations':[slot]})
            await asyncio.gather(*list(control.active.values()))
        self.assertEqual(self.posts,[])
        self.assertFalse(list((self.root/'control').glob('workflow-*')))

    async def test_pause_during_diagnostic_read_defers_before_factory_call(self):
        self.enabled=True;self.pause_on_room_read=True
        control=RoomOriginControl(config=self.config,request=self.request,thread='ORIGINAL-THREAD',state=self.root/'control',
            session_supervisor=SimpleNamespace(reconcile_admission=lambda:None,checkpoint=lambda:None))
        self.addAsyncCleanup(control.close)
        slot={'room':self.room,'node':self.node,'agent':self.child,'state':'pending','revision':1,'receipt':None}
        with patch('lax_connector.room_origin_control.RoomAdministration.call',side_effect=AssertionError('NO factory')):
            control.observe({'authorityId':self.authority,'roomAgentInitializations':[slot]})
            await asyncio.gather(*list(control.active.values()))
        key=next(p for p in (self.root/'control').glob('*.json') if len(p.stem)==64)
        self.assertEqual(json.loads(key.read_text())['state'],'placement-deferred')
        self.assertEqual(self.posts,[])


if __name__=='__main__':unittest.main()
