"""Actual Windows validators/phase machines on CPU with explicit kernel shims.

Private files/locks/common factory/bootstrap are real; Windows SID/ACL/process/
socket affinity and native RPC are SYNTHETIC. No actual Windows/native/model proof.
Real-owner original phase/source qualification is a separate retained input.
"""
import ast,asyncio,contextlib,fcntl,hashlib,json,os,sys,tempfile,time,types
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from lax_connector import room_bootstrap,room_origin_factory as factory,room_session_files as files
from lax_connector import room_windows_initial_configuration as successor
from lax_connector.room_administration import RoomAdministration,AdministrationUnconfirmed,FACTORY_TOOL,digest
from lax_connector.room_origin_control import RoomOriginControl
from lax_connector.journal import saved


class WinPath(type(Path())):
    def lstat(self):
        st=super().lstat()
        class WindowsStat:
            st_file_attributes=0
            def __getattr__(self,k):return getattr(st,k)
        return WindowsStat()


def source_module(name,path,namespace):
    tree=ast.parse(path.read_text());tree.body=[n for n in tree.body if not isinstance(n,(ast.Import,ast.ImportFrom))]
    module=types.ModuleType(name);module.__dict__.update(namespace,__file__=str(path),__package__='lax_connector')
    exec(compile(tree,str(path),'exec'),module.__dict__);return module


async def scenario(root,lose=False):
    root.mkdir(mode=0o700);authority,node,actor,agent,room=[str(uuid4()) for _ in range(5)]
    for n in ('agents','parent','native','profile','parent-work'):(root/n).mkdir(mode=0o700)
    (root/'profile/auth.json').write_text('SYNTHETIC-NO-AUTH-COPY')
    binary=str(Path(sys.executable).resolve());sid='SYNTHETIC-LIMITED-OWNER';sidsha=hashlib.sha256(sid.encode()).hexdigest()
    native={'pid':100,'created':'NATIVE-ORIGINAL','image':binary,'ownerSidSha256':sidsha,'sessionId':1}
    parent={'pid':101,'created':'PARENT-ORIGINAL','image':binary,'ownerSidSha256':sidsha,'sessionId':1};pid=[101]
    source=Path(factory.__file__).parent
    def private(path,directory=False):
        st=Path(path).lstat();assert not Path(path).is_symlink() and not st.st_mode&0o077
    def mkdir(path):Path(path).mkdir(mode=0o700)
    locker=types.SimpleNamespace(LK_NBLCK=1,LK_UNLCK=2,locking=lambda fd,mode,size:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB if mode==1 else fcntl.LOCK_UN))
    platform=source_module('lax_connector.room_factory_windows_state',source/'room_factory_windows_state.py',
        {'contextmanager':contextlib.contextmanager,'hashlib':hashlib,'json':json,'os':os,'time':time,'Path':WinPath,'UUID':__import__('uuid').UUID,
         'private_path':private,'create_private_directory':mkdir,'msvcrt':locker})
    platform.current_owner=lambda:sid;platform.process=lambda n:parent if n==parent['pid'] else native
    platform.native_peer=lambda manifest:native
    adapter=source_module('lax_connector.room_factory_windows',source/'room_factory_windows.py',
        {'hashlib':hashlib,'os':os,'sys':sys,'time':time,'Path':WinPath,'UUID':__import__('uuid').UUID,'room_bootstrap':room_bootstrap,
         'platform':platform,'TOOLS':__import__('lax_connector.room_tools',fromlist=['TOOLS']).TOOLS})
    manifest={'schema':'lax-native-host/v1','runtimeMode':'room-conversation','platform':'windows','authorityId':authority,'hostId':node,
        'ownerAgentId':actor,'binary':binary,'codexHome':str(root/'profile'),'state':str(root/'native'),'socket':str(root/'SYNTHETIC-SOCKET'),'workspace':str(root/'parent-work')}
    saved(root/'manifest',manifest);guide=root/'AGENTS.md';guide.write_text('SYNTHETIC approved guide')
    cfg={'runtimeMode':'room-conversation','authorityId':authority,'hostId':node,'agentId':actor,'state':str(root/'parent'),
        'workspace':str(root/'parent-work'),'nativeThreadId':str(uuid4()),'model':'declared-model','effort':'xhigh','binary':binary,
        'codexHome':str(root/'profile'),'nativeServer':{'manifest':str(root/'manifest')},'hollywoodUrl':'http://127.0.0.1:1','token':'SYNTHETIC-PARENT'}
    saved(root/'parent-config',cfg);saved(root/'runtime',{'state':'running','pid':101})
    policy={'schema':'lax-windows-room-parent-policy/v2','authorityId':authority,'hostId':node,'parentAgentId':actor,'ownerSidSha256':sidsha,
        'agentRoot':str(root/'agents'),'nativeHostManifest':str(root/'manifest'),'nativeHostManifestSha256':successor.sha(root/'manifest'),
        'parentTaskName':'SYNTHETIC-NO-TASK','parentRuntimeMetadata':str(root/'runtime'),'parentConfigPath':str(root/'parent-config'),
        'parentAcceptanceLocator':{'path':str(root/'acceptance')},'operatingInstructions':[{'path':str(guide),'sha256':successor.sha(guide)}],
        'model':cfg['model'],'effort':cfg['effort'],'initialPermissions':{'sandbox':'danger-full-access','approvalPolicy':'never'}}
    saved(root/'policy',policy);cfg['roomOriginPolicy']={'path':str(root/'policy'),'sha256':successor.sha(root/'policy')}
    def accept():saved(root/'acceptance',{'schema':'lax-windows-parent-runtime-acceptance/v2','policySha256':cfg['roomOriginPolicy']['sha256'],
        **{k:policy[k] for k in ('authorityId','hostId','parentAgentId','nativeHostManifestSha256','parentTaskName')},'ownerAcceptanceOperationId':'SYNTHETIC-SEPARATE-OWNER',
        'state':'running','admissionAllowed':True,'runtimeIdentity':parent,'nativeIdentity':native,'parentArgvSha256':platform.argv_digest(sys.orig_argv)})
    accept();slot={'room':room,'node':node,'agent':agent,'coordinator':actor,'revision':1,'state':'pending','receipt':None};base='rooms/'+room+'/environment-agents';writes=[]
    async def request(method,path,body=None):
        if method!='GET':writes.append((path,body))
        if path=='principals/'+actor:return {'id':actor,'authority':authority,'kind':'agent','active':True,'administrator':True}
        if path=='principals/'+agent:return {'name':'SYNTHETIC Windows child'}
        if path=='agents/'+agent+'/role':return {'home_room':room,'primary_role':'room-agent','purpose':'SYNTHETIC'}
        if path.endswith('/control-status'):return {'accepted':True,'coordinatorId':actor,'revision':body['revision'],'status':body}
        if path.endswith('/report'):slot.update(state=body['state'],revision=slot['revision']+1,receipt=body['receipt'])
        if path==base or path.endswith('/enroll') or path.endswith('/report'):
            return json.loads(json.dumps({'roomId':room,'agents':[{**slot,'control_revision':0}],'capabilities':{'controlStatus':1}}))
        raise AssertionError(path)
    attached=[];supervisor=types.SimpleNamespace(config=cfg,attach=lambda r:attached.append(r))
    key=hashlib.sha256((room+'\0'+node+'\0'+agent).encode()).hexdigest();control=root/'control';state=control/key;thread=cfg['nativeThreadId']
    def admin():return RoomAdministration(authority=authority,agent=actor,thread=thread,request=request,state=state,host_config=cfg,session_supervisor=supervisor)
    calls=[]
    class RPC:
        async def start(self):pass
        async def close(self):pass
        async def call(self,method,params):
            calls.append(method)
            if method=='thread/start':
                if lose:raise TimeoutError('SYNTHETIC unknown native reply')
                return {'thread':{'id':str(uuid4())},'sandbox':{'type':'dangerFullAccess'},'approvalPolicy':'never'}
            return {}
    real=factory.origin_configuration
    def legacy(*a,**kw):v=real(*a,**kw);v.pop('sandbox');v.pop('approvalPolicy');return v
    with patch.dict(sys.modules,{'lax_connector.room_factory_windows_state':platform,'lax_connector.room_factory_windows':adapter}),\
         patch.object(successor,'sys',types.SimpleNamespace(platform='win32')),patch.object(factory,'sys',types.SimpleNamespace(platform='win32')),\
         patch.object(files,'Path',WinPath),patch.object(files,'host_policy',files.windows_host_policy),patch.object(os,'getpid',side_effect=lambda:pid[0]),\
         patch.object(room_bootstrap,'native_client',side_effect=lambda *a:RPC()):
        with patch.object(factory,'origin_configuration',legacy):
            try:await admin().call(FACTORY_TOOL,{'roomId':room},'room-origin:'+key)
            except AdministrationUnconfirmed as error:assert str(error.__cause__)==successor.GUARD
            else:raise AssertionError('Actual original Windows guard must reject')
        assert calls==[];workflow=next(state.glob('workflow-*.json'));old=json.loads(workflow.read_text());operation=old['operationId']
        assert len(list((state/digest(operation)).glob('[0-9].json')))==5
        controller=RoomOriginControl(config=cfg,request=request,thread=thread,state=control)
        await controller.diagnose(slot,key,1,'blocked',successor.GUARD)
        parent={**parent,'pid':102,'created':'PARENT-MAINTAINED-SUCCESSOR'};pid[0]=102;saved(root/'runtime',{'state':'running','pid':102});accept()
        diagnostic=next(control.glob(key+'-diagnostic-*-blocked.json'));raw_diag=diagnostic.read_bytes();v=json.loads(raw_diag);v['accepted']=False;saved(diagnostic,v)
        assert successor.select(admin(),workflow,old)[0]==workflow # Missing positive phase witness is NOT inferred from absence.
        diagnostic.write_bytes(raw_diag)
        accept_raw=(root/'acceptance').read_bytes();v=json.loads(accept_raw);v['admissionAllowed']=False;saved(root/'acceptance',v)
        try:successor.select(admin(),workflow,old)
        except platform.Held:pass
        else:raise AssertionError('Closed independent V2 owner acceptance was bypassed')
        (root/'acceptance').write_bytes(accept_raw)
        cfg['sandbox']='read-only'
        try:successor.select(admin(),workflow,old)
        except PermissionError:pass
        else:raise AssertionError('Current explicit parent restriction was widened')
        cfg.pop('sandbox')
        directory=Path(cfg['state'])/'room-origin-factory'/('room-origin-'+agent)
        intent=directory/'native-initialization-intent.json';saved(intent,{'SYNTHETIC':'unknown'})
        try:successor.select(admin(),workflow,old)
        except platform.Held:pass
        else:raise AssertionError('Unknown original intent cannot be replaced')
        intent.unlink() # Fixture-only negative, no production unknown is removed.
        target,prepared=successor.select(admin(),workflow,old);pins=prepared['configurationSuccessor']['originalFiles']
        result=await admin().call('hollywood_admin_reconcile',{'operationId':operation},'original')
        again=await admin().call('hollywood_admin_reconcile',{'operationId':operation},'original')
        assert result==again and calls.count('thread/start')==1 and 'turn/start' not in calls
        assert all(successor.sha(p)==h for p,h in pins.items()) and len(attached)==(0 if lose else 1)
        assert all(len(body['operationId'])<=128 for path,body in writes if path.endswith('/report'))
        assert len([path for path,body in writes if path.endswith('/enroll')])==1
        spec=json.loads(Path(prepared['configurationSuccessor']['spec']['path']).read_text());assert spec['parentRuntime']['pid']==102
        await controller.close()
    return {'passed':True,'unknownNativeReply':lose,'sameNativeOperationCredentialAndAgent':True,'originalProofFilesByteExact':len(pins),
        'acceptedFiveStepOriginalAndActualScopeGuard':True,'currentProtectedV2Parent102NotOld101':True,'threadStartAttempts':1,
        'unknownIntentMissingPositiveDiagnosticClosedV2AndParentRestrictionHeld':True,
        'fullActualWindowsValidatorsAndPhaseMachine':True,'kernelSidAclProcessPipeAndNativeRpcSynthetic':True,'realNativeCalls':0,'modelCalls':0}


async def main():
    mask=os.umask(0o077)
    try:
        with tempfile.TemporaryDirectory() as d:results=[await scenario(Path(d)/str(i),lose) for i,lose in enumerate((False,True))]
        result={'passed':True,'scenarios':results};Path(os.environ['SDK251_WINDOWS_RESULT']).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    finally:os.umask(mask)


asyncio.run(main())
