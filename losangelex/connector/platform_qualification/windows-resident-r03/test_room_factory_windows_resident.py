"""Pinned r03 wrapper: actual parent/ACL/native peer, synthetic bootstrap only."""
import ast,copy,hashlib,importlib.util,json,sys,time
from pathlib import Path
from uuid import uuid4
S=Path(__file__).parent;W=S.parent;H=W.parent
sys.path.insert(0,str(W/'windows-room-factory-56611f4a-r01/base246/losangelex/connector'))
from lax_connector.windows_ipc import create_private_directory,private_path
from lax_connector import room_bootstrap
import win32com.client
def load(name,path):
    x=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(x);sys.modules[name]=m;x.loader.exec_module(m);return m
p=load('lax_connector.room_factory_windows_state',S/'room_factory_windows_state.py')
a=load('lax_connector.room_factory_windows',S/'room_factory_windows.py')
Q=S/'qualification-r01'
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,value):p.once(path,value)
def held(call):
    try:call()
    except (p.Held,PermissionError):return True
    raise AssertionError('Expected held/no-bootstrap boundary')
def task_snapshot():
    x=win32com.client.Dispatch('Schedule.Service');x.Connect()
    return {t.Name:(p.digest(t.Xml.encode()),p.digest(t.GetSecurityDescriptor(7).encode()),bool(t.Enabled)) for t in x.GetFolder('\\').GetTasks(1) if t.Name.startswith('LaxHost-')}
async def run():
    assert not Q.exists(),'Read original qualification instead of replaying it'
    create_private_directory(Q);create_private_directory(Q/'agents')
    sources={n:sha(S/n) for n in ('room_factory_windows.py','room_factory_windows_state.py','test_room_factory_windows_resident.py')}
    save(Q/'frozen-source.json',{'files':sources,'at':time.time(),'contractSha256':a.CONTRACT_SHA})
    cfg=p.read(H/'global-config.private.json');before_tasks=task_snapshot()
    files=[H/'global-config.private.json',H/'native-manifest.private.json',H/'codex-home/auth.json',H/'global-service/python.json']
    before_files={str(f):sha(f) for f in files}
    task_owner=win32com.client.Dispatch('Schedule.Service');task_owner.Connect();task=task_owner.GetFolder('\\').GetTask('LaxHost-BLD-11a7ef1b-Global-r01')
    guide=H/'work/HOST_RESOURCE_GUIDE.md';guide_hash=sha(guide)
    policy={'schema':'lax-windows-room-parent-policy/v1','authorityId':cfg['authorityId'],'hostId':cfg['hostId'],
        'parentAgentId':cfg['agentId'],'ownerSidSha256':p.digest(p.current_owner().encode()),'agentRoot':str(Q/'agents'),
        'nativeHostManifest':str(H/'native-manifest.private.json'),'nativeHostManifestSha256':sha(H/'native-manifest.private.json'),
        'parentTaskName':task.Name,'parentTaskXmlSha256':p.digest(task.Xml.encode()),
        'parentTaskAclSha256':p.digest(task.GetSecurityDescriptor(7).encode()),'parentRuntimeMetadata':str(H/'global-service/python.json'),
        'parentConfigPath':str(H/'global-config.private.json'),'model':cfg.get('model','gpt-6.1-sol'),'effort':cfg.get('effort','xhigh')}
    # This one host-boundary fixture seed reads existing acceptance/processes;
    # the ADAPTER itself performs no manager/WMI query or control at all.
    previous=load('prior_state_inspector',W/'windows-room-state-96690ada-r02/room_factory_windows_state.py')
    parent_prior=previous.process(2556);native_prior=previous.process(31396)
    parent_identity={k:v for k,v in parent_prior.items() if k!='argvSha256'}
    native_identity={k:v for k,v in native_prior.items() if k!='argvSha256'}
    acceptance={'schema':'lax-windows-parent-runtime-acceptance/v1',
        **{k:policy[k] for k in ('authorityId','hostId','parentAgentId','nativeHostManifestSha256','parentTaskName')},
        'state':'running','admissionAllowed':True,'runtimeIdentity':parent_identity,'nativeIdentity':native_identity,
        'parentArgvSha256':parent_prior['argvSha256']}
    acceptfile=Q/'host-acceptance.private.json';save(acceptfile,acceptance)
    policy.update(parentAcceptancePath=str(acceptfile),parentAcceptanceSha256=sha(acceptfile))
    policyfile=Q/'host-policy.private.json';save(policyfile,policy)
    proof=p.inspect_parent(policyfile,expected_policy_sha256=sha(policyfile));save(Q/'actual-parent-proof.private.json',proof)
    assert proof['parentRuntime']['pid']==2556 and proof['sharedNative']['pid']==31396
    def spec(label):
        agent=str(uuid4());room=str(uuid4());slot=Q/'agents'/agent;op=Q/(label+'-op');create_private_directory(op)
        instructions='SYNTHETIC '+label+' role. Approved guide '+str(guide)+' SHA256 '+guide_hash
        new={'runtimeMode':'room-conversation','authorityId':cfg['authorityId'],'hostId':cfg['hostId'],'agentId':agent,
            'nativeName':'SYNTHETIC resident qualification '+label,'instructions':instructions,
            'conversationResumeInstructions':{'baseInstructions':instructions,'developerInstructions':'Fresh synthetic origin '+room},
            'rooms':[{'roomId':room,'after':0}],'sandbox':'danger-full-access','approvalPolicy':'never',
            'token':'SYNTHETIC_NOT_AN_ENROLLED_CREDENTIAL','hollywoodUrl':'http://127.0.0.1:1','model':policy['model'],'effort':policy['effort'],
            'state':str(slot/'state'),'workspace':str(slot/'home/work'),'codexHome':cfg['codexHome'],'binary':cfg['binary'],'nativeServer':cfg['nativeServer']}
        value={'schema':'lax-room-origin-local-spec/v1','operationId':'synthetic-'+label,'authorityId':cfg['authorityId'],
            'hostId':cfg['hostId'],'nodeId':cfg['hostId'],'originRoomId':room,'agentId':agent,'connectorConfig':new,
            'nativeHostManifestSha256':policy['nativeHostManifestSha256'],'nativeIdentity':proof['sharedNative'],
            'parentRuntime':{'agentId':cfg['agentId'],'pid':proof['parentRuntime']['pid'],
                'roomOriginPolicy':{'path':str(policyfile),'sha256':sha(policyfile)}},
            'operatingInstructions':[{'path':str(guide),'sha256':guide_hash}]}
        file=Q/(label+'.private.json');save(file,value);return value,file,op
    calls=[];connections=[];mode={'value':'ready'};fake_thread={'value':'fixture-'+str(uuid4())}
    class RPC:
        def __init__(self,*args):pass
        async def start(self):
            connections.append(mode['value'])
            if mode['value']=='transport-unavailable':raise ConnectionError('Synthetic pre-thread transport failure')
        async def close(self):pass
        async def call(self,method,params,**kwargs):
            calls.append({'method':method,'params':params})
            if method=='thread/start':
                if mode['value']=='unknown-thread-start':raise TimeoutError('Synthetic uncertain thread/start')
                return {'thread':{'id':fake_thread['value']},'sandbox':{'type':'dangerFullAccess'},'approvalPolicy':'never'}
            return {}
    old_rpc=room_bootstrap.native_client;room_bootstrap.native_client=RPC
    value,file,op=spec('ready')
    # Real source rejects an out-of-parent operator. ONLY this fixture then
    # supplies the synthetic current-parent affinity for the mocked bootstrap.
    assert held(lambda:a._load(file,sha(file))) and not (op/'windows-resident-original.json').exists()
    original_pid=a._runtime_pid;original_argv=a._own_argv_digest
    a._runtime_pid=lambda:proof['parentRuntime']['pid'];a._own_argv_digest=lambda expected_argv=acceptance['parentArgvSha256']:expected_argv
    result=await a.provision_local(file,op,inspect=False,expected_spec_sha256=sha(file))
    assert result['state']=='ready' and result['logicalSessionAttached'] is False and result['canonicalObservationRequired'] is True
    assert result['parentRuntimePid']==2556 and result['nativeIdentity']==proof['sharedNative']
    runtime=p.read(Path(result['sessionConfigPath']));assert runtime['nativeThreadId']==fake_thread['value'] and runtime['nativeThreadId']!=cfg['nativeThreadId']
    assert runtime['conversationResumeInstructions']==value['connectorConfig']['conversationResumeInstructions']
    methods=[r['method'] for r in calls];assert methods==['thread/start','thread/settings/update','thread/name/set']
    assert calls[0]['params']['sandbox']=='danger-full-access' and calls[0]['params']['approvalPolicy']=='never'
    acceptance=sha(op/'resident-initialization-accepted.json');context=sha(Path(runtime['state'])/'native-context.json')
    save(Path(runtime['state'])/'retained-unknown.private.json',{'originalOperation':'held','state':'unknown'})
    retained=sha(Path(runtime['state'])/'retained-unknown.private.json')
    before=len(calls);connections_before=len(connections)
    inspected=await a.provision_local(file,op,inspect=True,expected_spec_sha256=sha(file))
    assert inspected['sessionConfigSha256']==result['sessionConfigSha256'] and len(calls)==before and len(connections)==connections_before
    assert acceptance==sha(op/'resident-initialization-accepted.json') and context==sha(Path(runtime['state'])/'native-context.json')
    assert retained==sha(Path(runtime['state'])/'retained-unknown.private.json')
    # Proven unstarted transport failure resumes only SAME original operation.
    recovery,recovery_file,recovery_op=spec('unstarted');mode['value']='transport-unavailable'
    initial=await a.provision_local(recovery_file,recovery_op,inspect=False,expected_spec_sha256=sha(recovery_file))
    assert initial['state']=='blocked'
    record=p.read(Path(recovery['connectorConfig']['state'])/'native-context.json')
    assert record['state']=='transport-unavailable' and record['threadStartAttempted'] is False
    sealed=sha(recovery_op/'windows-resident-original.json');before=len(calls)
    mode['value']='ready';fake_thread['value']='fixture-'+str(uuid4())
    resumed=await a.provision_local(recovery_file,recovery_op,inspect=True,expected_spec_sha256=sha(recovery_file))
    assert resumed['state']=='ready' and len(calls)==before+3 and sealed==sha(recovery_op/'windows-resident-original.json')
    uncertain,uncertain_file,uncertain_op=spec('uncertain');mode['value']='unknown-thread-start'
    failed=await a.provision_local(uncertain_file,uncertain_op,inspect=False,expected_spec_sha256=sha(uncertain_file))
    assert failed['state']=='unknown';before=len(calls)
    held_result=await a.provision_local(uncertain_file,uncertain_op,inspect=True,expected_spec_sha256=sha(uncertain_file))
    assert held_result['state']=='unknown' and len(calls)==before and not (uncertain_op/'session-config.private.json').exists()
    # Native incarnation mismatch and guide tampering fail before initialization.
    mismatch,mismatch_file,mismatch_op=spec('wrong-native');mismatch['nativeIdentity']={**proof['sharedNative'],'created':'wrong-birth'}
    mismatch_file.unlink();save(mismatch_file,mismatch)
    assert held(lambda:a._load(mismatch_file,sha(mismatch_file))) and not (mismatch_op/'windows-resident-original.json').exists()
    badguide,badguide_file,badguide_op=spec('wrong-guide');badguide['operatingInstructions'][0]['sha256']='0'*64
    badguide_file.unlink();save(badguide_file,badguide)
    assert held(lambda:a._load(badguide_file,sha(badguide_file))) and not (badguide_op/'windows-resident-original.json').exists()
    a._runtime_pid=original_pid;a._own_argv_digest=original_argv;room_bootstrap.native_client=old_rpc
    after=p.inspect_parent(policyfile,expected_policy_sha256=sha(policyfile));assert after==proof
    assert task_snapshot()==before_tasks and before_files=={str(f):sha(f) for f in files}
    assert sources=={n:sha(S/n) for n in sources}
    for name in ('room_factory_windows.py','room_factory_windows_state.py'):
        for node in ast.walk(ast.parse((S/name).read_text())):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):
                assert node.func.attr not in {'RegisterTaskDefinition','DeleteTask','Run','Stop','Popen','create_subprocess_exec','CreateProcess','Dispatch','GetObject','GetTask','GetTasks'}
    outcome={'passed':True,'sourceEvent':'51426829-b2fd-4b28-9009-6fe1b8417b2b','contractSha256':a.CONTRACT_SHA,
        'sourceHashes':sources,'actualParentAndNativeIdentityVerified':True,'unpatchedOutOfParentRejected':True,
        'residentConfigAndFreshRoleResumePreserved':True,'repeatInspectNoNativeRpc':True,'unknownReceiptRetained':True,
        'sameOperationProvenUnstartedRecovery':True,'uncertainThreadStartNotReplayed':True,
        'nativeIncarnationAndHostGuideNegatives':True,'originalTasksAuthAndParentNativeProcessesPreserved':True,
        'noOsManagerOrWmiCallsInPerAgentAdapter':True,'servicesCreated':0,'newChildProcessesByAdapter':0,'actualNativeThreadsCreated':0,'modelsRequested':0,
        'logicalSessionsAttached':0,'actualNewEnrolledAgents':0,
        'limits':['Actual Windows parent/kernel socket/ACL checks; native bootstrap RPC responses are SYNTHETIC.',
            'Wrapper current-parent PID/own argv were stubbed ONLY after real out-of-parent rejection; no code injected into live parent.',
            'No actual host supervisor attach/fresh canonical observation, and no real new agent/bootstrap performed.']}
    save(Q/'result.json',outcome)
    print(json.dumps({'passed':True,'result':str(Q/'result.json'),'sha256':sha(Q/'result.json'),'sourceHashes':sources,
        'servicesCreated':0,'actualThreadsCreated':0,'sessionsAttached':0}))
if __name__=='__main__':
    import asyncio
    asyncio.run(run())
