"""Finite receipt/deferred-registration proof. Processes/native/model are synthetic.

Real private registration files/async supervisor; no live owner approval, manager,
network, native transport or model. Windows platform facts are source mocks here;
BLD's separate retained-layout fixture qualifies real Windows ACLs.
"""
import asyncio,hashlib,json,os,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
from uuid import uuid4
from lax_connector.journal import saved
from lax_connector.room_session_files import digest_file
from lax_connector.room_session_supervisor import RoomSessionSupervisor
from lax_connector.room_origin_control import RoomOriginControl
from lax_connector import room_session_files as files
from lax_connector.room_parent_startup import windows_startup

class AdmissionTests(unittest.IsolatedAsyncioTestCase):
 def fixture(self,root):
  config={'state':str(root/'parent'),'agentId':str(uuid4()),'hostId':str(uuid4()),'authorityId':str(uuid4()),'nativeServer':{'manifest':'ORIGINAL'},'codexHome':'ORIGINAL','roomOriginPolicy':{'path':'OWNER-POLICY','sha256':'1'*64}}
  parent=SimpleNamespace(config=config,thread='ORIGINAL-GLOBAL');started=[]
  class Session:
   def __init__(self,c):self.c=c;self.native_state=SimpleNamespace(status={'type':'idle'});self.native_active_turn=None;self.conversation_io=SimpleNamespace(pending=lambda:[])
   async def serve(self):
    started.append((self.c['agentId'],self.c['nativeThreadId']))
    if self.c['nativeThreadId']=='FAILED-SIBLING':raise RuntimeError('Separate native transport failure')
    await asyncio.Event().wait()
  def record(thread):
   agent=str(uuid4());home=root/'agents'/agent
   for n in ('state','work'):(home/n).mkdir(parents=True,mode=0o700)
   cfg={**config,'agentId':agent,'nativeThreadId':thread,'originRoomId':str(uuid4()),'state':str(home/'state'),'workspace':str(home/'work')};p=home/'config';saved(p,cfg)
   return {'agentId':agent,'nativeThreadId':thread,'originRoomId':cfg['originRoomId'],'sessionConfigPath':str(p),'sessionConfigSha256':digest_file(p)}
  return parent,Session,started,record,{'root':str(root/'agents')}

 async def test_catalog_owner_change_restores_only_deferred_once_and_preserves_running_failed_stopped(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);parent,Session,started,record,policy=self.fixture(root);clock=[0.];owner=['open-A'];revision=['A'];checks=[]
   def host(c):
    checks.append(owner[0])
    if owner[0].startswith('closed'):raise PermissionError('Owner admission CLOSED')
    return policy,{}
   with patch('lax_connector.room_session_supervisor.host_policy',side_effect=host),patch('lax_connector.room_session_supervisor.parent_admission_revision',side_effect=lambda c:revision[0]),patch('asyncio.create_subprocess_exec',side_effect=AssertionError('NO process')):
    sup=RoomSessionSupervisor(parent,session_factory=Session,now=lambda:clock[0])
    live,bad=[record(n) for n in ('RUNNING-SIBLING','FAILED-SIBLING')]
    for r in (live,bad):sup.attach({**r,'state':'ready','sharedAppServer':True})
    await asyncio.sleep(0);self.assertEqual(sup.records[bad['agentId']]['state'],'blocked')
    deferred=[record('ORIGINAL-DEFERRED-1'),record('ORIGINAL-DEFERRED-2')]
    for r in deferred:saved(sup.state/('session-'+r['agentId']+'.json'),r)
    stopped={**record('STOPPED'),'state':'stopped'};saved(sup.state/('session-'+stopped['agentId']+'.json'),stopped)
    owner[0]='closed-A';sup.load();self.assertEqual(set(sup.parent_deferred),{r['agentId'] for r in deferred})
    self.assertNotEqual(sup.records[live['agentId']].get('state'),'blocked');self.assertNotEqual(sup.records[bad['agentId']]['errorType'],'ParentAdmissionUnavailable')
    control=RoomOriginControl(config=parent.config,request=None,thread=parent.thread,state=root/'control',session_supervisor=sup)
    before=len(checks);control.observe({'authorityId':parent.config['authorityId'],'roomAgentInitializations':[]});self.assertEqual(len(checks),before)
    # A new CLOSED receipt may be inspected once but cannot admit or relabel.
    revision[0]='closed-B';control.observe({'authorityId':parent.config['authorityId']});self.assertEqual(len(checks),before+1)
    control.observe({'authorityId':parent.config['authorityId']});self.assertEqual(len(checks),before+1)
    owner[0]='open-B';revision[0]='open-B';control.observe({'authorityId':parent.config['authorityId']});await asyncio.sleep(0)
    self.assertFalse(sup.parent_deferred);self.assertEqual(len(started),4)
    self.assertCountEqual([t for _,t in started],['RUNNING-SIBLING','FAILED-SIBLING','ORIGINAL-DEFERRED-1','ORIGINAL-DEFERRED-2'])
    for _ in range(3):control.observe({'authorityId':parent.config['authorityId']})
    self.assertEqual(len(started),4);self.assertEqual(len(sup.tasks),4)
    self.assertTrue(sup.tasks[bad['agentId']].done());self.assertNotIn(stopped['agentId'],sup.tasks)
    self.assertEqual(json.loads((sup.state/'admission-reconciled.private.json').read_text())['restoredAgentIds'],[r['agentId'] for r in sorted(deferred,key=lambda r:r['agentId'])])
    await control.close();await sup.close()

 async def test_owner_closure_during_restore_keeps_unattached_original_and_does_not_relabel_running(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);parent,Session,started,record,policy=self.fixture(root);stage=['closed'];revision=['closed'];calls=[0]
   def host(c):
    if stage[0]=='closed':raise PermissionError('CLOSED')
    calls[0]+=1
    if stage[0]=='closing' and calls[0]>=3:raise PermissionError('Owner closed between registrations')
    return policy,{}
   with patch('lax_connector.room_session_supervisor.host_policy',side_effect=host),patch('lax_connector.room_session_supervisor.parent_admission_revision',side_effect=lambda c:revision[0]):
    sup=RoomSessionSupervisor(parent,session_factory=Session)
    records=sorted([record('ORIGINAL-A'),record('ORIGINAL-B')],key=lambda r:r['agentId'])
    for r in records:saved(sup.state/('session-'+r['agentId']+'.json'),r)
    sup.load();stage[0]='closing';revision[0]='approved-A';self.assertFalse(sup.reconcile_admission());await asyncio.sleep(0)
    self.assertEqual(len(started),1);self.assertEqual(set(sup.parent_deferred),{records[1]['agentId']})
    self.assertNotEqual(sup.records[records[0]['agentId']].get('state'),'blocked')
    stage[0]='open';revision[0]='approved-B';self.assertTrue(sup.reconcile_admission());await asyncio.sleep(0)
    self.assertCountEqual(started,[(r['agentId'],r['nativeThreadId']) for r in records]);self.assertFalse(sup.parent_deferred)
    await sup.close()

 async def test_deferred_original_registration_drift_holds_without_new_thread_or_retry(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);parent,Session,started,record,policy=self.fixture(root);approved=[False];revision=[None]
   def host(c):
    if not approved[0]:raise PermissionError('Owner approval absent')
    return policy,{}
   with patch('lax_connector.room_session_supervisor.host_policy',side_effect=host),patch('lax_connector.room_session_supervisor.parent_admission_revision',side_effect=lambda c:revision[0]):
    sup=RoomSessionSupervisor(parent,session_factory=Session);r=record('ORIGINAL');path=sup.state/('session-'+r['agentId']+'.json');saved(path,r);sup.load()
    saved(path,{**r,'nativeThreadId':'UNAUTHORIZED-REPLACEMENT'});approved[0]=True;revision[0]='owner'
    self.assertTrue(sup.reconcile_admission());self.assertFalse(sup.reconcile_admission());self.assertEqual(started,[]);self.assertEqual(sup.tasks,{})
    self.assertEqual(sup.records[r['agentId']]['errorType'],'ValueError');self.assertEqual(json.loads(path.read_text())['nativeThreadId'],'UNAUTHORIZED-REPLACEMENT')
    await sup.close()

 async def test_known_unattached_backoff_recovers_on_existing_metadata_edge_only(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);parent,Session,started,record,policy=self.fixture(root);approved=[False];clock=[0.]
   def host(c):
    if not approved[0]:raise PermissionError('Known read-only prerequisite unavailable')
    return policy,{}
   with patch('lax_connector.room_session_supervisor.host_policy',side_effect=host),patch('lax_connector.room_session_supervisor.parent_admission_revision',return_value=None):
    sup=RoomSessionSupervisor(parent,session_factory=Session,now=lambda:clock[0]);r=record('ORIGINAL');saved(sup.state/('session-'+r['agentId']+'.json'),r);sup.load()
    approved[0]=True;clock[0]=24.;self.assertFalse(sup.reconcile_admission());self.assertEqual(started,[])
    clock[0]=25.;self.assertTrue(sup.reconcile_admission());await asyncio.sleep(0);self.assertEqual(started,[(r['agentId'],'ORIGINAL')]);self.assertFalse(sup.reconcile_admission())
    await sup.close()

class WindowsCommonTests(unittest.TestCase):
 def platform(self,root):
  guide=root/'guide';guide.write_text('Owned guide');policy={'schema':'lax-windows-room-parent-policy/v2','authorityId':'a','hostId':'h','parentAgentId':'p','nativeHostManifest':'ORIGINAL','nativeHostManifestSha256':'m'*64,'parentConfigPath':'PROJECTION','agentRoot':'APPROVED','operatingInstructions':[{'path':str(guide),'sha256':digest_file(guide)}],'model':'approved','effort':'high','parentRuntimeMetadata':'RUNTIME','parentTaskName':'ORIGINAL'}
  runtime={'pid':os.getpid(),'created':'SYNTHETIC-A'};native={'pid':123,'created':'SYNTHETIC-N'}
  accepted={'schema':'lax-windows-parent-runtime-acceptance/v2','state':'running','admissionAllowed':True,'runtimeIdentity':runtime,'nativeIdentity':native,'parentArgvSha256':'ARGV'}
  config={'authorityId':'a','hostId':'h','agentId':'p','state':str(root/'state'),'nativeThreadId':'GLOBAL','nativeServer':{'manifest':'ORIGINAL'},'roomOriginPolicy':{'path':'POLICY','sha256':'1'*64}}
  manifest={'schema':'lax-native-host/v1','authorityId':'a','hostId':'h','ownerAgentId':'p','hostId':'h'}
  values={'POLICY':policy,'PROJECTION':config,'ORIGINAL':manifest,'RUNTIME':{'state':'running','pid':os.getpid()}}
  def require(ok,reason):
   if not ok:raise PermissionError(reason)
  platform=SimpleNamespace(read=Mock(side_effect=lambda path,*a:values[str(path)]),read_parent_acceptance=Mock(return_value=accepted),require=require,inspect_parent=Mock(return_value={'parentRuntime':runtime,'sharedNative':native}),argv_digest=lambda _: 'ARGV',process=Mock(return_value=runtime),native_peer=Mock(return_value=native))
  return config,policy,accepted,platform

 def test_common_uses_shared_reader_v2_and_rechecks_closed_or_stale_acceptance(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);config,policy,accepted,platform=self.platform(root)
   with patch.dict('sys.modules',{'lax_connector.room_factory_windows_state':platform}),patch.object(Path,'lstat',return_value=SimpleNamespace(st_file_attributes=0)),patch.object(files,'host_manifest',return_value={'fixture':True}):
    normalized,_=files.windows_host_policy(config);self.assertEqual(normalized['model'],'approved')
    platform.read_parent_acceptance.assert_called_once_with(policy,expected_policy_sha256='1'*64)
    accepted['admissionAllowed']=False
    with self.assertRaisesRegex(PermissionError,'closed or changed'):files.windows_host_policy(config)
    accepted['admissionAllowed']=True;accepted['runtimeIdentity']={'pid':999,'created':'STALE'}
    with self.assertRaisesRegex(PermissionError,'closed or changed'):files.windows_host_policy(config)

 def test_readonly_release_inspection_validates_owner_parent_not_cli_but_factory_stays_fenced(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);config,policy,accepted,platform=self.platform(root)
   accepted['runtimeIdentity']={'pid':9999,'created':'OWNER-PARENT'}
   platform.inspect_parent.return_value['parentRuntime']=accepted['runtimeIdentity']
   with patch.dict('sys.modules',{'lax_connector.room_factory_windows_state':platform}),patch.object(Path,'lstat',return_value=SimpleNamespace(st_file_attributes=0)),patch.object(files,'host_manifest',return_value={'fixture':True}):
    with self.assertRaisesRegex(PermissionError,'inside accepted'):files.windows_host_policy(config)
    with patch.object(files,'os',SimpleNamespace(name='nt')):
     result,_=files.inspection_policy(config);self.assertEqual(result['parentAgentId'],'p')
    accepted['admissionAllowed']=False
    with self.assertRaisesRegex(PermissionError,'closed or changed'):files.windows_host_policy(config,resident=False)

 def test_revision_is_bound_record_not_self_approval_and_startup_remains_closed(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);config,policy,accepted,platform=self.platform(root)
   # Only local os reference is mocked; Linux Path semantics stay real.
   with patch.dict('sys.modules',{'lax_connector.room_factory_windows_state':platform}),patch.object(files,'os',SimpleNamespace(name='nt')):
    first=files.parent_admission_revision(config);accepted['admissionAllowed']=False;second=files.parent_admission_revision(config);self.assertNotEqual(first,second)
    policy['schema']='lax-windows-room-parent-policy/v1';self.assertIsNone(files.parent_admission_revision(config));policy['schema']='lax-windows-room-parent-policy/v2'
   with patch.dict('sys.modules',{'lax_connector.room_factory_windows_state':platform}):
    result=windows_startup(config);self.assertFalse(result['admissionAllowed']);self.assertEqual(result['schema'],'lax-room-parent-startup/v1')
   self.assertFalse(platform.inspect_parent.called) # startup cannot approve itself
