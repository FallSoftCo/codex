import asyncio,json,os,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from lax_connector.journal import saved
from lax_connector.room_origin_control import RoomOriginControl
from lax_connector.room_session_supervisor import RoomSessionSupervisor
from lax_connector.room_session_files import digest_file
from lax_connector.room_factory_linux import provision_local
from lax_connector.conversational_agent import ConversationalAgent

class ResidentTests(unittest.IsolatedAsyncioTestCase):
 async def test_two_instances_one_parent_restart_same_threads_and_failure_isolation(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);ids=[str(uuid4()) for _ in range(4)];config={'state':str(root/'parent'),'agentId':ids[0],'hostId':ids[1],'authorityId':ids[2],'nativeServer':{'manifest':'ORIGINAL-MANIFEST'},'codexHome':'ORIGINAL-PROFILE','roomOriginPolicy':{'fixture':True}}
   parent=SimpleNamespace(config=config,thread='ORIGINAL-GLOBAL-THREAD');started=[];events=[]
   class Session:
    def __init__(self,c):
     self.config=c;self.native_state=SimpleNamespace(status={'type':'idle'});self.native_active_turn=None;self.closed=False
     def pending():
      if self.closed:raise RuntimeError('Original SQLite journal is closed')
      return []
     self.conversation_io=SimpleNamespace(pending=pending)
    async def serve(self):
     started.append((self.config['agentId'],self.config['nativeThreadId'],os.getpid()))
     if self.config['nativeThreadId']=='NEW-2':raise RuntimeError('isolated transport loss')
     try:await asyncio.Event().wait()
     finally:self.closed=True
   results=[]
   for i in [1,2]:
    agent=str(uuid4());home=root/'agents'/agent
    for f in ['state','work']:(home/f).mkdir(parents=True,mode=0o700)
    c={**config,'state':str(home/'state'),'workspace':str(home/'work'),'agentId':agent,'nativeThreadId':'NEW-'+str(i),'originRoomId':ids[3]};file=home/'session.json';saved(file,c)
    results.append({'state':'ready','sharedAppServer':True,'agentId':agent,'originRoomId':ids[3],'nativeThreadId':c['nativeThreadId'],'sessionConfigPath':str(file),'sessionConfigSha256':digest_file(file)})
   with patch('lax_connector.room_session_supervisor.host_policy',return_value=({'root':str(root/'agents')},{})),patch('asyncio.create_subprocess_exec',side_effect=AssertionError('NO child process')):
    sup=RoomSessionSupervisor(parent,session_factory=Session)
    sup.attach(results[0]);sup.attach(results[0]);sup.attach(results[1]);await asyncio.sleep(0)
    self.assertEqual(len(started),2);self.assertEqual({p for _,_,p in started},{os.getpid()});self.assertFalse(sup.tasks[results[0]['agentId']].done());self.assertTrue(sup.tasks[results[1]['agentId']].done());self.assertFalse(sup.snapshot()['quiet'])
    # A repeated metadata callback cannot silently revive failed native I/O.
    sup.attach(results[1]);self.assertEqual(len(started),2)
    await sup.close();restarted=RoomSessionSupervisor(parent,session_factory=Session);restarted.load();await asyncio.sleep(0)
    await restarted.close();self.assertCountEqual([t for _,t,_ in started],['NEW-1','NEW-2','NEW-1','NEW-2'])

 async def test_actual_instance_event_callback_rejects_other_thread(self):
  # Exercise production callback, not a routing reimplementation. Nothing is
  # connected; all process/HTTP/native effects absent.
  a=ConversationalAgent.__new__(ConversationalAgent);a.thread='THREAD-A';a.host_supervisor=None
  a.native_state=SimpleNamespace(status={'type':'unavailable'},update=lambda value,source:events.append(value))
  a.native_active_turn=None;a.turn_sources={};a.activity=SimpleNamespace(record=lambda *_:None);events=[]
  await a.event('thread/status/changed',{'threadId':'THREAD-B','status':{'type':'idle'}});self.assertEqual(events,[])
  await a.event('thread/status/changed',{'threadId':'THREAD-A','status':{'type':'idle'}});self.assertEqual(events,[{'type':'idle'}])

 async def test_linux_adapter_bootstraps_once_without_service_or_subprocess(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);config={'state':str(root/'agent'/'state'),'workspace':str(root/'agent'/'work')};spec={**{k:str(uuid4()) for k in ('operationId','authorityId','originRoomId','agentId','hostId')},'connectorConfig':config,'nativeIdentity':{'pid':111,'startTicks':123,'image':'ORIGINAL'},'nativeHostManifestSha256':'1'*64};calls=[]
   async def initialize(c):
    calls.append(c);saved(Path(c['state'])/'native-context.json',{'state':'ready','nativeThreadId':'NEW-EMPTY','threadStartAttempted':True});return {'nativeThreadId':'NEW-EMPTY'}
   config['nativeServer']={'manifest':'ORIGINAL'}
   operation=root/'op';operation.mkdir(mode=0o700)
   with patch('lax_connector.room_factory_linux.validate_spec',return_value=spec),patch('lax_connector.room_factory_linux.linux_process',side_effect=lambda x:x),patch('lax_connector.room_factory_linux.digest_file',return_value='1'*64),patch('lax_connector.room_factory_linux.initialize',initialize),patch('asyncio.create_subprocess_exec',side_effect=AssertionError('NO subprocess')):
    first=await provision_local(root/'spec',operation,inspect=False,expected_spec_sha256='2'*64)
    # Use real room_bootstrap idempotence separately in OriginTests; this
    # adapter inspection proves original config/thread rather than new service.
    self.assertEqual(first['parentRuntimePid'],os.getpid());self.assertNotIn('service',first);self.assertEqual(first['nativeThreadId'],'NEW-EMPTY')
    self.assertEqual(len(calls),1)

 async def test_control_resumes_same_original_after_prerequisite_change_but_holds_unknown_thread(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);authority,agent,node,room,child=[str(uuid4()) for _ in range(5)]
   config={'authorityId':authority,'agentId':agent,'hostId':node,'state':str(root/'parent')};slot={'room':room,'node':node,'agent':child,'state':'pending','revision':1,'receipt':None};catalog={'authorityId':authority,'roomAgentInitializations':[slot]};calls=[];clock=[100.]
   async def call(owner,name,args,call_id):
    calls.append(call_id)
    if len(calls)==1:raise PermissionError('Missing approved parent policy BEFORE any native dispatch')
    return {'complete':False}
   with patch('lax_connector.room_origin_control.RoomAdministration.call',call):
    sup=RoomOriginControl(config=config,request=None,thread='GLOBAL',state=root/'control',now=lambda:clock[0]);sup.observe(catalog);await asyncio.gather(*sup.active.values());sup.observe(catalog);self.assertEqual(len(calls),1)
    # Original accepted-control-intent/recoverable workflow survives restart;
    # backoff boundary permits inspection/resume with SAME call/operation.
    clock[0]=126.;sup=RoomOriginControl(config=config,request=None,thread='GLOBAL',state=root/'control',now=lambda:clock[0]);sup.observe(catalog);await asyncio.gather(*sup.active.values());self.assertEqual(calls,[calls[0],calls[0]])
    unknown=str(uuid4());slot2={**slot,'agent':unknown,'room':str(uuid4())};directory=Path(config['state'])/'room-origin-factory'/('room-origin-'+unknown);directory.mkdir(parents=True,mode=0o700);native=root/'uncertain';native.mkdir();saved(native/'native-context.json',{'state':'creating','threadStartAttempted':True});saved(directory/'spec.private.json',{'connectorConfig':{'state':str(native)}})
    clock[0]=1000;sup.observe({'authorityId':authority,'roomAgentInitializations':[slot2]});self.assertEqual(len(calls),2);self.assertEqual(sup.active,{})
    await sup.close()

 async def test_release_inspection_uses_each_original_thread_and_holds_on_child_output(self):
  from lax_connector.room_session_inspect import inspect_sessions
  from lax_connector.conversation_io import ConversationIO
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);authority,host,parent,child,room=[str(uuid4()) for _ in range(5)]
   config={'authorityId':authority,'hostId':host,'agentId':parent,'nativeThreadId':'GLOBAL','nativeServer':{'manifest':'ORIGINAL'},'state':str(root/'parent'),'roomOriginPolicy':{'fixture':True}}
   registry=Path(config['state'])/'room-sessions';registry.mkdir(parents=True,mode=0o700)
   c={**config,'agentId':child,'nativeThreadId':'ORIGINAL-CHILD','state':str(root/'child'),'rooms':[{'roomId':room}]}
   io=ConversationIO(root/'child'/'conversation-io.sqlite',authority=authority,agent=child,thread='ORIGINAL-CHILD');file=root/'config';saved(file,c)
   saved(registry/('session-'+child+'.json'),{'agentId':child,'originRoomId':room,'nativeThreadId':c['nativeThreadId'],'sessionConfigPath':str(file),'sessionConfigSha256':digest_file(file)})
   calls=[]
   class Rpc:
    def __init__(self,c,*_):self.c=c
    async def start(self):pass
    async def close(self):pass
    async def call(self,m,p):
     calls.append((m,p));assert m=='thread/read' and p=={'threadId':'ORIGINAL-CHILD','includeTurns':False}
     return {'thread':{'id':'ORIGINAL-CHILD','status':{'type':'idle'}}}
   with patch('lax_connector.room_session_inspect.host_policy',return_value=({},{})):
    result=await inspect_sessions(config,rpc_factory=Rpc);self.assertTrue(result['quiet']);self.assertEqual(len(calls),1)
    io.final('ORIGINAL-TURN','UNDELIVERED-FINAL','Original unresolved answer')
    with self.assertRaisesRegex(ValueError,'unsettled I/O'):await inspect_sessions(config,rpc_factory=Rpc)
    self.assertEqual(io.db.execute('SELECT body,state FROM output').fetchone()['body'],'Original unresolved answer')
   io.close()

 async def test_control_diagnostic_lost_ack_reconciles_without_second_post_or_native_work(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);authority,parent,node,room,agent=[str(uuid4()) for _ in range(5)]
   slot={'room':room,'node':node,'agent':agent,'coordinator':parent,'control_revision':0,'control_status':None};posts=[]
   async def request(method,path,payload=None):
    if method=='GET':return {'capabilities':{'controlStatus':1},'agents':[slot]}
    posts.append(payload);slot.update(control_revision=payload['revision'],control_status=payload)
    raise ConnectionError('SYNTHETIC lost diagnostic ACK after canonical acceptance')
   control=RoomOriginControl(config={'authorityId':authority,'agentId':parent,'hostId':node,'state':str(root/'parent')},request=request,thread='unchanged-global',state=root/'control')
   await control.diagnose(slot,'fixture',1,'blocked','Known unstarted parent-policy prerequisite')
   await control.diagnose(slot,'fixture',1,'blocked','Known unstarted parent-policy prerequisite')
   self.assertEqual(len(posts),1);self.assertEqual(posts[0]['originalOperation'],'room-origin:fixture')
   record=json.loads((root/'control/fixture-diagnostic-1-blocked.json').read_text());self.assertTrue(record['accepted']);self.assertTrue(record['reconciled']);self.assertEqual(control.active,{})
   await control.close()

 async def test_actual_admin_workflow_safe_transport_result_resumes_original_without_metadata_replay(self):
  from lax_connector.room_administration import RoomAdministration,AdministrationUnconfirmed,FACTORY_TOOL
  from uuid import UUID,uuid5
  from lax_connector.room_session_files import digest_file
  import importlib
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);authority,parent,node,room=[str(uuid4()) for _ in range(4)]
   agent=str(uuid5(UUID(room),'room-agent:'+node));manifest=root/'manifest';saved(manifest,{'fixture':True});guide=root/'AGENTS.md';guide.write_text('Fixture guide')
   config={'runtimeMode':'room-conversation','authorityId':authority,'agentId':parent,'hostId':node,
           'nativeServer':{'manifest':str(manifest)},'state':str(root/'parent'),'binary':'/original/native',
           'codexHome':str(root/'original-profile'),'model':'original-model','effort':'high','roomOriginPolicy':{'path':'/approved/policy','sha256':'1'*64}}
   slot={'room':room,'node':node,'agent':agent,'coordinator':parent,'revision':1,'state':'pending','receipt':None};posts=[];adapter_calls=[];attachments=[]
   async def request(method,path,payload=None):
    if path=='principals/'+parent:return {'id':parent,'authority':authority,'kind':'agent','active':True,'administrator':True}
    if method=='POST':posts.append((path,payload))
    if path.endswith('/enroll'):return {'agentId':agent}
    if path.endswith('/report'):return {'agents':[slot],'complete':False}
    if path=='agents/'+agent+'/role':return {'home_room':room,'primary_role':'room-agent','purpose':'Local fixture origin'}
    if path=='principals/'+agent:return {'name':'Fixture local contributor'}
    return {'agents':[slot],'complete':False}
   supervisor=SimpleNamespace(config=config,attach=lambda result:attachments.append(result))
   async def adapter(spec_file,directory,*,inspect,expected_spec_sha256):
    spec=json.loads(spec_file.read_text());adapter_calls.append(inspect);state=Path(spec['connectorConfig']['state']);state.mkdir(parents=True,mode=0o700,exist_ok=True)
    base={k:spec[k] for k in ('operationId','authorityId','originRoomId','agentId','hostId')}
    if len(adapter_calls)==1:
     saved(state/'native-context.json',{'state':'transport-unavailable','threadStartAttempted':False})
     return {**base,'state':'unknown','reason':'Conservative platform result, exact bootstrap proves unstarted'}
    saved(state/'native-context.json',{'state':'ready','threadStartAttempted':True,'nativeThreadId':'NEW-EMPTY-FIXTURE'})
    return {**base,'state':'ready','nativeThreadId':'NEW-EMPTY-FIXTURE','appServerManifestSha256':digest_file(manifest),'sharedAppServer':True}
   original_import=importlib.import_module
   def modules(name,*args,**kwargs):
    if name=='.room_factory_linux':return SimpleNamespace(provision_local=adapter)
    return original_import(name,*args,**kwargs)
   policy={'root':str(root/'agents'),'nativeIdentity':{'fixture':True},'operatingInstructions':[{'path':str(guide),'sha256':digest_file(guide)}]}
   with patch('lax_connector.room_session_files.host_policy',return_value=(policy,{})),patch('lax_connector.room_origin_factory.importlib.import_module',modules):
    admin=RoomAdministration(authority=authority,agent=parent,thread='PARENT-NO-NEW-NATIVE-THREAD',request=request,state=root/'admin',host_config=config,session_supervisor=supervisor)
    with self.assertRaises(AdministrationUnconfirmed):await admin.call(FACTORY_TOOL,{'roomId':room},'ORIGINAL-CONTROL-CALL')
    result=await admin.call(FACTORY_TOOL,{'roomId':room},'ORIGINAL-CONTROL-CALL')
   self.assertEqual(adapter_calls,[False,True]);self.assertEqual(len(attachments),1)
   self.assertEqual(sum(path.endswith('/enroll') for path,_ in posts),1)
   self.assertEqual(sum(path.endswith('/report') for path,_ in posts),1)
   self.assertTrue(list((root/'parent/room-origin-factory'/('room-origin-'+agent)).glob('host-unstarted-result-*.json')))
   self.assertEqual(result['complete'],False) # Not canonical native-ready/business complete.
